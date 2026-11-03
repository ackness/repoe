//! Structured `unique -> base -> mods/roll/variant` relations over the pinned
//! vendor catalog, with base names resolved against target `BaseItemTypes`.
//!
//! The PoE2 client has no unique->base or unique->mods table: unique mod
//! assignment is server-side and the community catalog is the retained source.
//! This domain keeps every vendor field byte-traceable while resolving vendor
//! base names to target `BaseItemTypes`/`ItemClasses` identities by exact
//! `Name` equality. Name equality verifies that the vendor text names a real
//! target base; it is not an official unique->base link.
use std::collections::{BTreeMap, BTreeSet};
use std::path::PathBuf;

use pobr_data::catalog::item_overlay::UniquesDef;
use serde::Deserialize;
use serde_json::{Value, json};

use super::convert::{column, resolve, text};
use super::stat_set_codec::{policy::hex, read_pinned};
use crate::native_facts::reader::{Tables, VerifiedFacts};
use crate::raw_source::sha256_hex;

#[cfg(all(test, any(target_os = "linux", target_os = "macos")))]
mod tests;

pub(super) const TABLES: [&str; 2] = ["BaseItemTypes", "ItemClasses"];

/// `Has Alt Variant<suffix>: true` / `Selected Alt Variant<suffix>: N` slots,
/// in vendor order.
const ALT_SUFFIXES: [&str; 5] = ["", " Two", " Three", " Four", " Five"];

/// Boolean annotation keys kept in `flags`, matching the consumer's
/// `ModLineAnnotations` boolean set. `range`/`corruptedRange` carry values and
/// stay in `annotations` instead.
const FLAG_KEYS: [&str; 8] = [
    "rune",
    "enchant",
    "custom",
    "fractured",
    "desecrated",
    "mutated",
    "crafted",
    "unscalable",
];

