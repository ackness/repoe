use super::{refresh, render::Renderer, source::Facts};
use crate::facts::reader::{self, VerifiedFacts};
use crate::ordinary_facts::coverage::{AdapterMode, Coverage};
use crate::ordinary_facts::{stat_set_codec::tests::table, tests::Fixture};
use crate::raw_source::sha256_hex;
use serde_json::{Value, json};
use std::fs;

fn hash(v: &impl serde::Serialize) -> String {
    sha256_hex(&reader::json_bytes(v).unwrap())
}
fn descriptor(ids: &[&str], template: &str) -> Value {
    json!({"kind":"description","ids":ids,"raw_slice_sha256":"fixture","groups":[{
        "language_origin":"implicit-default","declared_language":null,"branches":[{
            "condition_tokens_raw":ids.iter().map(|_|"#").collect::<Vec<_>>(),"template_raw":template,
            "template_syntax_diagnostics":[],"quantifiers_lexical":[],"quantifier_tokens_raw":[],"restrictions_raw":[],"span":{}}]}]})
}
pub(super) fn descriptions() -> Value {
    json!({"files":{
        "Data/StatDescriptions/passive_skill_stat_descriptions.csd":{
            "path":"Data/StatDescriptions/passive_skill_stat_descriptions.csd","records":[
                {"kind":"include","target":"Data/StatDescriptions/stat_descriptions.csd"}]},
        "Data/StatDescriptions/stat_descriptions.csd":{
            "path":"Data/StatDescriptions/stat_descriptions.csd","records":[
                descriptor(&["base_fire_damage_resistance_%"],"{0:+d}% to Fire Resistance"),
                descriptor(&["spell_damage_+%"],"{0}% increased Spell Damage")]}}})
}
pub(super) fn fixture() -> (Fixture, Value, Value, Value) {
    let mut f = super::tests::fixture();
    let passive = f.documents.get_mut("tables/PassiveSkills.json").unwrap();
    for field in [
        "IsNotable",
        "IsKeystone",
        "IsJewelSocket",
        "IsAscendancyStartingNode",
        "IsJustIcon",
    ] {
        let n = passive["columns"].as_array().unwrap().len();
        passive["columns"].as_array_mut().unwrap().push(json!({"source_column":n,"physical_fields":[field],"schema":{"name":field,"type":"bool","array":false,"interval":false,"references":null}}));
        passive["physical_fields"]
            .as_array_mut()
            .unwrap()
            .push(json!(field));
        for row in passive["rows"].as_array_mut().unwrap() {
            row["values"][field] = json!(false);
        }
    }
    // Use a second distinct stat: repeated IDs must never become partial native packets.
    let stat = f.documents.get_mut("tables/Stats.json").unwrap();
    stat["rows"]
        .as_array_mut()
        .unwrap()
        .push(json!({"_row":2,"values":{"Id":"spell_damage_+%"}}));
    stat["validation"]["rows"] = json!(3);
    f.values("PassiveSkills", 2)["Stats"] = json!([0, 2]);
    f.documents.insert(
        "tables/PassiveSkillTrees.json".into(),
        table(
            "PassiveSkillTrees",
            &[
                ("Id", "string", false, None),
                ("PassiveSkillGraph", "string", false, None),
            ],
            json!([{"Id":"Default","PassiveSkillGraph":"Metadata/PassiveSkillGraph"}]),
        ),
    );
    let instances:Vec<_>=[0,1,2].into_iter().map(|i| {
        let r=&f.documents["tables/PassiveSkills.json"]["rows"][i]["values"];
        json!({"definition":{"row":i,"id":r["Id"]},"graph_id":r["PassiveSkillGraphId"],"group":0,"radius":0,"position":0,
            "connections":if i==0 {vec![303]}else{vec![]},"splines":if i==0 {vec![0]}else{vec![]}})
    }).collect();
    f.documents.insert(
        "passives.json".into(),
        json!({"definitions":[],"class_overrides":[],"default_graph_instances":instances}),
    );
    let graph_nodes: Vec<_> = instances
        .iter()
        .map(|i| {
            let mut n = i.clone();
            n.as_object_mut().unwrap().remove("definition");
            n.as_object_mut().unwrap().remove("group");
            n
        })
        .collect();
    f.documents.insert("graph.json".into(),json!({"tree":{"id":"Default","row":0},"raw_resource":"Metadata/PassiveSkillGraph.psg","header":[3,0],
        "skills_per_orbit":[1],"roots":[{"graph_id":101,"unknown":0}],"groups":[{"group":0,"x":10.0,"y":20.0,"flag":0,"unknown1":0,"unknown2":0,"nodes":graph_nodes}],
        "parsed_bytes":f.manifest["source_identity"]["raw_resources"]["Metadata/PassiveSkillGraph.psg"]["bytes"],"radius_semantics":"opaque","warnings":[]}));
    f.seal();
    let mut base: Value =
        serde_json::from_slice(&fs::read(f.root.join("policy/policy.json")).unwrap()).unwrap();
    base["target"]["facts_manifest_sha256"] = json!(f.args().expected_manifest_sha256);
    base["qualification"]["context_sha256"] = json!(hash(
        &super::source::context(f.values("PassiveSkills", 0)).unwrap()
    ));
    base["legacy_id_bindings"] = json!([]);
    base["legacy_connection_exceptions"] = json!([]);
    let mut legacy = json!([
        {"skill":101,"id":"maximum_resistances1","name":"old","kind":"normal","stats":["+5% to Fire Resistance"],"connections":[],"unknown":{"keep":true}},
        {"skill":202,"id":"Unknown","name":"Unknown","kind":"normal","stats":["unparsed old complete effect"],"connections":[]},
        {"skill":303,"id":"Multi","name":"Multi","kind":"normal","stats":["stale old stat"],"connections":[]}
    ]);
    for n in legacy.as_array_mut().unwrap() {
        n["group"] = json!(1);
        n["orbit"] = json!(0);
        n["orbit_index"] = json!(0);
        n["x"] = json!(10.0);
        n["y"] = json!(20.0);
    }
    let bindings:serde_json::Map<_,_>=f.documents["tables/PassiveSkills.json"]["rows"].as_array().unwrap().iter().map(|r|{
        let raw=&r["values"];let stats:Vec<_>=raw["Stats"].as_array().unwrap().iter().enumerate().map(|(i,s)|
            json!([f.documents["tables/Stats.json"]["rows"][s.as_u64().unwrap() as usize]["values"]["Id"],raw[format!("Stat{}Value",i+1)]])).collect();
        (raw["Id"].as_str().unwrap().to_owned(),json!({"context_sha256":hash(&refresh::context(raw).unwrap()),"stats_sha256":hash(&stats)}))
    }).collect();
    let policy = json!({"schema":"pobr-ordinary-target-tree-policy/v1","base_policy":base,"reference_sha256":"0".repeat(64),
        "descriptions_sha256":"0".repeat(64),"descriptions_manifest_sha256":"0".repeat(64),"compatibility_bindings":bindings,"excluded":{},"class_bindings":[],"statement":"fixture compatibility"});
    let mut reference = json!({"tree":"Default","nodes":{},"groups":{"1":{"x":10.0,"y":20.0}}});
    for id in [101, 202, 303] {
        reference["nodes"][id.to_string()] =
            json!({"skill":id,"group":1,"orbit":0,"orbitIndex":0,"x":10.0,"y":20.0});
    }
    (f, policy, legacy, reference)
}
pub(super) fn input(f: &mut Fixture) -> VerifiedFacts {
    f.seal();
    let mut input = reader::open(
        &f.root.join("input"),
        &f.args().expected_manifest_sha256,
        "0.5.5.5",
        &super::REFRESH_TABLES,
    )
    .unwrap();
    reader::read_tree(&f.root.join("input"), &mut input).unwrap();
    input
}

fn pinned_refresh_args(
    f: &mut Fixture,
    policy: &mut Value,
    old: &Value,
    reference: &Value,
) -> crate::ordinary_facts::Args {
    f.seal();
    fs::create_dir_all(f.root.join("refresh-inputs")).unwrap();
    let write = |path: &str, value: &Value| {
        let bytes = reader::json_bytes(value).unwrap();
        fs::write(f.root.join(path), &bytes).unwrap();
        sha256_hex(&bytes)
    };
    policy["base_policy"]["source"]["sha256"] = json!(write("legacy/source.json", old));
    policy["base_policy"]["target"]["facts_manifest_sha256"] =
        json!(f.args().expected_manifest_sha256);
    policy["reference_sha256"] = json!(write("refresh-inputs/reference.json", reference));
    policy["descriptions_sha256"] =
        json!(write("refresh-inputs/descriptions.json", &descriptions()));
    let manifest = json!({
        "format":"repoe-native-descriptions/v1",
        "source_identity":f.manifest["source_identity"],
        "files":{"descriptions.json":{
            "sha256":policy["descriptions_sha256"],
            "bytes":fs::read(f.root.join("refresh-inputs/descriptions.json")).unwrap().len()
        }}
    });
    policy["descriptions_manifest_sha256"] =
        json!(write("refresh-inputs/manifest.json", &manifest));
    write("policy/policy.json", policy);
    let mut args = super::tests::args(f);
    args.tree_refresh = Some(Box::new(refresh::Args {
        reference: f.root.join("refresh-inputs/reference.json"),
        descriptions: f.root.join("refresh-inputs/descriptions.json"),
        context_baseline: None,
    }));
    args
}

pub(super) fn baseline_input(
    f: &Fixture,
    policy: &mut Value,
    table: &Value,
) -> refresh::ContextBaselineArgs {
    fs::create_dir_all(f.root.join("context-baseline")).unwrap();
    let path = f.root.join("context-baseline/PassiveSkills.json");
    let bytes = reader::json_bytes(table).unwrap();
    fs::write(&path, &bytes).unwrap();
    let sha256 = sha256_hex(&bytes);
    policy["context_baseline"] = reviewed(json!({"sha256":sha256}));
    refresh::ContextBaselineArgs { path, sha256 }
}

#[test]
fn context_baseline_requires_reviewed_policy_and_the_exact_input_pin_in_both_modes() {
    for mode in [AdapterMode::Strict, AdapterMode::Forward] {
        for case in [
            "absent-input",
            "absent-policy",
            "cli-pin",
            "tampered",
            "null",
            "empty",
            "missing-sha",
            "missing-review",
            "unreviewed",
            "missing-reason",
            "blank-reason",
            "bad-sha",
            "uppercase-sha",
            "extra-field",
        ] {
            let (mut f, mut p, old, reference) = fixture();
            let table = f.documents["tables/PassiveSkills.json"].clone();
            let mut baseline = baseline_input(&f, &mut p, &table);
            match case {
                "absent-policy" => {
                    p.as_object_mut().unwrap().remove("context_baseline");
                }
                "cli-pin" => baseline.sha256 = "f".repeat(64),
                "tampered" => fs::write(&baseline.path, b"{not JSON").unwrap(),
                "null" => p["context_baseline"] = Value::Null,
                "empty" => p["context_baseline"] = json!({}),
                "missing-sha" => {
                    p["context_baseline"]
                        .as_object_mut()
                        .unwrap()
                        .remove("sha256");
                }
                "missing-review" => {
                    p["context_baseline"]
                        .as_object_mut()
                        .unwrap()
                        .remove("review");
                }
                "unreviewed" => p["context_baseline"]["review"] = json!("unreviewed"),
                "missing-reason" => {
                    p["context_baseline"]
                        .as_object_mut()
                        .unwrap()
                        .remove("reason");
                }
                "blank-reason" => p["context_baseline"]["reason"] = json!(" \n "),
                "bad-sha" => p["context_baseline"]["sha256"] = json!("invalid"),
                "uppercase-sha" => p["context_baseline"]["sha256"] = json!("A".repeat(64)),
                "extra-field" => p["context_baseline"]["unknown"] = json!(true),
                _ => {}
            }
            let mut args = pinned_refresh_args(&mut f, &mut p, &old, &reference);
            args.mode = mode;
            if case != "absent-input" {
                args.tree_refresh.as_mut().unwrap().context_baseline = Some(baseline);
            }
            let error = crate::ordinary_facts::run(args).unwrap_err();
            if case == "tampered" {
                assert!(
                    error.contains("SHA256 mismatch (checked before parsing)"),
                    "{error}"
                );
            }
            assert!(!f.root.join("out").exists(), "{case}: {error}");
        }
    }
}

#[test]
fn context_baseline_validates_native_shape_and_original_qualification() {
    let (f, mut p, _, _) = fixture();
    let original = f.documents["tables/PassiveSkills.json"].clone();
    for case in [
        "table",
        "resource",
        "row-key",
        "fields-type",
        "field-type",
        "blank-field",
        "duplicate-field",
        "missing-id-field",
        "rows-type",
        "row-type",
        "row-index",
        "values-type",
        "missing-value",
        "extra-value",
        "duplicate-id",
        "empty-id",
        "invalid-id",
        "missing-reference",
        "changed-reference",
    ] {
        let mut table = original.clone();
        match case {
            "table" => table["table"] = json!("Stats"),
            "resource" => table["raw_resource"] = json!("Data/Balance/Stats.datc64"),
            "row-key" => table["row_key"] = Value::Null,
            "fields-type" => table["physical_fields"] = json!({}),
            "field-type" => table["physical_fields"][0] = json!(1),
            "blank-field" => table["physical_fields"][0] = json!(" "),
            "duplicate-field" => {
                let field = table["physical_fields"][0].clone();
                table["physical_fields"].as_array_mut().unwrap().push(field);
            }
            "missing-id-field" => {
                table["physical_fields"]
                    .as_array_mut()
                    .unwrap()
                    .retain(|f| f != "Id");
            }
            "rows-type" => table["rows"] = Value::Null,
            "row-type" => table["rows"][1] = json!([]),
            "row-index" => table["rows"][1]["_row"] = json!(55),
            "values-type" => table["rows"][1]["values"] = json!([]),
            "missing-value" => {
                table["rows"][1]["values"]
                    .as_object_mut()
                    .unwrap()
                    .remove("Opaque");
            }
            "extra-value" => table["rows"][1]["values"]["extra"] = json!(0),
            "duplicate-id" => {
                table["rows"][1]["values"]["Id"] = table["rows"][0]["values"]["Id"].clone()
            }
            "empty-id" => table["rows"][1]["values"]["Id"] = json!(" "),
            "invalid-id" => table["rows"][1]["values"]["Id"] = Value::Null,
            "missing-reference" => table["rows"][0]["values"]["Id"] = json!("different-reference"),
            "changed-reference" => table["rows"][0]["values"]["Opaque"] = json!(99),
            _ => unreachable!(),
        }
        // Re-pin malformed tables so the native validator, rather than byte tampering, rejects them.
        let baseline = baseline_input(&f, &mut p, &table);
        let policy: refresh::Policy = serde_json::from_value(p.clone()).unwrap();
        let error = refresh::read_context_baseline(&policy, Some(&baseline))
            .err()
            .unwrap();
        assert!(error.contains("tree context baseline"), "{case}: {error}");
        if case == "changed-reference" {
            assert!(
                error.contains("reference context SHA256 mismatch"),
                "{error}"
            );
        }
    }
}

#[test]
fn context_baseline_indexes_old_rows_by_id_and_sorts_fields() {
    let (mut f, mut p, _, _) = fixture();
    let mut table = f.documents["tables/PassiveSkills.json"].clone();
    // Native exports describe the row key in prose; `_row` lives on each row.
    table["row_key"] = json!(
        "Zero-based physical source row; ephemeral within these exact raw bytes, never a stable game ID."
    );
    let target_row = f.values("PassiveSkills", 0).clone();
    table["physical_fields"].as_array_mut().unwrap().reverse();
    table["rows"].as_array_mut().unwrap().reverse();
    for (index, row) in table["rows"].as_array_mut().unwrap().iter_mut().enumerate() {
        row["_row"] = json!(index);
    }
    let baseline = baseline_input(&f, &mut p, &table);
    let policy: refresh::Policy = serde_json::from_value(p).unwrap();
    let (baseline, _) = refresh::read_context_baseline(&policy, Some(&baseline))
        .unwrap()
        .unwrap();
    assert_eq!(baseline.row("maximum_resistances1"), Some(&target_row));
    assert_ne!(baseline.rows["maximum_resistances1"]["_row"], json!(0));
    assert!(baseline.row("absent").is_none());
    assert!(baseline.fields.windows(2).all(|pair| pair[0] < pair[1]));
}

