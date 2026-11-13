//! Source-owned ascendancy membership and replacement relationships.
use super::{refresh, source::Facts};
use crate::facts::reader::{self, VerifiedFacts, selected};
use crate::ordinary_facts::coverage::{Action, Coverage, Issue};
use crate::raw_source::sha256_hex;
use serde::Deserialize;
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Policy {
    pub excluded: BTreeMap<String, refresh::Exclusion>,
}

pub(super) struct Entry {
    pub id: String,
    pub name: String,
    pub character: String,
    pub row: usize,
}
pub(super) struct Link {
    pub row: usize,
    pub target: usize,
    pub selector: String,
    pub previous_selector: Option<String>,
}
pub(super) struct Source {
    pub entries: BTreeMap<usize, Entry>,
    pub quarantined: BTreeMap<usize, String>,
    pub links: BTreeMap<String, Vec<Link>>,
    pub previous_selectors: BTreeSet<String>,
    pub receipt: Value,
}

fn index(value: &Value) -> Result<usize, String> {
    value
        .as_u64()
        .and_then(|v| usize::try_from(v).ok())
        .ok_or("invalid ascendancy reference".into())
}
fn text(value: &Value) -> Result<&str, String> {
    value
        .as_str()
        .filter(|s| !s.is_empty())
        .ok_or("empty ascendancy identity/name".into())
}

impl Source {
    pub fn read(
        input: &VerifiedFacts,
        facts: &Facts<'_>,
        extra: &selected::Input,
        policy: &Policy,
        old_meta: &Value,
        coverage: &mut Coverage,
    ) -> Result<Self, String> {
        super::source::column(
            input,
            "PassiveSkills",
            "Ascendancy",
            "foreignrow",
            false,
            Some("Ascendancy"),
        )?;
        let tables = extra.tables(&["Ascendancy", "AscendancyPassiveSkillOverrides"])?;
        for (table, field, kind, target) in [
            ("Ascendancy", "Id", "string", None),
            ("Ascendancy", "Name", "string", None),
            ("Ascendancy", "Character", "foreignrow", Some("Characters")),
            ("Ascendancy", "Disabled", "bool", None),
            ("Ascendancy", "BaseAscendancy", "row", Some("Ascendancy")),
            (
                "AscendancyPassiveSkillOverrides",
                "AscendancyToOverrideFor",
                "foreignrow",
                Some("Ascendancy"),
            ),
            (
                "AscendancyPassiveSkillOverrides",
                "SkillToOverride",
                "foreignrow",
                Some("PassiveSkills"),
            ),
            (
                "AscendancyPassiveSkillOverrides",
                "Override",
                "foreignrow",
                Some("PassiveSkills"),
            ),
        ] {
            let column = extra.documents[&format!("tables/{table}.json")]["columns"]
                .as_array()
                .ok_or("missing ascendancy columns")?
                .iter()
                .find(|c| c["physical_fields"] == json!([field]))
                .ok_or("missing ascendancy column")?;
            if column["schema"]["type"] != kind
                || column["schema"]["array"] != false
                || column["schema"]["references"]
                    != target.map(|t| json!({"table":t})).unwrap_or(Value::Null)
            {
                return Err("ascendancy column schema mismatch".into());
            }
        }
        let mut entries = BTreeMap::new();
        let mut quarantined = BTreeMap::new();
        let mut excluded = BTreeSet::new();
        let mut names = BTreeSet::new();
        let mut records = Vec::new();
        for row in 0..tables.len("Ascendancy") {
            let raw = tables.row("Ascendancy", row)?;
            let id = text(&raw["Id"])?;
            let character_row = index(&raw["Character"])?;
            let character = text(&facts.tables.row("Characters", character_row)?["Name"])?;
            if !raw["BaseAscendancy"].is_null() {
                let base = index(&raw["BaseAscendancy"])?;
                tables.row("Ascendancy", base)?;
                if base == row {
                    return Err("self-referential base ascendancy".into());
                }
            }
            let is_excluded = if let Some(binding) = policy.excluded.get(id) {
                let definition_sha256 = sha256_hex(&reader::json_bytes(raw)?);
                if binding.reason.trim().is_empty()
                    || binding.definition_sha256 != definition_sha256
                {
                    let still_placeholder = raw["Disabled"] != false
                        || raw["Name"]
                            .as_str()
                            .is_none_or(|name| name.is_empty() || name.starts_with("[DNT"));
                    coverage.decide(
                        Issue::new(
                            "ascendancy-exclusion-changed",
                            id,
                            if still_placeholder {
                                Action::Quarantined
                            } else {
                                Action::EmittedWithGap
                            },
                            "changed ascendancy eligibility exclusion",
                        )
                        .observed("definition_sha256", definition_sha256)
                        .observed(
                            "policy_definition_sha256",
                            binding.definition_sha256.clone(),
                        ),
                    )?;
                    raw["Name"].as_str().ok_or("invalid ascendancy name")?;
                    raw["Disabled"]
                        .as_bool()
                        .ok_or("invalid ascendancy Disabled")?;
                    excluded.insert(id.to_owned());
                    if still_placeholder {
                        quarantined.insert(row, id.to_owned());
                    }
                    still_placeholder
                } else {
                    excluded.insert(id.to_owned());
                    true
                }
            } else {
                false
            };
            records.push(json!({"source_row":row,"raw":raw,"character_row":character_row,"character":character,"excluded":is_excluded}));
            if is_excluded {
                continue;
            }
            let name = text(&raw["Name"])?;
            if raw["Disabled"] != false
                || name.starts_with("[DNT")
                || !names.insert(name.to_owned())
            {
                return Err("unclassified/disabled/ambiguous ascendancy".into());
            }
            entries.insert(
                row,
                Entry {
                    id: id.into(),
                    name: name.into(),
                    character: character.into(),
                    row,
                },
            );
        }
        if excluded.len() != policy.excluded.len() {
            for (id, binding) in &policy.excluded {
                if !excluded.contains(id) {
                    coverage.decide(
                        Issue::new(
                            "unused-ascendancy-exclusion",
                            id,
                            Action::Listed,
                            "unused ascendancy exclusion",
                        )
                        .observed(
                            "policy_definition_sha256",
                            binding.definition_sha256.clone(),
                        ),
                    )?;
                }
            }
        }
        let mut previous = BTreeMap::new();
        for class in old_meta["classes"].as_array().ok_or("missing classes")? {
            for asc in class["ascendancies"].as_array().into_iter().flatten() {
                previous.insert(text(&asc["id"])?.to_owned(), text(&asc["name"])?.to_owned());
            }
        }
        let mut links: BTreeMap<String, Vec<Link>> = BTreeMap::new();
        let mut keys = BTreeSet::new();
        let mut relations = Vec::new();
        for row in 0..tables.len("AscendancyPassiveSkillOverrides") {
            let raw = tables.row("AscendancyPassiveSkillOverrides", row)?;
            let owner = index(&raw["AscendancyToOverrideFor"])?;
            let asc = if quarantined.contains_key(&owner) {
                None
            } else {
                Some(
                    entries
                        .get(&owner)
                        .ok_or("override targets unavailable ascendancy")?,
                )
            };
            let base = index(&raw["SkillToOverride"])?;
            let target = index(&raw["Override"])?;
            let base_raw = facts.tables.row("PassiveSkills", base)?;
            let target_raw = facts.tables.row("PassiveSkills", target)?;
            let id = text(&base_raw["Id"])?;
            if !keys.insert((base, owner)) {
                return Err("duplicate ascendancy replacement owner".into());
            }
            let Some(asc) = asc else {
                continue;
            };
            links.entry(id.into()).or_default().push(Link {
                row,
                target,
                selector: asc.name.clone(),
                previous_selector: previous.get(&asc.id).cloned(),
            });
            relations.push(json!({"source_row":row,"raw":raw,"ascendancy_id":asc.id,"selector":asc.name,"base_id":id,"target_id":target_raw["Id"]}));
        }
        Ok(Self {
            entries,
            quarantined,
            links,
            previous_selectors: previous.into_values().collect(),
            receipt: json!({
            "manifest_sha256":sha256_hex(&extra.manifest_bytes),"manifest":extra.manifest,
            "ascendancies":records,"relationships":relations,
            "limits":"Eligibility exclusions are exact source-bound policy. BaseAscendancy, ClassNo and UI fields remain raw evidence; they do not create new allocation or import-ordinal laws."}),
        })
    }

