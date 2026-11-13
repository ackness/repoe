//! Shape/reference validation of prepared compatibility without normalizing its Values.

use super::source::{Facts, integer};
use crate::facts::reader;
use crate::ordinary_facts::coverage::{Action, Coverage, Issue};
use crate::raw_source::sha256_hex;
use pobr_data::catalog::{PassiveNodeDef, PassiveTreeMeta};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};

pub(super) fn validate(nodes: &[PassiveNodeDef], meta: &PassiveTreeMeta) -> Result<(), String> {
    let mut classes = BTreeSet::new();
    let mut asc = BTreeSet::new();
    let mut selectors = BTreeSet::new();
    for class in &meta.classes {
        if class.name.is_empty() || !classes.insert(class.name.as_str()) {
            return Err("empty/duplicate prepared class name".into());
        }
        selectors.insert(class.name.as_str());
        for a in &class.ascendancies {
            if a.id.is_empty() || a.name.is_empty() || !asc.insert(a.id.as_str()) {
                return Err("empty/duplicate prepared ascendancy identity".into());
            }
            selectors.insert(a.name.as_str());
        }
    }
    let mut skills = BTreeSet::new();
    let mut ids = BTreeSet::new();
    for node in nodes {
        if node.id.is_empty() || !ids.insert(&node.id) || !skills.insert(node.skill) {
            return Err("empty/duplicate prepared skill/id".into());
        }
        match (node.x, node.y) {
            (None, None) => {}
            (Some(x), Some(y)) if x.is_finite() && y.is_finite() => {}
            _ => {
                return Err(format!(
                    "node {}: finite coordinate pair required",
                    node.skill
                ));
            }
        }
    }
    let mut variant_bases = BTreeMap::new();
    for node in nodes {
        if let Some(id) = &node.ascendancy_id
            && !asc.contains(id.as_str())
        {
            return Err(format!("node {}: unavailable ascendancy {id}", node.skill));
        }
        if let Some(unlock) = &node.unlock_constraint {
            if unlock.nodes.iter().any(|id| !skills.contains(id)) {
                return Err(format!("node {}: unknown unlock node", node.skill));
            }
            if let Some(id) = &unlock.ascendancy
                && !asc.contains(id.as_str())
            {
                return Err(format!(
                    "node {}: unavailable unlock ascendancy",
                    node.skill
                ));
            }
        }
        let mut variant_selectors = BTreeSet::new();
        for v in &node.variants {
            if !selectors.contains(v.class.as_str()) || !variant_selectors.insert(&v.class) {
                return Err(format!(
                    "node {}: unknown/duplicate variant selector",
                    node.skill
                ));
            }
            if let Some(alias) = v.variant_skill {
                if skills.contains(&alias) {
                    return Err("variant alias collides with emitted node".into());
                }
                if let Some(base) = variant_bases.insert(alias, node.skill)
                    && base != node.skill
                {
                    return Err("variant alias has multiple base nodes".into());
                }
            }
        }
    }
    Ok(())
}