#[test]
fn context_baseline_records_only_optional_conversion_evidence_and_protects_its_parent() {
    for mode in [AdapterMode::Strict, AdapterMode::Forward] {
        let (mut f, mut p, old, reference) = fixture();
        let mut args = pinned_refresh_args(&mut f, &mut p, &old, &reference);
        args.mode = mode;
        args.out = f.root.join("without-baseline");
        crate::ordinary_facts::run(args).unwrap();
        let absent: Value =
            crate::read_json(&f.root.join("without-baseline/producer-receipt.json")).unwrap();
        assert!(absent["conversion"].get("context_baseline").is_none());
        let table = f.documents["tables/PassiveSkills.json"].clone();
        let baseline = baseline_input(&f, &mut p, &table);
        let baseline_pin = baseline.sha256.clone();
        let baseline_path = baseline.path.clone();
        let mut args = pinned_refresh_args(&mut f, &mut p, &old, &reference);
        args.mode = mode;
        args.tree_refresh.as_mut().unwrap().context_baseline = Some(baseline);
        crate::ordinary_facts::run(args).unwrap();
        let present: Value = crate::read_json(&f.root.join("out/producer-receipt.json")).unwrap();
        assert_eq!(
            present.as_object().unwrap().keys().collect::<Vec<_>>(),
            absent.as_object().unwrap().keys().collect::<Vec<_>>()
        );
        assert_eq!(
            present["files"]
                .as_object()
                .unwrap()
                .keys()
                .collect::<Vec<_>>(),
            absent["files"]
                .as_object()
                .unwrap()
                .keys()
                .collect::<Vec<_>>()
        );
        for file in ["base/passive_tree.json", "base/passive_tree_meta.json"] {
            assert_eq!(
                fs::read(f.root.join("out").join(file)).unwrap(),
                fs::read(f.root.join("without-baseline").join(file)).unwrap()
            );
        }
        let evidence = &present["conversion"]["context_baseline"];
        assert_eq!(evidence["sha256"], baseline_pin);
        assert_eq!(evidence["reason"], p["context_baseline"]["reason"]);
        assert_eq!(evidence["review"], "reviewed");
        assert_eq!(
            evidence["reference_context_sha256"],
            p["base_policy"]["qualification"]["context_sha256"]
        );
        assert_eq!(
            evidence["row_count"],
            table["rows"].as_array().unwrap().len()
        );
        assert_eq!(
            evidence["physical_field_count"],
            table["physical_fields"].as_array().unwrap().len()
        );
        let mut conversion = present["conversion"].clone();
        conversion
            .as_object_mut()
            .unwrap()
            .remove("context_baseline");
        conversion["codec_policy"] = absent["conversion"]["codec_policy"].clone();
        assert_eq!(conversion, absent["conversion"]);
        assert_eq!(sha256_hex(&fs::read(&baseline_path).unwrap()), baseline_pin);

        for out in [
            baseline_path.clone(),
            baseline_path.parent().unwrap().join("candidate"),
        ] {
            let mut args = pinned_refresh_args(&mut f, &mut p, &old, &reference);
            args.mode = mode;
            args.tree_refresh.as_mut().unwrap().context_baseline =
                Some(refresh::ContextBaselineArgs {
                    path: baseline_path.clone(),
                    sha256: baseline_pin.clone(),
                });
            args.out = out.clone();
            let error = crate::ordinary_facts::run(args).unwrap_err();
            if out != baseline_path {
                assert!(error.contains("supplemental input"), "{error}");
                assert!(!out.exists());
            }
            assert_eq!(sha256_hex(&fs::read(&baseline_path).unwrap()), baseline_pin);
        }
    }
}

#[test]
fn a_valid_context_baseline_cannot_bypass_target_qualification_or_consumed_columns() {
    for mode in [AdapterMode::Strict, AdapterMode::Forward] {
        for case in ["qualification", "column"] {
            let (mut f, mut p, old, reference) = fixture();
            let table = f.documents["tables/PassiveSkills.json"].clone();
            let baseline = baseline_input(&f, &mut p, &table);
            if case == "qualification" {
                f.values("PassiveSkills", 0)["Opaque"] = json!(99);
            } else {
                let columns = f.documents.get_mut("tables/PassiveSkills.json").unwrap()["columns"]
                    .as_array_mut()
                    .unwrap();
                let stats = columns
                    .iter_mut()
                    .find(|c| c["schema"]["name"] == "Stats")
                    .unwrap();
                stats["schema"]["type"] = json!("string");
            }
            let mut args = pinned_refresh_args(&mut f, &mut p, &old, &reference);
            args.mode = mode;
            args.tree_refresh.as_mut().unwrap().context_baseline = Some(baseline);
            let error = crate::ordinary_facts::run(args).unwrap_err();
            if case == "qualification" {
                assert_eq!(error, "reference context SHA256 mismatch");
            } else {
                assert!(
                    error.contains("column") || error.contains("schema"),
                    "{error}"
                );
            }
            assert!(!f.root.join("out").exists());
        }
    }
}

fn project(
    f: &mut Fixture,
    policy: &Value,
    old: &Value,
    reference: &Value,
) -> Result<(Value, Value, Value), String> {
    project_with_coverage(
        f,
        policy,
        old,
        reference,
        &mut Coverage::new(AdapterMode::Strict, "passive-tree"),
    )
}
fn project_with_coverage(
    f: &mut Fixture,
    policy: &Value,
    old: &Value,
    reference: &Value,
    coverage: &mut Coverage,
) -> Result<(Value, Value, Value), String> {
    project_with_baseline(f, policy, old, reference, None, coverage)
}

pub(super) fn add_context_column(f: &mut Fixture, field: &str, value: Value) {
    let descriptor = table("PassiveSkills", &[(field, "i32", false, None)], json!([]));
    let doc = f.documents.get_mut("tables/PassiveSkills.json").unwrap();
    let mut column = descriptor["columns"][0].clone();
    column["source_column"] = json!(doc["columns"].as_array().unwrap().len());
    doc["columns"].as_array_mut().unwrap().push(column);
    doc["physical_fields"]
        .as_array_mut()
        .unwrap()
        .push(json!(field));
    for row in doc["rows"].as_array_mut().unwrap() {
        row["values"][field] = value.clone();
    }
}

fn remove_context_column(f: &mut Fixture, field: &str) {
    let doc = f.documents.get_mut("tables/PassiveSkills.json").unwrap();
    doc["physical_fields"]
        .as_array_mut()
        .unwrap()
        .retain(|v| v != field);
    doc["columns"]
        .as_array_mut()
        .unwrap()
        .retain(|c| c["schema"]["name"] != field);
    for (i, column) in doc["columns"]
        .as_array_mut()
        .unwrap()
        .iter_mut()
        .enumerate()
    {
        column["source_column"] = json!(i);
    }
    for row in doc["rows"].as_array_mut().unwrap() {
        row["values"].as_object_mut().unwrap().remove(field);
    }
}

fn column_allowance(old: &Value, f: &Fixture, added: Value, removed: Value) -> Value {
    let sorted = |table: &Value| {
        let mut fields = table["physical_fields"].as_array().unwrap().clone();
        fields.sort_by(|a, b| a.as_str().cmp(&b.as_str()));
        fields
    };
    reviewed(json!({
        "bound_fields_sha256":hash(&sorted(old)),
        "target_fields_sha256":hash(&sorted(&f.documents["tables/PassiveSkills.json"])),
        "added":added,"removed":removed
    }))
}

fn column_projection(
    f: &mut Fixture,
    p: &Value,
    old: &Value,
    reference: &Value,
    baseline: &refresh::ContextBaselineArgs,
    mode: AdapterMode,
) -> Result<(Value, Value, Value), String> {
    let mut coverage = Coverage::new(mode, "passive-tree");
    let (tree, meta, mut receipt) =
        project_with_baseline(f, p, old, reference, Some(baseline), &mut coverage)?;
    coverage.finish(&mut receipt)?;
    Ok((tree, meta, receipt))
}

#[test]
fn column_diagnostics_prove_each_projection_and_suppress_all_affected_packets() {
    let (mut f, mut p, old, r) = fixture();
    let table = f.documents["tables/PassiveSkills.json"].clone();
    let baseline = baseline_input(&f, &mut p, &table);
    add_context_column(&mut f, "NewContext", json!(0));
    // Target-owned values still render from the actual target, not old evidence.
    f.values("PassiveSkills", 0)["Name"] = json!("Current target name");
    f.values("PassiveSkills", 0)["Stat1Value"] = json!(11);
    assert_eq!(
        column_projection(&mut f, &p, &old, &r, &baseline, AdapterMode::Strict).unwrap_err(),
        "reference context SHA256 mismatch"
    );
    let open = column_projection(&mut f, &p, &old, &r, &baseline, AdapterMode::Forward).unwrap();
    assert_eq!(open.0[0]["name"], "Current target name");
    assert_eq!(open.0[0]["stats"], json!(["+11% to Fire Resistance"]));
    assert!(
        open.0
            .as_array()
            .unwrap()
            .iter()
            .all(|n| n.get("native_stats").is_none())
    );
    let issues = open.2["coverage"]["issues"].as_array().unwrap();
    assert_eq!(issues.len(), 1);
    assert_eq!(issues[0]["kind"], "context-columns-changed");
    assert_eq!(issues[0]["entity"], "PassiveSkills");
    assert_eq!(issues[0]["action"], "emitted-with-gap");
    let expected = column_allowance(&table, &f, json!([]), json!([]));
    assert_eq!(
        issues[0]["observed"]["bound_fields_sha256"],
        expected["bound_fields_sha256"]
    );
    assert_eq!(
        issues[0]["observed"]["target_fields_sha256"],
        expected["target_fields_sha256"]
    );
    assert_eq!(issues[0]["observed"]["added"], json!(["NewContext"]));
    assert_eq!(issues[0]["observed"]["removed"], json!([]));
    assert_eq!(
        issues[0]["observed"]["context_baseline_sha256"],
        baseline.sha256
    );
    assert_eq!(issues[0]["observed"]["ids_without_old_evidence"], json!([]));
    assert_eq!(
        column_projection(&mut f, &p, &old, &r, &baseline, AdapterMode::Forward).unwrap(),
        open
    );
    // Reordering fields changes neither evidence nor row comparisons.
    f.documents.get_mut("tables/PassiveSkills.json").unwrap()["physical_fields"]
        .as_array_mut()
        .unwrap()
        .reverse();
    let columns = f.documents.get_mut("tables/PassiveSkills.json").unwrap()["columns"]
        .as_array_mut()
        .unwrap();
    columns.reverse();
    for (i, column) in columns.iter_mut().enumerate() {
        column["source_column"] = json!(i);
    }
    assert_eq!(
        column_projection(&mut f, &p, &old, &r, &baseline, AdapterMode::Forward).unwrap(),
        open
    );
}

#[test]
fn column_review_is_row_specific_for_ordinary_nodes_and_class_variants() {
    let (mut f, mut p, mut old, r) = fixture();
    f.values("ClassPassiveSkillOverrides", 0)["SkillToOverride"] = json!(0);
    p["class_bindings"] = json!([{"base_id":"maximum_resistances1","class":"Witch"}]);
    old[0]["variants"] = json!([{"class":"Witch","variant_skill":606,"stats":["old variant"]}]);
    let table = f.documents["tables/PassiveSkills.json"].clone();
    let baseline = baseline_input(&f, &mut p, &table);
    add_context_column(&mut f, "NewContext", Value::Null);
    let diagnostic =
        column_projection(&mut f, &p, &old, &r, &baseline, AdapterMode::Forward).unwrap();
    assert_eq!(
        diagnostic.2["coverage"]["issues"].as_array().unwrap().len(),
        1
    );
    assert!(diagnostic.0[0].get("variants").is_some());
    assert!(diagnostic.0[0].get("native_stats").is_none());
    p["context_columns"] = column_allowance(
        &table,
        &f,
        json!([reviewed(json!({"field":"NewContext","neutral_value":null}))]),
        json!([]),
    );
    // Explicit null is a valid reviewed value, and the target text remains current.
    f.values("PassiveSkills", 5)["Stat1Value"] = json!(42);
    let closed = column_projection(&mut f, &p, &old, &r, &baseline, AdapterMode::Forward).unwrap();
    assert_eq!(closed.2["coverage"]["issues"], json!([]));
    assert_eq!(
        closed.0[0]["variants"][0]["stats"],
        json!(["+42% to Fire Resistance"])
    );
    assert_eq!(
        column_projection(&mut f, &p, &old, &r, &baseline, AdapterMode::Strict)
            .unwrap()
            .0,
        closed.0
    );
    f.values("PassiveSkills", 2)["NewContext"] = json!(1);
    f.values("PassiveSkills", 5)["NewContext"] = json!(1);
    let partial = column_projection(&mut f, &p, &old, &r, &baseline, AdapterMode::Forward).unwrap();
    let issues = partial.2["coverage"]["issues"].as_array().unwrap();
    assert_eq!(issues.len(), 2);
    assert!(
        issues
            .iter()
            .any(|i| i["kind"] == "render-context-changed" && i["entity"] == "Multi")
    );
    assert!(
        issues
            .iter()
            .any(|i| i["kind"] == "variant-context-changed")
    );
    assert!(
        issues
            .iter()
            .all(|i| i["kind"] != "context-columns-changed")
    );
    assert!(partial.0[0].get("native_stats").is_none());
    assert!(partial.0[0].get("variants").is_none());
    assert!(partial.0[2].get("native_stats").is_none());
    assert!(column_projection(&mut f, &p, &old, &r, &baseline, AdapterMode::Strict).is_err());
}

#[test]
fn column_removal_uses_each_old_id_and_never_the_reference_constant_or_row_number() {
    let (mut f, mut p, old, r) = fixture();
    // Give the unrenderable row a different historical value and exact old binding.
    f.values("PassiveSkills", 1)["Opaque"] = json!(9);
    p["compatibility_bindings"]["Unknown"]["context_sha256"] = json!(hash(
        &refresh::context(f.values("PassiveSkills", 1)).unwrap()
    ));
    let mut table = f.documents["tables/PassiveSkills.json"].clone();
    table["rows"].as_array_mut().unwrap().reverse();
    for (i, row) in table["rows"].as_array_mut().unwrap().iter_mut().enumerate() {
        row["_row"] = json!(i);
    }
    let baseline = baseline_input(&f, &mut p, &table);
    remove_context_column(&mut f, "Opaque");
    p["context_columns"] = column_allowance(
        &table,
        &f,
        json!([]),
        json!([reviewed(json!({"field":"Opaque","constant_value":7}))]),
    );
    let partial = column_projection(&mut f, &p, &old, &r, &baseline, AdapterMode::Forward).unwrap();
    let issues = partial.2["coverage"]["issues"].as_array().unwrap();
    assert!(
        issues
            .iter()
            .any(|i| i["entity"] == "Unknown" && i["kind"] == "text-binding-stale")
    );
    assert!(
        issues
            .iter()
            .all(|i| i["kind"] != "context-columns-changed")
    );
    assert!(partial.0[0].get("native_stats").is_some());
    assert!(partial.0[1].get("native_stats").is_none());
    assert_eq!(partial.0[1]["stats"], old[1]["stats"]);
    // The observed unsupported row hashes its actual missing content.
    let stale = issues
        .iter()
        .find(|i| i["kind"] == "text-binding-stale")
        .unwrap();
    assert_eq!(
        stale["observed"]["context_sha256"],
        hash(&refresh::context(f.values("PassiveSkills", 1)).unwrap())
    );
    // Explicit exact row review can bind that actual new content.
    p["compatibility_bindings"]["Unknown"]["context_sha256"] =
        stale["observed"]["context_sha256"].clone();
    let closed = column_projection(&mut f, &p, &old, &r, &baseline, AdapterMode::Forward).unwrap();
    assert_eq!(closed.2["coverage"]["issues"], json!([]));
    // Losing old-Id evidence must not manufacture the reference constant.
    table["rows"]
        .as_array_mut()
        .unwrap()
        .retain(|row| row["values"]["Id"] != "Multi");
    for (i, row) in table["rows"].as_array_mut().unwrap().iter_mut().enumerate() {
        row["_row"] = json!(i);
    }
    let baseline = baseline_input(&f, &mut p, &table);
    let absent = column_projection(&mut f, &p, &old, &r, &baseline, AdapterMode::Forward).unwrap();
    assert!(
        absent.2["coverage"]["issues"]
            .as_array()
            .unwrap()
            .iter()
            .any(|i| i["kind"] == "render-context-changed" && i["entity"] == "Multi")
    );
    // Unreviewed diagnostics may restore the row's actual varying old value.
    p.as_object_mut().unwrap().remove("context_columns");
    p["compatibility_bindings"]["Unknown"]["context_sha256"] = json!(hash(
        &refresh::context(
            &table["rows"]
                .as_array()
                .unwrap()
                .iter()
                .find(|row| row["values"]["Id"] == "Unknown")
                .unwrap()["values"]
        )
        .unwrap()
    ));
    let diagnostic =
        column_projection(&mut f, &p, &old, &r, &baseline, AdapterMode::Forward).unwrap();
    assert!(
        diagnostic.2["coverage"]["issues"]
            .as_array()
            .unwrap()
            .iter()
            .all(|i| i["entity"] != "Unknown")
    );
    assert!(
        diagnostic.2["coverage"]["issues"]
            .as_array()
            .unwrap()
            .iter()
            .any(|i| i["entity"] == "Multi" && i["kind"] == "render-context-changed")
    );
}