/// Non-mod item-text directives (`kind` is the emitted discriminator). Vendor
/// `Variant:`/`Version:`/`Implicits:`/`Has Alt`/`Selected`/`Allow Duplicate`
/// lines are parsed into `selection`, and `Grants Skill:` stays a mod line.
/// `Requires ` keeps its trailing space; the bare `Replica` flag is matched by
/// exact equality so mod text starting with the word is not misfilled.
const DIRECTIVES: [(&str, &str); 13] = [
    ("Sockets:", "sockets"),
    ("Limited to:", "limited_to"),
    ("Radius:", "radius"),
    ("League:", "league"),
    ("Source:", "source"),
    ("Upgrade:", "upgrade"),
    ("Replica:", "replica"),
    ("Crafted:", "crafted"),
    ("Note:", "note"),
    ("Item Level:", "item_level"),
    ("LevelReq:", "level_req"),
    ("Quality:", "quality"),
    ("Requires ", "requires"),
];

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Policy {
    schema: String,
    version: String,
    source_sha256: String,
    source: Source,
    vendor: Vendor,
    source_metadata: SourceMetadata,
    ownership: Value,
    statement: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Source {
    path: String,
    member_of: String,
    bytes: u64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Vendor {
    repository: String,
    revision: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SourceMetadata {
    schema: String,
    generator: String,
}

pub(super) struct Converted {
    pub bytes: Vec<u8>,
    pub sidecars: BTreeMap<String, Vec<u8>>,
    pub protected_parents: Vec<PathBuf>,
    pub receipt: Value,
}

pub(super) fn convert(input: &VerifiedFacts, args: &super::CodecArgs) -> Result<Converted, String> {
    let pinned = read_pinned(&args.policy, &args.policy_sha256, "unique relations policy")?;
    let policy: Policy =
        serde_json::from_value(pinned.document.clone()).map_err(|e| e.to_string())?;
    let old = read_pinned(&args.source, &args.source_sha256, "legacy unique catalog")?;
    validate(input, args, &policy, &old.document, old.bytes.len() as u64)?;
    // The DTO tolerates unknown per-unique keys; this domain does not silently
    // drop source fields, so unexpected keys fail before projection.
    const UNIQUE_FIELDS: [&str; 8] = [
        "name",
        "base",
        "item_type",
        "raw",
        "variants",
        "league",
        "source",
        "upgrade",
    ];
    for (index, entry) in old.document["uniques"]
        .as_array()
        .ok_or("legacy uniques must be an array")?
        .iter()
        .enumerate()
    {
        for key in entry
            .as_object()
            .ok_or("legacy unique entry must be an object")?
            .keys()
        {
            if !UNIQUE_FIELDS.contains(&key.as_str()) {
                return Err(format!("legacy unique {index}: unexpected field {key}"));
            }
        }
    }
    let source: UniquesDef =
        serde_json::from_value(old.document.clone()).map_err(|e| e.to_string())?;
    let legacy_meta = old.document["_meta"].clone();
    let (relations, diagnostics) = project(input, &source)?;
    let document = json!({
        "_meta": {
            "schema": "unique_relations/v1",
            "generator": "pobr-data-adapter ordinary uniques",
            "facts_manifest_sha256": sha256_hex(&input.manifest_bytes),
            "legacy_source_sha256": args.source_sha256,
            "policy_sha256": args.policy_sha256,
            "legacy_metadata_present": !legacy_meta.is_null(),
            "legacy_metadata": legacy_meta,
            "ownership": policy.ownership,
            "diagnostics": diagnostics,
        },
        "uniques": relations,
    });
    let receipt = json!({
        "uniques": source.uniques.len(),
        "interpretation_policy": pinned.document,
        "legacy_source_sha256": args.source_sha256,
        "diagnostics": diagnostics,
        "semantic_boundary": "Vendor base names resolve to target BaseItemTypes/ItemClasses only by exact Name equality; the official client ships no unique->base or unique->mods table, so mod lists, roll ranges, variants and selection remain pinned vendor text, not target facts.",
    });
    Ok(Converted {
        bytes: super::pretty_bytes(&document)?,
        sidecars: BTreeMap::from([
            ("legacy-uniques.json".into(), old.bytes),
            ("codec-policy.json".into(), pinned.bytes),
        ]),
        protected_parents: vec![old.parent, pinned.parent],
        receipt,
    })
}

fn validate(
    input: &VerifiedFacts,
    args: &super::CodecArgs,
    p: &Policy,
    source: &Value,
    source_bytes: u64,
) -> Result<(), String> {
    if p.schema != "pobr-ordinary-uniques-policy/v1"
        || p.version != input.manifest["source_identity"]["game_patch"]
        || p.source_sha256 != args.source_sha256
        || p.source.path != format!("{}/overlay/uniques.json", p.version)
        || p.source.member_of != format!("publication/{}-game.plan.json", p.version)
        || p.source.bytes != source_bytes
        || p.vendor.repository != "https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2"
        || p.statement.trim().is_empty()
    {
        return Err("unique relations policy identity mismatch".into());
    }
    hex(&p.vendor.revision, 40, "vendor revision")?;
    let meta = &source["_meta"];
    if meta["schema"] != json!(p.source_metadata.schema)
        || meta["generator"] != json!(p.source_metadata.generator)
        || meta["vendor"] != json!("PathOfBuilding-PoE2")
        || meta["vendor_commit"] != json!(p.vendor.revision)
    {
        return Err("unique source metadata/vendor identity mismatch".into());
    }
    Ok(())
}

fn project(input: &VerifiedFacts, source: &UniquesDef) -> Result<(Vec<Value>, Value), String> {
    for (table, field, kind, reference) in [
        ("BaseItemTypes", "Id", "string", None),
        ("BaseItemTypes", "Name", "string", None),
        (
            "BaseItemTypes",
            "ItemClass",
            "foreignrow",
            Some("ItemClasses"),
        ),
        ("ItemClasses", "Id", "string", None),
    ] {
        column(
            input,
            table,
            &[field],
            &json!({"name":field,"type":kind,"array":false,"interval":false,
                "references":reference.map(|t| json!({"table":t}))}),
        )?;
    }
    let tables = Tables::selected(input, &TABLES)?;
    let mut by_name: BTreeMap<String, Vec<Value>> = BTreeMap::new();
    for row in 0..tables.len("BaseItemTypes") {
        let base = tables.row("BaseItemTypes", row)?;
        let id = text(&base["Id"]).map_err(|e| format!("BaseItemTypes/{row}/Id: {e}"))?;
        if id.is_empty() {
            return Err(format!("BaseItemTypes/{row}: empty Id"));
        }
        let item_class = if base["ItemClass"].is_null() {
            Value::Null
        } else {
            json!(
                resolve(&tables, "ItemClasses", &base["ItemClass"], "Id")
                    .map_err(|e| format!("BaseItemTypes/{row}/ItemClass: {e}"))?
            )
        };
        let name = text(&base["Name"]).map_err(|e| format!("BaseItemTypes/{row}/Name: {e}"))?;
        if name.is_empty() {
            continue;
        }
        by_name.entry(name.into()).or_default().push(json!({
            "row": row, "id": id, "item_class": item_class,
        }));
    }
    let mut uniques = Vec::new();
    let mut diagnostics = Diagnostics::default();
    for (index, unique) in source.uniques.iter().enumerate() {
        uniques.push(relation(index, unique, &by_name, &mut diagnostics)?);
    }
    Ok((uniques, diagnostics.finish(source.uniques.len())))
}

#[derive(Default)]
struct Diagnostics {
    name_line_mismatches: Vec<Value>,
    base_column_mismatches: Vec<Value>,
    no_bases: Vec<Value>,
    unresolved_bases: Vec<Value>,
    ambiguous_bases: Vec<Value>,
    index_column_mismatches: Vec<Value>,
    unparsed_grants_skill: Vec<Value>,
    repeated_implicits: Vec<Value>,
    counts: Counts,
}

#[derive(Default)]
struct Counts {
    bases: usize,
    resolved_bases: usize,
    mods: usize,
    rolled_mods: usize,
    implicit_mods: usize,
    variants: usize,
    versions: usize,
    alt_variant_slots: usize,
    groups: usize,
    directives: usize,
    grants_skill: usize,
}

impl Diagnostics {
    fn finish(self, uniques: usize) -> Value {
        json!({
            "name_line_mismatches": self.name_line_mismatches,
            "base_column_mismatches": self.base_column_mismatches,
            "no_bases": self.no_bases,
            "unresolved_bases": self.unresolved_bases,
            "ambiguous_bases": self.ambiguous_bases,
            "index_column_mismatches": self.index_column_mismatches,
            "unparsed_grants_skill": self.unparsed_grants_skill,
            "repeated_implicits": self.repeated_implicits,
            "counts": {
                "uniques": uniques,
                "bases": self.counts.bases,
                "resolved_bases": self.counts.resolved_bases,
                "mods": self.counts.mods,
                "rolled_mods": self.counts.rolled_mods,
                "implicit_mods": self.counts.implicit_mods,
                "variants": self.counts.variants,
                "versions": self.counts.versions,
                "alt_variant_slots": self.counts.alt_variant_slots,
                "groups": self.counts.groups,
                "directives": self.counts.directives,
                "grants_skill": self.counts.grants_skill,
            },
        })
    }
}

#[derive(Default)]
struct Annotations {
    variants: Vec<u32>,
    versions: Vec<u32>,
    groups: Vec<u32>,
    tags: Vec<String>,
    flags: Vec<String>,
    range: Option<f64>,
    corrupted_range: Option<f64>,
    other: Vec<Value>,
}

impl Annotations {
    fn emit(&self, out: &mut serde_json::Map<String, Value>) {
        for (key, list) in [
            ("variants", &self.variants),
            ("versions", &self.versions),
            ("groups", &self.groups),
        ] {
            if !list.is_empty() {
                out.insert(key.into(), json!(list));
            }
        }
        if !self.tags.is_empty() {
            out.insert("tags".into(), json!(self.tags));
        }
        if !self.flags.is_empty() {
            out.insert("flags".into(), json!(self.flags));
        }
        if let Some(range) = self.range {
            out.insert("range".into(), json!(range));
        }
        if let Some(range) = self.corrupted_range {
            out.insert("corrupted_range".into(), json!(range));
        }
        if !self.other.is_empty() {
            out.insert("annotations".into(), json!(self.other));
        }
    }
}

fn u32_list(value: &str, key: &str) -> Result<Vec<u32>, String> {
    value
        .split(',')
        .map(|part| {
            part.trim()
                .parse::<u32>()
                .map_err(|_| format!("invalid {{{key}:}} id list member: {part}"))
        })
        .collect()
}

/// Strips leading `{key[:value]}` annotation groups, mirroring the consumer's
/// `parse_mod_line` loop. `variant`/`version`/`group`/`tags` go to typed lists,
/// known booleans to `flags`, everything else verbatim to `other`.
fn annotations(line: &str) -> Result<(Annotations, &str), String> {
    let mut result = Annotations::default();
    let mut rest = line;
    loop {
        let trimmed = rest.trim_start();
        if !trimmed.starts_with('{') {
            return Ok((result, trimmed));
        }
        let Some(close) = trimmed.find('}') else {
            return Ok((result, trimmed));
        };
        let inner = &trimmed[1..close];
        let (key, value) = match inner.split_once(':') {
            Some((key, value)) => (key, Some(value)),
            None => (inner, None),
        };
        match key {
            "variant" => result
                .variants
                .extend(u32_list(value.unwrap_or(""), "variant")?),
            "version" => result
                .versions
                .extend(u32_list(value.unwrap_or(""), "version")?),
            "group" => result
                .groups
                .extend(u32_list(value.unwrap_or(""), "group")?),
            "tags" => result.tags.extend(
                value
                    .unwrap_or("")
                    .split(',')
                    .map(|tag| tag.trim().to_string())
                    .filter(|tag| !tag.is_empty()),
            ),
            // The consumer carries these as numeric fields; an unparseable
            // value is preserved verbatim instead of silently dropped.
            "range" | "corruptedRange" => {
                let target = if key == "range" {
                    &mut result.range
                } else {
                    &mut result.corrupted_range
                };
                match value.and_then(|v| v.trim().parse::<f64>().ok()) {
                    Some(parsed) => *target = Some(parsed),
                    None => result.other.push(json!({"key": key, "value": value})),
                }
            }
            _ if value.is_none() && FLAG_KEYS.contains(&key) => result.flags.push(key.to_string()),
            other => result.other.push(json!({
                "key": other,
                "value": value,
            })),
        }
        rest = &trimmed[close + 1..];
    }
}

/// Integral endpoints stay JSON integers; only true fractions emit floats.
/// `as` saturates, so the round-trip comparison is safe for out-of-range input.
fn number(value: f64) -> Value {
    let integer = value as i64;
    if integer as f64 == value {
        return json!(integer);
    }
    json!(value)
}

/// Scans `[+-]?(min-max)` roll templates, mirroring the consumer's
/// `apply_range`/`try_range_at` grammar (optional sign, optional negative or
/// decimal endpoints).
fn rolls(text: &str) -> Vec<Value> {
    let mut result = Vec::new();
    let bytes = text.as_bytes();
    let mut index = 0;
    while index < bytes.len() {
        let mut at = index;
        let sign = match bytes[at] {
            byte @ (b'+' | b'-') => {
                at += 1;
                Some(byte as char)
            }
            _ => None,
        };
        if bytes.get(at) == Some(&b'(')
            && let Some(close) = text[at + 1..].find(')')
            && let Some((min, max)) = range_body(&text[at + 1..at + 1 + close])
        {
            result.push(json!({"min": number(min), "max": number(max), "sign": sign}));
            index = at + 1 + close + 1;
            continue;
        }
        index += text[index..].chars().next().map_or(1, char::len_utf8);
    }
    result
}

/// `min-max` where each endpoint matches `-?\d+\.?\d*` (the vendor roll
/// grammar); the separating hyphen cannot be `min`'s own leading sign.
fn range_body(body: &str) -> Option<(f64, f64)> {
    fn endpoint(s: &str) -> Option<f64> {
        let digits = s.strip_prefix('-').unwrap_or(s);
        let (integer, fraction) = match digits.split_once('.') {
            Some((i, f)) => (i, Some(f)),
            None => (digits, None),
        };
        if integer.is_empty()
            || !integer.bytes().all(|b| b.is_ascii_digit())
            || !fraction.is_none_or(|f| f.bytes().all(|b| b.is_ascii_digit()))
        {
            return None;
        }
        s.parse().ok()
    }
    let bytes = body.as_bytes();
    let start = usize::from(bytes.first() == Some(&b'-'));
    let separator = start + body[start..].find('-')?;
    Some((
        endpoint(&body[..separator])?,
        endpoint(&body[separator + 1..])?,
    ))
}

/// `Grants Skill: [Level (a-b)|Level N] Name` structured convenience; the
/// raw text stays authoritative. Vendor forms without an explicit `Level`
/// prefix (for example `Raise Shield` or `Parry`) carry `skill_name` alone.
fn grants_skill(text: &str) -> Option<Value> {
    let rest = text.strip_prefix("Grants Skill:")?.trim();
    let Some(levelled) = rest.strip_prefix("Level") else {
        return (!rest.is_empty()).then(|| json!({"skill_name": rest}));
    };
    let rest = levelled.trim_start();
    let (level, name) = if rest.starts_with('(') {
        let close = rest.find(')')?;
        let (min, max) = range_body(&rest[1..close])?;
        (
            json!({"min": number(min), "max": number(max)}),
            rest[close + 1..].trim(),
        )
    } else {
        let end = rest.find(char::is_whitespace).unwrap_or(rest.len());
        let value: u64 = rest[..end].parse().ok()?;
        (json!({"value": value}), rest[end..].trim())
    };
    if name.is_empty() {
        return None;
    }
    Some(json!({"level": level, "skill_name": name}))
}

fn directive(text: &str) -> Option<&'static str> {
    if text == "Replica" {
        return Some("replica");
    }
    DIRECTIVES
        .iter()
        .find(|(prefix, _)| text.starts_with(prefix))
        .map(|(_, kind)| *kind)
}

/// `Has Alt Variant<suffix>: true`; a `Has Alt Variant`-prefixed line in any
/// other shape is an explicit parse failure, never a silent mod line.
fn has_alt(text: &str) -> Result<Option<usize>, String> {
    for (slot, suffix) in ALT_SUFFIXES.iter().enumerate() {
        if let Some(rest) = text.strip_prefix(&format!("Has Alt Variant{suffix}:")) {
            return if rest.trim() == "true" {
                Ok(Some(slot))
            } else {
                Err(format!("invalid Has Alt Variant value: {rest}"))
            };
        }
    }
    if text.starts_with("Has Alt Variant") {
        return Err(format!("invalid Has Alt Variant line: {text}"));
    }
    Ok(None)
}

/// `Selected Alt Variant<suffix>: N` → (slot, value text).
fn selected_alt(text: &str) -> Result<Option<(usize, &str)>, String> {
    for (slot, suffix) in ALT_SUFFIXES.iter().enumerate() {
        if let Some(rest) = text.strip_prefix(&format!("Selected Alt Variant{suffix}:")) {
            return Ok(Some((slot, rest)));
        }
    }
    if text.starts_with("Selected Alt Variant") {
        return Err(format!("invalid Selected Alt Variant line: {text}"));
    }
    Ok(None)
}

fn u32_value(text: &str, key: &str) -> Result<u32, String> {
    text.trim()
        .parse::<u32>()
        .map_err(|_| format!("invalid {key} value: {text}"))
}

fn relation(
    index: usize,
    unique: &pobr_data::catalog::item_overlay::UniqueDef,
    by_name: &BTreeMap<String, Vec<Value>>,
    diagnostics: &mut Diagnostics,
) -> Result<Value, String> {
    let mut bases = Vec::new();
    let mut mods = Vec::new();
    let mut directives = Vec::new();
    let mut variants = Vec::new();
    let mut versions = Vec::new();
    let mut alt_slots = BTreeSet::new();
    let mut implicit_count: Option<u32> = None;
    let mut pending_implicits = 0_u32;
    let mut selected = serde_json::Map::new();
    let mut groups = BTreeSet::new();
    let ctx = |line_index: usize, e: String| {
        format!("unique {index} ({}), line {line_index}: {e}", unique.name)
    };

    for (line_index, raw_line) in unique.raw.lines().enumerate() {
        let line = raw_line.trim();
        if line.is_empty() {
            continue;
        }
        if line_index == 0 {
            if line != unique.name {
                diagnostics.name_line_mismatches.push(json!({
                    "unique_index": index, "name": unique.name, "line": line,
                }));
            }
            continue;
        }
        let (ann, stripped) = annotations(line).map_err(|e| ctx(line_index, e))?;
        groups.extend(ann.groups.iter().copied());
        // Selection directives drive variant/version/group choices.
        if let Some(name) = stripped.strip_prefix("Variant:") {
            variants.push(name.trim().to_string());
            continue;
        }
        if let Some(name) = stripped.strip_prefix("Version:") {
            versions.push(name.trim().to_string());
            continue;
        }
        if let Some(value) = stripped.strip_prefix("Implicits:") {
            let count = u32_value(value, "Implicits").map_err(|e| ctx(line_index, e))?;
            if implicit_count.replace(count).is_some() {
                diagnostics.repeated_implicits.push(json!({
                    "unique_index": index, "name": unique.name, "source_line": line_index,
                }));
            }
            pending_implicits = count;
            continue;
        }
        if let Some(slot) = has_alt(stripped).map_err(|e| ctx(line_index, e))? {
            alt_slots.insert(slot);
            continue;
        }
        if let Some(value) = stripped.strip_prefix("Allow Duplicate Variants:") {
            selected.insert(
                "allow_duplicate_variants".into(),
                json!({"value": value.trim() == "true", "source_line": line_index}),
            );
            continue;
        }
        if let Some(value) = stripped.strip_prefix("Selected Variant Group:") {
            let (group, variant) = value.trim().split_once('=').ok_or_else(|| {
                ctx(
                    line_index,
                    format!("invalid Selected Variant Group line: {value}"),
                )
            })?;
            selected
                .entry("variant_groups")
                .or_insert_with(|| json!([]))
                .as_array_mut()
                .ok_or_else(|| ctx(line_index, "variant_groups must be an array".into()))?
                .push(json!({
                    "group": u32_value(group, "Selected Variant Group").map_err(|e| ctx(line_index, e))?,
                    "variant": u32_value(variant, "Selected Variant Group").map_err(|e| ctx(line_index, e))?,
                    "source_line": line_index,
                }));
            continue;
        }
        if let Some((slot, value)) = selected_alt(stripped).map_err(|e| ctx(line_index, e))? {
            selected.insert(
                format!("alt_variant_{slot}"),
                json!({
                    "value": u32_value(value, "Selected Alt Variant").map_err(|e| ctx(line_index, e))?,
                    "source_line": line_index,
                }),
            );
            continue;
        }
        if let Some(value) = stripped.strip_prefix("Selected Version:") {
            selected.insert(
                "version".into(),
                json!({
                    "value": u32_value(value, "Selected Version").map_err(|e| ctx(line_index, e))?,
                    "source_line": line_index,
                }),
            );
            continue;
        }
        if let Some(value) = stripped.strip_prefix("Selected Variant:") {
            selected.insert(
                "variant".into(),
                json!({
                    "value": u32_value(value, "Selected Variant").map_err(|e| ctx(line_index, e))?,
                    "source_line": line_index,
                }),
            );
            continue;
        }
        // Other item-text directives keep their whole line verbatim.
        if let Some(kind) = directive(stripped) {
            let mut entry = json!({
                "source_line": line_index,
                "kind": kind,
                "text": stripped,
            });
            ann.emit(entry.as_object_mut().ok_or("directive must be an object")?);
            directives.push(entry);
            continue;
        }
        // Base lines are vendor text that exactly names a target base item.
        if let Some(candidates) = by_name.get(stripped) {
            let ambiguous = candidates.len() > 1;
            let mut entry = json!({
                "source_line": line_index,
                "name": stripped,
                "base_items": candidates,
                "resolution": if ambiguous { "ambiguous" } else { "resolved" },
            });
            ann.emit(entry.as_object_mut().ok_or("base must be an object")?);
            if ambiguous {
                diagnostics.ambiguous_bases.push(json!({
                    "unique_index": index, "name": unique.name,
                    "base": stripped, "candidates": candidates,
                }));
            } else {
                diagnostics.counts.resolved_bases += 1;
            }
            diagnostics.counts.bases += 1;
            bases.push(entry);
            continue;
        }
        // Remaining lines are effect text; unresolvable text is kept, not dropped.
        let implicit = pending_implicits > 0;
        pending_implicits = pending_implicits.saturating_sub(1);
        let kind = if stripped.starts_with("Grants Skill:") {
            diagnostics.counts.grants_skill += 1;
            "grants_skill"
        } else {
            "mod"
        };
        let mut entry = json!({
            "source_line": line_index,
            "kind": kind,
            "text": stripped,
            "implicit": implicit,
        });
        ann.emit(entry.as_object_mut().ok_or("mod must be an object")?);
        let rolled = rolls(stripped);
        if !rolled.is_empty() {
            entry["rolled"] = json!(true);
            entry["rolls"] = json!(rolled);
            diagnostics.counts.rolled_mods += 1;
        }
        if kind == "grants_skill" {
            match grants_skill(stripped) {
                Some(grant) => entry["grants_skill"] = grant,
                None => diagnostics.unparsed_grants_skill.push(json!({
                    "unique_index": index, "name": unique.name, "source_line": line_index,
                })),
            }
        }
        diagnostics.counts.mods += 1;
        diagnostics.counts.implicit_mods += usize::from(implicit);
        mods.push(entry);
    }
    let base_names: Vec<&str> = bases.iter().filter_map(|b| b["name"].as_str()).collect();
    if bases.is_empty() {
        diagnostics.no_bases.push(json!({
            "unique_index": index, "name": unique.name,
        }));
    }
    if !base_names.contains(&unique.base.as_str()) {
        diagnostics.unresolved_bases.push(json!({
            "unique_index": index, "name": unique.name,
            "index_base": unique.base, "matched_bases": base_names,
        }));
    }
    if let Some(first) = bases.first()
        && first["name"] != json!(unique.base)
    {
        diagnostics.base_column_mismatches.push(json!({
            "unique_index": index, "name": unique.name,
            "index_base": unique.base, "first_base_line": first["name"],
        }));
    }
    // Index columns and parsed directives must agree; parsed text stays authoritative.
    if unique.variants != variants {
        diagnostics.index_column_mismatches.push(json!({
            "unique_index": index, "name": unique.name, "column": "variants",
            "index": unique.variants, "parsed": variants,
        }));
    }
    for (column_name, kind, prefix, index_value) in [
        ("league", "league", "League: ", unique.league.as_deref()),
        ("source", "source", "Source: ", unique.source.as_deref()),
        ("upgrade", "upgrade", "Upgrade: ", unique.upgrade.as_deref()),
    ] {
        if let Some(value) = index_value {
            let expected = format!("{prefix}{value}");
            let matched = directives
                .iter()
                .any(|d| d["kind"] == json!(kind) && d["text"].as_str() == Some(expected.as_str()));
            if !matched {
                diagnostics.index_column_mismatches.push(json!({
                    "unique_index": index, "name": unique.name, "column": column_name,
                    "index": value,
                }));
            }
        }
    }
    diagnostics.counts.variants += variants.len();
    diagnostics.counts.versions += versions.len();
    diagnostics.counts.alt_variant_slots += alt_slots.len();
    diagnostics.counts.groups += groups.len();
    diagnostics.counts.directives += directives.len();
    let mut selection = serde_json::Map::new();
    selection.insert("variants".into(), json!(variants));
    selection.insert("versions".into(), json!(versions));
    selection.insert("alt_variant_slots".into(), json!(alt_slots));
    selection.insert("groups".into(), json!(groups));
    if !selected.is_empty() {
        selection.insert("selected".into(), json!(selected));
    }
    Ok(json!({
        "name": unique.name,
        "item_type": unique.item_type,
        "bases": bases,
        "selection": selection,
        "implicit_count": implicit_count,
        "mods": mods,
        "directives": directives,
        "raw": unique.raw,
    }))
}
