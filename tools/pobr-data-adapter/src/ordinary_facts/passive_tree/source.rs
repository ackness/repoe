//! Authenticated physical identities, complete stat slots and whole-row context.

use super::policy::{Policy, VARIABLES};
use crate::facts::reader::{Tables, VerifiedFacts};
use crate::raw_source::sha256_hex;
use pobr_data::native_stat::{NativeStat, NativeStatProvenance, NativeStatReference};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};

/// Historical evidence only. Rows retain their native wrapper and old `_row`;
/// callers must join through stable Id, never through a target row number.
pub(super) struct ContextBaseline {
    pub fields: Vec<String>,
    pub rows: BTreeMap<String, Value>,
}

impl ContextBaseline {
    pub fn read(
        document: Value,
        qualification: &super::policy::Qualification,
    ) -> Result<Self, String> {
        if document["table"] != "PassiveSkills"
            || document["raw_resource"] != "Data/Balance/PassiveSkills.datc64"
            || document["row_key"]
                .as_str()
                .is_none_or(|description| description.trim().is_empty())
        {
            return Err("tree context baseline must be a native PassiveSkills table".into());
        }
        let fields = physical_fields(&document, "tree context baseline")?;
        let mut rows = BTreeMap::new();
        for (index, row) in document["rows"]
            .as_array()
            .ok_or("tree context baseline rows must be an array")?
            .iter()
            .enumerate()
        {
            if !row.is_object() || row["_row"].as_u64() != Some(index as u64) {
                return Err(format!(
                    "tree context baseline row {index}: invalid native row"
                ));
            }
            let values = row["values"].as_object().ok_or_else(|| {
                format!("tree context baseline row {index}: values must be an object")
            })?;
            if values.keys().ne(fields.iter()) {
                return Err(format!(
                    "tree context baseline row {index}: incomplete physical fields"
                ));
            }
            let id = values["Id"]
                .as_str()
                .filter(|id| !id.trim().is_empty())
                .ok_or("tree context baseline has an empty/invalid Id")?;
            if rows.insert(id.to_owned(), row.clone()).is_some() {
                return Err(format!("tree context baseline has a duplicate Id: {id}"));
            }
        }
        let baseline = Self {
            fields: fields.into_iter().collect(),
            rows,
        };
        let raw = baseline
            .row(&qualification.reference_passive_id)
            .ok_or("tree context baseline is missing the reviewed passive reference")?;
        if super::refresh::hash(&context(raw)?)? != qualification.context_sha256 {
            return Err("tree context baseline reference context SHA256 mismatch".into());
        }
        Ok(baseline)
    }

    pub fn row(&self, id: &str) -> Option<&Value> {
        self.rows.get(id).map(|row| &row["values"])
    }
}

fn physical_fields(document: &Value, label: &str) -> Result<BTreeSet<String>, String> {
    let mut fields = BTreeSet::new();
    for field in document["physical_fields"]
        .as_array()
        .ok_or_else(|| format!("{label} physical_fields must be an array"))?
    {
        let field = field
            .as_str()
            .filter(|name| !name.trim().is_empty())
            .ok_or_else(|| format!("{label} has an invalid physical field"))?;
        if !fields.insert(field.to_owned()) {
            return Err(format!("{label} has a duplicate physical field"));
        }
    }
    if !fields.contains("Id") {
        return Err(format!("{label} fields must include Id"));
    }
    Ok(fields)
}