#[test]
fn column_allowances_reject_incomplete_stale_and_contradictory_authorizations() {
    for mode in [AdapterMode::Strict, AdapterMode::Forward] {
        for case in [
            "null",
            "unknown",
            "unreviewed",
            "column-unreviewed",
            "blank",
            "column-blank",
            "missing-value",
            "missing-constant",
            "removed-null-entry",
            "null-entry",
            "duplicate",
            "overlap",
            "wrong-added",
            "wrong-removed",
            "bound-hash",
            "target-hash",
            "bad-hash",
            "no-baseline",
            "unused",
            "unknown-column-key",
        ] {
            let (mut f, mut p, old, r) = fixture();
            let table = f.documents["tables/PassiveSkills.json"].clone();
            let baseline = baseline_input(&f, &mut p, &table);
            if case != "unused" {
                add_context_column(&mut f, "NewContext", json!(0));
            }
            p["context_columns"] = column_allowance(
                &table,
                &f,
                json!([reviewed(json!({"field":"NewContext","neutral_value":0}))]),
                json!([]),
            );
            match case {
                "null" => p["context_columns"] = Value::Null,
                "unknown" => p["context_columns"]["extra"] = json!(true),
                "unreviewed" => p["context_columns"]["review"] = json!("unreviewed"),
                "column-unreviewed" => {
                    p["context_columns"]["added"][0]["review"] = json!("unreviewed")
                }
                "blank" => p["context_columns"]["reason"] = json!(" \n"),
                "column-blank" => p["context_columns"]["added"][0]["reason"] = json!(" "),
                "missing-value" => {
                    p["context_columns"]["added"][0]
                        .as_object_mut()
                        .unwrap()
                        .remove("neutral_value");
                }
                "missing-constant" => {
                    p["context_columns"]["removed"] = json!([reviewed(json!({"field":"Opaque"}))])
                }
                "removed-null-entry" => p["context_columns"]["removed"] = json!([null]),
                "null-entry" => p["context_columns"]["added"][0] = Value::Null,
                "duplicate" => {
                    let c = p["context_columns"]["added"][0].clone();
                    p["context_columns"]["added"]
                        .as_array_mut()
                        .unwrap()
                        .push(c);
                }
                "overlap" => {
                    p["context_columns"]["removed"] =
                        json!([reviewed(json!({"field":"NewContext","constant_value":0}))])
                }
                "wrong-added" => p["context_columns"]["added"][0]["field"] = json!("Different"),
                "wrong-removed" => {
                    p["context_columns"]["removed"] =
                        json!([reviewed(json!({"field":"Opaque","constant_value":0}))])
                }
                "bound-hash" => p["context_columns"]["bound_fields_sha256"] = json!("f".repeat(64)),
                "target-hash" => {
                    p["context_columns"]["target_fields_sha256"] = json!("f".repeat(64))
                }
                "bad-hash" => p["context_columns"]["target_fields_sha256"] = json!("A".repeat(64)),
                "unknown-column-key" => p["context_columns"]["added"][0]["extra"] = json!(true),
                "no-baseline" => {
                    p.as_object_mut().unwrap().remove("context_baseline");
                }
                _ => {}
            }
            assert!(
                column_projection(&mut f, &p, &old, &r, &baseline, mode).is_err(),
                "{case}"
            );
        }
    }
}

#[test]
fn column_diagnostics_and_reviews_cannot_waive_semantic_or_physical_failures() {
    for mode in [AdapterMode::Strict, AdapterMode::Forward] {
        for approved in [false, true] {
            for case in [
                "surviving-reference",
                "scalar",
                "fk",
                "duplicate-stat",
                "missing-column",
                "wrong-kind",
                "wrong-array",
                "wrong-fk",
                "stat-slot",
            ] {
                let (mut f, mut p, old, r) = fixture();
                let table = f.documents["tables/PassiveSkills.json"].clone();
                let baseline = baseline_input(&f, &mut p, &table);
                add_context_column(&mut f, "NewContext", json!(0));
                if approved {
                    p["context_columns"] = column_allowance(
                        &table,
                        &f,
                        json!([reviewed(json!({"field":"NewContext","neutral_value":0}))]),
                        json!([]),
                    );
                }
                match case {
                    "surviving-reference" => f.values("PassiveSkills", 0)["Opaque"] = json!(5),
                    "scalar" => f.values("PassiveSkills", 2)["Stat1Value"] = json!("bad"),
                    "fk" => f.values("PassiveSkills", 2)["Stats"] = json!([999]),
                    "duplicate-stat" => f.values("PassiveSkills", 2)["Stats"] = json!([0, 0]),
                    "missing-column" => remove_context_column(&mut f, "Name"),
                    "stat-slot" => remove_context_column(&mut f, "Stat1Value"),
                    _ => {
                        let columns =
                            f.documents.get_mut("tables/PassiveSkills.json").unwrap()["columns"]
                                .as_array_mut()
                                .unwrap();
                        let stats = columns
                            .iter_mut()
                            .find(|c| c["schema"]["name"] == "Stats")
                            .unwrap();
                        match case {
                            "wrong-kind" => stats["schema"]["type"] = json!("string"),
                            "wrong-array" => stats["schema"]["array"] = json!(false),
                            _ => stats["schema"]["references"]["table"] = json!("Characters"),
                        }
                    }
                }
                assert!(
                    column_projection(&mut f, &p, &old, &r, &baseline, mode).is_err(),
                    "{case}"
                );
            }
        }
    }
    for case in ["surviving-row", "whole-text-stat", "missing-old-row"] {
        let (mut f, mut p, old, r) = fixture();
        let mut table = f.documents["tables/PassiveSkills.json"].clone();
        if case == "missing-old-row" {
            table["rows"].as_array_mut().unwrap().remove(1);
            for (i, row) in table["rows"].as_array_mut().unwrap().iter_mut().enumerate() {
                row["_row"] = json!(i);
            }
        }
        let baseline = baseline_input(&f, &mut p, &table);
        add_context_column(&mut f, "NewContext", json!(0));
        match case {
            "surviving-row" => f.values("PassiveSkills", 1)["Opaque"] = json!(33),
            "whole-text-stat" => f.values("PassiveSkills", 1)["Stat1Value"] = json!(33),
            _ => {}
        }
        let result =
            column_projection(&mut f, &p, &old, &r, &baseline, AdapterMode::Forward).unwrap();
        let issues = result.2["coverage"]["issues"].as_array().unwrap();
        assert!(
            issues
                .iter()
                .any(|i| i["kind"] == "context-columns-changed")
        );
        assert!(
            issues
                .iter()
                .any(|i| i["entity"] == "Unknown" && i["kind"] == "text-binding-stale"),
            "{case}"
        );
        assert!(result.0[1].get("native_stats").is_none());
    }
}

#[test]
fn column_adjustment_preserves_the_consumed_definition_scope() {
    for approved in [false, true] {
        let (mut f, mut p, old, r) = fixture();
        let table = f.documents["tables/PassiveSkills.json"].clone();
        let baseline = baseline_input(&f, &mut p, &table);
        add_context_column(&mut f, "NewContext", json!(0));
        if approved {
            p["context_columns"] = column_allowance(
                &table,
                &f,
                json!([reviewed(json!({"field":"NewContext","neutral_value":0}))]),
                json!([]),
            );
        }
        // The published table contains an unused definition with duplicate
        // stats. Column review cannot introduce a new consumer for such rows.
        f.values("PassiveSkills", 3)["Stats"] = json!([0, 0]);
        let result =
            column_projection(&mut f, &p, &old, &r, &baseline, AdapterMode::Forward).unwrap();
        assert_eq!(
            result.2["coverage"]["issues"].as_array().unwrap().len(),
            usize::from(!approved)
        );
        // The same physical defect on a consumed definition remains fatal.
        f.values("PassiveSkills", 2)["Stats"] = json!([0, 0]);
        let error =
            column_projection(&mut f, &p, &old, &r, &baseline, AdapterMode::Forward).unwrap_err();
        assert!(error.contains("duplicate"), "{error}");
    }
}

#[test]
fn column_exclusion_proofs_keep_actual_definition_and_stats_changes_visible() {
    for change in ["none", "name", "stats"] {
        let (mut f, mut p, old, r) = fixture();
        p["excluded"]["Unknown"] = json!({
            "definition_sha256":hash(f.values("PassiveSkills",1)), "reason":"reviewed placeholder"
        });
        let table = f.documents["tables/PassiveSkills.json"].clone();
        let baseline = baseline_input(&f, &mut p, &table);
        add_context_column(&mut f, "NewContext", json!(0));
        match change {
            "name" => f.values("PassiveSkills", 1)["Name"] = json!("new actual definition"),
            "stats" => f.values("PassiveSkills", 1)["Stat1Value"] = json!(44),
            _ => {}
        }
        let result =
            column_projection(&mut f, &p, &old, &r, &baseline, AdapterMode::Forward).unwrap();
        let issues = result.2["coverage"]["issues"].as_array().unwrap();
        if change == "none" {
            assert_eq!(issues.len(), 1);
            assert_eq!(result.2["excluded"].as_array().unwrap().len(), 1);
        } else {
            assert!(
                issues.iter().any(|i| i["kind"] == "excluded-definition"),
                "{change}"
            );
        }
    }
}
#[test]
fn columns_round_trip_through_production_conversion_build_coverage_and_policy_draft() {
    let (mut f, mut p, old, r) = fixture();
    let table = f.documents["tables/PassiveSkills.json"].clone();
    let baseline = baseline_input(&f, &mut p, &table);
    add_context_column(&mut f, "NewContext", json!(0));
    let make_args = |f: &mut Fixture, p: &mut Value, mode, name: &str| {
        let mut args = pinned_refresh_args(f, p, &old, &r);
        args.mode = mode;
        args.out = f.root.join(name);
        args.tree_refresh.as_mut().unwrap().context_baseline = Some(refresh::ContextBaselineArgs {
            path: baseline.path.clone(),
            sha256: baseline.sha256.clone(),
        });
        args
    };
    crate::ordinary_facts::run(make_args(
        &mut f,
        &mut p,
        AdapterMode::Forward,
        "column-open",
    ))
    .unwrap();
    let evidence = f.root.join("column-consumer");
    fs::create_dir(&evidence).unwrap();
    fs::copy(
        f.root.join("column-open/producer-receipt.json"),
        evidence.join("producer-receipt.json"),
    )
    .unwrap();
    let consumer = r#"
import json, sys
from pathlib import Path
from types import SimpleNamespace
from RePoE.release import build, policy_draft
root = Path(sys.argv[1])
receipt = json.loads((root / 'producer-receipt.json').read_text())
coverage = build.build_coverage(SimpleNamespace(coverage={'tree': receipt['conversion']['coverage']}))
assert coverage['open_tree_issues'] == 1
(root / 'build-receipt.json').write_text(json.dumps({'coverage': coverage}, sort_keys=True) + '\n')
summary = policy_draft.draft(receipt=root / 'build-receipt.json', out=root / 'draft')
assert summary['entries'] == summary['drafted'] == 1
assert summary['by_entry_type']['context_columns'] == 1
assert not summary['by_entry_type']['blocked'] and not summary['by_entry_type']['unhandled']
print(json.dumps(summary, sort_keys=True))
"#;
    fs::write(evidence.join("consume.py"), consumer).unwrap();
    let repo = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap();
    let result = std::process::Command::new("python3")
        .arg("-B")
        .arg(evidence.join("consume.py"))
        .arg(&evidence)
        .current_dir(repo)
        .env("PYTHONPATH", repo)
        .output()
        .unwrap();
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
    let draft: Value = crate::read_json(&evidence.join("draft/passive-tree.draft.json")).unwrap();
    let fields = column_allowance(&table, &f, json!([]), json!([]));
    let columns = &draft["context_columns"];
    assert_eq!(
        columns["bound_fields_sha256"],
        fields["bound_fields_sha256"]
    );
    assert_eq!(
        columns["target_fields_sha256"],
        fields["target_fields_sha256"]
    );
    assert_eq!(columns["review"], "unreviewed");
    assert_eq!(
        columns["added"],
        json!([{
            "field":"NewContext","neutral_value":null,"review":"unreviewed","reason":""
        }])
    );
    assert_eq!(columns["removed"], json!([]));
    p["context_columns"] = columns.clone();
    fs::write(
        evidence.join("unreviewed-policy.json"),
        reader::json_bytes(&p).unwrap(),
    )
    .unwrap();
    for mode in [AdapterMode::Strict, AdapterMode::Forward] {
        assert!(crate::ordinary_facts::run(make_args(&mut f, &mut p, mode, "unreviewed")).is_err());
        assert!(!f.root.join("unreviewed").exists());
    }
    p["context_columns"] = reviewed(columns.clone());
    p["context_columns"]["added"][0] = reviewed(columns["added"][0].clone());
    p["context_columns"]["added"][0]["neutral_value"] = json!(0);
    fs::write(
        evidence.join("reviewed-policy.json"),
        reader::json_bytes(&p).unwrap(),
    )
    .unwrap();
    for (mode, name) in [
        (AdapterMode::Forward, "column-closed-forward"),
        (AdapterMode::Strict, "column-closed-strict"),
    ] {
        crate::ordinary_facts::run(make_args(&mut f, &mut p, mode, name)).unwrap();
        let receipt: Value =
            crate::read_json(&f.root.join(name).join("producer-receipt.json")).unwrap();
        let tree: Value =
            crate::read_json(&f.root.join(name).join("base/passive_tree.json")).unwrap();
        if mode == AdapterMode::Forward {
            assert_eq!(receipt["conversion"]["coverage"]["issues"], json!([]));
        }
        assert!(tree[0].get("native_stats").is_some());
        assert_eq!(tree[0]["stats"], json!(["-7% to Fire Resistance"]));
        fs::write(
            evidence.join(format!("{name}-receipt.json")),
            reader::json_bytes(&receipt).unwrap(),
        )
        .unwrap();
        fs::write(
            evidence.join(format!("{name}-tree.json")),
            reader::json_bytes(&tree).unwrap(),
        )
        .unwrap();
    }
    assert_eq!(
        fs::read(f.root.join("column-closed-forward/base/passive_tree.json")).unwrap(),
        fs::read(f.root.join("column-closed-strict/base/passive_tree.json")).unwrap()
    );
    if let Some(destination) = std::env::var_os("P12A_COLUMNS_EVIDENCE_DIR") {
        let destination = std::path::PathBuf::from(destination);
        fs::create_dir_all(destination.join("draft")).unwrap();
        for file in [
            "producer-receipt.json",
            "build-receipt.json",
            "consume.py",
            "draft/passive-tree.draft.json",
            "draft/summary.json",
            "unreviewed-policy.json",
            "reviewed-policy.json",
            "column-closed-forward-receipt.json",
            "column-closed-forward-tree.json",
            "column-closed-strict-receipt.json",
            "column-closed-strict-tree.json",
        ] {
            fs::copy(evidence.join(file), destination.join(file)).unwrap();
        }
        fs::copy(
            &baseline.path,
            destination.join("PassiveSkills-baseline.json"),
        )
        .unwrap();
        fs::write(
            destination.join("PassiveSkills-target.json"),
            reader::json_bytes(&f.documents["tables/PassiveSkills.json"]).unwrap(),
        )
        .unwrap();
    }
}

pub(super) fn project_with_baseline(
    f: &mut Fixture,
    policy: &Value,
    old: &Value,
    reference: &Value,
    baseline: Option<&refresh::ContextBaselineArgs>,
    coverage: &mut Coverage,
) -> Result<(Value, Value, Value), String> {
    let input = input(f);
    let policy: refresh::Policy =
        serde_json::from_value(policy.clone()).map_err(|e| e.to_string())?;
    let baseline = refresh::read_context_baseline(&policy, baseline)?;
    let facts = Facts::read_with_context(
        &input,
        &policy.base_policy,
        baseline.as_ref().map(|(b, _)| b),
        policy.context_columns.as_ref(),
        coverage.is_forward(),
    )?;
    let descriptions = descriptions();
    let renderer = Renderer::new(&descriptions)?;
    refresh::project(
        &input,
        &facts,
        &policy,
        old,
        reference,
        &renderer,
        None,
        &hash(old),
        coverage,
    )
}
fn edit_node(f: &mut Fixture, id: u64, edit: impl Fn(&mut Value)) {
    for n in f.documents.get_mut("graph.json").unwrap()["groups"][0]["nodes"]
        .as_array_mut()
        .unwrap()
    {
        if n["graph_id"] == id {
            edit(n);
        }
    }
    for n in f.documents.get_mut("passives.json").unwrap()["default_graph_instances"]
        .as_array_mut()
        .unwrap()
    {
        if n["graph_id"] == id {
            edit(n);
        }
    }
}

fn forward_project(
    f: &mut Fixture,
    policy: &Value,
    old: &Value,
    reference: &Value,
) -> (Value, Value, Value) {
    let mut coverage = Coverage::new(AdapterMode::Forward, "passive-tree");
    let (tree, meta, mut receipt) =
        project_with_coverage(f, policy, old, reference, &mut coverage).unwrap();
    coverage.finish(&mut receipt).unwrap();
    (tree, meta, receipt)
}

pub(super) fn reviewed(mut entry: Value) -> Value {
    entry["review"] = json!("reviewed");
    entry["reason"] = json!("explicit fixture review of current evidence");
    entry
}

pub(super) fn closing_entry(receipt: &Value, kind: &str) -> Value {
    reviewed(
        receipt["coverage"]["issues"]
            .as_array()
            .unwrap()
            .iter()
            .find(|issue| issue["kind"] == kind)
            .unwrap()["observed"]
            .clone(),
    )
}