    pub fn node(
        &self,
        raw: &Value,
        out: &mut serde_json::Map<String, Value>,
    ) -> Result<(), String> {
        if raw["Ascendancy"].is_null() {
            out.remove("ascendancy_id");
        } else {
            let entry = self
                .entries
                .get(&index(&raw["Ascendancy"])?)
                .ok_or("node targets unavailable ascendancy")?;
            out.insert("ascendancy_id".into(), json!(entry.id));
            // Source ownership cannot leave the unconditional optimization attached.
            out.remove("native_stats");
        }
        Ok(())
    }

    pub fn metadata(&self, out: &mut Value) -> Result<(), String> {
        let old: BTreeMap<_, _> = out["classes"]
            .as_array()
            .ok_or("missing classes")?
            .iter()
            .flat_map(|c| c["ascendancies"].as_array().into_iter().flatten())
            .map(|a| Ok((text(&a["id"])?.to_owned(), a.clone())))
            .collect::<Result<_, String>>()?;
        let mut used = BTreeSet::new();
        for class in out["classes"].as_array_mut().ok_or("missing classes")? {
            let name = text(&class["name"])?.to_owned();
            let order: BTreeMap<_, _> = class["ascendancies"]
                .as_array()
                .into_iter()
                .flatten()
                .enumerate()
                .map(|(i, a)| (a["id"].as_str().unwrap_or("").to_owned(), i))
                .collect();
            let mut entries: Vec<_> = self
                .entries
                .values()
                .filter(|a| a.character == name)
                .collect();
            entries.sort_by_key(|a| (order.get(&a.id).copied().unwrap_or(usize::MAX), a.row));
            let values: Vec<_> = entries
                .into_iter()
                .map(|a| {
                    used.insert(a.row);
                    let mut value = old.get(&a.id).cloned().unwrap_or(json!({}));
                    value["id"] = json!(a.id);
                    value["name"] = json!(a.name);
                    value
                })
                .collect();
            if values.is_empty() {
                class
                    .as_object_mut()
                    .ok_or("invalid class")?
                    .remove("ascendancies");
            } else {
                class["ascendancies"] = json!(values);
            }
        }
        if used.len() != self.entries.len() {
            return Err("ascendancy character is absent from ordinary metadata".into());
        }
        Ok(())
    }
}

#[cfg(all(test, any(target_os = "linux", target_os = "macos")))]
mod tests;