/// The sole owner of column comparison views. It never changes target facts.
#[derive(Default)]
pub(super) struct RowContext<'a> {
    pub baseline: Option<&'a ContextBaseline>,
    columns: Option<&'a super::refresh::ContextColumns>,
    pub change: Option<ColumnChange>,
    pub diagnostic: bool,
}
pub(super) struct ColumnChange {
    pub bound_fields_sha256: String,
    pub target_fields_sha256: String,
    pub added: Vec<String>,
    pub removed: Vec<String>,
}
impl<'a> RowContext<'a> {
    fn new(
        input: &VerifiedFacts,
        baseline: Option<&'a ContextBaseline>,
        columns: Option<&'a super::refresh::ContextColumns>,
        forward: bool,
    ) -> Result<Self, String> {
        let Some(old) = baseline else {
            if columns.is_some() {
                return Err("context_columns requires a verified context baseline".into());
            }
            return Ok(Self::default());
        };
        if let Some(entry) = columns {
            entry.validate()?;
        }
        let table = &input.documents["tables/PassiveSkills.json"];
        // Tables::selected has already checked target row wrappers, exact value
        // keys and physical column mapping; only the sorted inventory is needed.
        let target = physical_fields(table, "target PassiveSkills")?;
        let bound: BTreeSet<_> = old.fields.iter().cloned().collect();
        let added: Vec<_> = target.difference(&bound).cloned().collect();
        let removed: Vec<_> = bound.difference(&target).cloned().collect();
        let bound_hash = super::refresh::hash(&old.fields)?;
        let target_hash = super::refresh::hash(&target.iter().collect::<Vec<_>>())?;
        let changed = !added.is_empty() || !removed.is_empty();
        if let Some(entry) = columns {
            let expected_added: BTreeSet<_> = entry.added.iter().map(|c| &c.field).collect();
            let expected_removed: BTreeSet<_> = entry.removed.iter().map(|c| &c.field).collect();
            if !changed
                || entry.bound_fields_sha256 != bound_hash
                || entry.target_fields_sha256 != target_hash
                || expected_added != added.iter().collect()
                || expected_removed != removed.iter().collect()
            {
                return Err("stale or mismatched context_columns field evidence".into());
            }
        }
        Ok(Self {
            baseline,
            columns,
            change: changed.then_some(ColumnChange {
                bound_fields_sha256: bound_hash,
                target_fields_sha256: target_hash,
                added,
                removed,
            }),
            diagnostic: changed && columns.is_none() && forward,
        })
    }

    /// Project only after adjusting a comparison copy. Diagnostic views are
    /// usable only when this exact projection equals the authenticated old row.
    pub fn project(
        &self,
        raw: &Value,
        projection: impl Fn(&Value) -> Result<Value, String>,
    ) -> Result<Value, String> {
        if self.columns.is_none() && !self.diagnostic {
            return projection(raw);
        }
        let old = raw["Id"].as_str().and_then(|id| self.baseline?.row(id));
        let mut adjusted = raw.as_object().ok_or("invalid passive row")?.clone();
        if let Some(columns) = self.columns {
            for column in &columns.added {
                if adjusted.get(&column.field) == Some(&column.neutral_value) {
                    adjusted.remove(&column.field);
                }
            }
            for column in &columns.removed {
                if old.and_then(|raw| raw.get(&column.field)) == Some(&column.constant_value) {
                    adjusted.insert(column.field.clone(), column.constant_value.clone());
                }
            }
        } else if self.diagnostic
            && let Some(old) = old
        {
            let change = self
                .change
                .as_ref()
                .ok_or("missing diagnostic field change")?;
            for field in &change.added {
                adjusted.remove(field);
            }
            for field in &change.removed {
                adjusted.insert(field.clone(), old[field].clone());
            }
        }
        let projected = projection(&Value::Object(adjusted))?;
        if self.diagnostic && old.map(&projection).transpose()?.as_ref() != Some(&projected) {
            return projection(raw);
        }
        Ok(projected)
    }
}

pub(super) struct Facts<'a> {
    pub tables: Tables<'a>,
    pub passives: BTreeMap<String, usize>,
    pub characters: BTreeMap<String, usize>,
    pub involved: BTreeMap<usize, Vec<usize>>,
    pub relations: Vec<Value>,
    pub reference_row: usize,
    pub reference_context: Value,
    pub slots: Vec<String>,
    pub context: RowContext<'a>,
}