#[test]
fn audit_reviewed_placement_validates_consumed_flags_without_reordering_stale_errors() {
    let (mut f, mut p, mut old, r) = fixture();
    old[0]["group"] = json!(2);
    let (_, _, open) = forward_project(&mut f, &p, &old, &r);
    p["placement_rebase"] = closing_entry(&open, "placement-rebase");
    // Both classification fields are outside the context projection. The first
    // true flag must not hide a malformed later flag after geometry review.
    f.values("PassiveSkills", 2)["IsKeystone"] = json!(true);
    f.values("PassiveSkills", 2)["IsNotable"] = json!("bad");
    let mut stale = p.clone();
    stale["placement_rebase"]["moved_count"] = json!(2);
    assert_eq!(
        project(&mut f, &stale, &old, &r).unwrap_err(),
        "prepared placement lacks exact reference group/orbit/slot binding"
    );
    let result = project(&mut f, &p, &old, &r);
    assert!(
        result.is_err(),
        "reviewed placement accepted malformed flags"
    );
    assert!(result.unwrap_err().contains("IsNotable"));
}

#[test]
fn audit_quarantined_new_node_keeps_anointment_scalar_validation() {
    let (mut f, mut p, mut old, r) = fixture();
    anointment_column(&mut f, &mut p, &[]);
    old.as_array_mut().unwrap().remove(2);
    f.values("PassiveSkills", 2)["Name"] = json!("[DNT] New placeholder");
    f.values("PassiveSkills", 2)["IsAnointmentOnly"] = json!("bad");
    let result = project_with_coverage(
        &mut f,
        &p,
        &old,
        &r,
        &mut Coverage::new(AdapterMode::Forward, "passive-tree"),
    );
    assert!(
        result.is_err(),
        "quarantine swallowed anointment scalar validation"
    );
    assert!(
        result
            .unwrap_err()
            .contains("IsAnointmentOnly: bool required")
    );
}

#[test]
fn audit_forward_quarantine_and_exclusion_keep_complete_physical_validation() {
    for skip in ["name", "identity", "exclusion"] {
        for defect in ["stats", "flag"] {
            let (mut f, mut p, mut old, r) = fixture();
            match defect {
                "stats" => f.values("PassiveSkills", 2)["Stats"] = json!([0, 0]),
                _ => f.values("PassiveSkills", 2)["IsNotable"] = json!("bad"),
            }
            match skip {
                "name" => f.values("PassiveSkills", 2)["Name"] = json!("[DNT] Placeholder"),
                "identity" => old[2]["id"] = json!("previous-Multi"),
                _ => {
                    p["excluded"]["Multi"] = json!({
                        "definition_sha256":hash(f.values("PassiveSkills", 2)),
                        "reason":"reviewed placeholder"
                    });
                }
            }
            let result = project_with_coverage(
                &mut f,
                &p,
                &old,
                &r,
                &mut Coverage::new(AdapterMode::Forward, "passive-tree"),
            );
            assert!(
                result.is_err(),
                "{skip}/{defect}: skipped physical validation"
            );
            let error = result.unwrap_err();
            assert!(
                error.contains(if defect == "stats" {
                    "duplicate"
                } else {
                    "IsNotable"
                }),
                "{skip}/{defect}: {error}"
            );
        }
    }
}

#[test]
fn audit_column_preflight_does_not_consume_unused_or_replaced_alias_rows() {
    for replaced in [false, true] {
        let (mut f, mut p, mut old, r) = fixture();
        if replaced {
            f.values("ClassPassiveSkillOverrides", 0)["SkillToOverride"] = json!(0);
            p["class_bindings"] = json!([{"base_id":"maximum_resistances1","class":"Witch"}]);
            old[0]["variants"] =
                json!([{"class":"Witch","variant_skill":707,"stats":["superseded"]}]);
            f.values("PassiveSkills", 6)["Stats"] = json!([0, 0]);
        } else {
            f.values("PassiveSkills", 3)["PassiveSkillGraphId"] = json!("unused");
        }
        let mut original = project(&mut f, &p, &old, &r).unwrap().0;
        let table = f.documents["tables/PassiveSkills.json"].clone();
        let baseline = baseline_input(&f, &mut p, &table);
        add_context_column(&mut f, "NewContext", json!(0));
        p["context_columns"] = column_allowance(
            &table,
            &f,
            json!([reviewed(json!({"field":"NewContext","neutral_value":0}))]),
            json!([]),
        );
        let result = column_projection(&mut f, &p, &old, &r, &baseline, AdapterMode::Strict);
        assert!(result.is_ok(), "unused row became a consumer: {result:?}");
        let mut adjusted = result.unwrap().0;
        for (before, after) in original
            .as_array_mut()
            .unwrap()
            .iter_mut()
            .zip(adjusted.as_array_mut().unwrap())
        {
            let old_packet = before.as_object_mut().unwrap().remove("native_stats");
            let new_packet = after.as_object_mut().unwrap().remove("native_stats");
            assert_eq!(old_packet.is_some(), new_packet.is_some());
            if let (Some(mut old_packet), Some(mut new_packet)) = (old_packet, new_packet) {
                // Re-sealing the target table changes its provenance pin.
                for packet in [&mut old_packet, &mut new_packet] {
                    for stat in packet["stats"].as_array_mut().unwrap() {
                        stat.as_object_mut().unwrap().remove("provenance");
                    }
                }
                assert_eq!(old_packet, new_packet);
            }
        }
        assert_eq!(adjusted, original);
    }
}

#[test]
fn audit_quarantine_keeps_retained_alias_identity_unambiguous() {
    for duplicate in [false, true] {
        let (mut f, p, mut old, r) = fixture();
        old[0]["variants"] = json!([{
            "class":"Lich","variant_skill":if duplicate {707} else {65000},"stats":["old"]
        }]);
        if duplicate {
            f.values("PassiveSkills", 3)["PassiveSkillGraphId"] = json!(707);
        }
        f.values("PassiveSkills", 0)["Name"] = json!("[DNT] Placeholder");
        let result = project_with_coverage(
            &mut f,
            &p,
            &old,
            &r,
            &mut Coverage::new(AdapterMode::Forward, "passive-tree"),
        );
        assert!(
            result.is_err(),
            "quarantine swallowed alias identity failure"
        );
        assert!(
            result
                .unwrap_err()
                .contains("ambiguous/missing physical identity")
        );
    }
}

#[test]
fn audit_preflight_resolves_alias_owners_from_actual_target_membership_and_identity() {
    for renamed in [false, true] {
        let (mut f, mut p, mut old, r) = fixture();
        f.values("PassiveSkills", 6)["Stats"] = json!([0, 0]);
        if renamed {
            f.values("ClassPassiveSkillOverrides", 0)["SkillToOverride"] = json!(0);
            p["class_bindings"] = json!([{"base_id":"maximum_resistances1","class":"Witch"}]);
            old[0]["id"] = json!("legacy-resistance");
            old[0]["variants"] =
                json!([{"class":"Witch","variant_skill":707,"stats":["superseded"]}]);
            p["base_policy"]["legacy_id_bindings"] = json!([{
                "legacy_id":"legacy-resistance","skill":101,"target_passive_id":"maximum_resistances1",
                "expected_name":"old","source_entry_sha256":hash(&old[0]),"role":"fixture alias"
            }]);
        } else {
            old[2]["variants"] =
                json!([{"class":"Lich","variant_skill":707,"stats":["removed base"]}]);
            edit_node(&mut f, 101, |node| {
                node["connections"] = json!([]);
                node["splines"] = json!([]);
            });
            f.documents.get_mut("graph.json").unwrap()["groups"][0]["nodes"]
                .as_array_mut()
                .unwrap()
                .retain(|n| n["graph_id"] != 303);
            f.documents.get_mut("passives.json").unwrap()["default_graph_instances"]
                .as_array_mut()
                .unwrap()
                .retain(|n| n["graph_id"] != 303);
        }
        // The original strict path consumes neither retired alias.
        project(&mut f, &p, &old, &r).unwrap();
        let result = project_with_coverage(
            &mut f,
            &p,
            &old,
            &r,
            &mut Coverage::new(AdapterMode::Forward, "passive-tree"),
        );
        assert!(
            result.is_ok(),
            "retired alias became a consumer: {result:?}"
        );
    }
}

#[test]
fn audit_quarantined_base_still_rejects_duplicate_class_replacement_selectors() {
    let (mut f, p, old, r) = fixture();
    f.values("ClassPassiveSkillOverrides", 0)["SkillToOverride"] = json!(0);
    let overrides = f
        .documents
        .get_mut("tables/ClassPassiveSkillOverrides.json")
        .unwrap();
    let mut duplicate = overrides["rows"][0].clone();
    duplicate["_row"] = json!(1);
    overrides["rows"].as_array_mut().unwrap().push(duplicate);
    overrides["validation"]["rows"] = json!(2);
    f.values("PassiveSkills", 0)["Name"] = json!("[DNT] Placeholder");
    let result = project_with_coverage(
        &mut f,
        &p,
        &old,
        &r,
        &mut Coverage::new(AdapterMode::Forward, "passive-tree"),
    );
    assert!(result.is_err(), "quarantine swallowed duplicate selectors");
    assert!(
        result
            .unwrap_err()
            .contains("repeated replacement selector")
    );
}

#[test]
fn audit_column_adjusted_exclusions_preserve_exact_placement_sets_and_independent_gaps() {
    for columns in ["absent", "diagnostic", "reviewed"] {
        let (mut f, mut p, mut old, r) = fixture();
        old[0]["group"] = json!(2);
        old[1]["group"] = json!(2);
        let table = f.documents["tables/PassiveSkills.json"].clone();
        p["excluded"]["Unknown"] = json!({
            "definition_sha256":hash(&table["rows"][1]["values"]),
            "reason":"reviewed placeholder"
        });
        let baseline = if columns == "absent" {
            None
        } else {
            let baseline = baseline_input(&f, &mut p, &table);
            add_context_column(&mut f, "NewContext", json!(0));
            if columns == "reviewed" {
                p["context_columns"] = column_allowance(
                    &table,
                    &f,
                    json!([reviewed(json!({"field":"NewContext","neutral_value":0}))]),
                    json!([]),
                );
            }
            Some(baseline)
        };
        let run = |f: &mut Fixture, p: &Value, mode| {
            let mut coverage = Coverage::new(mode, "passive-tree");
            let (tree, meta, mut receipt) =
                project_with_baseline(f, p, &old, &r, baseline.as_ref(), &mut coverage)?;
            coverage.finish(&mut receipt)?;
            Ok::<_, String>((tree, meta, receipt))
        };
        let open = run(&mut f, &p, AdapterMode::Forward).unwrap();
        p["placement_rebase"] = closing_entry(&open.2, "placement-rebase");
        assert_eq!(
            p["placement_rebase"]["moved_skills_sha256"],
            hash(&vec![101_u64])
        );
        let closed = run(&mut f, &p, AdapterMode::Forward).unwrap();
        assert!(
            closed.2["coverage"]["issues"]
                .as_array()
                .unwrap()
                .iter()
                .all(|issue| issue["kind"] == "context-columns-changed")
        );
        // Change only which exact row is excluded: source/reference pins and
        // moved count stay fixed, so only the set hash can invalidate review.
        p["excluded"] = json!({"maximum_resistances1":{
            "definition_sha256":hash(&table["rows"][0]["values"]),
            "reason":"reviewed placeholder"
        }});
        let stale = run(&mut f, &p, AdapterMode::Forward).unwrap();
        let moved = closing_entry(&stale.2, "placement-rebase");
        assert_eq!(moved["moved_count"], 1);
        assert_eq!(moved["moved_skills_sha256"], hash(&vec![202_u64]));
        assert!(stale.0[0].get("native_stats").is_none());
        assert_eq!(
            run(&mut f, &p, AdapterMode::Strict).unwrap_err(),
            if columns == "diagnostic" {
                "reference context SHA256 mismatch"
            } else {
                "prepared placement lacks exact reference group/orbit/slot binding"
            }
        );
        // Fresh geometry review cannot close a separate changed exclusion or
        // the whole-text semantic change on that row.
        p["excluded"] = json!({"Unknown":{
            "definition_sha256":hash(&table["rows"][1]["values"]),
            "reason":"reviewed placeholder"
        }});
        f.values("PassiveSkills", 1)["Opaque"] = json!(99);
        let open = run(&mut f, &p, AdapterMode::Forward).unwrap();
        p["placement_rebase"] = closing_entry(&open.2, "placement-rebase");
        let partial = run(&mut f, &p, AdapterMode::Forward).unwrap();
        let issues = partial.2["coverage"]["issues"].as_array().unwrap();
        assert!(
            issues
                .iter()
                .any(|issue| issue["kind"] == "excluded-definition")
        );
        assert!(
            issues
                .iter()
                .any(|issue| issue["kind"] == "text-binding-stale")
        );
        assert!(
            issues
                .iter()
                .all(|issue| issue["kind"] != "placement-rebase")
        );
        assert!(partial.0[1].get("native_stats").is_none());
    }
}

#[test]
fn reviewed_placement_closes_only_exact_moved_evidence_at_the_old_strict_site() {
    let (mut f, mut p, mut old, r) = fixture();
    old[0]["group"] = json!(2);
    old[0].as_object_mut().unwrap().remove("x");
    old[0].as_object_mut().unwrap().remove("y");
    f.documents.get_mut("graph.json").unwrap()["groups"][0]["x"] = json!(35.0);
    let (_, _, open) = forward_project(&mut f, &p, &old, &r);
    p["placement_rebase"] = closing_entry(&open, "placement-rebase");
    let (tree, _, closed) = forward_project(&mut f, &p, &old, &r);
    assert_eq!(closed["coverage"]["issues"], json!([]));
    assert!(tree[0].get("x").is_none());
    assert!(tree[0].get("y").is_none());
    assert!(tree[0].get("native_stats").is_some());
    assert_eq!(project(&mut f, &p, &old, &r).unwrap().0, tree);
    for field in [
        "reference_sha256",
        "legacy_source_sha256",
        "moved_skills_sha256",
        "moved_count",
    ] {
        let mut stale = p.clone();
        stale["placement_rebase"][field] = if field == "moved_count" {
            json!(2)
        } else {
            json!("f".repeat(64))
        };
        let (_, _, receipt) = forward_project(&mut f, &stale, &old, &r);
        assert_eq!(receipt["coverage"], open["coverage"], "{field}");
        let mut later_defect = r.clone();
        later_defect["nodes"].as_object_mut().unwrap().remove("303");
        assert_eq!(
            project(&mut f, &stale, &old, &later_defect).unwrap_err(),
            "prepared placement lacks exact reference group/orbit/slot binding",
            "{field}"
        );
    }
    // Same count, different set cannot reuse the approval.
    let mut other = old.clone();
    other[0]["group"] = json!(1);
    other[1]["group"] = json!(2);
    let (_, _, receipt) = forward_project(&mut f, &p, &other, &r);
    assert!(
        receipt["coverage"]["issues"]
            .as_array()
            .unwrap()
            .iter()
            .any(|issue| issue["kind"] == "placement-rebase")
    );
    // Approval does not excuse another open variant issue.
    old[0]["variants"] = json!([{"class":"Lich","stats":["unknown alias"]}]);
    let (_, _, open) = forward_project(&mut f, &p, &old, &r);
    p["placement_rebase"] = closing_entry(&open, "placement-rebase");
    let (tree, _, receipt) = forward_project(&mut f, &p, &old, &r);
    assert_eq!(
        receipt["coverage"]["issues"][0]["kind"],
        "variant-alias-missing"
    );
    assert!(tree[0].get("native_stats").is_none());
    let (_, _, original_old, _) = fixture();
    assert!(
        project(&mut f, &p, &original_old, &r)
            .unwrap_err()
            .contains("unused placement_rebase")
    );
}

#[test]
fn closing_entries_require_complete_review_in_both_modes() {
    let (_, p, old, r) = fixture();
    let entries = [
        (
            "placement_rebase",
            reviewed(json!({
                "reference_sha256":p["reference_sha256"],"legacy_source_sha256":hash(&old),
                "moved_skills_sha256":hash(&vec![101_u64]),"moved_count":1
            })),
        ),
        (
            "ascendancy_frames",
            json!({"Witch3":reviewed(json!({
                "start_skill":303,"dx":10.0,"dy":20.0,
                "reference_start_node_sha256":hash(&r["nodes"]["303"]),
                "member_skills_sha256":hash(&vec![303_u64])
            }))}),
        ),
        (
            "compatibility_bindings",
            json!({"Unknown":reviewed(json!({
                "context_sha256":p["compatibility_bindings"]["Unknown"]["context_sha256"],
                "stats_sha256":p["compatibility_bindings"]["Unknown"]["stats_sha256"],
                "lines":["reviewed complete text"],"origin":"manual"
            }))}),
        ),
    ];
    for (field, valid) in entries {
        for defect in [
            "review",
            "reason",
            "blank-reason",
            "draft",
            "null",
            "unknown",
            "partial",
        ] {
            let mut policy = p.clone();
            policy[field] = valid.clone();
            let entry = match field {
                "ascendancy_frames" => &mut policy[field]["Witch3"],
                "compatibility_bindings" => &mut policy[field]["Unknown"],
                _ => &mut policy[field],
            };
            match defect {
                "review" | "reason" => {
                    entry.as_object_mut().unwrap().remove(defect);
                }
                "blank-reason" => entry["reason"] = json!(" \t\n "),
                "draft" => entry["review"] = json!("unreviewed"),
                "null" => {
                    entry[if field == "ascendancy_frames" {
                        "dx"
                    } else {
                        "review"
                    }] = Value::Null
                }
                "unknown" => entry["unexpected"] = json!(true),
                _ => {
                    entry.as_object_mut().unwrap().remove(match field {
                        "placement_rebase" => "moved_skills_sha256",
                        "ascendancy_frames" => "dy",
                        _ => "origin",
                    });
                }
            }
            for mode in [AdapterMode::Strict, AdapterMode::Forward] {
                let (mut f, _, _, _) = fixture();
                assert!(
                    project_with_coverage(
                        &mut f,
                        &policy,
                        &old,
                        &r,
                        &mut Coverage::new(mode, "passive-tree")
                    )
                    .is_err(),
                    "{field}/{defect}"
                );
            }
        }
    }
    for lines in [json!([]), json!(["  "]), json!([4]), Value::Null] {
        let (mut f, mut p, old, r) = fixture();
        let mut binding = reviewed(p["compatibility_bindings"]["Unknown"].clone());
        binding["lines"] = lines;
        binding["origin"] = json!("manual");
        p["compatibility_bindings"]["Unknown"] = binding;
        assert!(project(&mut f, &p, &old, &r).is_err());
    }
}