pub(super) fn metadata(
    raw: &Value,
    meta: &PassiveTreeMeta,
    facts: &Facts<'_>,
    coverage: &mut Coverage,
) -> Result<(Value, Vec<Value>), String> {
    let provided: BTreeSet<_> = meta.classes.iter().map(|c| c.name.as_str()).collect();
    let expected: BTreeSet<_> = facts.characters.keys().map(String::as_str).collect();
    if !provided.is_subset(&expected) {
        return Err("prepared metadata does not completely cover exact target class names".into());
    }
    let added: Vec<_> = expected.difference(&provided).copied().collect();
    for name in &added {
        let source = facts.tables.row("Characters", facts.characters[*name])?;
        coverage.decide(
            Issue::new(
                "new-class",
                *name,
                Action::EmittedWithGap,
                "prepared metadata does not completely cover exact target class names",
            )
            .observed(
                "definition_sha256",
                sha256_hex(&reader::json_bytes(source)?),
            )
            .observed("character", source.clone()),
        )?;
    }
    let mut out = raw.clone();
    let mut records = Vec::new();
    let classes = out["classes"]
        .as_array_mut()
        .ok_or("metadata classes must be an array")?;
    classes.extend(added.into_iter().map(|name| json!({"name":name})));
    for (position, output) in classes.iter_mut().enumerate() {
        let name = output["name"]
            .as_str()
            .ok_or("invalid prepared class name")?
            .to_owned();
        let row = facts.characters[&name];
        let source = facts.tables.row("Characters", row)?;
        let mut attrs = Vec::new();
        for (field, target) in [
            ("BaseStrength", "base_str"),
            ("BaseDexterity", "base_dex"),
            ("BaseIntelligence", "base_int"),
        ] {
            let value = integer(&source[field], field)?;
            output[target] = json!(value);
            attrs.push(json!({"column":field,"field":target,"raw":value,"output":value,
                "source_pointer":format!("/rows/{row}/values/{field}"),"legacy":raw["classes"][position][target]}));
        }
        let retained: Vec<_> = if position < meta.classes.len() {
            raw["classes"][position].as_object().ok_or("invalid prepared class")?.iter()
            .filter(|(field,_)|!["base_str","base_dex","base_int"].contains(&field.as_str()))
            .map(|(field,value)|Ok(json!({"field":field,"policy_pointer":format!("/legacy_metadata/value/classes/{position}/{}",token(field)),"value_sha256":sha256_hex(&reader::json_bytes(value)?)})))
            .collect::<Result<_,String>>()?
        } else {
            Vec::new()
        };
        records.push(json!({"policy_class_position":if position<meta.classes.len(){Some(position)}else{None},"name":name,"source_row":row,"character_id":source["Id"],
            "attributes":attrs,"retained_fields":retained,"output_class_sha256":sha256_hex(&reader::json_bytes(output)?)}));
    }
    let _: PassiveTreeMeta = serde_json::from_value(out.clone()).map_err(|e| e.to_string())?;
    Ok((out, records))
}

pub(super) fn token(value: &str) -> String {
    value.replace('~', "~0").replace('/', "~1")
}

// Exceptions bind original occurrences, never a replacement edge or a target lookup by graph ID.
pub(super) fn connections(
    nodes: &[PassiveNodeDef],
    raw: &Value,
    policy: &super::policy::Policy,
    facts: &Facts<'_>,
) -> Result<Vec<Value>, String> {
    let skills: BTreeSet<_> = nodes.iter().map(|n| n.skill).collect();
    let aliases: BTreeSet<_> = nodes
        .iter()
        .flat_map(|n| n.variants.iter().filter_map(|v| v.variant_skill))
        .collect();
    let cases: BTreeMap<_, _> = policy
        .legacy_connection_exceptions
        .iter()
        .enumerate()
        .map(|(i, c)| ((c.source_row, c.position), (i, c)))
        .collect();
    let mut consumed = BTreeSet::new();
    let mut records = Vec::new();
    for (source_row, node) in nodes.iter().enumerate() {
        for (position, &target) in node.connections.iter().enumerate() {
            if skills.contains(&target) || aliases.contains(&target) {
                continue;
            }
            let &(index, case) = cases.get(&(source_row, position)).ok_or_else(|| {
                format!("undeclared outside connection /{source_row}/connections/{position}")
            })?;
            let source_hash = sha256_hex(&reader::json_bytes(&raw[source_row])?);
            if case.skill != node.skill
                || case.id != node.id
                || case.target_skill != target
                || case.source_entry_sha256 != source_hash
            {
                return Err("prepared connection source identity/hash/target mismatch".into());
            }
            let &row = facts
                .passives
                .get(&case.target_passive_id)
                .ok_or("connection target stable Id missing")?;
            let target_raw = facts.tables.row("PassiveSkills", row)?;
            if row != case.target_row_evidence
                || super::source::graph_id(target_raw)? != target
                || target_raw["Name"].as_str() != Some(case.expected_target_name.as_str())
            {
                return Err("connection target row/name/graph mismatch".into());
            }
            consumed.insert(index);
            records.push(json!({"declaration":case,"source_entry_sha256":source_hash,
                "source_pointer":format!("/{source_row}/connections/{position}"),
                "actual_target":{"source_row":row,"id":target_raw["Id"],"name":target_raw["Name"],"graph_id":target},
                "scope":"retained prepared compatibility reference outside emitted membership; no added node, rewiring or reachability/eligibility certification"}));
        }
    }
    if consumed.len() != cases.len() {
        return Err(
            "unused/stale connection exception (including now emitted/variant target)".into(),
        );
    }
    Ok(records)
}
