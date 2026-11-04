//! Verify the quality owner partition against physical gem relationships.

use std::collections::{BTreeMap, BTreeSet};

use serde::Deserialize;
use serde_json::{Value, json};

use crate::facts::reader::{Tables, VerifiedFacts};
use crate::skills::quality::Compatibility;

pub(super) const TABLES: [&str; 6] = [
    "GrantedEffects",
    "Stats",
    "GrantedEffectQualityStats",
    "BaseItemTypes",
    "SkillGems",
    "GemEffects",
];

#[derive(Deserialize)]
struct Gem {
    #[serde(rename = "BaseItemType")]
    base: Option<usize>,
    #[serde(rename = "GemEffects")]
    variants: Vec<usize>,
}

#[derive(Deserialize)]
struct Variant {
    #[serde(rename = "GrantedEffect")]
    primary: Option<usize>,
    #[serde(rename = "AdditionalGrantedEffects")]
    additional: Vec<usize>,
}

pub(super) fn validate(
    input: &VerifiedFacts,
    tables: &Tables<'_>,
    policy: &Compatibility,
) -> Result<Value, String> {
    check_columns(input)?;
    let effects = super::identities(tables, "GrantedEffects")?;
    let bases = super::identities(tables, "BaseItemTypes")?;
    let mut names = Vec::new();
    for row in 0..tables.len("BaseItemTypes") {
        names.push(
            tables.row("BaseItemTypes", row)?["Name"]
                .as_str()
                .ok_or("invalid base Name")?,
        );
    }
    // Validate even unused variants and placeholder links before classification.
    let mut variants = Vec::new();
    for row in 0..tables.len("GemEffects") {
        let variant: Variant = serde_json::from_value(tables.row("GemEffects", row)?.clone())
            .map_err(|e| format!("GemEffects/{row}: {e}"))?;
        for effect in variant.primary.iter().chain(&variant.additional) {
            if !effects.contains_key(effect) {
                return Err(format!("GemEffects/{row}: dangling GrantedEffect {effect}"));
            }
        }
        variants.push(variant);
    }
    let mut links: BTreeMap<&str, Vec<Value>> = BTreeMap::new();
    let mut non_dnt = BTreeSet::new();
    for row in 0..tables.len("SkillGems") {
        let gem: Gem = serde_json::from_value(tables.row("SkillGems", row)?.clone())
            .map_err(|e| format!("SkillGems/{row}: {e}"))?;
        let base = gem
            .base
            .map(|key| {
                bases
                    .get(&key)
                    .map(|id| (id, names[key]))
                    .ok_or_else(|| format!("SkillGems/{row}: dangling BaseItemType {key}"))
            })
            .transpose()?;
        // Only positively identified DNT gems justify an exclusion. A missing
        // base, OLD/UNUSED name or no gem relationship is not DNT evidence.
        let dnt = base.is_some_and(|(_, name)| name.contains("[DNT"));
        if gem.variants.len() > 1 {
            return Err(format!("SkillGems/{row}: multiple GemEffects"));
        }
        if base.is_some_and(|(_, name)| !crate::is_placeholder(name)) && gem.variants.is_empty() {
            return Err(format!("SkillGems/{row}: normal gem requires GemEffects"));
        }
        for key in gem.variants {
            let variant = variants
                .get(key)
                .ok_or_else(|| format!("SkillGems/{row}: dangling GemEffects {key}"))?;
            if base.is_some_and(|(_, name)| !crate::is_placeholder(name))
                && variant.primary.is_none()
            {
                return Err(format!(
                    "SkillGems/{row}: normal gem requires primary GrantedEffect"
                ));
            }
            for (channel, position, effect) in
                variant.primary.iter().map(|key| ("primary", 0, key)).chain(
                    variant
                        .additional
                        .iter()
                        .enumerate()
                        .map(|(i, key)| ("additional", i, key)),
                )
            {
                let id = effects[effect].as_str();
                if !dnt {
                    non_dnt.insert(id);
                }
                links.entry(id).or_default().push(json!({
                    "skill_gem_source_row":row,"base_source_row":gem.base,
                    "gem_id":base.map(|(id, _)|id),"name":base.map(|(_, name)|name),
                    "gem_effect_source_row":key,"channel":channel,"position":position,"dnt":dnt
                }));
            }
        }
    }
    let mut evidence = BTreeMap::new();
    for id in policy.effects.iter().chain(policy.excluded_effects.keys()) {
        let dnt_only = links.contains_key(id.as_str()) && !non_dnt.contains(id.as_str());
        if policy.excluded_effects.contains_key(id) != dnt_only {
            return Err(format!(
                "quality {id}: publication must include every owner except verified DNT-only gem owners"
            ));
        }
        evidence.insert(
            id,
            json!({
                "decision":if dnt_only { "excluded-dnt-only" } else { "published" },
                "gem_links":links.get(id.as_str()).map(Vec::as_slice).unwrap_or_default()
            }),
        );
    }
    Ok(json!({
        "rule":"all-quality-owners-except-dnt-only-gems",
        "owners":evidence,
        "unlinked_owners":"published; gem membership does not define quality eligibility",
        "scope":"ordered source scopes preserved; no calculation support inferred"
    }))
}

fn check_columns(input: &VerifiedFacts) -> Result<(), String> {
    for (table, field, kind, array, target) in [
        ("BaseItemTypes", "Id", "string", false, None),
        ("BaseItemTypes", "Name", "string", false, None),
        (
            "SkillGems",
            "BaseItemType",
            "foreignrow",
            false,
            Some("BaseItemTypes"),
        ),
        (
            "SkillGems",
            "GemEffects",
            "foreignrow",
            true,
            Some("GemEffects"),
        ),
        (
            "GemEffects",
            "GrantedEffect",
            "foreignrow",
            false,
            Some("GrantedEffects"),
        ),
        (
            "GemEffects",
            "AdditionalGrantedEffects",
            "foreignrow",
            true,
            Some("GrantedEffects"),
        ),
    ] {
        super::super::convert::column(
            input,
            table,
            &[field],
            &json!({
                "name":field,"type":kind,"array":array,"interval":false,
                "references":target.map(|table| json!({"table":table}))
            }),
        )?;
    }
    Ok(())
}