#[test]
fn reviewed_new_whole_text_requires_exact_evidence_and_never_creates_a_packet() {
    let (mut f, mut p, mut old, mut r) = fixture();
    anointment_column(&mut f, &mut p, &[]);
    old.as_array_mut().unwrap().remove(1);
    let mut binding = reviewed(p["compatibility_bindings"]["Unknown"].clone());
    binding["lines"] = json!(["Approved one", "Approved two"]);
    binding["origin"] = json!("official-reference");
    p["compatibility_bindings"]["Unknown"] = binding;
    r["nodes"]["202"]["stats"] = json!([" Approved one\n\n Approved two "]);
    let (tree, _, receipt) = forward_project(&mut f, &p, &old, &r);
    assert_eq!(receipt["coverage"]["issues"], json!([]));
    assert_eq!(tree[1]["stats"], json!(["Approved one", "Approved two"]));
    assert!(tree[1].get("native_stats").is_none());
    assert_eq!(
        receipt["source_records"][1]["text"]["owner"],
        "reviewed-whole-text"
    );
    assert_eq!(project(&mut f, &p, &old, &r).unwrap().0, tree);
    for field in ["context_sha256", "stats_sha256"] {
        let mut stale = p.clone();
        stale["compatibility_bindings"]["Unknown"][field] = json!("f".repeat(64));
        let (tree, _, receipt) = forward_project(&mut f, &stale, &old, &r);
        assert_eq!(tree[1]["stats"], json!([]));
        assert!(
            receipt["coverage"]["issues"]
                .as_array()
                .unwrap()
                .iter()
                .any(|issue| issue["kind"] == "text-unrenderable-new")
        );
        assert!(project(&mut f, &stale, &old, &r).is_err());
    }
    // Conflicting reference candidates leave the new node empty and open.
    r["nodes"]["202"]["stats"] = json!(["Different official text"]);
    let (tree, _, receipt) = forward_project(&mut f, &p, &old, &r);
    assert_eq!(tree[1]["stats"], json!([]));
    assert!(
        receipt["coverage"]["issues"][0]["message"]
            .as_str()
            .unwrap()
            .contains("differs from reference")
    );
    assert!(project(&mut f, &p, &old, &r).is_err());
    r["nodes"]["202"].as_object_mut().unwrap().remove("stats");
    // A manual review can supply text when the reference has none.
    p["compatibility_bindings"]["Unknown"]["origin"] = json!("manual");
    assert_eq!(
        forward_project(&mut f, &p, &old, &r).0[1]["stats"],
        json!(["Approved one", "Approved two"])
    );
    // Prepared text, even if the renderer would succeed, cannot be overridden.
    let (_, _, original_old, _) = fixture();
    for mode in [AdapterMode::Strict, AdapterMode::Forward] {
        assert!(
            project_with_coverage(
                &mut f,
                &p,
                &original_old,
                &r,
                &mut Coverage::new(mode, "passive-tree")
            )
            .unwrap_err()
            .contains("existing prepared text")
        );
    }
    // Rendering success keeps target numbers, without borrowing reviewed text.
    f.values("PassiveSkills", 1)["Stats"] = json!([0]);
    let (tree, _, receipt) = forward_project(&mut f, &p, &old, &r);
    assert_eq!(tree[1]["stats"], json!(["-7% to Fire Resistance"]));
    assert_eq!(receipt["source_records"][1]["text"]["owner"], "target-csd");
    assert_eq!(receipt["coverage"]["issues"], json!([]));
    // An unrelated open variant issue still suppresses its base packet.
    old[0]["variants"] = json!([{"class":"Lich","stats":["aliasless"]}]);
    let (tree, _, receipt) = forward_project(&mut f, &p, &old, &r);
    assert_eq!(
        receipt["coverage"]["issues"][0]["kind"],
        "variant-alias-missing"
    );
    assert!(tree[0].get("native_stats").is_none());
    // Complete reviewed text cannot swallow malformed stats or later flags.
    for defect in ["duplicate-stats", "bad-flag", "bad-stat", "dangling-stat"] {
        let (mut f, _, _, _) = fixture();
        anointment_column(&mut f, &mut p, &[]);
        match defect {
            "duplicate-stats" => {
                f.values("PassiveSkills", 1)["Stats"] = json!([1, 1]);
                f.values("PassiveSkills", 1)["Stat2Value"] = json!(-7);
            }
            "bad-flag" => {
                f.values("PassiveSkills", 1)["IsKeystone"] = json!(true);
                f.values("PassiveSkills", 1)["IsNotable"] = json!("bad");
            }
            "bad-stat" => f.values("PassiveSkills", 1)["Stat1Value"] = json!("bad"),
            _ => f.values("PassiveSkills", 1)["Stats"] = json!([999]),
        }
        for mode in [AdapterMode::Strict, AdapterMode::Forward] {
            assert!(
                project_with_coverage(
                    &mut f,
                    &p,
                    &old,
                    &r,
                    &mut Coverage::new(mode, "passive-tree")
                )
                .is_err(),
                "{defect}"
            );
        }
    }
}

#[test]
fn reviewed_text_entries_cannot_name_unknown_unused_or_prepared_variant_targets() {
    for id in ["Absent", "Context", "OverrideTarget"] {
        let (mut f, mut p, mut old, r) = fixture();
        let mut binding = reviewed(p["compatibility_bindings"]["Unknown"].clone());
        binding["lines"] = json!(["complete text"]);
        binding["origin"] = json!("manual");
        p["compatibility_bindings"][id] = binding;
        if id == "OverrideTarget" {
            old[0]["variants"] =
                json!([{"class":"Lich","variant_skill":606,"stats":["prepared text"]}]);
        }
        for mode in [AdapterMode::Strict, AdapterMode::Forward] {
            let error = project_with_coverage(
                &mut f,
                &p,
                &old,
                &r,
                &mut Coverage::new(mode, "passive-tree"),
            )
            .unwrap_err();
            assert!(
                error.contains(match id {
                    "Absent" => "unknown reviewed text identity",
                    "Context" => "unused reviewed whole-text binding",
                    _ => "existing prepared text",
                }),
                "{error}"
            );
        }
    }
}

pub(super) fn anointment_column(f: &mut Fixture, p: &mut Value, flagged: &[usize]) {
    let stats = f.documents["tables/Stats.json"]["rows"].clone();
    let passive = f.documents.get_mut("tables/PassiveSkills.json").unwrap();
    let n = passive["columns"].as_array().unwrap().len();
    passive["columns"].as_array_mut().unwrap().push(json!({
        "source_column":n,"physical_fields":["IsAnointmentOnly"],
        "schema":{"name":"IsAnointmentOnly","type":"bool","array":false,
            "interval":false,"references":null}
    }));
    passive["physical_fields"]
        .as_array_mut()
        .unwrap()
        .push(json!("IsAnointmentOnly"));
    for (row, raw) in passive["rows"]
        .as_array_mut()
        .unwrap()
        .iter_mut()
        .enumerate()
    {
        raw["values"]["IsAnointmentOnly"] = json!(flagged.contains(&row));
        let values = &raw["values"];
        let id = values["Id"].as_str().unwrap();
        if p["compatibility_bindings"].get(id).is_some() || flagged.contains(&row) {
            let binding = &mut p["compatibility_bindings"][id];
            binding["context_sha256"] = json!(hash(&refresh::context(values).unwrap()));
            let raw_stats: Vec<_> = values["Stats"]
                .as_array()
                .unwrap()
                .iter()
                .enumerate()
                .map(|(i, stat)| {
                    json!([
                        stats[stat.as_u64().unwrap() as usize]["values"]["Id"],
                        values[format!("Stat{}Value", i + 1)]
                    ])
                })
                .collect();
            binding["stats_sha256"] = json!(hash(&raw_stats));
        }
    }
    p["base_policy"]["qualification"]["context_sha256"] = json!(hash(
        &super::source::context(f.values("PassiveSkills", 0)).unwrap()
    ));
}

pub(super) fn instantiate(f: &mut Fixture, row: usize) {
    let raw = f.values("PassiveSkills", row).clone();
    let instance = json!({
        "definition":{"row":row,"id":raw["Id"]},"graph_id":raw["PassiveSkillGraphId"],
        "group":0,"radius":0,"position":0,"connections":[],"splines":[]
    });
    let mut node = instance.clone();
    node.as_object_mut().unwrap().remove("definition");
    node.as_object_mut().unwrap().remove("group");
    f.documents.get_mut("graph.json").unwrap()["groups"][0]["nodes"]
        .as_array_mut()
        .unwrap()
        .push(node);
    f.documents.get_mut("passives.json").unwrap()["default_graph_instances"]
        .as_array_mut()
        .unwrap()
        .push(instance);
}

#[test]
fn two_new_nodes_without_reference_coordinates_are_both_quarantined() {
    let (mut f, mut p, old, mut r) = fixture();
    anointment_column(&mut f, &mut p, &[]);
    for row in [11, 12] {
        instantiate(&mut f, row);
    }
    r["nodes"]["1203"] = json!({"skill":1203,"group":1,"orbit":0,"orbitIndex":0});
    assert_eq!(
        project(&mut f, &p, &old, &r).unwrap_err(),
        "invalid reference coordinate"
    );
    let (tree, _, receipt) = forward_project(&mut f, &p, &old, &r);
    assert_eq!(tree.as_array().unwrap().len(), 3);
    let issues: Vec<_> = receipt["coverage"]["issues"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|issue| issue["kind"] == "reference-missing")
        .collect();
    assert_eq!(issues.len(), 2);
    assert_eq!(issues[0]["entity"], "Outside");
    assert_eq!(issues[1]["entity"], "Trailing ");
    assert!(issues.iter().all(|issue| issue["action"] == "quarantined"));
}

#[test]
fn new_anointment_nodes_keep_coordinate_absence_and_report_only_reference_disagreement() {
    for reference_state in ["absent", "blighted", "unflagged"] {
        let (mut f, mut p, old, mut r) = fixture();
        anointment_column(&mut f, &mut p, &[12]);
        instantiate(&mut f, 12);
        if reference_state != "absent" {
            r["nodes"]["1304"] = json!({
                "skill":1304,"group":1,"orbit":0,"orbitIndex":0,"x":90.0,"y":80.0
            });
            if reference_state == "blighted" {
                r["nodes"]["1304"]["isBlighted"] = json!(true);
            }
            // Strict keeps the old coordinate behavior even for a target anointment.
            assert_eq!(project(&mut f, &p, &old, &r).unwrap().0[3]["x"], 90.0);
        } else {
            assert_eq!(
                project(&mut f, &p, &old, &r).unwrap_err(),
                "node 1304: missing physical orbit-offset compatibility; refusing incomplete radius geometry"
            );
        }
        let (tree, _, receipt) = forward_project(&mut f, &p, &old, &r);
        assert_eq!(tree[3]["id"], "Trailing ");
        assert!(tree[3].get("x").is_none());
        assert!(tree[3].get("y").is_none());
        let issues: Vec<_> = receipt["coverage"]["issues"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|issue| issue["action"] != "listed")
            .collect();
        if reference_state == "unflagged" {
            assert_eq!(issues.len(), 1);
            assert_eq!(issues[0]["kind"], "anointment-geometry");
            assert_eq!(issues[0]["entity"], "Trailing ");
            assert_eq!(issues[0]["action"], "emitted-with-gap");
            assert_eq!(
                issues[0]["observed"]["definition_sha256"],
                hash(f.values("PassiveSkills", 12))
            );
            assert_eq!(
                issues[0]["observed"]["reference_node_sha256"],
                hash(&r["nodes"]["1304"])
            );
        } else {
            assert!(issues.is_empty());
        }
    }
}

#[test]
fn anointment_column_contract_is_checked_only_for_new_forward_nodes() {
    let (mut f, mut p, old, mut r) = fixture();
    anointment_column(&mut f, &mut p, &[]);
    instantiate(&mut f, 12);
    r["nodes"]["1304"] = json!({
        "skill":1304,"group":1,"orbit":0,"orbitIndex":0,"x":10.0,"y":20.0
    });
    let columns = f.documents.get_mut("tables/PassiveSkills.json").unwrap()["columns"]
        .as_array_mut()
        .unwrap();
    let column = columns
        .iter_mut()
        .find(|c| c["physical_fields"] == json!(["IsAnointmentOnly"]))
        .unwrap();
    column["schema"]["type"] = json!("i32");
    project(&mut f, &p, &old, &r).unwrap();
    let mut coverage = Coverage::new(AdapterMode::Forward, "passive-tree");
    let error = project_with_coverage(&mut f, &p, &old, &r, &mut coverage).unwrap_err();
    assert!(error.contains("IsAnointmentOnly"), "{error}");
}

#[test]
fn placement_rebase_is_aggregated_and_preserves_coordinate_absence() {
    let (mut f, p, mut old, r) = fixture();
    old[0]["group"] = json!(2);
    old[0]["x"] = json!(999.0);
    old[1]["orbit_index"] = json!(1);
    old[1].as_object_mut().unwrap().remove("x");
    old[1].as_object_mut().unwrap().remove("y");
    f.documents.get_mut("graph.json").unwrap()["groups"][0]["x"] = json!(110.0);
    assert_eq!(
        project(&mut f, &p, &old, &r).unwrap_err(),
        "prepared placement lacks exact reference group/orbit/slot binding"
    );
    let (tree, _, receipt) = forward_project(&mut f, &p, &old, &r);
    assert_eq!(tree[0]["x"], 110.0);
    assert_eq!(tree[0]["y"], 20.0);
    assert!(tree[0].get("native_stats").is_none());
    assert!(tree[1].get("x").is_none());
    assert!(tree[1].get("y").is_none());
    let issues = receipt["coverage"]["issues"].as_array().unwrap();
    assert_eq!(issues.len(), 1);
    assert_eq!(issues[0]["kind"], "placement-rebase");
    assert_eq!(issues[0]["entity"], "passive-tree");
    assert_eq!(issues[0]["action"], "emitted-with-gap");
    assert_eq!(
        issues[0]["observed"],
        json!({
            "reference_sha256":p["reference_sha256"],
            "legacy_source_sha256":hash(&old),
            "moved_skills_sha256":hash(&vec![101_u64, 202]),
            "moved_count":2
        })
    );
}

#[test]
fn new_target_class_is_appended_with_target_attributes_and_no_ascendancies() {
    let (mut f, p, old, r) = fixture();
    let raw = json!({
        "Id":"DruidId","Name":"Druid","BaseStrength":45,"BaseDexterity":-4,"BaseIntelligence":30
    });
    let table = f.documents.get_mut("tables/Characters.json").unwrap();
    table["rows"]
        .as_array_mut()
        .unwrap()
        .push(json!({"_row":2,"values":raw}));
    table["validation"]["rows"] = json!(3);
    assert_eq!(
        project(&mut f, &p, &old, &r).unwrap_err(),
        "prepared metadata does not completely cover exact target class names"
    );
    let (_, meta, receipt) = forward_project(&mut f, &p, &old, &r);
    assert_eq!(meta["classes"][0]["name"], "Witch");
    assert_eq!(meta["classes"][1]["name"], "Warrior");
    assert_eq!(
        meta["classes"][2],
        json!({"name":"Druid","base_str":45,"base_dex":-4,"base_int":30})
    );
    assert_eq!(
        receipt["class_records"][2]["policy_class_position"],
        Value::Null
    );
    assert_eq!(receipt["class_records"][2]["source_row"], 2);
    let issues = receipt["coverage"]["issues"].as_array().unwrap();
    assert_eq!(issues.len(), 1);
    assert_eq!(issues[0]["kind"], "new-class");
    assert_eq!(issues[0]["entity"], "Druid");
    assert_eq!(issues[0]["action"], "emitted-with-gap");
    assert_eq!(
        issues[0]["observed"],
        json!({"definition_sha256":hash(&raw),"character":raw})
    );
}

#[test]
fn metadata_class_absent_from_the_target_remains_fatal_in_both_modes() {
    let (mut f, mut p, old, r) = fixture();
    p["base_policy"]["legacy_metadata"]["value"]["classes"]
        .as_array_mut()
        .unwrap()
        .push(json!({"name":"Removed","base_str":0,"base_dex":0,"base_int":0}));
    for mode in [AdapterMode::Strict, AdapterMode::Forward] {
        let mut coverage = Coverage::new(mode, "passive-tree");
        assert_eq!(
            project_with_coverage(&mut f, &p, &old, &r, &mut coverage).unwrap_err(),
            "prepared metadata does not completely cover exact target class names"
        );
    }
}

