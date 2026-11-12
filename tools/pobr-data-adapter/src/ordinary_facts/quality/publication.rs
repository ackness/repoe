//! Verify the quality owner partition against physical gem relationships.

use std::collections::{BTreeMap, BTreeSet};

use serde::Deserialize;
use serde_json::{Value, json};

use super::super::coverage::Coverage;
use super::super::gem_effects::{
    gem_issue, invalid_gem_links, isolate_own_fields, required_primary, valid_gem_links,
};
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
    source_owners: &BTreeSet<String>,
    coverage: &mut Coverage,
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
    let mut isolated_effects = BTreeSet::new();
    let mut isolated_placeholder = false;
    for row in 0..tables.len("SkillGems") {
        let raw = tables.row("SkillGems", row)?;
        let resolve_base = |key: Option<usize>| {
            key.map(|key| {
                bases
                    .get(&key)
                    .map(|id| (id, names[key]))
                    .ok_or_else(|| format!("SkillGems/{row}: dangling BaseItemType {key}"))
            })
            .transpose()
        };
        let gem: Gem = match serde_json::from_value(raw.clone()) {
            Err(error) if invalid_gem_links(&raw["GemEffects"]) => {
                let message = format!("SkillGems/{row}: {error}");
                let base = serde_json::from_value::<Option<usize>>(raw["BaseItemType"].clone())
                    .map_err(|_| message.clone())
                    .and_then(resolve_base);
                if base.is_err() {
                    return Err(message);
                }
                let identity = base.as_ref().ok().copied().flatten();
                coverage.decide(gem_issue(
                    "gem-invalid-field",
                    identity.map_or("null BaseItemType", |(id, _)| id.as_str()),
                    identity.is_none_or(|(_, name)| crate::is_placeholder(name)),
                    message,
                    raw,
                ))?;
                let base = base?;
                isolate_own_fields(
                    input,
                    row,
                    base.map_or("null BaseItemType", |(id, _)| id.as_str()),
                    base.is_none_or(|(_, name)| crate::is_placeholder(name)),
                    raw,
                    coverage,
                )?;
                for key in valid_gem_links(&raw["GemEffects"]) {
                    let variant = variants
                        .get(key)
                        .ok_or_else(|| format!("SkillGems/{row}: dangling GemEffects {key}"))?;
                    if base.is_some_and(|(_, name)| !crate::is_placeholder(name)) {
                        required_primary(row, variant.primary)?;
                    }
                    for effect in variant.primary.iter().chain(&variant.additional) {
                        isolated_effects.insert(effects[effect].clone());
                    }
                }
                isolated_placeholder |= base.is_none_or(|(_, name)| crate::is_placeholder(name));
                continue;
            }
            parsed => parsed.map_err(|e| format!("SkillGems/{row}: {e}"))?,
        };
        let base = resolve_base(gem.base)?;
        // Only positively identified DNT gems justify an exclusion. A missing
        // base, OLD/UNUSED name or no gem relationship is not DNT evidence.
        let dnt = base.is_some_and(|(_, name)| name.contains("[DNT"));
        let placeholder = base.is_none_or(|(_, name)| crate::is_placeholder(name));
        let id = base.map_or("null BaseItemType", |(id, _)| id.as_str());
        let isolated_fields = isolate_own_fields(input, row, id, placeholder, raw, coverage)?;
        if gem.variants.len() > 1 {
            coverage.decide(gem_issue(
                "gem-effects-count",
                id,
                placeholder,
                format!("SkillGems/{row}: multiple GemEffects"),
                raw,
            ))?;
        }
        if base.is_some_and(|(_, name)| !crate::is_placeholder(name)) && gem.variants.is_empty() {
            coverage.decide(gem_issue(
                "gem-effects-count",
                id,
                false,
                format!("SkillGems/{row}: normal gem requires GemEffects"),
                raw,
            ))?;
            continue;
        }
        if placeholder && gem.variants.is_empty() {
            coverage.note(gem_issue(
                "gem-effects-count",
                id,
                true,
                format!("SkillGems/{row}: placeholder has no GemEffects reference"),
                raw,
            ));
            isolated_placeholder = true;
        }
        let linked = gem
            .variants
            .iter()
            .map(|key| {
                variants
                    .get(*key)
                    .ok_or_else(|| format!("SkillGems/{row}: dangling GemEffects {key}"))
            })
            .collect::<Result<Vec<_>, _>>()?;
        let isolate = |isolated: &mut BTreeSet<String>| {
            for variant in &linked {
                for effect in variant.primary.iter().chain(&variant.additional) {
                    isolated.insert(effects[effect].clone());
                }
            }
        };
        for variant in &linked {
            if !placeholder {
                required_primary(row, variant.primary)?;
            }
        }
        if gem.variants.len() > 1 || isolated_fields {
            isolate(&mut isolated_effects);
            isolated_placeholder |= placeholder;
            continue;
        }
        for (&key, variant) in gem.variants.iter().zip(&linked) {
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
        if !source_owners.contains(id) {
            continue;
        }
        let dnt_only = links.contains_key(id.as_str()) && !non_dnt.contains(id.as_str());
        if policy.excluded_effects.contains_key(id) != dnt_only {
            // Isolated links cannot certify or overturn a DNT-only decision.
            if !non_dnt.contains(id.as_str())
                && (isolated_effects.contains(id)
                    || (isolated_placeholder && !links.contains_key(id.as_str())))
            {
                continue;
            }
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
