//! Native client text for complete passive skill and point grants.

use super::{render, source};
use crate::facts::reader::{self, Tables, VerifiedFacts, selected};
use crate::ordinary_facts::convert;
use crate::raw_source::sha256_hex;
use serde_json::{Value, json};
use std::collections::BTreeMap;

pub(super) const OWNED_FIELDS: [&str; 3] =
    ["GrantedSkill", "SkillPointsGranted", "WeaponPointsGranted"];
const TABLES: [&str; 3] = ["ClientStrings", "SkillGems", "BaseItemTypes"];
const POINTS: [(&str, &str, &str); 2] = [
    (
        "SkillPointsGranted",
        "PassiveNodeGrantsPassivePoint",
        "PassiveNodeGrantsPassivePoints",
    ),
    (
        "WeaponPointsGranted",
        "PassiveNodeGrantsSpecialisationPoint",
        "PassiveNodeGrantsSpecialisationPoints",
    ),
];

struct Grant<'a> {
    skill_row: usize,
    base_row: usize,
    base: &'a Value,
    name: &'a str,
}

pub(super) struct Source<'a> {
    tables: Tables<'a>,
    strings: BTreeMap<String, usize>,
    pub receipt: Value,
}

impl<'a> Source<'a> {
    pub fn read(input: &VerifiedFacts, extra: &'a selected::Input) -> Result<Self, String> {
        let tables = extra.tables(&TABLES)?;
        for table in TABLES {
            let path = format!("Data/Balance/{table}.datc64");
            let parent = &input.manifest["source_identity"]["raw_resources"][&path];
            if parent.is_null()
                || extra.manifest["source_identity"]["raw_resources"][&path] != *parent
            {
                return Err(format!(
                    "tree text supplement differs from parent raw source: {table}"
                ));
            }
        }
        for (table, field, kind, target) in [
            ("ClientStrings", "Id", "string", None),
            ("ClientStrings", "Text", "string", None),
            ("BaseItemTypes", "Id", "string", None),
            ("BaseItemTypes", "Name", "string", None),
            (
                "SkillGems",
                "BaseItemType",
                "foreignrow",
                Some("BaseItemTypes"),
            ),
        ] {
            extra.column(
                table,
                field,
                &json!({"name":field,"type":kind,"array":false,"interval":false,
                "references":target.map(|t|json!({"table":t}))}),
            )?;
        }
        for (field, kind, array, target) in [
            ("GrantedSkill", "foreignrow", false, Some("SkillGems")),
            ("SkillPointsGranted", "i32", false, None),
            ("WeaponPointsGranted", "i32", false, None),
            (
                "PassiveSkillBuffs",
                "foreignrow",
                true,
                Some("BuffTemplates"),
            ),
        ] {
            source::column(input, "PassiveSkills", field, kind, array, target)?;
        }
        let mut strings = BTreeMap::new();
        for row in 0..tables.len("ClientStrings") {
            let raw = tables.row("ClientStrings", row)?;
            let id = convert::text(&raw["Id"])?;
            if strings.insert(id.to_owned(), row).is_some() {
                return Err("duplicate ClientStrings identity".into());
            }
        }
        Ok(Self {
            tables,
            strings,
            receipt: json!({
            "manifest_sha256":sha256_hex(&extra.manifest_bytes),"manifest":extra.manifest,
            "owned_fields":OWNED_FIELDS,"tables":TABLES,
            "scope":"complete CSD stats plus source-named skill grants and ClientStrings point text; passive buffs and unknown effects still require whole-text compatibility"}),
        })
    }

    /// Physical integrity is independent of which effect can supply output text.
    pub fn validate_physical(&self, raw: &Value) -> Result<(), String> {
        for buff in buffs(raw)? {
            // BuffTemplates are not selected; validate the index without
            // interpreting an unavailable buff effect.
            source::physical_index(buff)?;
        }
        for point in points(raw) {
            let (_, value, template) = point?;
            if value > 0 {
                self.template_source(template)?;
            }
        }
        if let Some(grant) = self.grant(raw, source::physical_index)?
            && !grant.name.is_empty()
        {
            self.template_source("ItemDisplayGrantedSkillNoScaling")?;
        }
        Ok(())
    }