#[test]
fn changed_exclusion_emits_target_without_a_native_packet() {
    let (mut f, mut p, old, r) = fixture();
    p["excluded"]["maximum_resistances1"] = json!({
        "definition_sha256":hash(f.values("PassiveSkills", 0)),
        "reason":"previous placeholder"
    });
    f.values("PassiveSkills", 0)["Name"] = json!("Now allocatable");
    assert_eq!(
        project(&mut f, &p, &old, &r).unwrap_err(),
        "maximum_resistances1: non-allocatable compatibility binding changed"
    );
    let (tree, _, receipt) = forward_project(&mut f, &p, &old, &r);
    assert_eq!(tree[0]["name"], "Now allocatable");
    assert_eq!(tree[0]["stats"], json!(["-7% to Fire Resistance"]));
    assert!(tree[0].get("native_stats").is_none());
    assert_eq!(receipt["excluded"], json!([]));
    assert_eq!(receipt["coverage"]["counts"]["emitted-with-gap"], 1);
    let issue = &receipt["coverage"]["issues"][0];
    assert_eq!(issue["kind"], "excluded-definition");
    assert_eq!(issue["entity"], "maximum_resistances1");
    assert_eq!(
        issue["observed"]["definition_sha256"],
        hash(f.values("PassiveSkills", 0))
    );
    assert_eq!(
        issue["observed"]["policy_definition_sha256"],
        p["excluded"]["maximum_resistances1"]["definition_sha256"]
    );
    for field in ["context_sha256", "render_context_sha256", "stats_sha256"] {
        assert_eq!(issue["observed"][field].as_str().unwrap().len(), 64);
    }
    p["excluded"] = json!({});
    let (closed, _, _) = forward_project(&mut f, &p, &old, &r);
    assert!(closed[0].get("native_stats").is_some());
}

#[test]
fn membership_quarantines_preserve_each_original_strict_message() {
    for (kind, message) in [
        (
            "identity-collision",
            "Multi: prepared identity collision at 303",
        ),
        ("stale-alias", "Multi: stale prepared identity alias"),
        (
            "unclassified-name",
            "Multi: unclassified layout/unreleased definition",
        ),
        (
            "empty-name",
            "Multi: unclassified layout/unreleased definition",
        ),
        (
            "reference-missing",
            "node 303: missing physical orbit-offset compatibility; refusing incomplete radius geometry",
        ),
        (
            "reference-slot-changed",
            "node 303: changed orbit/slot needs explicit geometry compatibility",
        ),
    ] {
        let (mut f, mut p, mut old, mut r) = fixture();
        match kind {
            "identity-collision" => old[2]["id"] = json!("previous-Multi"),
            "stale-alias" => {
                old[2]["id"] = json!("303");
                p["base_policy"]["legacy_id_bindings"] = json!([{
                    "legacy_id":"303","skill":303,"target_passive_id":"Multi",
                    "expected_name":"Multi","source_entry_sha256":hash(&old[2]),"role":"fixture alias"
                }]);
                old[2]["stats"] = json!(["changed prepared entry"]);
            }
            "unclassified-name" => {
                f.values("PassiveSkills", 2)["Name"] = json!("[DNT] Placeholder")
            }
            "empty-name" => f.values("PassiveSkills", 2)["Name"] = json!(""),
            "reference-missing" => {
                r["nodes"].as_object_mut().unwrap().remove("303");
            }
            _ => r["nodes"]["303"]["orbitIndex"] = json!(1),
        }
        assert_eq!(project(&mut f, &p, &old, &r).unwrap_err(), message);
        let (tree, _, receipt) = forward_project(&mut f, &p, &old, &r);
        assert_eq!(tree.as_array().unwrap().len(), 2);
        assert_eq!(tree[0]["connections"], json!([]));
        let expected_kind = if kind == "empty-name" {
            "unclassified-name"
        } else {
            kind
        };
        let issue = receipt["coverage"]["issues"]
            .as_array()
            .unwrap()
            .iter()
            .find(|issue| issue["kind"] == expected_kind)
            .unwrap();
        assert_eq!(issue["entity"], "Multi");
        assert_eq!(issue["action"], "quarantined");
        assert_eq!(issue["message"], message);
        assert_eq!(
            issue["observed"]["definition_sha256"],
            hash(f.values("PassiveSkills", 2))
        );
        assert_eq!(
            receipt["source_records"][0]["output_entry_sha256"],
            hash(&tree[0])
        );
    }
}