impl<'a> Facts<'a> {
    pub fn read(input: &'a VerifiedFacts, policy: &Policy) -> Result<Self, String> {
        Self::read_with_context(input, policy, None, None, false)
    }
    pub fn read_with_context(
        input: &'a VerifiedFacts,
        policy: &Policy,
        baseline: Option<&'a ContextBaseline>,
        columns: Option<&'a super::refresh::ContextColumns>,
        forward: bool,
    ) -> Result<Self, String> {
        let tables = Tables::selected(input, &super::TABLES)?;
        for (table, field, kind, array, target) in [
            ("PassiveSkills", "Id", "string", false, None),
            ("PassiveSkills", "Name", "string", false, None),
            ("PassiveSkills", "Icon_DDSFile", "string", false, None),
            ("PassiveSkills", "PassiveSkillGraphId", "u16", false, None),
            ("PassiveSkills", "Stats", "foreignrow", true, Some("Stats")),
            ("Stats", "Id", "string", false, None),
            ("Characters", "Id", "string", false, None),
            ("Characters", "Name", "string", false, None),
            ("Characters", "BaseStrength", "i32", false, None),
            ("Characters", "BaseDexterity", "i32", false, None),
            ("Characters", "BaseIntelligence", "i32", false, None),
            (
                "ClassPassiveSkillOverrides",
                "CharacterToOverrideFor",
                "foreignrow",
                false,
                Some("Characters"),
            ),
            (
                "ClassPassiveSkillOverrides",
                "SkillToOverride",
                "foreignrow",
                false,
                Some("PassiveSkills"),
            ),
            (
                "ClassPassiveSkillOverrides",
                "Override",
                "foreignrow",
                false,
                Some("PassiveSkills"),
            ),
        ] {
            column(input, table, field, kind, array, target)?;
        }
        let fields = input.documents["tables/PassiveSkills.json"]["physical_fields"]
            .as_array()
            .ok_or("missing passive fields")?;
        let mut indexed = BTreeMap::new();
        for f in fields {
            let name = f.as_str().ok_or("invalid field name")?;
            if let Some(slot) = name
                .strip_prefix("Stat")
                .and_then(|s| s.strip_suffix("Value"))
            {
                let n = slot
                    .parse::<usize>()
                    .map_err(|_| "invalid stat value slot column")?;
                if n == 0 || slot != n.to_string() || indexed.insert(n, name.to_owned()).is_some() {
                    return Err("invalid/duplicate stat value slot column".into());
                }
                column(input, "PassiveSkills", name, "i32", false, None)?;
            }
        }
        if indexed.is_empty() || indexed.keys().copied().ne(1..=indexed.len()) {
            return Err("missing/noncontiguous stat value slots".into());
        }
        let slots: Vec<_> = indexed.into_values().collect();
        let passives = identities(&tables, "PassiveSkills", "Id")?;
        let characters = identities(&tables, "Characters", "Name")?;
        for row in 0..tables.len("Characters") {
            let raw = tables.row("Characters", row)?;
            for f in ["BaseStrength", "BaseDexterity", "BaseIntelligence"] {
                integer(&raw[f], f)?;
            }
        }
        let mut involved: BTreeMap<usize, Vec<usize>> = BTreeMap::new();
        let mut relations = Vec::new();
        for row in 0..tables.len("ClassPassiveSkillOverrides") {
            let raw = tables.row("ClassPassiveSkillOverrides", row)?;
            let character = reference(&tables, "Characters", &raw["CharacterToOverrideFor"])?;
            let base = reference(&tables, "PassiveSkills", &raw["SkillToOverride"])?;
            let replacement = reference(&tables, "PassiveSkills", &raw["Override"])?;
            involved.entry(base).or_default().push(row);
            involved.entry(replacement).or_default().push(row);
            let mut endpoints = Vec::new();
            for (field, source_row) in [("SkillToOverride", base), ("Override", replacement)] {
                let definition = tables.row("PassiveSkills", source_row)?;
                endpoints.push(json!({"field":field,"source_row":source_row,"id":definition["Id"],"graph_id":graph_id(definition)?}));
            }
            relations.push(json!({"source_row":row,"raw":raw,"character":{"source_row":character,"id":tables.row("Characters",character)?["Id"],"name":tables.row("Characters",character)?["Name"]},"definitions":endpoints}));
        }
        let &reference_row = passives
            .get(&policy.qualification.reference_passive_id)
            .ok_or("missing reviewed passive reference")?;
        let raw = tables.row("PassiveSkills", reference_row)?;
        let row_context = RowContext::new(input, baseline, columns, forward)?;
        let mut out = Self {
            tables,
            passives,
            characters,
            involved,
            relations,
            reference_row,
            reference_context: context(raw)?,
            slots,
            context: row_context,
        };
        if out.context.diagnostic || columns.is_some() {
            // Validate the actual qualification row before adjusting its view.
            // Projection separately preflights its consumed nodes and variants;
            // unused definitions do not become new stat consumers.
            let stats = out.stats(input, reference_row)?;
            let stats: Vec<_> = stats.into_iter().map(|s| (s.id, s.value)).collect();
            super::render::Renderer::stat_values(&stats)?;
        }
        out.reference_context = out.context.project(raw, context)?;
        if super::refresh::hash(&out.reference_context)? != policy.qualification.context_sha256 {
            return Err("reference context SHA256 mismatch".into());
        }
        let stats = out.stats(input, reference_row)?;
        if stats.len() != 1 || stats[0].id != "base_fire_damage_resistance_%" {
            return Err("reference must have the complete one fire-resistance stat".into());
        }
        Ok(out)
    }