    pub fn render(&self, raw: &Value) -> Result<(Vec<String>, Vec<Value>), String> {
        if !buffs(raw)?.is_empty() {
            return Err("passive buff effects require complete compatibility text".into());
        }
        let mut lines = Vec::new();
        let mut records = Vec::new();
        for point in points(raw) {
            let (field, value, template) = point?;
            if value < 0 {
                return Err(format!("negative {field} has no proven grant template"));
            }
            if value != 0 {
                let argument = value.to_string();
                let (line, mut evidence) = self.template(template, &[&argument])?;
                evidence["source_field"] = json!(field);
                evidence["raw_value"] = json!(value);
                lines.push(line);
                records.push(evidence);
            }
        }
        if let Some(Grant {
            skill_row,
            base_row,
            base,
            name,
        }) = self.grant(raw, index)?
        {
            if name.is_empty() {
                return Err("granted skill has no source name".into());
            }
            let (line, mut evidence) =
                self.template("ItemDisplayGrantedSkillNoScaling", &[name])?;
            evidence["source_field"] = json!("GrantedSkill");
            evidence["skill_gem_row"] = json!(skill_row);
            evidence["base_item_row"] = json!(base_row);
            evidence["base_item_id"] = base["Id"].clone();
            evidence["name"] = json!(name);
            lines.push(line);
            records.push(evidence);
        }
        Ok((lines, records))
    }

    fn grant(
        &self,
        raw: &Value,
        parse_index: fn(&Value) -> Result<usize, String>,
    ) -> Result<Option<Grant<'_>>, String> {
        let grant = raw.get("GrantedSkill").ok_or("missing GrantedSkill")?;
        if grant.is_null() {
            return Ok(None);
        }
        // The renderer keeps its original diagnostic; preflight keeps the
        // physical-index diagnostic. Both traverse the same grant chain.
        let skill_row = parse_index(grant)?;
        let gem = self.tables.row("SkillGems", skill_row)?;
        let base_row = parse_index(&gem["BaseItemType"])?;
        let base = self.tables.row("BaseItemTypes", base_row)?;
        let name = convert::text(&base["Name"])?;
        Ok(Some(Grant {
            skill_row,
            base_row,
            base,
            name,
        }))
    }

    fn template_source(&self, id: &str) -> Result<Option<(usize, &Value, &str)>, String> {
        let Some(&row) = self.strings.get(id) else {
            return Ok(None);
        };
        let raw = self.tables.row("ClientStrings", row)?;
        Ok(Some((row, raw, convert::text(&raw["Text"])?)))
    }

    fn template(&self, id: &str, args: &[&str]) -> Result<(String, Value), String> {
        let (row, raw, template) = self
            .template_source(id)?
            .ok_or_else(|| format!("missing ClientStrings template {id}"))?;
        let text = render::format_template(template, args)?;
        if text.is_empty() {
            return Err(format!("empty ClientStrings template output {id}"));
        }
        Ok((
            text.clone(),
            json!({"owner":"target-client-strings","id":id,"source_row":row,
            "source_pointer":format!("/rows/{row}/values/Text"),"raw_template":template,"arguments":args,
            "text":text,"row_sha256":sha256_hex(&reader::json_bytes(raw)?)}),
        ))
    }
}

fn buffs(raw: &Value) -> Result<&[Value], String> {
    raw["PassiveSkillBuffs"]
        .as_array()
        .map(Vec::as_slice)
        .ok_or("PassiveSkillBuffs must be an array".into())
}

fn points(raw: &Value) -> impl Iterator<Item = Result<(&'static str, i32, &'static str), String>> {
    POINTS.into_iter().map(|(field, singular, plural)| {
        let value = source::integer(&raw[field], field)?;
        Ok((field, value, if value == 1 { singular } else { plural }))
    })
}

fn index(value: &Value) -> Result<usize, String> {
    source::physical_index(value).map_err(|_| "invalid granted-skill physical reference".into())
}