#[test]
fn strict_reports_the_first_site_before_later_node_defects_or_cascade() {
    for (kind, message) in [
        (
            "excluded-definition",
            "maximum_resistances1: non-allocatable compatibility binding changed",
        ),
        (
            "identity-collision",
            "maximum_resistances1: prepared identity collision at 101",
        ),
        (
            "stale-alias",
            "maximum_resistances1: stale prepared identity alias",
        ),
        (
            "unclassified-name",
            "maximum_resistances1: unclassified layout/unreleased definition",
        ),
        (
            "reference-missing",
            "node 101: missing physical orbit-offset compatibility; refusing incomplete radius geometry",
        ),
        (
            "reference-slot-changed",
            "node 101: changed orbit/slot needs explicit geometry compatibility",
        ),
        (
            "placement-rebase",
            "prepared placement lacks exact reference group/orbit/slot binding",
        ),
    ] {
        let (mut f, mut p, mut old, mut r) = fixture();
        match kind {
            "excluded-definition" => {
                p["excluded"]["maximum_resistances1"] = json!({
                    "definition_sha256":"0".repeat(64),"reason":"old placeholder"
                });
            }
            "identity-collision" => old[0]["id"] = json!("previous-resistance"),
            "stale-alias" => {
                old[0]["id"] = json!("previous-resistance");
                p["base_policy"]["legacy_id_bindings"] = json!([{
                    "legacy_id":"previous-resistance","skill":101,
                    "target_passive_id":"maximum_resistances1","expected_name":"old",
                    "source_entry_sha256":hash(&old[0]),"role":"fixture alias"
                }]);
                old[0]["stats"] = json!(["changed prepared entry"]);
            }
            "unclassified-name" => {
                f.values("PassiveSkills", 0)["Name"] = json!("[DNT] Placeholder")
            }
            "reference-missing" => {
                r["nodes"].as_object_mut().unwrap().remove("101");
            }
            "reference-slot-changed" => r["nodes"]["101"]["orbitIndex"] = json!(1),
            _ => old[0]["group"] = json!(2),
        }
        // A later geometry defect must not supersede the first decision, including
        // a rebase whose forward issue is deferred until after projection.
        r["nodes"].as_object_mut().unwrap().remove("303");
        old[1]["unlock_constraint"] = json!({"nodes":[101]});
        assert_eq!(project(&mut f, &p, &old, &r).unwrap_err(), message);
        let (tree, _, receipt) = forward_project(&mut f, &p, &old, &r);
        assert_eq!(
            receipt["coverage"]["issues"]
                .as_array()
                .unwrap()
                .iter()
                .filter(|issue| issue["kind"] == "reference-missing")
                .count(),
            if kind == "reference-missing" { 2 } else { 1 },
            "{kind}"
        );
        if !["excluded-definition", "placement-rebase"].contains(&kind) {
            assert_eq!(tree, json!([]), "{kind}");
            assert!(
                receipt["coverage"]["issues"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .any(|issue| issue["kind"] == "dependant-quarantined"),
                "{kind}"
            );
        }
    }
}

#[test]
fn strict_decision_precedes_invalid_observation_and_forward_keeps_integrity_fatal() {
    let (mut f, mut p, mut old, r) = fixture();
    old[2]["id"] = json!("previous-Multi");
    f.values("PassiveSkills", 2)["Stat1Value"] = json!("invalid integer");
    assert_eq!(
        project(&mut f, &p, &old, &r).unwrap_err(),
        "Multi: prepared identity collision at 303"
    );
    let mut coverage = Coverage::new(AdapterMode::Forward, "passive-tree");
    assert!(
        project_with_coverage(&mut f, &p, &old, &r, &mut coverage)
            .unwrap_err()
            .contains("Stat1Value")
    );
    p["excluded"]["Multi"] = json!({
        "definition_sha256":"0".repeat(64), "reason":"old placeholder"
    });
    assert_eq!(
        project(&mut f, &p, &old, &r).unwrap_err(),
        "Multi: non-allocatable compatibility binding changed"
    );
}

#[test]
fn reference_membership_lists_numeric_differences_and_ignores_non_nodes() {
    let (mut f, p, old, mut r) = fixture();
    for key in ["root", "placeholder", "+404"] {
        r["nodes"][key] = json!({"skill":404});
    }
    let (_, _, receipt) = forward_project(&mut f, &p, &old, &r);
    assert_eq!(receipt["coverage"]["issues"], json!([]));
    r["nodes"]["404"] = json!({"skill":404});
    r["nodes"].as_object_mut().unwrap().remove("303");
    let (_, _, receipt) = forward_project(&mut f, &p, &old, &r);
    let issue = receipt["coverage"]["issues"]
        .as_array()
        .unwrap()
        .iter()
        .find(|issue| issue["kind"] == "reference-membership")
        .unwrap();
    assert_eq!(issue["entity"], "passive-tree");
    assert_eq!(issue["action"], "listed");
    assert_eq!(
        issue["observed"]["target_absent_from_reference"],
        json!([303])
    );
    assert_eq!(
        issue["observed"]["reference_absent_from_target"],
        json!([404])
    );
}

#[test]
fn forward_run_records_multiple_kinds_in_conversion_coverage() {
    let (mut f, mut p, old, r) = fixture();
    p["excluded"]["maximum_resistances1"] = json!({
        "definition_sha256":hash(f.values("PassiveSkills", 0)), "reason":"old placeholder"
    });
    f.values("PassiveSkills", 0)["Name"] = json!("Now real");
    f.values("PassiveSkills", 2)["Name"] = json!("[DNT] Not released");
    f.seal();
    fs::create_dir(f.root.join("refresh-inputs")).unwrap();
    let write = |path: &str, value: &Value| {
        let bytes = reader::json_bytes(value).unwrap();
        fs::write(f.root.join(path), &bytes).unwrap();
        sha256_hex(&bytes)
    };
    let source_sha256 = write("legacy/source.json", &old);
    p["base_policy"]["source"]["sha256"] = json!(source_sha256);
    p["base_policy"]["target"]["facts_manifest_sha256"] = json!(f.args().expected_manifest_sha256);
    p["reference_sha256"] = json!(write("refresh-inputs/reference.json", &r));
    p["descriptions_sha256"] = json!(write("refresh-inputs/descriptions.json", &descriptions()));
    let manifest = json!({
        "format":"repoe-native-descriptions/v1",
        "source_identity":f.manifest["source_identity"],
        "files":{"descriptions.json":{
            "sha256":p["descriptions_sha256"],
            "bytes":fs::read(f.root.join("refresh-inputs/descriptions.json")).unwrap().len()
        }}
    });
    p["descriptions_manifest_sha256"] = json!(write("refresh-inputs/manifest.json", &manifest));
    write("policy/policy.json", &p);
    let mut args = super::tests::args(&f);
    args.mode = AdapterMode::Forward;
    args.tree_refresh = Some(Box::new(refresh::Args {
        reference: f.root.join("refresh-inputs/reference.json"),
        descriptions: f.root.join("refresh-inputs/descriptions.json"),
        context_baseline: None,
    }));
    crate::ordinary_facts::run(args).unwrap();
    let receipt: Value =
        serde_json::from_slice(&fs::read(f.root.join("out/producer-receipt.json")).unwrap())
            .unwrap();
    let coverage = &receipt["conversion"]["coverage"];
    let kinds: Vec<_> = coverage["issues"]
        .as_array()
        .unwrap()
        .iter()
        .map(|issue| issue["kind"].as_str().unwrap())
        .collect();
    assert_eq!(kinds, ["excluded-definition", "unclassified-name"]);
    assert_eq!(coverage["counts"]["emitted-with-gap"], 1);
    assert_eq!(coverage["counts"]["quarantined"], 1);
    assert_eq!(receipt["files"].as_object().unwrap().len(), 7);
    let tree: Value =
        serde_json::from_slice(&fs::read(f.root.join("out/base/passive_tree.json")).unwrap())
            .unwrap();
    assert_eq!(tree.as_array().unwrap().len(), 2);
    assert!(tree[0].get("native_stats").is_none());
    assert_eq!(tree[0]["connections"], json!([]));
}

#[test]
fn complete_multistat_values_and_name_reach_ordinary_text_without_changing_math() {
    let (mut f, p, old, r) = fixture();
    f.values("PassiveSkills", 2)["Name"] = json!("Renamed from source");
    f.values("PassiveSkills", 2)["Stat1Value"] = json!(19);
    f.values("PassiveSkills", 2)["Stat2Value"] = json!(31);
    let (tree, _, receipt) = project(&mut f, &p, &old, &r).unwrap();
    assert_eq!(tree[2]["name"], "Renamed from source");
    assert_eq!(
        tree[2]["stats"],
        json!(["+19% to Fire Resistance", "31% increased Spell Damage"])
    );
    assert!(tree[2]["native_stats"].is_null());
    assert_eq!(tree[0]["unknown"], old[0]["unknown"]);
    assert_eq!(receipt["target_multistat_nodes"], 1);
}
#[test]
fn target_edges_membership_and_group_centres_propagate() {
    let (mut f, p, old, r) = fixture();
    edit_node(&mut f, 101, |n| {
        n["connections"] = json!([202, 303]);
        n["splines"] = json!([0, 0]);
    });
    f.documents.get_mut("graph.json").unwrap()["groups"][0]["x"] = json!(35.0);
    let (tree, _, _) = project(&mut f, &p, &old, &r).unwrap();
    assert_eq!(tree[0]["connections"], json!([202, 303]));
    assert_eq!(tree[0]["x"], 35.0);
    // Remove an unallocated source member and its edge; the prepared node must not survive.
    edit_node(&mut f, 101, |n| {
        n["connections"] = json!([303]);
        n["splines"] = json!([0]);
    });
    f.documents.get_mut("graph.json").unwrap()["groups"][0]["nodes"]
        .as_array_mut()
        .unwrap()
        .retain(|n| n["graph_id"] != 202);
    f.documents.get_mut("passives.json").unwrap()["default_graph_instances"]
        .as_array_mut()
        .unwrap()
        .retain(|n| n["graph_id"] != 202);
    let (tree, _, receipt) = project(&mut f, &p, &old, &r).unwrap();
    assert_eq!(tree.as_array().unwrap().len(), 2);
    assert_eq!(receipt["removed_prepared_skills"], json!([202]));
}
#[test]
fn new_normal_source_member_requires_explicit_geometry_and_then_is_emitted() {
    let (mut f, p, old, mut r) = fixture();
    // A previously uninstantiated physical definition with ordinary context joins the graph.
    let n = json!({"graph_id":1304,"radius":0,"position":0,"connections":[101],"splines":[0]});
    f.documents.get_mut("graph.json").unwrap()["groups"][0]["nodes"]
        .as_array_mut()
        .unwrap()
        .push(n.clone());
    let mut instance = n;
    instance["group"] = json!(0);
    instance["definition"] = json!({"id":"Trailing ","row":12});
    f.documents.get_mut("passives.json").unwrap()["default_graph_instances"]
        .as_array_mut()
        .unwrap()
        .push(instance);
    assert!(
        project(&mut f, &p, &old, &r)
            .unwrap_err()
            .contains("missing physical orbit-offset")
    );
    r["nodes"]["1304"] = json!({"skill":1304,"group":1,"orbit":0,"orbitIndex":0,"x":10.0,"y":20.0});
    let (tree, _, _) = project(&mut f, &p, &old, &r).unwrap();
    assert_eq!(tree.as_array().unwrap().len(), 4);
    assert_eq!(tree[3]["id"], "Trailing ");
    assert_eq!(tree[3]["stats"], json!(["-7% to Fire Resistance"]));
    assert_eq!(tree[3]["x"], 10.0);
}

#[test]
fn changed_unrenderable_values_or_context_cannot_reuse_old_numbers() {
    let (mut f, p, old, r) = fixture();
    assert_eq!(
        project(&mut f, &p, &old, &r).unwrap().0[1]["stats"],
        old[1]["stats"]
    );
    f.values("PassiveSkills", 1)["Stat1Value"] = json!(99);
    assert!(
        project(&mut f, &p, &old, &r)
            .unwrap_err()
            .contains("stale whole-text")
    );
    f.values("PassiveSkills", 1)["Stat1Value"] = json!(-7);
    f.values("PassiveSkills", 2)["Opaque"] = json!(999);
    assert!(
        project(&mut f, &p, &old, &r)
            .unwrap_err()
            .contains("context change")
    );
}

#[test]
fn forward_missing_and_stale_text_bindings_keep_prepared_text_with_exact_hashes() {
    let (mut f, mut p, old, r) = fixture();
    p["compatibility_bindings"]
        .as_object_mut()
        .unwrap()
        .remove("Unknown");
    f.values("PassiveSkills", 2)["Stats"] = json!([1]);
    assert_eq!(
        project(&mut f, &p, &old, &r).unwrap_err(),
        "Unknown: no whole-text compatibility binding"
    );
    let (tree, _, receipt) = forward_project(&mut f, &p, &old, &r);
    let issues = receipt["coverage"]["issues"].as_array().unwrap();
    assert_eq!(issues.len(), 2);
    for (issue, row, kind) in [
        (&issues[0], 1, "text-binding-missing"),
        (&issues[1], 2, "text-binding-stale"),
    ] {
        assert_eq!(issue["kind"], kind);
        assert_eq!(issue["entity"], f.values("PassiveSkills", row)["Id"]);
        assert_eq!(issue["action"], "emitted-with-gap");
        assert_eq!(
            issue["observed"]["context_sha256"],
            hash(&refresh::context(f.values("PassiveSkills", row)).unwrap())
        );
        assert_eq!(
            issue["observed"]["stats_sha256"],
            hash(&json!([["unknown_stat", -7]]))
        );
        assert_eq!(tree[row]["stats"], old[row]["stats"]);
        assert!(tree[row].get("native_stats").is_none());
    }
    p["compatibility_bindings"]["Unknown"] = json!({
        "context_sha256":hash(&refresh::context(f.values("PassiveSkills", 1)).unwrap()),
        "stats_sha256":hash(&json!([["unknown_stat", -7]]))
    });
    assert_eq!(
        project(&mut f, &p, &old, &r).unwrap_err(),
        "Multi: target semantics changed; stale whole-text compatibility rejected"
    );
}

#[test]
fn forward_new_unrenderable_text_has_one_issue_and_never_emits_reference_lines() {
    for binding in ["missing", "stale", "exact"] {
        for candidates in [true, false] {
            let (mut f, mut p, mut old, mut r) = fixture();
            anointment_column(&mut f, &mut p, &[]);
            old.as_array_mut().unwrap().remove(1);
            if candidates {
                r["nodes"]["202"]["stats"] = json!([" Candidate one\r\n\n Candidate two ", ""]);
            }
            match binding {
                "missing" => {
                    p["compatibility_bindings"]
                        .as_object_mut()
                        .unwrap()
                        .remove("Unknown");
                }
                "stale" => {
                    p["compatibility_bindings"]["Unknown"]["stats_sha256"] = json!("0".repeat(64));
                }
                _ => {}
            }
            let strict = project(&mut f, &p, &old, &r).unwrap_err();
            match binding {
                "missing" => assert_eq!(strict, "Unknown: no whole-text compatibility binding"),
                "stale" => assert_eq!(
                    strict,
                    "Unknown: target semantics changed; stale whole-text compatibility rejected"
                ),
                _ => assert!(
                    strict.starts_with("Unknown: ")
                        && strict.ends_with("; no complete compatibility text")
                ),
            }
            let (tree, _, receipt) = forward_project(&mut f, &p, &old, &r);
            assert_eq!(tree[1]["id"], "Unknown");
            assert_eq!(tree[1]["stats"], json!([]));
            assert!(tree[1].get("native_stats").is_none());
            let issues = receipt["coverage"]["issues"].as_array().unwrap();
            assert_eq!(issues.len(), 1);
            assert_eq!(issues[0]["kind"], "text-unrenderable-new");
            assert_eq!(issues[0]["entity"], "Unknown");
            assert_eq!(issues[0]["action"], "emitted-with-gap");
            assert_eq!(issues[0]["message"], strict);
            assert_eq!(
                issues[0]["observed"]["context_sha256"],
                hash(&refresh::context(f.values("PassiveSkills", 1)).unwrap())
            );
            assert_eq!(
                issues[0]["observed"]["stats_sha256"],
                hash(&json!([["unknown_stat", -7]]))
            );
            if candidates {
                assert_eq!(
                    issues[0]["observed"]["candidate_lines"],
                    json!(["Candidate one", "Candidate two"])
                );
            } else {
                assert!(issues[0]["observed"].get("candidate_lines").is_none());
            }
        }
    }
}

#[test]
fn forward_render_context_change_keeps_target_text_without_a_native_packet() {
    let (mut f, mut p, old, r) = fixture();
    let bound = p["compatibility_bindings"]["maximum_resistances1"]["context_sha256"].clone();
    f.values("PassiveSkills", 0)["Opaque"] = json!(99);
    f.values("PassiveSkills", 0)["Stat1Value"] = json!(31);
    p["base_policy"]["qualification"]["context_sha256"] = json!(hash(
        &super::source::context(f.values("PassiveSkills", 0)).unwrap()
    ));
    assert_eq!(
        project(&mut f, &p, &old, &r).unwrap_err(),
        "maximum_resistances1: unsupported source context change or new conditional identity"
    );
    let (tree, _, receipt) = forward_project(&mut f, &p, &old, &r);
    assert_eq!(tree[0]["stats"], json!(["+31% to Fire Resistance"]));
    assert!(tree[0].get("native_stats").is_none());
    assert_eq!(receipt["native_packets"], 0);
    let issues = receipt["coverage"]["issues"].as_array().unwrap();
    assert_eq!(issues.len(), 1);
    assert_eq!(issues[0]["kind"], "render-context-changed");
    assert_eq!(issues[0]["entity"], "maximum_resistances1");
    assert_eq!(
        issues[0]["observed"],
        json!({
            "render_context_sha256":hash(&refresh::context(f.values("PassiveSkills", 0)).unwrap()),
            "bound_render_context_sha256":bound
        })
    );
    // The original context error still wins over a later scalar error in strict.
    f.values("PassiveSkills", 1)["Stat1Value"] = json!("malformed");
    assert_eq!(
        project(&mut f, &p, &old, &r).unwrap_err(),
        "maximum_resistances1: unsupported source context change or new conditional identity"
    );
    let mut coverage = Coverage::new(AdapterMode::Forward, "passive-tree");
    assert_eq!(
        project_with_coverage(&mut f, &p, &old, &r, &mut coverage).unwrap_err(),
        "Stat1Value: exact i32 required"
    );
}

#[test]
fn forward_preserves_reference_qualification_and_consumed_column_contracts() {
    for defect in ["qualification", "type", "array", "reference"] {
        let (mut f, mut p, old, r) = fixture();
        match defect {
            "qualification" => {
                p["base_policy"]["qualification"]["context_sha256"] = json!("0".repeat(64));
            }
            "type" => {
                f.documents.get_mut("tables/PassiveSkills.json").unwrap()["columns"][5]["schema"]
                    ["type"] = json!("u32");
            }
            "array" => {
                f.documents.get_mut("tables/PassiveSkills.json").unwrap()["columns"][4]["schema"]
                    ["array"] = json!(false);
            }
            _ => {
                f.documents.get_mut("tables/PassiveSkills.json").unwrap()["columns"][4]["schema"]
                    ["references"]["table"] = json!("Characters");
            }
        }
        let strict = project(&mut f, &p, &old, &r).unwrap_err();
        if defect == "qualification" {
            assert_eq!(strict, "reference context SHA256 mismatch");
        }
        let mut coverage = Coverage::new(AdapterMode::Forward, "passive-tree");
        assert_eq!(
            project_with_coverage(&mut f, &p, &old, &r, &mut coverage).unwrap_err(),
            strict,
            "{defect}"
        );
        let mut receipt = json!({});
        coverage.finish(&mut receipt).unwrap();
        assert_eq!(receipt["coverage"]["issues"], json!([]));
    }
}

#[test]
fn forward_render_and_variant_context_gaps_are_both_listed_and_variants_are_omitted() {
    for context in ["missing", "changed"] {
        let (mut f, mut p, mut old, r) = fixture();
        f.values("ClassPassiveSkillOverrides", 0)["SkillToOverride"] = json!(0);
        p["class_bindings"] = json!([{"base_id":"maximum_resistances1","class":"Witch"}]);
        old[0]["variants"] =
            json!([{"class":"Witch","variant_skill":606,"stats":["old complete variant"]}]);
        let bound = p["compatibility_bindings"]["OverrideTarget"]["context_sha256"].clone();
        if context == "missing" {
            p["compatibility_bindings"]
                .as_object_mut()
                .unwrap()
                .remove("OverrideTarget");
        } else {
            f.values("PassiveSkills", 5)["Opaque"] = json!(88);
        }
        let expected = if context == "missing" {
            "OverrideTarget: missing variant context binding"
        } else {
            "OverrideTarget: changed variant context"
        };
        assert_eq!(project(&mut f, &p, &old, &r).unwrap_err(), expected);
        f.values("PassiveSkills", 0)["Opaque"] = json!(99);
        p["base_policy"]["qualification"]["context_sha256"] = json!(hash(
            &super::source::context(f.values("PassiveSkills", 0)).unwrap()
        ));
        assert_eq!(
            project(&mut f, &p, &old, &r).unwrap_err(),
            "maximum_resistances1: unsupported source context change or new conditional identity"
        );
        let (tree, _, receipt) = forward_project(&mut f, &p, &old, &r);
        assert_eq!(tree[0]["stats"], json!(["-7% to Fire Resistance"]));
        assert!(tree[0].get("variants").is_none());
        assert!(tree[0].get("native_stats").is_none());
        let issues = receipt["coverage"]["issues"].as_array().unwrap();
        assert_eq!(issues.len(), 2);
        assert_eq!(issues[0]["kind"], "render-context-changed");
        assert_eq!(issues[1]["kind"], format!("variant-context-{context}"));
        assert_eq!(issues[1]["entity"], "maximum_resistances1/Witch");
        assert_eq!(issues[1]["action"], "emitted-with-gap");
        assert_eq!(issues[1]["observed"]["target_passive_id"], "OverrideTarget");
        assert_eq!(issues[1]["observed"]["target_skill"], 606);
        assert_eq!(
            issues[1]["observed"]["render_context_sha256"],
            hash(&refresh::context(f.values("PassiveSkills", 5)).unwrap())
        );
        if context == "changed" {
            assert_eq!(issues[1]["observed"]["bound_render_context_sha256"], bound);
        }
    }
}

#[test]
fn omitted_class_variants_still_validate_scalars_fks_and_duplicate_selectors() {
    for defect in ["stat", "slot", "name", "flag", "duplicate"] {
        let (mut f, mut p, old, r) = fixture();
        f.values("ClassPassiveSkillOverrides", 0)["SkillToOverride"] = json!(0);
        p["compatibility_bindings"]
            .as_object_mut()
            .unwrap()
            .remove("OverrideTarget");
        match defect {
            "stat" => f.values("PassiveSkills", 5)["Stats"] = json!([999]),
            "slot" => f.values("PassiveSkills", 5)["Stat2Value"] = json!("invalid"),
            "name" => f.values("PassiveSkills", 5)["Name"] = json!(null),
            "flag" => f.values("PassiveSkills", 5)["IsKeystone"] = json!(0),
            _ => {
                let d = f
                    .documents
                    .get_mut("tables/ClassPassiveSkillOverrides.json")
                    .unwrap();
                let mut row = d["rows"][0].clone();
                row["_row"] = json!(1);
                d["rows"].as_array_mut().unwrap().push(row);
                d["validation"]["rows"] = json!(2);
            }
        }
        assert_eq!(
            project(&mut f, &p, &old, &r).unwrap_err(),
            "OverrideTarget: missing variant context binding"
        );
        let mut coverage = Coverage::new(AdapterMode::Forward, "passive-tree");
        let error = project_with_coverage(&mut f, &p, &old, &r, &mut coverage).unwrap_err();
        let expected = match defect {
            "stat" => "unresolved physical row Stats/999",
            "slot" => "Stat2Value: exact i32 required",
            "name" => "PassiveSkills/5.Name: string required",
            "flag" => "IsKeystone: bool required",
            _ => "maximum_resistances1: repeated replacement selector Witch",
        };
        assert_eq!(error, expected, "{defect}");
    }
}

#[test]
fn forward_retained_variant_guards_omit_only_the_unbound_variant() {
    for defect in ["missing", "stale", "alias", "physical"] {
        let (mut f, mut p, mut old, r) = fixture();
        old[0]["variants"] =
            json!([{"class":"Lich","variant_skill":606,"stats":["old complete variant"]}]);
        match defect {
            "missing" => {
                p["compatibility_bindings"]
                    .as_object_mut()
                    .unwrap()
                    .remove("OverrideTarget");
            }
            "stale" => f.values("PassiveSkills", 5)["Stat1Value"] = json!(33),
            "alias" => {
                old[0]["variants"][0]
                    .as_object_mut()
                    .unwrap()
                    .remove("variant_skill");
            }
            _ => old[0]["variants"][0]["variant_skill"] = json!(65000),
        }
        let strict = project(&mut f, &p, &old, &r).unwrap_err();
        let expected = match defect {
            "missing" => "OverrideTarget: no whole-text compatibility binding",
            "stale" => {
                "OverrideTarget: target semantics changed; stale whole-text compatibility rejected"
            }
            "alias" => {
                "maximum_resistances1: variant without a stable alias requires explicit binding"
            }
            _ => "variant 65000: ambiguous/missing physical identity",
        };
        assert_eq!(strict, expected);
        if defect == "physical" {
            let mut coverage = Coverage::new(AdapterMode::Forward, "passive-tree");
            assert_eq!(
                project_with_coverage(&mut f, &p, &old, &r, &mut coverage).unwrap_err(),
                strict
            );
            continue;
        }
        let (tree, _, receipt) = forward_project(&mut f, &p, &old, &r);
        assert!(tree[0].get("variants").is_none());
        assert!(tree[0].get("native_stats").is_none());
        let issues = receipt["coverage"]["issues"].as_array().unwrap();
        assert_eq!(issues.len(), 1);
        assert_eq!(issues[0]["entity"], "maximum_resistances1/Lich");
        assert_eq!(issues[0]["action"], "emitted-with-gap");
        assert_eq!(issues[0]["message"], strict);
        assert_eq!(
            issues[0]["kind"],
            match defect {
                "missing" => "variant-context-missing",
                "stale" => "variant-context-changed",
                _ => "variant-alias-missing",
            }
        );
        if defect == "alias" {
            assert_eq!(
                issues[0]["observed"]["prepared_variant"],
                old[0]["variants"][0]
            );
        }
    }
}

#[test]
fn forward_variant_text_gaps_use_the_replacement_policy_key_and_never_borrow_text() {
    for same_target in [true, false] {
        let (mut f, mut p, mut old, r) = fixture();
        f.values("ClassPassiveSkillOverrides", 0)["SkillToOverride"] = json!(0);
        f.values("PassiveSkills", 5)["Stats"] = json!([1]);
        p["class_bindings"] = json!([{"base_id":"maximum_resistances1","class":"Witch"}]);
        old[0]["variants"] = json!([{
            "class":"Witch","variant_skill":if same_target {606}else{707},
            "stats":["prepared variant text"],"extension":7
        }]);
        assert_eq!(
            project(&mut f, &p, &old, &r).unwrap_err(),
            "OverrideTarget: target semantics changed; stale whole-text compatibility rejected"
        );
        let (tree, _, receipt) = forward_project(&mut f, &p, &old, &r);
        let variant = &tree[0]["variants"][0];
        assert_eq!(variant["variant_skill"], 606);
        assert_eq!(variant["extension"], 7);
        assert_eq!(
            variant["stats"],
            if same_target {
                json!(["prepared variant text"])
            } else {
                json!([])
            }
        );
        assert!(tree[0].get("native_stats").is_none());
        let issues = receipt["coverage"]["issues"].as_array().unwrap();
        assert_eq!(issues.len(), 1);
        assert_eq!(issues[0]["entity"], "OverrideTarget");
        assert_eq!(
            issues[0]["kind"],
            if same_target {
                "text-binding-stale"
            } else {
                "text-unrenderable-new"
            }
        );
        assert_eq!(
            issues[0]["observed"]["stats_sha256"],
            hash(&json!([["unknown_stat", -7]]))
        );
    }
}
#[test]
fn audit_text_and_variant_skips_reject_duplicate_stats() {
    for (row, retained) in [(2, false), (5, false), (5, true)] {
        let (mut f, mut p, mut old, r) = fixture();
        let id = f.values("PassiveSkills", row)["Id"]
            .as_str()
            .unwrap()
            .to_owned();
        f.values("PassiveSkills", row)["Stats"] = json!([1, 1]);
        if retained {
            old[0]["variants"] =
                json!([{"class":"Lich","variant_skill":606,"stats":["complete retained text"]}]);
        } else if row == 5 {
            f.values("ClassPassiveSkillOverrides", 0)["SkillToOverride"] = json!(0);
        }
        p["compatibility_bindings"]
            .as_object_mut()
            .unwrap()
            .remove(&id);
        assert_eq!(
            project(&mut f, &p, &old, &r).unwrap_err(),
            if row == 2 {
                "Multi: no whole-text compatibility binding"
            } else if retained {
                "OverrideTarget: no whole-text compatibility binding"
            } else {
                "OverrideTarget: missing variant context binding"
            }
        );
        let mut coverage = Coverage::new(AdapterMode::Forward, "passive-tree");
        assert_eq!(
            project_with_coverage(&mut f, &p, &old, &r, &mut coverage)
                .err()
                .as_deref(),
            Some("duplicate source stat occurrence"),
            "{row}"
        );
    }
}

#[test]
fn audit_text_and_variant_skips_validate_flags_after_the_first_true_flag() {
    for (row, retained) in [(2, false), (5, false), (5, true)] {
        let (mut f, mut p, mut old, r) = fixture();
        let id = f.values("PassiveSkills", row)["Id"]
            .as_str()
            .unwrap()
            .to_owned();
        f.values("PassiveSkills", row)["IsKeystone"] = json!(true);
        f.values("PassiveSkills", row)["IsNotable"] = json!("bad later flag");
        if row == 2 {
            f.values("PassiveSkills", row)["Stats"] = json!([1]);
        } else if retained {
            old[0]["variants"] =
                json!([{"class":"Lich","variant_skill":606,"stats":["complete retained text"]}]);
        } else {
            f.values("ClassPassiveSkillOverrides", 0)["SkillToOverride"] = json!(0);
        }
        p["compatibility_bindings"]
            .as_object_mut()
            .unwrap()
            .remove(&id);
        assert_eq!(
            project(&mut f, &p, &old, &r).unwrap_err(),
            if row == 2 {
                "Multi: no whole-text compatibility binding"
            } else if retained {
                "OverrideTarget: no whole-text compatibility binding"
            } else {
                "OverrideTarget: missing variant context binding"
            }
        );
        let mut coverage = Coverage::new(AdapterMode::Forward, "passive-tree");
        assert_eq!(
            project_with_coverage(&mut f, &p, &old, &r, &mut coverage)
                .err()
                .as_deref(),
            Some("IsNotable: bool required"),
            "{row}"
        );
    }
}

#[test]
fn audit_nonzero_text_render_and_variant_receipt_keeps_mergeable_evidence() {
    let (mut f, mut p, mut old, mut r) = fixture();
    anointment_column(&mut f, &mut p, &[]);
    old.as_array_mut().unwrap().remove(2);
    old[0]["variants"] =
        json!([{"class":"Lich","stats":["prepared aliasless text"],"extension":9}]);
    f.values("PassiveSkills", 0)["Opaque"] = json!(99);
    f.values("PassiveSkills", 0)["Stat1Value"] = json!(31);
    p["base_policy"]["qualification"]["context_sha256"] = json!(hash(
        &super::source::context(f.values("PassiveSkills", 0)).unwrap()
    ));
    f.values("PassiveSkills", 1)["Opaque"] = json!(88);
    f.values("PassiveSkills", 2)["Stats"] = json!([1]);
    f.values("ClassPassiveSkillOverrides", 0)["SkillToOverride"] = json!(0);
    p["compatibility_bindings"]
        .as_object_mut()
        .unwrap()
        .remove("OverrideTarget");
    r["nodes"]["202"]["stats"] = json!([" Existing candidate\n Second existing "]);
    r["nodes"]["303"]["stats"] = json!([" New candidate\n Second new "]);
    assert_eq!(
        project(&mut f, &p, &old, &r).unwrap_err(),
        "maximum_resistances1: unsupported source context change or new conditional identity"
    );
    let (tree, _, receipt) = forward_project(&mut f, &p, &old, &r);
    assert_eq!(tree[0]["stats"], json!(["+31% to Fire Resistance"]));
    assert_eq!(tree[1]["stats"], old[1]["stats"]);
    assert_eq!(tree[2]["stats"], json!([]));
    assert!(tree[0].get("variants").is_none());
    assert!(
        tree.as_array()
            .unwrap()
            .iter()
            .all(|node| node.get("native_stats").is_none())
    );
    let issues = receipt["coverage"]["issues"].as_array().unwrap();
    assert_eq!(issues.len(), 6);
    for issue in issues {
        let entity = issue["entity"].as_str().unwrap();
        if issue["kind"].as_str().unwrap().starts_with("text-") {
            assert!(p["compatibility_bindings"].get(entity).is_some());
            let render = issues.iter().find(|other| {
                other["kind"] == "render-context-changed" && other["entity"] == entity
            });
            if let Some(render) = render {
                assert_eq!(
                    issue["observed"]["render_context_sha256"],
                    render["observed"]["render_context_sha256"]
                );
            }
        }
    }
    let replay = forward_project(&mut f, &p, &old, &r);
    assert_eq!(replay.0, tree);
    assert_eq!(replay.2, receipt);
    // Keep an actual production projection/coverage receipt available to the
    // offline Python policy-draft integration smoke check via --nocapture.
    println!("P6_AUDIT_RECEIPT={receipt}");
}

#[test]
fn topology_and_geometry_conflicts_are_explicit_errors() {
    let (mut f, p, old, r) = fixture();
    edit_node(&mut f, 101, |n| {
        n["connections"] = json!([65500]);
        n["splines"] = json!([0]);
    });
    assert!(
        project(&mut f, &p, &old, &r)
            .unwrap_err()
            .contains("unresolved graph edge")
    );
    edit_node(&mut f, 101, |n| {
        n["connections"] = json!([]);
        n["splines"] = json!([]);
        n["radius"] = json!(3);
    });
    assert!(
        project(&mut f, &p, &old, &r)
            .unwrap_err()
            .contains("changed orbit/slot")
    );
}
#[test]
fn exclusions_are_source_bound_and_edges_to_layout_are_recorded() {
    let (mut f, mut p, old, r) = fixture();
    let raw = &f.documents["tables/PassiveSkills.json"]["rows"][2]["values"];
    p["excluded"]["Multi"] =
        json!({"definition_sha256":hash(raw),"reason":"fixture non-allocatable"});
    let (tree, _, receipt) = project(&mut f, &p, &old, &r).unwrap();
    assert_eq!(tree.as_array().unwrap().len(), 2);
    assert_eq!(tree[0]["connections"], json!([]));
    assert_eq!(
        receipt["source_records"][0]["excluded_connections"],
        json!([303])
    );
    f.values("PassiveSkills", 2)["Name"] = json!("now real");
    assert!(
        project(&mut f, &p, &old, &r)
            .unwrap_err()
            .contains("non-allocatable compatibility binding changed")
    );
}
#[test]
fn target_notable_category_replaces_prepared_normal() {
    let (mut f, p, old, r) = fixture();
    f.values("PassiveSkills", 2)["IsNotable"] = json!(true);
    assert_eq!(
        project(&mut f, &p, &old, &r).unwrap().0[2]["kind"],
        "notable"
    );
}
#[test]
fn renderer_compound_child_scope_and_unknown_handlers_are_whole_node() {
    let mut d = descriptions();
    d["files"]["Data/StatDescriptions/passive_skill_stat_descriptions.csd"]["records"]
        .as_array_mut()
        .unwrap()
        .push(descriptor(
            &["base_fire_damage_resistance_%", "spell_damage_+%"],
            "{0:+d}% resistance and {1}% spell damage",
        ));
    let r = Renderer::new(&d).unwrap();
    let stats = vec![
        ("base_fire_damage_resistance_%".into(), 7),
        ("spell_damage_+%".into(), 12),
    ];
    assert_eq!(
        r.render(&stats).unwrap().0,
        vec!["+7% resistance and 12% spell damage"]
    );
    assert!(
        r.render(&stats[..1])
            .unwrap_err()
            .contains("incomplete compound")
    );
    d["files"]["Data/StatDescriptions/passive_skill_stat_descriptions.csd"]["records"][1]["groups"]
        [0]["branches"][0]["quantifiers_lexical"] =
        json!([{"name_raw":"mystery","argument_tokens_raw":["1"]}]);
    d["files"]["Data/StatDescriptions/passive_skill_stat_descriptions.csd"]["records"][1]["groups"]
        [0]["branches"][0]["quantifier_tokens_raw"] = json!(["mystery", "1"]);
    assert!(
        Renderer::new(&d)
            .unwrap()
            .render(&stats)
            .unwrap_err()
            .contains("unsupported CSD handler")
    );
}
#[test]
fn renderer_negatives_zero_and_unmatched_branch_are_explicit() {
    let mut d = descriptions();
    let b = &mut d["files"]["Data/StatDescriptions/stat_descriptions.csd"]["records"][1]["groups"]
        [0]["branches"];
    let mut negative = b[0].clone();
    negative["condition_tokens_raw"] = json!(["#|-1"]);
    negative["template_raw"] = json!("{0}% reduced Spell Damage");
    negative["quantifiers_lexical"] = json!([{"name_raw":"negate","argument_tokens_raw":["1"]}]);
    negative["quantifier_tokens_raw"] = json!(["negate", "1"]);
    b[0]["condition_tokens_raw"] = json!(["1|#"]);
    b.as_array_mut().unwrap().push(negative);
    let r = Renderer::new(&d).unwrap();
    assert_eq!(
        r.render(&[("spell_damage_+%".into(), -17)]).unwrap().0,
        vec!["17% reduced Spell Damage"]
    );
    assert!(
        r.render(&[("spell_damage_+%".into(), 0)])
            .unwrap_err()
            .contains("no CSD branch")
    );
    assert_eq!(
        r.render(&[("base_fire_damage_resistance_%".into(), 0)])
            .unwrap()
            .0,
        vec!["+0% to Fire Resistance"]
    );
    d["files"]["Data/StatDescriptions/stat_descriptions.csd"]["records"][0]["groups"][0]["branches"]
        [0]["quantifier_tokens_raw"] = json!(["unparsed_token"]);
    assert!(
        Renderer::new(&d)
            .unwrap()
            .render(&[("base_fire_damage_resistance_%".into(), 0)])
            .unwrap_err()
            .contains("unaccounted CSD handler tokens")
    );
}

#[test]
fn identity_alias_requires_original_entry_and_keeps_new_target_name() {
    let (mut f, mut p, mut old, r) = fixture();
    old[2]["id"] = json!("303");
    p["base_policy"]["legacy_id_bindings"] = json!([{
        "legacy_id":"303","skill":303,"target_passive_id":"Multi",
        "expected_name":"Multi","source_entry_sha256":hash(&old[2]),"role":"fixture alias"
    }]);
    f.values("PassiveSkills", 2)["Name"] = json!("New target name");
    let (tree, _, _) = project(&mut f, &p, &old, &r).unwrap();
    assert_eq!(tree[2]["id"], "Multi");
    assert_eq!(tree[2]["name"], "New target name");
    old[2]["stats"] = json!(["tampered"]);
    assert!(
        project(&mut f, &p, &old, &r)
            .unwrap_err()
            .contains("stale prepared identity alias")
    );
}

#[test]
fn source_class_replacement_value_name_and_removal_propagate_with_extensions() {
    let (mut f, mut p, mut old, r) = fixture();
    f.values("ClassPassiveSkillOverrides", 0)["SkillToOverride"] = json!(2);
    f.values("PassiveSkills", 5)["Stat1Value"] = json!(37);
    f.values("PassiveSkills", 5)["Name"] = json!("Target class choice");
    p["class_bindings"] = json!([{"base_id":"Multi","class":"Witch"}]);
    old[2]["variants"] = json!([{"class":"Witch","variant_skill":606,"name":"old","stats":["+1% to Fire Resistance"],"future":{"keep":true}}]);
    let (tree, _, _) = project(&mut f, &p, &old, &r).unwrap();
    assert_eq!(tree[2]["variants"][0]["name"], "Target class choice");
    assert_eq!(
        tree[2]["variants"][0]["stats"],
        json!(["+37% to Fire Resistance"])
    );
    assert_eq!(
        tree[2]["variants"][0]["future"],
        old[2]["variants"][0]["future"]
    );
    let table = f
        .documents
        .get_mut("tables/ClassPassiveSkillOverrides.json")
        .unwrap();
    table["rows"] = json!([]);
    table["validation"]["rows"] = json!(0);
    table["validation"]["actual_row_bytes"] = json!(0);
    assert!(
        project(&mut f, &p, &old, &r).unwrap().0[2]
            .get("variants")
            .is_none()
    );
}

#[test]
fn supplemental_cli_pair_and_tree_payload_pins_are_enforced() {
    let (mut f, _, _, _) = fixture();
    let error = crate::ordinary_facts::parse_args(
        vec!["--tree-reference".into(), "reference.json".into()].into_iter(),
    )
    .err()
    .unwrap();
    assert!(error.contains("both tree-reference and tree-descriptions"));
    let mut verified = input(&mut f);
    fs::write(f.root.join("input/graph.json"), b"{}").unwrap();
    assert!(
        reader::read_tree(&f.root.join("input"), &mut verified)
            .unwrap_err()
            .contains("fingerprint mismatch")
    );
}

#[test]
fn target_centres_translate_prepared_offsets_without_promoting_coordinate_less_nodes() {
    let (mut f, p, mut old, r) = fixture();
    old[0]["x"] = json!(9.0); // Deliberately different from reference physical offset.
    old[1].as_object_mut().unwrap().remove("x");
    old[1].as_object_mut().unwrap().remove("y");
    f.documents.get_mut("graph.json").unwrap()["groups"][0]["x"] = json!(110.0);
    let (tree, _, _) = project(&mut f, &p, &old, &r).unwrap();
    assert_eq!(tree[0]["x"], 109.0);
    assert_eq!(tree[0]["y"], 20.0);
    assert!(!tree[1].as_object().unwrap().contains_key("x"));
    assert!(!tree[1].as_object().unwrap().contains_key("y"));
}

#[test]
fn class_target_swap_cannot_borrow_the_previous_targets_fallback_text() {
    let (mut f, mut p, mut old, r) = fixture();
    f.values("PassiveSkills", 6)["Stats"] = json!([1]);
    p["compatibility_bindings"]["Variant"]["stats_sha256"] =
        json!(hash(&json!([["unknown_stat", -7]])));
    f.documents.insert(
        "tables/ClassPassiveSkillOverrides.json".into(),
        table(
            "ClassPassiveSkillOverrides",
            &[
                (
                    "CharacterToOverrideFor",
                    "foreignrow",
                    false,
                    Some("Characters"),
                ),
                (
                    "SkillToOverride",
                    "foreignrow",
                    false,
                    Some("PassiveSkills"),
                ),
                ("Override", "foreignrow", false, Some("PassiveSkills")),
            ],
            json!([
                {"CharacterToOverrideFor":1,"SkillToOverride":0,"Override":6},
                {"CharacterToOverrideFor":1,"SkillToOverride":2,"Override":5}
            ]),
        ),
    );
    p["class_bindings"] = json!([
        {"base_id":"maximum_resistances1","class":"Witch"},
        {"base_id":"Multi","class":"Witch"}
    ]);
    old[0]["variants"] =
        json!([{"class":"Witch","variant_skill":707,"stats":["unknown target's complete text"]}]);
    old[2]["variants"] =
        json!([{"class":"Witch","variant_skill":606,"stats":["+5% to Fire Resistance"]}]);
    let baseline = project(&mut f, &p, &old, &r).unwrap().0;
    assert_eq!(
        baseline[0]["variants"][0]["stats"],
        old[0]["variants"][0]["stats"]
    );
    // Both targets have valid semantic bindings, but their old text is not interchangeable.
    f.values("ClassPassiveSkillOverrides", 0)["Override"] = json!(5);
    f.values("ClassPassiveSkillOverrides", 1)["Override"] = json!(6);
    assert!(
        project(&mut f, &p, &old, &r)
            .unwrap_err()
            .contains("no complete compatibility text")
    );
    // A changed target with complete source rendering remains legal.
    let table = f
        .documents
        .get_mut("tables/ClassPassiveSkillOverrides.json")
        .unwrap();
    table["rows"].as_array_mut().unwrap().pop();
    table["validation"]["rows"] = json!(1);
    let changed = project(&mut f, &p, &old, &r).unwrap().0;
    assert_eq!(changed[0]["variants"][0]["variant_skill"], 606);
    assert_eq!(
        changed[0]["variants"][0]["stats"],
        json!(["-7% to Fire Resistance"])
    );
}

#[test]
fn compound_csd_cannot_consume_a_members_child_owner_or_ambiguity() {
    let mut d = descriptions();
    let child = "Data/StatDescriptions/passive_skill_stat_descriptions.csd";
    let parent = "Data/StatDescriptions/stat_descriptions.csd";
    d["files"][parent]["records"] = json!([descriptor(&["a", "b"], "{0} and {1}")]);
    let mut override_b = descriptor(&["b"], "{0} child");
    override_b["groups"][0]["branches"][0]["quantifiers_lexical"] =
        json!([{"name_raw":"unknown","argument_tokens_raw":["1"]}]);
    override_b["groups"][0]["branches"][0]["quantifier_tokens_raw"] = json!(["unknown", "1"]);
    d["files"][child]["records"]
        .as_array_mut()
        .unwrap()
        .push(override_b.clone());
    for stats in [
        vec![("a".into(), 1), ("b".into(), 7)],
        vec![("b".into(), 7), ("a".into(), 1)],
    ] {
        assert!(
            Renderer::new(&d).unwrap().render(&stats).is_err(),
            "child ownership must hold for both stat orders"
        );
    }
    // Even a supported child or ambiguous child cannot be silently consumed by its parent.
    override_b["groups"][0]["branches"][0]["quantifiers_lexical"] = json!([]);
    override_b["groups"][0]["branches"][0]["quantifier_tokens_raw"] = json!([]);
    d["files"][child]["records"][1] = override_b.clone();
    assert!(
        Renderer::new(&d)
            .unwrap()
            .render(&[("a".into(), 1), ("b".into(), 7)])
            .is_err()
    );
    d["files"][child]["records"]
        .as_array_mut()
        .unwrap()
        .push(override_b);
    assert!(
        Renderer::new(&d)
            .unwrap()
            .render(&[("a".into(), 1), ("b".into(), 7)])
            .is_err()
    );
}