    pub fn stats(&self, input: &VerifiedFacts, row: usize) -> Result<Vec<NativeStat>, String> {
        let raw = self.tables.row("PassiveSkills", row)?;
        graph_id(raw)?;
        for field in ["Name", "Icon_DDSFile"] {
            raw[field]
                .as_str()
                .ok_or_else(|| format!("PassiveSkills/{row}.{field}: string required"))?;
        }
        for field in &self.slots {
            integer(&raw[field], field)?;
        }
        let refs = raw["Stats"].as_array().ok_or("Stats must be an array")?;
        if refs.len() > self.slots.len() {
            return Err("stat/value slot cardinality exceeds declared columns".into());
        }
        let patch = input.manifest["source_identity"]["game_patch"]
            .as_str()
            .ok_or("missing game patch")?;
        refs.iter()
            .enumerate()
            .map(|(position, value)| {
                let stat_row = reference(&self.tables, "Stats", value)?;
                let id = self.tables.row("Stats", stat_row)?["Id"]
                    .as_str()
                    .ok_or("invalid stat Id")?;
                let value = i64::from(integer(&raw[&self.slots[position]], &self.slots[position])?);
                Ok(NativeStat {
                    id: id.into(),
                    value,
                    provenance: NativeStatProvenance {
                        game_patch: patch.into(),
                        source_manifest_sha256: sha256_hex(&input.manifest_bytes),
                        passive_id: raw["Id"].as_str().ok_or("invalid passive Id")?.into(),
                        passive_row: u32::try_from(row).map_err(|e| e.to_string())?,
                        stat_row: u32::try_from(stat_row).map_err(|e| e.to_string())?,
                        references: vec![
                            address(
                                input,
                                "PassiveSkills",
                                format!("/rows/{row}/values/{}", self.slots[position]),
                            )?,
                            address(input, "Stats", format!("/rows/{stat_row}/values/Id"))?,
                        ],
                    },
                })
            })
            .collect()
    }
    pub fn differences(&self, raw: &Value) -> Result<Vec<String>, String> {
        let reference = self.context.project(
            self.tables.row("PassiveSkills", self.reference_row)?,
            |raw| Ok(raw.clone()),
        )?;
        let raw = self.context.project(raw, |raw| Ok(raw.clone()))?;
        let reference = reference.as_object().ok_or("invalid reference context")?;
        let raw = raw.as_object().ok_or("invalid passive context")?;
        // Whole-row rule: identical keys;
        // only these six fields vary. No interpretation of unknown/context keys.
        let keys: BTreeSet<_> = raw.keys().chain(reference.keys()).collect();
        Ok(keys
            .into_iter()
            .filter(|key| {
                !raw.contains_key(*key)
                    || !reference.contains_key(*key)
                    || (!VARIABLES.contains(&key.as_str()) && raw.get(*key) != reference.get(*key))
            })
            .cloned()
            .collect())
    }
    pub fn unmapped(&self, input: &VerifiedFacts) -> Result<Vec<Value>, String> {
        super::TABLES.iter().map(|table| {
            let mut used:Vec<&str>=match *table {
                "PassiveSkills"=>vec!["Id","Name","Icon_DDSFile","PassiveSkillGraphId","Stats"],
                "Stats"=>vec!["Id"],"Characters"=>vec!["Id","Name","BaseStrength","BaseDexterity","BaseIntelligence"],
                _=>vec!["CharacterToOverrideFor","SkillToOverride","Override"],
            };
            if *table=="PassiveSkills" {used.extend(self.slots.iter().map(String::as_str));}
            let path=format!("tables/{table}.json");
            let columns:Vec<_>=input.documents[&path]["columns"].as_array().ok_or("missing columns")?.iter()
                .filter(|c| c["physical_fields"].as_array().is_some_and(|fs|fs.iter().any(|f|!used.iter().any(|u|f.as_str()==Some(*u))))).collect();
            Ok(json!({"table":table,"payload":path,"consumed_identity_or_value_columns":used,
                "qualification_only_columns":if *table=="PassiveSkills"{columns.clone()}else{vec![]},
                "unmapped_columns":if *table=="PassiveSkills"{vec![]}else{columns},
                "source_row_range":{"start":0,"end_exclusive":self.tables.len(table)},
                "scope":"remaining passive fields are compared as opaque complete context only (including ClientStrings Requirement and unavailable Ascendancy references); no predicate/ordinal/text rules inferred"}))
        }).collect()
    }
}
pub(super) fn column(
    input: &VerifiedFacts,
    table: &str,
    field: &str,
    kind: &str,
    array: bool,
    target: Option<&str>,
) -> Result<(), String> {
    super::super::convert::column(
        input,
        table,
        &[field],
        &json!({"name":field,"type":kind,"array":array,"interval":false,"references":target.map(|t|json!({"table":t}))}),
    )
}
fn identities(
    tables: &Tables<'_>,
    table: &str,
    field: &str,
) -> Result<BTreeMap<String, usize>, String> {
    let mut out = BTreeMap::new();
    for row in 0..tables.len(table) {
        let id = tables.row(table, row)?[field]
            .as_str()
            .ok_or("invalid source identity")?;
        if id.is_empty() || out.insert(id.into(), row).is_some() {
            return Err(format!("empty/duplicate {table}.{field}"));
        }
    }
    Ok(out)
}
pub(super) fn integer(v: &Value, field: &str) -> Result<i32, String> {
    v.as_i64()
        .and_then(|n| i32::try_from(n).ok())
        .ok_or_else(|| format!("{field}: exact i32 required"))
}
pub(super) fn graph_id(raw: &Value) -> Result<u32, String> {
    raw["PassiveSkillGraphId"]
        .as_u64()
        .and_then(|n| u16::try_from(n).ok())
        .map(u32::from)
        .ok_or("PassiveSkillGraphId: exact u16 required".into())
}
fn reference(tables: &Tables<'_>, table: &str, v: &Value) -> Result<usize, String> {
    let row = physical_index(v)?;
    tables.row(table, row)?;
    Ok(row)
}
pub(super) fn physical_index(v: &Value) -> Result<usize, String> {
    v.as_u64()
        .and_then(|n| usize::try_from(n).ok())
        .ok_or("required physical FK must be usize".into())
}
pub(super) fn context(raw: &Value) -> Result<Value, String> {
    let mut out = raw.as_object().ok_or("invalid raw context")?.clone();
    out.retain(|field, _| !VARIABLES.contains(&field.as_str()));
    Ok(Value::Object(out))
}
fn address(
    input: &VerifiedFacts,
    table: &str,
    pointer: String,
) -> Result<NativeStatReference, String> {
    let resource = format!("tables/{table}.json");
    let sha256 = input.manifest["files"][&resource]["sha256"]
        .as_str()
        .ok_or("missing payload hash")?
        .into();
    Ok(NativeStatReference {
        resource,
        sha256,
        pointer,
    })
}
