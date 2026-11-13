//! Target graph/definition ownership with explicitly bounded compatibility fields.

use super::super::stat_set_codec::read_pinned;
use super::{
    Converted, ascendancy, nonstat, policy, prepared, render::Renderer, source::Facts, unlock,
};
use crate::facts::reader::{self, VerifiedFacts};
use crate::ordinary_facts::coverage::{Action, Coverage, Issue};
use crate::raw_source::sha256_hex;
use pobr_data::catalog::{PassiveNodeDef, PassiveNodeKind, PassiveTreeMeta};
use pobr_data::native_stat::{NativePassiveContext, NativePassiveStats};
use serde::Deserialize;
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
use std::path::PathBuf;

pub(in crate::ordinary_facts) struct Args {
    pub reference: PathBuf,
    pub descriptions: PathBuf,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Policy {
    pub schema: String,
    pub base_policy: policy::Policy,
    pub reference_sha256: String,
    pub descriptions_sha256: String,
    pub descriptions_manifest_sha256: String,
    pub compatibility_bindings: BTreeMap<String, Binding>,
    pub excluded: BTreeMap<String, Exclusion>,
    pub class_bindings: Vec<ClassBinding>,
    pub statement: String,
    #[serde(default)]
    pub ascendancy: Option<ascendancy::Policy>,
    #[serde(default)]
    pub non_stat_manifest_sha256: Option<String>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Binding {
    pub context_sha256: String,
    pub stats_sha256: String,
    #[serde(default)]
    pub render_context_sha256: Option<String>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Exclusion {
    pub definition_sha256: String,
    pub reason: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ClassBinding {
    pub base_id: String,
    pub class: String,
}

impl Policy {
    pub(super) fn owns_unlocks(&self) -> bool {
        matches!(
            self.schema.as_str(),
            "pobr-ordinary-target-tree-policy/v3" | "pobr-ordinary-target-tree-policy/v4"
        )
    }
    fn owns_nonstat_text(&self) -> bool {
        self.schema == "pobr-ordinary-target-tree-policy/v4"
    }
}

pub(super) struct Supplement<'a> {
    pub ascendancy: &'a ascendancy::Source,
    pub input: &'a reader::selected::Input,
}

struct Effects<'a> {
    ascendancy: Option<&'a ascendancy::Source>,
    nonstat: Option<nonstat::Source<'a>>,
}

pub(super) fn convert(
    input: &VerifiedFacts,
    args: &super::super::CodecArgs,
    extra: &Args,
    supplement: Option<&reader::selected::Input>,
    coverage: &mut Coverage,
) -> Result<Converted, String> {
    let pinned = read_pinned(&args.policy, &args.policy_sha256, "target tree policy")?;
    let policy: Policy = serde_json::from_value(pinned.document).map_err(|e| e.to_string())?;
    if !matches!(
        policy.schema.as_str(),
        "pobr-ordinary-target-tree-policy/v1"
            | "pobr-ordinary-target-tree-policy/v2"
            | "pobr-ordinary-target-tree-policy/v3"
            | "pobr-ordinary-target-tree-policy/v4"
    ) || policy.statement.trim().is_empty()
    {
        return Err("unsupported target tree policy".into());
    }
    if (policy.schema != "pobr-ordinary-target-tree-policy/v1") != policy.ascendancy.is_some()
        || policy.ascendancy.is_some() != supplement.is_some()
    {
        return Err("target tree policy/supplement scope mismatch".into());
    }
    if policy.non_stat_manifest_sha256.is_some() != policy.owns_nonstat_text()
        || policy
            .compatibility_bindings
            .values()
            .any(|b| b.render_context_sha256.is_some() != policy.owns_nonstat_text())
    {
        return Err("target tree render-context policy scope mismatch".into());
    }
    policy.base_policy.validate(input)?;
    if args.source_sha256 != policy.base_policy.source.sha256 {
        return Err("prepared tree policy pin mismatch".into());
    }
    let legacy = read_pinned(
        &args.source,
        &args.source_sha256,
        "prepared field compatibility",
    )?;
    let reference = read_pinned(
        &extra.reference,
        &policy.reference_sha256,
        "coordinate/identity compatibility",
    )?;
    let descriptions = read_pinned(
        &extra.descriptions,
        &policy.descriptions_sha256,
        "target CSD descriptions",
    )?;
    let desc_manifest = read_pinned(
        &extra.descriptions.with_file_name("manifest.json"),
        &policy.descriptions_manifest_sha256,
        "CSD manifest",
    )?;
    if desc_manifest.document["format"] != "repoe-native-descriptions/v1"
        || desc_manifest.document["files"]["descriptions.json"]["sha256"]
            != policy.descriptions_sha256
        || desc_manifest.document["files"]["descriptions.json"]["bytes"] != descriptions.bytes.len()
        || desc_manifest.document["source_identity"]["game_patch"]
            != input.manifest["source_identity"]["game_patch"]
    {
        return Err("CSD manifest/payload/patch mismatch".into());
    }
    let facts = Facts::read(input, &policy.base_policy)?;
    let renderer = Renderer::new(&descriptions.document)?;
    let ascendancy = policy
        .ascendancy
        .as_ref()
        .zip(supplement)
        .map(|(p, s)| {
            ascendancy::Source::read(
                input,
                &facts,
                s,
                p,
                &policy.base_policy.legacy_metadata.value,
                coverage,
            )
        })
        .transpose()?;
    let (tree, metadata, receipt) = project(
        input,
        &facts,
        &policy,
        &legacy.document,
        &reference.document,
        &renderer,
        ascendancy
            .as_ref()
            .zip(supplement)
            .map(|(ascendancy, input)| Supplement { ascendancy, input }),
        &args.source_sha256,
        coverage,
    )?;
    Ok(Converted {
        base: BTreeMap::from([
            (
                "passive_tree.json".into(),
                super::super::pretty_bytes(&tree)?,
            ),
            (
                "passive_tree_meta.json".into(),
                super::super::pretty_bytes(&metadata)?,
            ),
        ]),
        receipt: json!({"projection":receipt,"legacy_source":{"sha256":args.source_sha256,"declaration":policy.base_policy.source},
            "codec_policy":{"sha256":args.policy_sha256},"reference":{"sha256":policy.reference_sha256,"patch":"unknown","role":"fixed coordinate offsets and canonical identity corroboration, not numeric target source"},
            "descriptions":{"sha256":policy.descriptions_sha256,"manifest_sha256":policy.descriptions_manifest_sha256,"source_identity":desc_manifest.document["source_identity"]},
            "target_fields":{"facts_manifest_sha256":sha256_hex(&input.manifest_bytes),"source_identity":input.manifest["source_identity"]},
            "compatibility_statement":policy.statement,"status":"source draft; candidate only; CURRENT unchanged"}),
        source_bytes: legacy.bytes,
        policy_bytes: pinned.bytes,
        protected_parents: vec![
            legacy.parent,
            pinned.parent,
            reference.parent,
            descriptions.parent,
            desc_manifest.parent,
        ],
    })
}

pub(super) fn context(raw: &Value) -> Result<Value, String> {
    let mut context = raw.as_object().ok_or("invalid passive row")?.clone();
    context.retain(|key, _| {
        ![
            "Id",
            "Name",
            "Icon_DDSFile",
            "PassiveSkillGraphId",
            "Stats",
            "IsNotable",
            "IsKeystone",
            "IsJewelSocket",
            "IsAscendancyStartingNode",
        ]
        .contains(&key.as_str())
            && !(key.starts_with("Stat") && key.ends_with("Value"))
    });
    Ok(Value::Object(context))
}
fn policy_context(policy: &Policy, raw: &Value) -> Result<Value, String> {
    let mut value = context(raw)?;
    if policy.ascendancy.is_some() {
        value
            .as_object_mut()
            .ok_or("invalid context")?
            .remove("Ascendancy");
    }
    if policy.owns_unlocks() {
        let object = value.as_object_mut().ok_or("invalid context")?;
        object.remove("UnlockedBy");
        object.remove("VisibleForAscendancy");
    }
    Ok(value)
}
fn render_context(policy: &Policy, raw: &Value) -> Result<Value, String> {
    let mut context = policy_context(policy, raw)?;
    if policy.owns_nonstat_text() {
        let object = context.as_object_mut().ok_or("invalid context")?;
        for field in nonstat::OWNED_FIELDS {
            object.remove(field);
        }
    }
    Ok(context)
}
fn hash(value: &impl serde::Serialize) -> Result<String, String> {
    Ok(sha256_hex(&reader::json_bytes(value)?))
}
fn raw_stats(
    input: &VerifiedFacts,
    facts: &Facts<'_>,
    row: usize,
) -> Result<Vec<(String, i64)>, String> {
    Ok(facts
        .stats(input, row)?
        .into_iter()
        .map(|s| (s.id, s.value))
        .collect())
}
fn observe_node(
    issue: Issue,
    input: &VerifiedFacts,
    facts: &Facts<'_>,
    policy: &Policy,
    row: usize,
) -> Result<Issue, String> {
    let raw = facts.tables.row("PassiveSkills", row)?;
    Ok(issue
        .observed("definition_sha256", hash(raw)?)
        .observed("context_sha256", hash(&policy_context(policy, raw)?)?)
        .observed(
            "render_context_sha256",
            hash(&render_context(policy, raw)?)?,
        )
        .observed("stats_sha256", hash(&raw_stats(input, facts, row)?)?))
}
fn decide_node(
    coverage: &mut Coverage,
    issue: Issue,
    input: &VerifiedFacts,
    facts: &Facts<'_>,
    policy: &Policy,
    row: usize,
) -> Result<(), String> {
    let observed = observe_node(issue.clone(), input, facts, policy, row);
    // Strict must return its original decision before any observation failure.
    coverage.decide(observed.as_ref().unwrap_or(&issue).clone())?;
    observed.map(|_| ())
}
fn exact_compatibility(
    policy: &Policy,
    id: &str,
    raw: &Value,
    stats: &[(String, i64)],
) -> Result<(), String> {
    let binding = policy
        .compatibility_bindings
        .get(id)
        .ok_or_else(|| format!("{id}: no whole-text compatibility binding"))?;
    if binding.context_sha256 != hash(&policy_context(policy, raw)?)?
        || binding.stats_sha256 != hash(&stats)?
    {
        return Err(format!(
            "{id}: target semantics changed; stale whole-text compatibility rejected"
        ));
    }
    Ok(())
}
fn text(
    input: &VerifiedFacts,
    facts: &Facts<'_>,
    row: usize,
    policy: &Policy,
    renderer: &Renderer<'_>,
    legacy: Option<&[String]>,
    nonstat: Option<&nonstat::Source<'_>>,
) -> Result<(Vec<String>, Value), String> {
    let raw = facts.tables.row("PassiveSkills", row)?;
    let id = raw["Id"].as_str().ok_or("missing passive Id")?;
    let stats = raw_stats(input, facts, row)?;
    // Non-stat grants cannot be inferred from the fact that all stat IDs render.
    let extra_effect = !raw["GrantedSkill"].is_null()
        || raw["SkillPointsGranted"].as_i64().is_some_and(|n| n != 0)
        || raw["WeaponPointsGranted"].as_i64().is_some_and(|n| n != 0)
        || raw["PassiveSkillBuffs"]
            .as_array()
            .is_some_and(|v| !v.is_empty())
        || (stats.is_empty() && legacy.is_some_and(|v| !v.is_empty()));
    let mut non_stat_evidence = Vec::new();
    let result = if let Some(source) = nonstat {
        source.render(raw).and_then(|(extra_lines, evidence)| {
            if stats.is_empty() && extra_lines.is_empty() && legacy.is_some_and(|v| !v.is_empty()) {
                return Err("source has no effect text for nonempty prepared node".into());
            }
            let (mut lines, descriptions) = renderer.render(&stats)?;
            lines.extend(extra_lines);
            non_stat_evidence = evidence;
            Ok((lines, descriptions))
        })
    } else if extra_effect {
        Err("non-stat effect requires complete compatibility text".into())
    } else {
        renderer.render(&stats)
    };
    match result {
        Ok((lines, evidence)) => Ok((
            lines,
            json!({"owner":if non_stat_evidence.is_empty(){"target-csd"}else{"target-csd-and-client-strings"},
                "complete_stats":stats,"descriptions":evidence,"non_stat":non_stat_evidence}),
        )),
        Err(reason) => {
            exact_compatibility(policy, id, raw, &stats)?;
            let lines =
                legacy.ok_or_else(|| format!("{id}: {reason}; no complete compatibility text"))?;
            Ok((
                lines.to_vec(),
                json!({"owner":"prepared-whole-text","reason":reason,"complete_stats":stats,
                "stats_sha256":hash(&stats)?,"target_applicability":"unknown; fixed transition text, no partial target packet"}),
            ))
        }
    }
}

#[allow(clippy::too_many_arguments)]
pub(super) fn project(
    input: &VerifiedFacts,
    facts: &Facts<'_>,
    policy: &Policy,
    legacy: &Value,
    reference: &Value,
    renderer: &Renderer<'_>,
    supplement: Option<Supplement<'_>>,
    source_sha256: &str,
    coverage: &mut Coverage,
) -> Result<(Value, Value, Value), String> {
    let effects = Effects {
        ascendancy: supplement.as_ref().map(|s| s.ascendancy),
        nonstat: if policy.owns_nonstat_text() {
            let extra = supplement
                .as_ref()
                .ok_or("non-stat text requires supplement")?
                .input;
            if policy.non_stat_manifest_sha256.as_deref()
                != Some(sha256_hex(&extra.manifest_bytes).as_str())
            {
                return Err("non-stat text supplement differs from policy pin".into());
            }
            Some(nonstat::Source::read(input, extra)?)
        } else {
            None
        },
    };
    let ascendancy = effects.ascendancy;
    if policy.owns_unlocks() {
        unlock::validate(input)?;
        if ascendancy.is_none() {
            return Err("source unlocks require target ascendancy identities".into());
        }
    }
    for field in [
        "IsNotable",
        "IsKeystone",
        "IsJewelSocket",
        "IsAscendancyStartingNode",
        "IsJustIcon",
    ] {
        super::source::column(input, "PassiveSkills", field, "bool", false, None)?;
    }
    let old_nodes: Vec<PassiveNodeDef> =
        serde_json::from_value(legacy.clone()).map_err(|e| e.to_string())?;
    let meta: PassiveTreeMeta =
        serde_json::from_value(policy.base_policy.legacy_metadata.value.clone())
            .map_err(|e| e.to_string())?;
    prepared::validate(&old_nodes, &meta)?;
    if reference["tree"] != "Default" {
        return Err("reference is not Default tree".into());
    }
    let old: BTreeMap<_, _> = old_nodes
        .iter()
        .enumerate()
        .map(|(i, n)| (n.skill, (i, n)))
        .collect();
    let (graph, instances) = reader::tree(input)?;
    let forward = coverage.is_forward();
    if forward && policy.owns_unlocks() {
        let owners = supplement
            .as_ref()
            .ok_or("source unlocks require target ascendancy identities")?
            .input
            .tables(&["Ascendancy"])?;
        // Quarantine changes output availability, never physical FK validity.
        for instance in &instances {
            unlock::validate_physical(facts, &owners, instance.definition.row)?;
        }
    }
    if forward
        && instances
            .iter()
            .any(|instance| !old.contains_key(&(instance.graph_id as u32)))
    {
        super::source::column(
            input,
            "PassiveSkills",
            "IsAnointmentOnly",
            "bool",
            false,
            None,
        )?;
    }
    let mut excluded = BTreeSet::new();
    let mut excluded_records = Vec::new();
    let mut gapped = BTreeSet::new();
    let mut quarantined = BTreeSet::new();
    for instance in &instances {
        let raw = facts.tables.row("PassiveSkills", instance.definition.row)?;
        if raw["Ascendancy"]
            .as_u64()
            .and_then(|row| usize::try_from(row).ok())
            .is_some_and(|row| {
                ascendancy.is_some_and(|source| source.quarantined.contains_key(&row))
            })
        {
            quarantined.insert(instance.graph_id);
            continue;
        }
        if let Some(exclusion) = policy.excluded.get(&instance.definition.id) {
            if exclusion.definition_sha256 != hash(raw)? || exclusion.reason.trim().is_empty() {
                decide_node(
                    coverage,
                    Issue::new(
                        "excluded-definition",
                        &instance.definition.id,
                        Action::EmittedWithGap,
                        format!(
                            "{}: non-allocatable compatibility binding changed",
                            instance.definition.id
                        ),
                    )
                    .observed(
                        "policy_definition_sha256",
                        exclusion.definition_sha256.clone(),
                    ),
                    input,
                    facts,
                    policy,
                    instance.definition.row,
                )?;
                gapped.insert(instance.graph_id);
                continue;
            }
            if let Some(entry) = raw["Ascendancy"]
                .as_u64()
                .and_then(|row| usize::try_from(row).ok())
                .and_then(|row| ascendancy?.entries.get(&row))
                && policy
                    .ascendancy
                    .as_ref()
                    .is_some_and(|p| p.excluded.contains_key(&entry.id))
            {
                coverage.note(observe_node(
                    Issue::new(
                        "stale-exclusion",
                        &instance.definition.id,
                        Action::EmittedWithGap,
                        format!(
                            "{}: node exclusion belongs to emitted ascendancy {}",
                            instance.definition.id, entry.id
                        ),
                    )
                    .observed("ascendancy_id", entry.id.clone()),
                    input,
                    facts,
                    policy,
                    instance.definition.row,
                )?);
            }
            excluded.insert(instance.graph_id);
            excluded_records.push(json!({"graph_id":instance.graph_id,"id":instance.definition.id,
                "source_row":instance.definition.row,"reason":exclusion.reason,"definition_sha256":exclusion.definition_sha256}));
        }
    }
    let mut output = Vec::new();
    let mut records = Vec::new();
    let mut native_count = 0;
    let mut rendered_count = 0;
    let mut multi_count = 0;
    let mut moved_skills = BTreeSet::new();
    let mut new_ascendancies = BTreeSet::new();
    for instance in &instances {
        if excluded.contains(&instance.graph_id) || quarantined.contains(&instance.graph_id) {
            continue;
        }
        let skill = u32::try_from(instance.graph_id).map_err(|e| e.to_string())?;
        let row = instance.definition.row;
        let raw = facts.tables.row("PassiveSkills", row)?;
        let id = instance.definition.id.as_str();
        let previous = old.get(&skill).copied();
        let mut has_open_issue = gapped.contains(&instance.graph_id);
        let expected_context = policy
            .compatibility_bindings
            .get(id)
            .map(|b| {
                b.render_context_sha256
                    .as_ref()
                    .unwrap_or(&b.context_sha256)
                    .clone()
            })
            .unwrap_or(hash(&render_context(
                policy,
                facts.tables.row("PassiveSkills", facts.reference_row)?,
            )?)?);
        if expected_context != hash(&render_context(policy, raw)?)? {
            return Err(format!(
                "{id}: unsupported source context change or new conditional identity"
            ));
        }
        let mut quarantine = |issue: Issue| {
            has_open_issue = true;
            decide_node(
                coverage,
                issue.observed("reference_sha256", policy.reference_sha256.clone()),
                input,
                facts,
                policy,
                row,
            )
        };
        if let Some((old_index, old)) = previous {
            let alias =
                policy.base_policy.legacy_id_bindings.iter().find(|b| {
                    b.legacy_id == old.id && b.target_passive_id == id && b.skill == skill
                });
            if old.id != id && alias.is_none() {
                quarantine(Issue::new(
                    "identity-collision",
                    id,
                    Action::Quarantined,
                    format!("{id}: prepared identity collision at {skill}"),
                ))?;
                quarantined.insert(instance.graph_id);
                continue;
            }
            if let Some(alias) = alias
                && (alias.source_entry_sha256 != hash(&legacy[old_index])?
                    || old.name.as_deref() != Some(alias.expected_name.as_str()))
            {
                quarantine(Issue::new(
                    "stale-alias",
                    id,
                    Action::Quarantined,
                    format!("{id}: stale prepared identity alias"),
                ))?;
                quarantined.insert(instance.graph_id);
                continue;
            }
        }
        let name = raw["Name"].as_str().ok_or("missing target Name")?;
        if name.is_empty() || name.starts_with("[DNT") {
            quarantine(Issue::new(
                "unclassified-name",
                id,
                Action::Quarantined,
                format!("{id}: unclassified layout/unreleased definition"),
            ))?;
            quarantined.insert(instance.graph_id);
            continue;
        }
        let quarantined_owner = if policy.owns_unlocks() {
            raw["VisibleForAscendancy"]
                .as_u64()
                .and_then(|row| usize::try_from(row).ok())
                .and_then(|row| ascendancy?.quarantined.get(&row))
        } else {
            previous
                .and_then(|(_, node)| node.unlock_constraint.as_ref())
                .and_then(|unlock| unlock.ascendancy.as_ref())
                .filter(|id| {
                    ascendancy
                        .is_some_and(|source| source.quarantined.values().any(|owner| owner == *id))
                })
        };
        if let Some(owner) = quarantined_owner {
            quarantine(
                Issue::new(
                    "dependant-quarantined",
                    id,
                    Action::Quarantined,
                    format!("{id}: prerequisite ascendancy quarantined"),
                )
                .observed("quarantined_ascendancy", owner.clone()),
            )?;
            quarantined.insert(instance.graph_id);
            continue;
        }
        let (lines, text_record) = text(
            input,
            facts,
            row,
            policy,
            renderer,
            previous.map(|(_, n)| n.stats.as_slice()),
            effects.nonstat.as_ref(),
        )?;
        if matches!(
            text_record["owner"].as_str(),
            Some("target-csd" | "target-csd-and-client-strings")
        ) {
            rendered_count += 1;
            if raw["Stats"].as_array().is_some_and(|v| v.len() > 1) {
                multi_count += 1;
            }
        }
        let kind = classify(raw)?;
        let mut entry = previous
            .map(|(i, _)| legacy[i].clone())
            .unwrap_or_else(|| json!({}));
        let object = entry.as_object_mut().ok_or("invalid prepared node")?;
        object.insert("skill".into(), json!(skill));
        object.insert("id".into(), json!(id));
        object.insert("name".into(), json!(name));
        object.insert(
            "kind".into(),
            serde_json::to_value(kind).map_err(|e| e.to_string())?,
        );
        object.insert("stats".into(), json!(lines));
        object.insert("group".into(), json!(instance.group + 1));
        object.insert("orbit".into(), json!(instance.radius));
        object.insert("orbit_index".into(), json!(instance.position));
        object.remove("native_stats");
        let connections: Vec<_> = instance
            .connections
            .iter()
            .filter(|id| !excluded.contains(id))
            .copied()
            .collect();
        object.insert("connections".into(), json!(connections));
        let ascendancy_id = if let Some(source) = ascendancy {
            raw["Ascendancy"]
                .as_u64()
                .and_then(|row| usize::try_from(row).ok())
                .and_then(|row| source.entries.get(&row))
                .map(|entry| entry.id.as_str())
        } else {
            previous.and_then(|(_, node)| node.ascendancy_id.as_deref())
        };
        let new_ascendancy = forward
            && ascendancy_id.is_some_and(|id| {
                !old_nodes
                    .iter()
                    .any(|node| node.ascendancy_id.as_deref() == Some(id))
            });
        let Some((geometry, rebased)) = geometry(
            reference,
            &graph,
            instance,
            Placement {
                previous: previous.map(|(_, n)| n),
                prepared: &old_nodes,
                ascendancy_id,
                forward,
                new_ascendancy,
                anointment_only: if forward && previous.is_none() {
                    raw["IsAnointmentOnly"]
                        .as_bool()
                        .ok_or("IsAnointmentOnly: bool required")?
                } else {
                    false
                },
            },
            object,
            &mut quarantine,
        )?
        else {
            quarantined.insert(instance.graph_id);
            continue;
        };
        if rebased {
            moved_skills.insert(instance.graph_id);
        }
        has_open_issue |= rebased || new_ascendancy;
        if new_ascendancy && let Some(id) = ascendancy_id {
            new_ascendancies.insert(id);
        }
        let variant_records = variants(
            input,
            facts,
            policy,
            renderer,
            previous.map(|(_, n)| n),
            object,
            &effects,
        )?;
        // Every complete single-stat whole-context node carries its native
        // packet, whatever PoBR maps today: the consumer decides per packet
        // (an unknown stat keeps the text path). Multi-stat nodes use the
        // same ordinary parser as every other rendered tree node.
        let stats = facts.stats(input, row)?;
        if !has_open_issue
            && text_record["owner"] == "target-csd"
            && kind == PassiveNodeKind::Normal
            && facts.differences(raw)?.is_empty()
            && !facts.involved.contains_key(&row)
            && previous.is_none_or(|(_, n)| {
                n.variants.is_empty()
                    && n.ascendancy_id.is_none()
                    && n.unlock_constraint.is_none()
                    && !n.apply_to_armour
            })
            && stats.len() == 1
            && lines.len() == 1
        {
            let packet = NativePassiveStats {
                data_version: input.manifest["source_identity"]["game_patch"]
                    .as_str()
                    .ok_or("missing patch")?
                    .into(),
                tree_version: Some(policy.base_policy.catalog.tree_compatibility_tag.clone()),
                node_id: skill,
                node_slug: id.into(),
                modifier_texts: lines.clone(),
                context: NativePassiveContext::UnconditionalPlayer,
                stats,
            };
            object.insert(
                "native_stats".into(),
                serde_json::to_value(packet).map_err(|e| e.to_string())?,
            );
            native_count += 1;
        }
        if let Some(source) = ascendancy {
            source.node(raw, object)?;
        }
        let unlock_record = if policy.owns_unlocks() {
            Some(unlock::project(
                facts,
                ascendancy.ok_or("source unlocks require target ascendancy identities")?,
                row,
                object,
            )?)
        } else {
            None
        };
        records.push(json!({"skill":skill,"id":id,"target_row":row,"previous_row":previous.map(|(i,_)|i),
            "name":name,"text":text_record,"geometry":geometry,"variants":variant_records,
            "unlock":unlock_record,
            "source_connections":instance.connections,"excluded_connections":instance.connections.iter().filter(|id|excluded.contains(id)).collect::<Vec<_>>(),
            "compatibility_fields":if policy.owns_unlocks(){vec!["apply_to_armour","unknown prepared extension fields"]}else if ascendancy.is_some(){vec!["unlock_constraint","apply_to_armour","unknown prepared extension fields"]}else{vec!["ascendancy_id","unlock_constraint","apply_to_armour","unknown prepared extension fields"]},
            "context_sha256":hash(&policy_context(policy, raw)?)?,"output_entry_sha256":hash(&entry)?}));
        output.push(entry);
    }
    if !moved_skills.is_empty() {
        coverage.decide(
            Issue::new(
                "placement-rebase",
                "passive-tree",
                Action::EmittedWithGap,
                "prepared placement lacks exact reference group/orbit/slot binding",
            )
            .observed("reference_sha256", policy.reference_sha256.clone())
            .observed("legacy_source_sha256", source_sha256)
            .observed(
                "moved_skills_sha256",
                hash(&moved_skills.iter().copied().collect::<Vec<_>>())?,
            )
            .observed("moved_count", moved_skills.len()),
        )?;
    }
    if !quarantined.is_empty() {
        loop {
            let mut changed = false;
            for entry in &output {
                let skill = entry["skill"].as_u64().ok_or("missing projected skill")?;
                if quarantined.contains(&skill) {
                    continue;
                }
                let prerequisites: BTreeSet<_> = entry["unlock_constraint"]["nodes"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .filter_map(Value::as_u64)
                    .filter(|id| quarantined.contains(id))
                    .collect();
                if prerequisites.is_empty() {
                    continue;
                }
                let record = records
                    .iter()
                    .find(|r| r["skill"] == skill)
                    .ok_or("missing projected source record")?;
                let row = record["target_row"]
                    .as_u64()
                    .and_then(|row| usize::try_from(row).ok())
                    .ok_or("missing projected source row")?;
                let id = entry["id"].as_str().ok_or("missing projected id")?;
                decide_node(
                    coverage,
                    Issue::new(
                        "dependant-quarantined",
                        id,
                        Action::Quarantined,
                        format!("{id}: prerequisite node quarantined"),
                    )
                    .observed("quarantined_prerequisites", json!(prerequisites)),
                    input,
                    facts,
                    policy,
                    row,
                )?;
                quarantined.insert(skill);
                changed = true;
            }
            if !changed {
                break;
            }
        }
        output.retain(|entry| {
            !entry["skill"]
                .as_u64()
                .is_some_and(|id| quarantined.contains(&id))
        });
        records.retain(|record| {
            !record["skill"]
                .as_u64()
                .is_some_and(|id| quarantined.contains(&id))
        });
        for (entry, record) in output.iter_mut().zip(&mut records) {
            entry["connections"]
                .as_array_mut()
                .ok_or("missing projected connections")?
                .retain(|id| !id.as_u64().is_some_and(|id| quarantined.contains(&id)));
            record["output_entry_sha256"] = json!(hash(entry)?);
        }
        native_count = output
            .iter()
            .filter(|entry| !entry["native_stats"].is_null())
            .count();
        let rendered: Vec<_> = records
            .iter()
            .filter(|record| {
                matches!(
                    record["text"]["owner"].as_str(),
                    Some("target-csd" | "target-csd-and-client-strings")
                )
            })
            .collect();
        rendered_count = rendered.len();
        multi_count = rendered
            .iter()
            .filter(|record| {
                record["text"]["complete_stats"]
                    .as_array()
                    .is_some_and(|stats| stats.len() > 1)
            })
            .count();
    }
    if forward && let Some(source) = ascendancy {
        for entry in source.entries.values() {
            if !new_ascendancies.contains(entry.id.as_str()) {
                continue;
            }
            let member_skills: BTreeSet<_> = output
                .iter()
                .filter(|node| node["ascendancy_id"] == entry.id)
                .filter_map(|node| node["skill"].as_u64())
                .collect();
            if member_skills.is_empty() {
                continue;
            }
            let mut start_skill = None;
            for instance in &instances {
                let raw = facts.tables.row("PassiveSkills", instance.definition.row)?;
                if raw["Ascendancy"] == entry.row && raw["IsAscendancyStartingNode"] == true {
                    start_skill = Some(instance.graph_id);
                    break;
                }
            }
            let start_skill = start_skill.ok_or("new ascendancy lacks a target start node")?;
            coverage.note(
                Issue::new(
                    "ascendancy-frame",
                    &entry.id,
                    Action::EmittedWithGap,
                    format!("{}: no prepared ascendancy coordinate frame", entry.id),
                )
                .observed("start_skill", start_skill)
                .observed(
                    "reference_start_node_sha256",
                    hash(&reference["nodes"][start_skill.to_string()])?,
                )
                .observed(
                    "member_skills_sha256",
                    hash(&member_skills.iter().copied().collect::<Vec<_>>())?,
                ),
            );
        }
    }
    output.sort_by_key(|n| n["skill"].as_u64());
    let typed: Vec<PassiveNodeDef> =
        serde_json::from_value(json!(output)).map_err(|e| e.to_string())?;
    let (mut metadata, classes) = prepared::metadata(
        &policy.base_policy.legacy_metadata.value,
        &meta,
        facts,
        coverage,
    )?;
    if let Some(source) = ascendancy {
        source.metadata(&mut metadata)?;
    }
    let output_meta =
        serde_json::from_value(metadata.clone()).map_err(|e| format!("projected metadata: {e}"))?;
    prepared::validate(&typed, &output_meta)?;
    let skills: BTreeSet<_> = typed.iter().map(|n| n.skill).collect();
    if typed
        .iter()
        .any(|n| n.connections.iter().any(|id| !skills.contains(id)))
    {
        return Err("emitted edge targets non-emitted node".into());
    }
    let removed: Vec<_> = old_nodes
        .iter()
        .filter(|n| !skills.contains(&n.skill))
        .map(|n| n.skill)
        .collect();
    let target_skills: BTreeSet<_> = instances.iter().map(|node| node.graph_id).collect();
    let reference_skills: BTreeSet<_> = reference["nodes"]
        .as_object()
        .into_iter()
        .flat_map(|nodes| nodes.keys())
        .filter(|key| !key.is_empty() && key.bytes().all(|byte| byte.is_ascii_digit()))
        .filter_map(|key| key.parse::<u64>().ok())
        .collect();
    let target_absent: Vec<_> = target_skills
        .difference(&reference_skills)
        .copied()
        .collect();
    let reference_absent: Vec<_> = reference_skills
        .difference(&target_skills)
        .copied()
        .collect();
    if !target_absent.is_empty() || !reference_absent.is_empty() {
        coverage.note(
            Issue::new(
                "reference-membership",
                "passive-tree",
                Action::Listed,
                "target/reference passive-tree membership differs",
            )
            .observed("target_absent_from_reference", json!(target_absent))
            .observed("reference_absent_from_target", json!(reference_absent))
            .observed("reference_sha256", policy.reference_sha256.clone()),
        );
    }
    Ok((
        json!(output),
        metadata,
        json!({"entries":typed.len(),"graph_instances":instances.len(),"target_text_nodes":rendered_count,
        "target_multistat_nodes":multi_count,"native_packets":native_count,"source_records":records,"excluded":excluded_records,
        "removed_prepared_skills":removed,"class_records":classes,"class_override_inventory":facts.relations,
        "ascendancy":ascendancy.map(|a|&a.receipt),"non_stat_text":effects.nonstat.as_ref().map(|s|&s.receipt),"ownership":{"ascendancy":if ascendancy.is_some(){"target physical membership, names, character FK, node FK and replacement relations; geometry remains compatibility"}else{"compatibility"},"unlock":if policy.owns_unlocks(){"target UnlockedBy ordered node identities and VisibleForAscendancy stable identity; existing all-prerequisites DTO semantics; Requirement remains opaque context"}else{"prepared compatibility"},"target":["membership minus source-bound eligibility exclusions","ordered emitted edges","id","name","kind","group","orbit","orbit_index","group centres","complete rendered stats","class override identities and rendered stats","base attributes"],
            "compatibility":["whole unrenderable text with exact semantic binding","prepared planar placement/coordinate absence under exact reference group-orbit-slot binding; explicit reference offsets for new nodes","unlock predicates in v1/v2 only; Requirement is never interpreted as a predicate","armour","non-class variants when no supplement","unknown prepared fields"]}}),
    ))
}

fn classify(raw: &Value) -> Result<PassiveNodeKind, String> {
    for (field, kind) in [
        ("IsKeystone", PassiveNodeKind::Keystone),
        ("IsNotable", PassiveNodeKind::Notable),
        ("IsJustIcon", PassiveNodeKind::Mastery),
        ("IsJewelSocket", PassiveNodeKind::JewelSocket),
        ("IsAscendancyStartingNode", PassiveNodeKind::AscendancyStart),
    ] {
        if raw[field]
            .as_bool()
            .ok_or_else(|| format!("{field}: bool required"))?
        {
            return Ok(kind);
        }
    }
    // MasteryGroup is shared by ordinary notables and icon-only records; it is
    // not a node category. IsJustIcon supplies the non-allocatable mastery icon.
    Ok(PassiveNodeKind::Normal)
}

struct Placement<'a> {
    previous: Option<&'a PassiveNodeDef>,
    prepared: &'a [PassiveNodeDef],
    ascendancy_id: Option<&'a str>,
    forward: bool,
    new_ascendancy: bool,
    anointment_only: bool,
}

fn geometry(
    reference: &Value,
    graph: &reader::Graph,
    instance: &reader::InstanceInput,
    placement: Placement<'_>,
    out: &mut serde_json::Map<String, Value>,
    quarantine: &mut impl FnMut(Issue) -> Result<(), String>,
) -> Result<Option<(Value, bool)>, String> {
    let previous = placement.previous;
    let group = &graph.groups[instance.group];
    if !group.x_raw.is_finite() || !group.y_raw.is_finite() {
        return Err("non-finite group centre".into());
    }
    let node = &reference["nodes"][instance.graph_id.to_string()];
    if placement.anointment_only && node.is_null() {
        return Ok(Some((
            json!({"owner":"target IsAnointmentOnly coordinate absence"}),
            false,
        )));
    }
    if node.is_null() {
        quarantine(Issue::new(
            "reference-missing",
            &instance.definition.id,
            Action::Quarantined,
            format!(
                "node {}: missing physical orbit-offset compatibility; refusing incomplete radius geometry",
                instance.graph_id
            ),
        ).observed("reference_node", node.clone()))?;
        return Ok(None);
    }
    if node["skill"] != instance.graph_id
        || node["orbit"] != instance.radius
        || node["orbitIndex"] != instance.position
    {
        quarantine(
            Issue::new(
                "reference-slot-changed",
                &instance.definition.id,
                Action::Quarantined,
                format!(
                    "node {}: changed orbit/slot needs explicit geometry compatibility",
                    instance.graph_id
                ),
            )
            .observed("reference_node_sha256", hash(node)?)
            .observed("target_orbit", instance.radius)
            .observed("target_orbit_index", instance.position)
            .observed("reference_node", node.clone()),
        )?;
        return Ok(None);
    }
    let group_key = node["group"]
        .as_u64()
        .ok_or("missing reference group")?
        .to_string();
    if placement.anointment_only {
        if node["isBlighted"] != true {
            quarantine(
                Issue::new(
                    "anointment-geometry",
                    &instance.definition.id,
                    Action::EmittedWithGap,
                    format!(
                        "node {}: target anointment-only node lacks reference isBlighted",
                        instance.graph_id
                    ),
                )
                .observed("reference_node_sha256", hash(node)?)
                .observed("is_anointment_only", true),
            )?;
        }
        return Ok(Some((
            json!({"owner":"target IsAnointmentOnly coordinate absence","reference_group":group_key,
                "source_group":instance.group,"radius":instance.radius,"position":instance.position}),
            false,
        )));
    }
    let rebased = previous.is_some_and(|old| {
        old.group.map(u64::from) != node["group"].as_u64()
            || old.orbit.map(u64::from) != node["orbit"].as_u64()
            || old.orbit_index.map(u64::from) != node["orbitIndex"].as_u64()
    });
    if rebased && !placement.forward {
        quarantine(Issue::new(
            "placement-rebase",
            "passive-tree",
            Action::EmittedWithGap,
            "prepared placement lacks exact reference group/orbit/slot binding",
        ))?;
    }
    let use_reference = previous.is_none() || rebased || placement.new_ascendancy;
    let start = placement
        .ascendancy_id
        .filter(|_| placement.forward && use_reference)
        .and_then(|id| {
            placement.prepared.iter().find(|node| {
                node.kind == PassiveNodeKind::AscendancyStart
                    && node.ascendancy_id.as_deref() == Some(id)
            })
        });
    let original_group = &reference["groups"][&group_key];
    for (key, centre) in [("x", group.x_raw), ("y", group.y_raw)] {
        // Coordinate absence remains meaningful even when placement is rebased.
        let prepared_coordinate = if let Some(old) = previous {
            let Some(value) = (if key == "x" { old.x } else { old.y }) else {
                continue;
            };
            Some(value)
        } else {
            None
        };
        let original = if use_reference {
            let offset = if let Some(start) = start {
                let prepared = (if key == "x" { start.x } else { start.y })
                    .ok_or("invalid prepared ascendancy start coordinate")?;
                let reference = reference["nodes"][start.skill.to_string()][key]
                    .as_f64()
                    .ok_or("invalid reference ascendancy start coordinate")?;
                prepared - reference
            } else {
                0.0
            };
            if placement.forward && previous.is_none() && node[key].is_null() {
                quarantine(
                    Issue::new(
                        "reference-missing",
                        &instance.definition.id,
                        Action::Quarantined,
                        "invalid reference coordinate",
                    )
                    .observed("reference_node_sha256", hash(node)?)
                    .observed("reference_node", node.clone()),
                )?;
                return Ok(None);
            }
            node[key].as_f64().ok_or("invalid reference coordinate")? + offset
        } else {
            prepared_coordinate.ok_or("invalid prepared coordinate")?
        };
        if !original.is_finite() {
            return Err("non-finite compatibility coordinate".into());
        }
        let original_centre = original_group[key]
            .as_f64()
            .filter(|n| n.is_finite())
            .ok_or("invalid reference group centre")?;
        // Preserve published six-significant-digit group coordinates, and translate
        // only the verified group centre. This does not interpret raw radius units.
        let rounded = round_group(centre)?;
        if !use_reference && rounded == original_centre {
            continue;
        }
        let value = original + (rounded - original_centre);
        if !value.is_finite() {
            return Err("non-finite projected coordinate".into());
        }
        out.insert(key.into(), json!(value));
    }
    Ok(Some((
        json!({"owner":if !use_reference{"target group translation + prepared physical placement/coordinate absence"}else{"target group translation + explicit reference physical offset"},"reference_group":group_key,
        "source_group":instance.group,"radius":instance.radius,"position":instance.position}),
        rebased,
    )))
}
fn round_group(value: f64) -> Result<f64, String> {
    if value == 0.0 {
        return Ok(value);
    }
    let places = 5 - value.abs().log10().floor() as i32;
    if places >= 0 {
        format!("{value:.precision$}", precision = places as usize)
            .parse()
            .map_err(|e| format!("group rounding: {e}"))
    } else {
        let scale = 10f64.powi(-places);
        Ok((value / scale).round() * scale)
    }
}

fn variants(
    input: &VerifiedFacts,
    facts: &Facts<'_>,
    policy: &Policy,
    renderer: &Renderer<'_>,
    previous: Option<&PassiveNodeDef>,
    out: &mut serde_json::Map<String, Value>,
    effects: &Effects<'_>,
) -> Result<Vec<Value>, String> {
    let ascendancy = effects.ascendancy;
    let id = out["id"]
        .as_str()
        .ok_or("missing output node identity")?
        .to_owned();
    let mut variants = out
        .get("variants")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let previous_classes: BTreeSet<_> = policy
        .class_bindings
        .iter()
        .filter(|b| b.base_id == id)
        .map(|b| b.class.as_str())
        .collect();
    let old_by_class: BTreeMap<_, _> = variants
        .iter()
        .cloned()
        .map(|v| {
            let class = v["class"]
                .as_str()
                .ok_or("invalid variant class")?
                .to_owned();
            Ok((class, v))
        })
        .collect::<Result<_, String>>()?;
    // Preserve unknown variant fields. Only declared target class relations replace
    // these entries; remaining ascendancy variants stay complete compatibility.
    variants.retain(|v| {
        let selector = v["class"].as_str().unwrap_or("");
        !previous_classes.contains(selector)
            && !ascendancy.is_some_and(|a| a.previous_selectors.contains(selector))
    });
    let mut records = Vec::new();
    for v in &variants {
        if let Some(skill) = v["variant_skill"].as_u64() {
            let rows: Vec<_> = facts
                .passives
                .values()
                .copied()
                .filter(|row| {
                    facts
                        .tables
                        .row("PassiveSkills", *row)
                        .is_ok_and(|r| r["PassiveSkillGraphId"] == skill)
                })
                .collect();
            let [row] = rows.as_slice() else {
                return Err(format!(
                    "variant {skill}: ambiguous/missing physical identity"
                ));
            };
            let raw = facts.tables.row("PassiveSkills", *row)?;
            if policy.owns_unlocks() {
                unlock::validate_variant(raw)?;
            }
            let variant_id = raw["Id"].as_str().ok_or("invalid variant Id")?;
            exact_compatibility(policy, variant_id, raw, &raw_stats(input, facts, *row)?)?;
            records.push(json!({"class":v["class"],"target":variant_id,"source_row":row,
                "owner":"prepared-whole-variant","reason":"non-class replacement law remains compatibility; changed source is rejected"}));
        } else {
            return Err(format!(
                "{id}: variant without a stable alias requires explicit binding"
            ));
        }
    }
    let mut relations = Vec::new();
    for relation in &facts.relations {
        if relation["definitions"][0]["id"] == id {
            let class = relation["character"]["name"]
                .as_str()
                .ok_or("invalid class relation")?;
            let row = relation["definitions"][1]["source_row"]
                .as_u64()
                .ok_or("invalid replacement row")? as usize;
            relations.push((
                class,
                row,
                Some(class),
                json!({"table":"ClassPassiveSkillOverrides","source_row":relation["source_row"]}),
            ));
        }
    }
    if let Some(source) = ascendancy {
        for link in source.links.get(&id).into_iter().flatten() {
            relations.push((
                link.selector.as_str(),
                link.target,
                link.previous_selector.as_deref(),
                json!({"table":"AscendancyPassiveSkillOverrides","source_row":link.row}),
            ));
        }
    }
    let mut classes = BTreeSet::new();
    for (class, row, old_selector, relationship) in relations {
        if !classes.insert(class) {
            return Err(format!("{id}: repeated replacement selector {class}"));
        }
        let raw = facts.tables.row("PassiveSkills", row)?;
        if policy.owns_unlocks() {
            unlock::validate_variant(raw)?;
        }
        let target = raw["Id"].as_str().ok_or("invalid replacement id")?;
        let binding = policy
            .compatibility_bindings
            .get(target)
            .ok_or_else(|| format!("{target}: missing variant context binding"))?;
        if binding
            .render_context_sha256
            .as_ref()
            .unwrap_or(&binding.context_sha256)
            != &hash(&render_context(policy, raw)?)?
        {
            return Err(format!("{target}: changed variant context"));
        }
        let old_variant = previous.and_then(|n| {
            n.variants
                .iter()
                .find(|v| Some(v.class.as_str()) == old_selector)
        });
        let target_skill = super::source::graph_id(raw)?;
        // A class slot can change its replacement. Its old text belongs only to
        // the original target, even if the new target has a valid semantic guard.
        let compatible_text = old_variant
            .filter(|v| v.variant_skill == Some(target_skill))
            .map(|v| v.stats.as_slice());
        let (stats, evidence) = text(
            input,
            facts,
            row,
            policy,
            renderer,
            compatible_text,
            effects.nonstat.as_ref(),
        )?;
        let mut replacement = old_by_class
            .get(old_selector.unwrap_or(class))
            .cloned()
            .unwrap_or_else(|| json!({}));
        replacement["class"] = json!(class);
        replacement["variant_skill"] = json!(target_skill);
        replacement["name"] = raw["Name"].clone();
        replacement["stats"] = json!(stats);
        variants.retain(|v| v["class"] != class);
        variants.push(replacement);
        records.push(json!({"class":class,"target":target,"source_row":row,"text":evidence,"relationship":relationship}));
    }
    if variants.is_empty() {
        out.remove("variants");
    } else {
        out.insert("variants".into(), json!(variants));
    }
    Ok(records)
}
