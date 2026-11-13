use super::super::{refresh_tests, render::Renderer};
use super::*;
use crate::ordinary_facts::coverage::{AdapterMode, Coverage};
use crate::ordinary_facts::{stat_set_codec::tests::table, tests::Fixture};

fn fixture() -> (Fixture, Value, Value, Value, selected::Input) {
    let (mut f, mut policy, mut old, reference) = refresh_tests::fixture();
    let doc = f.documents.get_mut("tables/PassiveSkills.json").unwrap();
    let n = doc["columns"].as_array().unwrap().len();
    doc["columns"].as_array_mut().unwrap().push(json!({"source_column":n,"physical_fields":["Ascendancy"],"schema":{"name":"Ascendancy","type":"foreignrow","array":false,"interval":false,"references":{"table":"Ascendancy"}}}));
    doc["physical_fields"]
        .as_array_mut()
        .unwrap()
        .push(json!("Ascendancy"));
    for row in doc["rows"].as_array_mut().unwrap() {
        row["values"]["Ascendancy"] = Value::Null;
    }
    policy["schema"] = json!("pobr-ordinary-target-tree-policy/v2");
    policy["ascendancy"] = json!({"excluded":{}});
    policy["base_policy"]["qualification"]["context_sha256"] = json!(sha256_hex(
        &reader::json_bytes(&super::super::source::context(f.values("PassiveSkills", 0)).unwrap())
            .unwrap()
    ));
    f.values("PassiveSkills", 2)["Ascendancy"] = json!(0);
    old[2]["variants"] = json!([{"class":"Lich","variant_skill":606,"name":"old","stats":["old effect"],"future":7}]);
    let a = table(
        "Ascendancy",
        &[
            ("Id", "string", false, None),
            ("Name", "string", false, None),
            ("Character", "foreignrow", false, Some("Characters")),
            ("Disabled", "bool", false, None),
            ("BaseAscendancy", "row", false, Some("Ascendancy")),
        ],
        json!([
            {"Id":"Witch3","Name":"Lich","Character":1,"Disabled":false,"BaseAscendancy":null}
        ]),
    );
    let b = table(
        "AscendancyPassiveSkillOverrides",
        &[
            (
                "AscendancyToOverrideFor",
                "foreignrow",
                false,
                Some("Ascendancy"),
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
            {"AscendancyToOverrideFor":0,"SkillToOverride":2,"Override":5}
        ]),
    );
    let extra = selected::Input {
        manifest: json!({"fixture":true}),
        manifest_bytes: b"fixture".to_vec(),
        documents: BTreeMap::from([
            ("tables/Ascendancy.json".into(), a),
            ("tables/AscendancyPassiveSkillOverrides.json".into(), b),
        ]),
    };
    (f, policy, old, reference, extra)
}
fn value<'a>(extra: &'a mut selected::Input, table: &str, row: usize) -> &'a mut Value {
    &mut extra
        .documents
        .get_mut(&format!("tables/{table}.json"))
        .unwrap()["rows"][row]["values"]
}
fn project(
    f: &mut Fixture,
    p: &Value,
    old: &Value,
    r: &Value,
    extra: &selected::Input,
) -> Result<(Value, Value, Value), String> {
    project_with_coverage(
        f,
        p,
        old,
        r,
        extra,
        &mut Coverage::new(AdapterMode::Strict, "passive-tree"),
    )
}
fn project_with_coverage(
    f: &mut Fixture,
    p: &Value,
    old: &Value,
    r: &Value,
    extra: &selected::Input,
    coverage: &mut Coverage,
) -> Result<(Value, Value, Value), String> {
    let input = refresh_tests::input(f);
    let policy: refresh::Policy = serde_json::from_value(p.clone()).unwrap();
    let facts = Facts::read(&input, &policy.base_policy)?;
    let source = Source::read(
        &input,
        &facts,
        extra,
        policy.ascendancy.as_ref().unwrap(),
        &policy.base_policy.legacy_metadata.value,
        coverage,
    )?;
    let descriptions = refresh_tests::descriptions();
    let renderer = Renderer::new(&descriptions)?;
    refresh::project(
        &input,
        &facts,
        &policy,
        old,
        r,
        &renderer,
        Some(refresh::Supplement {
            ascendancy: &source,
            input: extra,
        }),
        &sha256_hex(&reader::json_bytes(old)?),
        coverage,
    )
}

fn unlock_fixture() -> (Fixture, Value, Value, Value, selected::Input) {
    let (mut f, mut policy, old, reference, extra) = fixture();
    let doc = f.documents.get_mut("tables/PassiveSkills.json").unwrap();
    for (field, kind, array, target) in [
        ("UnlockedBy", "row", true, "PassiveSkills"),
        ("VisibleForAscendancy", "foreignrow", false, "Ascendancy"),
        ("Requirement", "foreignrow", false, "ClientStrings"),
    ] {
        let n = doc["columns"].as_array().unwrap().len();
        doc["columns"].as_array_mut().unwrap().push(json!({"source_column":n,"physical_fields":[field],
            "schema":{"name":field,"type":kind,"array":array,"interval":false,"references":{"table":target}}}));
        doc["physical_fields"]
            .as_array_mut()
            .unwrap()
            .push(json!(field));
        for row in doc["rows"].as_array_mut().unwrap() {
            row["values"][field] = if array { json!([]) } else { Value::Null };
        }
    }
    policy["schema"] = json!("pobr-ordinary-target-tree-policy/v3");
    policy["base_policy"]["qualification"]["context_sha256"] = json!(sha256_hex(
        &reader::json_bytes(&super::super::source::context(f.values("PassiveSkills", 0)).unwrap())
            .unwrap()
    ));
    for row in doc_rows(&f) {
        let raw = &row["values"];
        let mut context = refresh::context(raw).unwrap();
        for field in ["Ascendancy", "UnlockedBy", "VisibleForAscendancy"] {
            context.as_object_mut().unwrap().remove(field);
        }
        policy["compatibility_bindings"][raw["Id"].as_str().unwrap()]["context_sha256"] =
            json!(sha256_hex(&reader::json_bytes(&context).unwrap()));
    }
    (f, policy, old, reference, extra)
}

fn doc_rows(f: &Fixture) -> &[Value] {
    f.documents["tables/PassiveSkills.json"]["rows"]
        .as_array()
        .unwrap()
}

#[test]
fn moved_ascendancy_member_uses_the_prepared_start_offset() {
    let (mut f, mut p, mut old, mut r, extra) = fixture();
    old[2]["ascendancy_id"] = json!("Witch3");
    old[2]["kind"] = json!("ascendancy_start");
    old[2]["x"] = json!(100.0);
    old[2]["y"] = json!(200.0);
    f.values("PassiveSkills", 2)["IsAscendancyStartingNode"] = json!(true);
    f.values("PassiveSkills", 0)["Ascendancy"] = json!(0);
    p["base_policy"]["qualification"]["context_sha256"] = json!(sha256_hex(
        &reader::json_bytes(&super::super::source::context(f.values("PassiveSkills", 0)).unwrap())
            .unwrap()
    ));
    old[0]["ascendancy_id"] = json!("Witch3");
    old[0]["group"] = json!(2);
    old[0]["x"] = json!(999.0);
    r["nodes"]["101"]["x"] = json!(15.0);
    r["nodes"]["101"]["y"] = json!(25.0);
    f.documents.get_mut("graph.json").unwrap()["groups"][0]["x"] = json!(110.0);
    assert_eq!(
        project(&mut f, &p, &old, &r, &extra).unwrap_err(),
        "prepared placement lacks exact reference group/orbit/slot binding"
    );
    let mut coverage = Coverage::new(AdapterMode::Forward, "passive-tree");
    let (tree, _, mut receipt) =
        project_with_coverage(&mut f, &p, &old, &r, &extra, &mut coverage).unwrap();
    coverage.finish(&mut receipt).unwrap();
    assert_eq!(
        (tree[0]["x"].clone(), tree[0]["y"].clone()),
        (json!(205.0), json!(205.0))
    );
    assert_eq!(
        (tree[2]["x"].clone(), tree[2]["y"].clone()),
        (json!(200.0), json!(200.0))
    );
    assert_eq!(receipt["coverage"]["issues"].as_array().unwrap().len(), 1);
    assert_eq!(receipt["coverage"]["issues"][0]["kind"], "placement-rebase");
}

#[test]
fn new_ascendancy_uses_reference_geometry_with_one_frame_issue() {
    let (mut f, mut p, mut old, r, extra) = fixture();
    f.values("PassiveSkills", 0)["Ascendancy"] = json!(0);
    f.values("PassiveSkills", 2)["IsAscendancyStartingNode"] = json!(true);
    p["base_policy"]["qualification"]["context_sha256"] = json!(sha256_hex(
        &reader::json_bytes(&super::super::source::context(f.values("PassiveSkills", 0)).unwrap())
            .unwrap()
    ));
    old[0]["x"] = json!(999.0);
    assert_eq!(
        project(&mut f, &p, &old, &r, &extra).unwrap().0[0]["x"],
        999.0
    );
    let mut coverage = Coverage::new(AdapterMode::Forward, "passive-tree");
    let (tree, _, mut receipt) =
        project_with_coverage(&mut f, &p, &old, &r, &extra, &mut coverage).unwrap();
    coverage.finish(&mut receipt).unwrap();
    for index in [0, 2] {
        assert_eq!(tree[index]["x"], 10.0);
        assert_eq!(tree[index]["y"], 20.0);
        assert!(tree[index].get("native_stats").is_none());
    }
    assert_eq!(receipt["native_packets"], 0);
    let issues = receipt["coverage"]["issues"].as_array().unwrap();
    assert_eq!(issues.len(), 1);
    assert_eq!(issues[0]["kind"], "ascendancy-frame");
    assert_eq!(issues[0]["entity"], "Witch3");
    assert_eq!(issues[0]["action"], "emitted-with-gap");
    assert_eq!(
        issues[0]["observed"],
        json!({
            "start_skill":303,
            "reference_start_node_sha256":sha256_hex(&reader::json_bytes(&r["nodes"]["303"]).unwrap()),
            "member_skills_sha256":sha256_hex(&reader::json_bytes(&vec![101_u64,303]).unwrap())
        })
    );
}

#[test]
fn changed_ascendancy_exclusion_emits_and_exposes_its_stale_node_exclusion() {
    let (mut f, mut p, mut old, r, extra) = fixture();
    let mut placeholder = extra.documents["tables/Ascendancy.json"]["rows"][0]["values"].clone();
    placeholder["Name"] = json!("[DNT] Previous placeholder");
    p["ascendancy"]["excluded"]["Witch3"] = json!({
        "definition_sha256":sha256_hex(&reader::json_bytes(&placeholder).unwrap()),
        "reason":"previous placeholder"
    });
    p["excluded"]["Multi"] = json!({
        "definition_sha256":sha256_hex(&reader::json_bytes(f.values("PassiveSkills",2)).unwrap()),
        "reason":"placeholder member"
    });
    f.values("PassiveSkills", 0)["Ascendancy"] = json!(0);
    old[0]["ascendancy_id"] = json!("Witch3");
    p["base_policy"]["qualification"]["context_sha256"] = json!(sha256_hex(
        &reader::json_bytes(&super::super::source::context(f.values("PassiveSkills", 0)).unwrap())
            .unwrap()
    ));
    assert_eq!(
        project(&mut f, &p, &old, &r, &extra).unwrap_err(),
        "changed ascendancy eligibility exclusion"
    );
    let mut coverage = Coverage::new(AdapterMode::Forward, "passive-tree");
    let (tree, meta, mut receipt) =
        project_with_coverage(&mut f, &p, &old, &r, &extra, &mut coverage).unwrap();
    coverage.finish(&mut receipt).unwrap();
    assert_eq!(tree[0]["ascendancy_id"], "Witch3");
    assert_eq!(meta["classes"][0]["ascendancies"][0]["id"], "Witch3");
    assert_eq!(tree.as_array().unwrap().len(), 2);
    let issues = receipt["coverage"]["issues"].as_array().unwrap();
    assert_eq!(issues.len(), 2);
    assert_eq!(issues[0]["kind"], "ascendancy-exclusion-changed");
    assert_eq!(issues[0]["entity"], "Witch3");
    assert_eq!(issues[0]["action"], "emitted-with-gap");
    assert_eq!(
        issues[0]["observed"]["definition_sha256"],
        sha256_hex(
            &reader::json_bytes(&extra.documents["tables/Ascendancy.json"]["rows"][0]["values"])
                .unwrap()
        )
    );
    assert_eq!(issues[1]["kind"], "stale-exclusion");
    assert_eq!(issues[1]["entity"], "Multi");
    assert_eq!(issues[1]["action"], "emitted-with-gap");
}

#[test]
fn changed_placeholder_ascendancy_quarantines_members_and_unlock_dependants() {
    for state in ["dnt", "disabled", "empty"] {
        let (mut f, mut p, mut old, r, mut extra) = unlock_fixture();
        p["ascendancy"]["excluded"]["Witch3"] = json!({
            "definition_sha256":sha256_hex(&reader::json_bytes(value(&mut extra,"Ascendancy",0)).unwrap()),
            "reason":"previous eligibility decision"
        });
        match state {
            "dnt" => {
                value(&mut extra, "Ascendancy", 0)["Name"] = json!("[DNT] Changed placeholder")
            }
            "disabled" => value(&mut extra, "Ascendancy", 0)["Disabled"] = json!(true),
            _ => value(&mut extra, "Ascendancy", 0)["Name"] = json!(""),
        }
        old[2]["ascendancy_id"] = json!("Witch3");
        f.values("PassiveSkills", 0)["VisibleForAscendancy"] = json!(0);
        f.values("PassiveSkills", 1)["UnlockedBy"] = json!([0]);
        p["base_policy"]["qualification"]["context_sha256"] = json!(sha256_hex(
            &reader::json_bytes(
                &super::super::source::context(f.values("PassiveSkills", 0)).unwrap()
            )
            .unwrap()
        ));
        assert_eq!(
            project(&mut f, &p, &old, &r, &extra).unwrap_err(),
            "changed ascendancy eligibility exclusion"
        );
        let mut coverage = Coverage::new(AdapterMode::Forward, "passive-tree");
        let (tree, meta, mut receipt) =
            project_with_coverage(&mut f, &p, &old, &r, &extra, &mut coverage).unwrap();
        coverage.finish(&mut receipt).unwrap();
        assert_eq!(tree, json!([]), "{state}");
        assert!(meta["classes"][0].get("ascendancies").is_none());
        let issues = receipt["coverage"]["issues"].as_array().unwrap();
        assert_eq!(issues.len(), 3);
        assert_eq!(issues[0]["kind"], "ascendancy-exclusion-changed");
        assert_eq!(issues[0]["entity"], "Witch3");
        assert_eq!(issues[0]["action"], "quarantined");
        assert!(
            issues[1..]
                .iter()
                .all(|issue| issue["kind"] == "dependant-quarantined")
        );
        assert_eq!(receipt["coverage"]["counts"]["quarantined"], 3);
        // Quarantine does not excuse a dangling override endpoint.
        value(&mut extra, "AscendancyPassiveSkillOverrides", 0)["Override"] = json!(999);
        let mut coverage = Coverage::new(AdapterMode::Forward, "passive-tree");
        assert!(project_with_coverage(&mut f, &p, &old, &r, &extra, &mut coverage).is_err());
    }
}

#[test]
fn unused_ascendancy_exclusions_are_listed_with_the_original_strict_message() {
    let (mut f, mut p, mut old, r, extra) = fixture();
    old[2]["ascendancy_id"] = json!("Witch3");
    for id in ["AbsentA", "AbsentB"] {
        p["ascendancy"]["excluded"][id] = json!({
            "definition_sha256":"0".repeat(64),"reason":"absent placeholder"
        });
    }
    assert_eq!(
        project(&mut f, &p, &old, &r, &extra).unwrap_err(),
        "unused ascendancy exclusion"
    );
    let mut coverage = Coverage::new(AdapterMode::Forward, "passive-tree");
    let (_, _, mut receipt) =
        project_with_coverage(&mut f, &p, &old, &r, &extra, &mut coverage).unwrap();
    coverage.finish(&mut receipt).unwrap();
    let issues = receipt["coverage"]["issues"].as_array().unwrap();
    assert_eq!(issues.len(), 2);
    for (issue, id) in issues.iter().zip(["AbsentA", "AbsentB"]) {
        assert_eq!(issue["kind"], "unused-ascendancy-exclusion");
        assert_eq!(issue["entity"], id);
        assert_eq!(issue["action"], "listed");
        assert_eq!(issue["message"], "unused ascendancy exclusion");
        assert_eq!(
            issue["observed"]["policy_definition_sha256"],
            "0".repeat(64)
        );
    }
}

#[test]
fn changed_placeholder_ascendancy_also_quarantines_legacy_unlock_owners() {
    let (mut f, mut p, mut old, r, mut extra) = fixture();
    p["ascendancy"]["excluded"]["Witch3"] = json!({
        "definition_sha256":sha256_hex(&reader::json_bytes(value(&mut extra,"Ascendancy",0)).unwrap()),
        "reason":"previous eligibility decision"
    });
    value(&mut extra, "Ascendancy", 0)["Disabled"] = json!(true);
    old[0]["unlock_constraint"] = json!({"ascendancy":"Witch3"});
    old[2]["ascendancy_id"] = json!("Witch3");
    assert_eq!(
        project(&mut f, &p, &old, &r, &extra).unwrap_err(),
        "changed ascendancy eligibility exclusion"
    );
    let mut coverage = Coverage::new(AdapterMode::Forward, "passive-tree");
    let (tree, _, mut receipt) =
        project_with_coverage(&mut f, &p, &old, &r, &extra, &mut coverage).unwrap();
    coverage.finish(&mut receipt).unwrap();
    assert_eq!(tree.as_array().unwrap().len(), 1);
    assert_eq!(tree[0]["skill"], 202);
    let issues = receipt["coverage"]["issues"].as_array().unwrap();
    assert_eq!(issues.len(), 2);
    assert_eq!(issues[1]["kind"], "dependant-quarantined");
    assert_eq!(issues[1]["entity"], "maximum_resistances1");
    assert_eq!(issues[1]["observed"]["quarantined_ascendancy"], "Witch3");
}

#[test]
fn quarantine_cascades_through_target_unlocks_to_a_fixed_point() {
    for chain in [false, true] {
        let (mut f, mut p, old, mut r, extra) = unlock_fixture();
        let missing = if chain { "303" } else { "202" };
        if chain {
            // Instance order makes the first dependant wait until the second pass.
            f.values("PassiveSkills", 0)["UnlockedBy"] = json!([1]);
            f.values("PassiveSkills", 1)["UnlockedBy"] = json!([2]);
        } else {
            f.values("PassiveSkills", 2)["UnlockedBy"] = json!([1, 1]);
        }
        p["base_policy"]["qualification"]["context_sha256"] = json!(sha256_hex(
            &reader::json_bytes(
                &super::super::source::context(f.values("PassiveSkills", 0)).unwrap()
            )
            .unwrap()
        ));
        r["nodes"].as_object_mut().unwrap().remove(missing);
        assert_eq!(
            project(&mut f, &p, &old, &r, &extra).unwrap_err(),
            format!(
                "node {missing}: missing physical orbit-offset compatibility; refusing incomplete radius geometry"
            )
        );
        let mut coverage = Coverage::new(AdapterMode::Forward, "passive-tree");
        let (tree, _, mut receipt) =
            project_with_coverage(&mut f, &p, &old, &r, &extra, &mut coverage).unwrap();
        coverage.finish(&mut receipt).unwrap();
        let issues = receipt["coverage"]["issues"].as_array().unwrap();
        let dependants: Vec<_> = issues
            .iter()
            .filter(|issue| issue["kind"] == "dependant-quarantined")
            .collect();
        assert_eq!(dependants.len(), if chain { 2 } else { 1 });
        assert_eq!(
            receipt["coverage"]["counts"]["quarantined"],
            if chain { 3 } else { 2 }
        );
        for issue in &dependants {
            assert_eq!(issue["action"], "quarantined");
            assert_eq!(
                issue["observed"]["quarantined_prerequisites"]
                    .as_array()
                    .unwrap()
                    .len(),
                1
            );
            assert_eq!(
                issue["observed"]["definition_sha256"]
                    .as_str()
                    .unwrap()
                    .len(),
                64
            );
        }
        if chain {
            assert_eq!(tree, json!([]));
            assert_eq!(receipt["native_packets"], 0);
        } else {
            assert_eq!(tree.as_array().unwrap().len(), 1);
            assert_eq!(tree[0]["skill"], 101);
            assert_eq!(tree[0]["connections"], json!([]));
            assert_eq!(receipt["source_records"].as_array().unwrap().len(), 1);
            assert_eq!(receipt["target_multistat_nodes"], 0);
            assert_eq!(dependants[0]["entity"], "Multi");
            assert_eq!(
                dependants[0]["observed"]["quarantined_prerequisites"],
                json!([202])
            );
        }
    }
}

#[test]
fn strict_ascendancy_decisions_precede_later_relationship_defects() {
    for changed in [true, false] {
        let (mut f, mut p, old, r, mut extra) = fixture();
        let id = if changed { "Witch3" } else { "Absent" };
        p["ascendancy"]["excluded"][id] = json!({
            "definition_sha256":"0".repeat(64),"reason":"previous eligibility decision"
        });
        value(&mut extra, "AscendancyPassiveSkillOverrides", 0)["Override"] = json!(999);
        assert_eq!(
            project(&mut f, &p, &old, &r, &extra).unwrap_err(),
            if changed {
                "changed ascendancy eligibility exclusion"
            } else {
                "unused ascendancy exclusion"
            }
        );
    }
}

#[test]
fn quarantining_a_node_keeps_its_dangling_physical_unlock_fatal() {
    let (mut f, p, old, mut r, extra) = unlock_fixture();
    f.values("PassiveSkills", 2)["UnlockedBy"] = json!([999]);
    r["nodes"].as_object_mut().unwrap().remove("303");
    assert_eq!(
        project(&mut f, &p, &old, &r, &extra).unwrap_err(),
        "node 303: missing physical orbit-offset compatibility; refusing incomplete radius geometry"
    );
    let mut coverage = Coverage::new(AdapterMode::Forward, "passive-tree");
    assert_eq!(
        project_with_coverage(&mut f, &p, &old, &r, &extra, &mut coverage).unwrap_err(),
        "unresolved physical row PassiveSkills/999"
    );
}

#[test]
fn forward_early_quarantines_validate_physical_unlock_shapes_and_targets() {
    for path in [
        "geometry",
        "identity",
        "alias",
        "name",
        "owner",
        "member",
        "excluded",
        "changed-exclusion",
    ] {
        for (field, invalid, expected) in [
            ("UnlockedBy", json!(false), "UnlockedBy must be an array"),
            (
                "UnlockedBy",
                json!(["bad"]),
                "invalid unlock physical reference",
            ),
            (
                "UnlockedBy",
                json!([999]),
                "unresolved physical row PassiveSkills/999",
            ),
            (
                "VisibleForAscendancy",
                json!("bad"),
                "invalid unlock physical reference",
            ),
            (
                "VisibleForAscendancy",
                json!(999),
                "unresolved physical row Ascendancy/999",
            ),
        ] {
            let (mut f, mut p, mut old, mut r, mut extra) = unlock_fixture();
            let strict = match path {
                "geometry" => {
                    r["nodes"].as_object_mut().unwrap().remove("303");
                    Some(
                        "node 303: missing physical orbit-offset compatibility; refusing incomplete radius geometry",
                    )
                }
                "identity" => {
                    old[2]["id"] = json!("previous-Multi");
                    Some("Multi: prepared identity collision at 303")
                }
                "alias" => {
                    old[2]["id"] = json!("303");
                    p["base_policy"]["legacy_id_bindings"] = json!([{
                        "legacy_id":"303","skill":303,"target_passive_id":"Multi",
                        "expected_name":"Multi",
                        "source_entry_sha256":sha256_hex(&reader::json_bytes(&old[2]).unwrap()),
                        "role":"fixture alias"
                    }]);
                    old[2]["stats"] = json!(["changed prepared entry"]);
                    Some("Multi: stale prepared identity alias")
                }
                "name" => {
                    f.values("PassiveSkills", 2)["Name"] = json!("[DNT] Placeholder");
                    Some("Multi: unclassified layout/unreleased definition")
                }
                "owner" | "member" => {
                    p["ascendancy"]["excluded"]["Witch3"] = json!({
                        "definition_sha256":sha256_hex(
                            &reader::json_bytes(value(&mut extra,"Ascendancy",0)).unwrap()),
                        "reason":"previous eligibility decision"
                    });
                    value(&mut extra, "Ascendancy", 0)["Disabled"] = json!(true);
                    if path == "owner" {
                        f.values("PassiveSkills", 2)["Ascendancy"] = Value::Null;
                        f.values("PassiveSkills", 2)["VisibleForAscendancy"] = json!(0);
                    }
                    Some("changed ascendancy eligibility exclusion")
                }
                "changed-exclusion" => {
                    p["excluded"]["Multi"] = json!({
                        "definition_sha256":"0".repeat(64),"reason":"previous placeholder"
                    });
                    Some("Multi: non-allocatable compatibility binding changed")
                }
                _ => None,
            };
            f.values("PassiveSkills", 2)[field] = invalid;
            if path == "excluded" {
                p["excluded"]["Multi"] = json!({
                    "definition_sha256":sha256_hex(
                        &reader::json_bytes(f.values("PassiveSkills",2)).unwrap()),
                    "reason":"exact excluded definition"
                });
            }
            if let Some(message) = strict {
                assert_eq!(
                    project(&mut f, &p, &old, &r, &extra).unwrap_err(),
                    message,
                    "{path}/{field}"
                );
            } else {
                project(&mut f, &p, &old, &r, &extra).unwrap();
            }
            let mut coverage = Coverage::new(AdapterMode::Forward, "passive-tree");
            assert_eq!(
                project_with_coverage(&mut f, &p, &old, &r, &extra, &mut coverage).unwrap_err(),
                expected,
                "{path}/{field}"
            );
        }
    }
}

#[test]
fn physical_unlocks_to_quarantined_nodes_and_owners_still_cascade() {
    for owner_quarantined in [false, true] {
        let (mut f, mut p, old, mut r, mut extra) = unlock_fixture();
        f.values("PassiveSkills", 0)["UnlockedBy"] = json!([2, 2]);
        if owner_quarantined {
            p["ascendancy"]["excluded"]["Witch3"] = json!({
                "definition_sha256":sha256_hex(
                    &reader::json_bytes(value(&mut extra,"Ascendancy",0)).unwrap()),
                "reason":"previous eligibility decision"
            });
            value(&mut extra, "Ascendancy", 0)["Disabled"] = json!(true);
            f.values("PassiveSkills", 0)["VisibleForAscendancy"] = json!(0);
        } else {
            r["nodes"]["303"]["orbitIndex"] = json!(1);
        }
        p["base_policy"]["qualification"]["context_sha256"] = json!(sha256_hex(
            &reader::json_bytes(
                &super::super::source::context(f.values("PassiveSkills", 0)).unwrap()
            )
            .unwrap()
        ));
        let mut coverage = Coverage::new(AdapterMode::Forward, "passive-tree");
        let (tree, _, mut receipt) =
            project_with_coverage(&mut f, &p, &old, &r, &extra, &mut coverage).unwrap();
        coverage.finish(&mut receipt).unwrap();
        assert_eq!(tree.as_array().unwrap().len(), 1);
        assert_eq!(tree[0]["skill"], 202);
        assert_eq!(tree[0]["connections"], json!([]));
        let issues = receipt["coverage"]["issues"].as_array().unwrap();
        assert_eq!(issues.len(), 2);
        let dependant = issues
            .iter()
            .find(|issue| issue["kind"] == "dependant-quarantined")
            .unwrap();
        assert_eq!(dependant["entity"], "maximum_resistances1");
        assert_eq!(dependant["action"], "quarantined");
        if owner_quarantined {
            assert_eq!(dependant["observed"]["quarantined_ascendancy"], "Witch3");
        } else {
            assert_eq!(
                dependant["observed"]["quarantined_prerequisites"],
                json!([303])
            );
        }
    }
}

#[test]
fn stale_node_exclusion_requires_a_policy_excluded_and_now_emitted_ascendancy() {
    for policy_excluded in [false, true] {
        for emitted in [false, true] {
            let (mut f, mut p, old, r, extra) = fixture();
            p["excluded"]["Multi"] = json!({
                "definition_sha256":sha256_hex(&reader::json_bytes(f.values("PassiveSkills", 2)).unwrap()),
                "reason":"placeholder member"
            });
            let input = refresh_tests::input(&mut f);
            let initial_policy: refresh::Policy = serde_json::from_value(p.clone()).unwrap();
            let facts = Facts::read(&input, &initial_policy.base_policy).unwrap();
            let mut source = Source::read(
                &input,
                &facts,
                &extra,
                initial_policy.ascendancy.as_ref().unwrap(),
                &initial_policy.base_policy.legacy_metadata.value,
                &mut Coverage::new(AdapterMode::Strict, "passive-tree"),
            )
            .unwrap();
            // Part 1 synthesizes the emitted set; part 2 re-evaluates ascendancies.
            if !emitted {
                source.entries.clear();
            }
            if policy_excluded {
                p["ascendancy"]["excluded"]["Witch3"] = json!({
                    "definition_sha256":"0".repeat(64), "reason":"previous placeholder"
                });
            }
            let policy: refresh::Policy = serde_json::from_value(p).unwrap();
            let descriptions = refresh_tests::descriptions();
            let renderer = Renderer::new(&descriptions).unwrap();
            for mode in [AdapterMode::Strict, AdapterMode::Forward] {
                let mut coverage = Coverage::new(mode, "passive-tree");
                let (tree, _, mut receipt) = refresh::project(
                    &input,
                    &facts,
                    &policy,
                    &old,
                    &r,
                    &renderer,
                    Some(refresh::Supplement {
                        ascendancy: &source,
                        input: &extra,
                    }),
                    &sha256_hex(&reader::json_bytes(&old).unwrap()),
                    &mut coverage,
                )
                .unwrap();
                assert_eq!(tree.as_array().unwrap().len(), 2);
                coverage.finish(&mut receipt).unwrap();
                if mode == AdapterMode::Strict {
                    assert!(receipt.get("coverage").is_none());
                } else if policy_excluded && emitted {
                    let issue = &receipt["coverage"]["issues"][0];
                    assert_eq!(receipt["coverage"]["issues"].as_array().unwrap().len(), 1);
                    assert_eq!(issue["kind"], "stale-exclusion");
                    assert_eq!(issue["action"], "emitted-with-gap");
                    assert_eq!(issue["entity"], "Multi");
                    assert_eq!(issue["observed"]["ascendancy_id"], "Witch3");
                } else {
                    assert_eq!(receipt["coverage"]["issues"], json!([]));
                }
            }
        }
    }
}

fn text_fixture() -> (Fixture, Value, Value, Value, selected::Input) {
    let (mut f, mut policy, old, reference, mut extra) = unlock_fixture();
    let doc = f.documents.get_mut("tables/PassiveSkills.json").unwrap();
    for (field, kind, array, target, value) in [
        (
            "GrantedSkill",
            "foreignrow",
            false,
            Some("SkillGems"),
            Value::Null,
        ),
        ("SkillPointsGranted", "i32", false, None, json!(0)),
        ("WeaponPointsGranted", "i32", false, None, json!(0)),
        (
            "PassiveSkillBuffs",
            "foreignrow",
            true,
            Some("BuffTemplates"),
            json!([]),
        ),
    ] {
        let n = doc["columns"].as_array().unwrap().len();
        doc["columns"].as_array_mut().unwrap().push(json!({"source_column":n,"physical_fields":[field],
            "schema":{"name":field,"type":kind,"array":array,"interval":false,"references":target.map(|t|json!({"table":t}))}}));
        doc["physical_fields"]
            .as_array_mut()
            .unwrap()
            .push(json!(field));
        for row in doc["rows"].as_array_mut().unwrap() {
            row["values"][field] = value.clone();
        }
    }
    extra.documents.insert(
        "tables/SkillGems.json".into(),
        table(
            "SkillGems",
            &[("BaseItemType", "foreignrow", false, Some("BaseItemTypes"))],
            json!([{"BaseItemType":1},{"BaseItemType":0}]),
        ),
    );
    extra.documents.insert("tables/BaseItemTypes.json".into(), table("BaseItemTypes", &[
        ("Id", "string", false, None),("Name", "string", false, None)], json!([
            {"Id":"Metadata/OtherSkill","Name":"Other source skill"},{"Id":"Metadata/GrantedSkill","Name":"Source skill {0}"}])));
    extra.documents.insert(
        "tables/ClientStrings.json".into(),
        table(
            "ClientStrings",
            &[
                ("Id", "string", false, None),
                ("Text", "string", false, None),
            ],
            json!([
            {"Id":"PassiveNodeGrantsPassivePoint","Text":"Grants {0} Passive Skill Point"},
            {"Id":"PassiveNodeGrantsPassivePoints","Text":"Grants {0} Passive Skill Points"},
            {"Id":"PassiveNodeGrantsSpecialisationPoint","Text":"{0} point becomes a weapon point"},
            {"Id":"PassiveNodeGrantsSpecialisationPoints","Text":"{0} points become weapon points"},
            {"Id":"ItemDisplayGrantedSkillNoScaling","Text":"Grants Skill: <underline>{{{0}}}"}]),
        ),
    );
    for table in ["ClientStrings", "SkillGems", "BaseItemTypes"] {
        let resource = format!("Data/Balance/{table}.datc64");
        extra.manifest["source_identity"]["raw_resources"][&resource] =
            f.manifest["source_identity"]["raw_resources"][&resource].clone();
    }
    policy["schema"] = json!("pobr-ordinary-target-tree-policy/v4");
    policy["non_stat_manifest_sha256"] = json!(sha256_hex(&extra.manifest_bytes));
    bind_text_contexts(&mut f, &mut policy);
    (f, policy, old, reference, extra)
}

fn bind_text_contexts(f: &mut Fixture, policy: &mut Value) {
    policy["base_policy"]["qualification"]["context_sha256"] = json!(sha256_hex(
        &reader::json_bytes(&super::super::source::context(f.values("PassiveSkills", 0)).unwrap())
            .unwrap()
    ));
    for row in doc_rows(f) {
        let raw = &row["values"];
        let mut context = refresh::context(raw).unwrap();
        for field in ["Ascendancy", "UnlockedBy", "VisibleForAscendancy"] {
            context.as_object_mut().unwrap().remove(field);
        }
        let binding = &mut policy["compatibility_bindings"][raw["Id"].as_str().unwrap()];
        binding["context_sha256"] = json!(sha256_hex(&reader::json_bytes(&context).unwrap()));
        for field in super::super::nonstat::OWNED_FIELDS {
            context.as_object_mut().unwrap().remove(field);
        }
        binding["render_context_sha256"] =
            json!(sha256_hex(&reader::json_bytes(&context).unwrap()));
    }
}

#[test]
fn complete_stats_points_and_skill_name_grants_propagate_together() {
    let (mut f, p, old, r, mut extra) = text_fixture();
    f.values("PassiveSkills", 2)["SkillPointsGranted"] = json!(2);
    f.values("PassiveSkills", 2)["WeaponPointsGranted"] = json!(1);
    f.values("PassiveSkills", 2)["GrantedSkill"] = json!(0);
    let (tree, _, receipt) = project(&mut f, &p, &old, &r, &extra).unwrap();
    assert_eq!(
        tree[2]["stats"],
        json!([
            "-7% to Fire Resistance",
            "22% increased Spell Damage",
            "Grants 2 Passive Skill Points",
            "1 point becomes a weapon point",
            "Grants Skill: <underline>{Source skill {0}}"
        ])
    );
    assert_eq!(
        receipt["source_records"][2]["text"]["owner"],
        "target-csd-and-client-strings"
    );
    assert_eq!(
        receipt["source_records"][2]["text"]["non_stat"][2]["base_item_row"],
        1
    );
    value(&mut extra, "BaseItemTypes", 0)["Name"] = json!("Renamed source skill");
    f.values("PassiveSkills", 2)["GrantedSkill"] = json!(1);
    f.values("PassiveSkills", 2)["SkillPointsGranted"] = json!(1);
    f.values("PassiveSkills", 2)["WeaponPointsGranted"] = json!(0);
    let (tree, _, _) = project(&mut f, &p, &old, &r, &extra).unwrap();
    assert_eq!(
        tree[2]["stats"],
        json!([
            "-7% to Fire Resistance",
            "22% increased Spell Damage",
            "Grants 1 Passive Skill Point",
            "Grants Skill: <underline>{Renamed source skill}"
        ])
    );
    f.values("PassiveSkills", 2)["GrantedSkill"] = Value::Null;
    f.values("PassiveSkills", 2)["SkillPointsGranted"] = json!(0);
    let (tree, _, _) = project(&mut f, &p, &old, &r, &extra).unwrap();
    assert_eq!(
        tree[2]["stats"],
        json!(["-7% to Fire Resistance", "22% increased Spell Damage"])
    );
}

#[test]
fn buffs_or_unknown_stats_keep_whole_text_and_reject_changed_grants() {
    for row in [1, 2] {
        let (mut f, mut p, old, r, extra) = text_fixture();
        f.values("PassiveSkills", row)["GrantedSkill"] = json!(0);
        if row == 2 {
            f.values("PassiveSkills", row)["PassiveSkillBuffs"] = json!([0]);
        }
        bind_text_contexts(&mut f, &mut p);
        let (tree, _, receipt) = project(&mut f, &p, &old, &r, &extra).unwrap();
        assert_eq!(tree[row]["stats"], old[row]["stats"]);
        assert_eq!(
            receipt["source_records"][row]["text"]["owner"],
            "prepared-whole-text"
        );
        f.values("PassiveSkills", row)["GrantedSkill"] = json!(1);
        let error = project(&mut f, &p, &old, &r, &extra).unwrap_err();
        assert!(
            error.contains("stale whole-text compatibility rejected"),
            "row {row}: {error}"
        );
    }
}

#[test]
fn tree_text_requires_same_raw_source_pinned_supplement_and_resolved_skill_fk() {
    for mode in 0..4 {
        let (mut f, p, old, r, mut extra) = text_fixture();
        match mode {
            0 => {
                extra.manifest["source_identity"]["raw_resources"]["Data/Balance/SkillGems.datc64"]
                    ["sha256"] = json!("0".repeat(64))
            }
            1 => extra.manifest_bytes = b"another source identity".to_vec(),
            2 => f.values("PassiveSkills", 2)["GrantedSkill"] = json!(99),
            _ => f.values("PassiveSkills", 2)["SkillPointsGranted"] = json!(-1),
        }
        assert!(
            project(&mut f, &p, &old, &r, &extra).is_err(),
            "mode {mode}"
        );
    }
}

#[test]
fn source_unlock_members_order_visibility_and_removal_propagate() {
    let (mut f, p, mut old, r, mut extra) = unlock_fixture();
    old[2]["unlock_constraint"] = json!({"nodes":[101],"ascendancy":"Witch3","future":false});
    f.values("PassiveSkills", 2)["UnlockedBy"] = json!([1, 0]);
    f.values("PassiveSkills", 2)["VisibleForAscendancy"] = json!(0);
    value(&mut extra, "Ascendancy", 0)["Id"] = json!("SourceAscendancy");
    let (tree, _, receipt) = project(&mut f, &p, &old, &r, &extra).unwrap();
    assert_eq!(
        tree[2]["unlock_constraint"],
        json!({"nodes":[202,101],"ascendancy":"SourceAscendancy","future":false})
    );
    assert_eq!(
        receipt["source_records"][2]["unlock"]["nodes"][0]["target_row"],
        1
    );
    assert!(tree[2]["native_stats"].is_null());
    let doc = extra.documents.get_mut("tables/Ascendancy.json").unwrap();
    doc["rows"].as_array_mut().unwrap().push(json!({"_row":1,"values":{
        "Id":"OtherSourceAscendancy","Name":"Other source owner","Character":0,"Disabled":false,"BaseAscendancy":null}}));
    doc["validation"]["rows"] = json!(2);
    f.values("PassiveSkills", 2)["UnlockedBy"] = json!([0]);
    f.values("PassiveSkills", 2)["VisibleForAscendancy"] = json!(1);
    let (tree, _, _) = project(&mut f, &p, &old, &r, &extra).unwrap();
    assert_eq!(
        tree[2]["unlock_constraint"],
        json!({"nodes":[101],"ascendancy":"OtherSourceAscendancy","future":false})
    );
    f.values("PassiveSkills", 2)["UnlockedBy"] = json!([]);
    f.values("PassiveSkills", 2)["VisibleForAscendancy"] = Value::Null;
    let (tree, _, _) = project(&mut f, &p, &old, &r, &extra).unwrap();
    assert_eq!(tree[2]["unlock_constraint"], json!({"future":false}));
    old[2].as_object_mut().unwrap().remove("unlock_constraint");
    let (tree, _, _) = project(&mut f, &p, &old, &r, &extra).unwrap();
    assert!(tree[2].get("unlock_constraint").is_none());
}

#[test]
fn unresolved_unlock_nodes_owners_and_wrong_column_types_reject() {
    for mode in 0..5 {
        let (mut f, p, old, r, extra) = unlock_fixture();
        match mode {
            0 => f.values("PassiveSkills", 2)["UnlockedBy"] = json!([100]),
            // Physical row exists, but its graph node is not an emitted member.
            1 => f.values("PassiveSkills", 2)["UnlockedBy"] = json!([3]),
            2 => f.values("PassiveSkills", 2)["VisibleForAscendancy"] = json!(100),
            3 => f.values("PassiveSkills", 2)["UnlockedBy"] = json!(null),
            _ => {
                let doc = f.documents.get_mut("tables/PassiveSkills.json").unwrap();
                let column = doc["columns"]
                    .as_array_mut()
                    .unwrap()
                    .iter_mut()
                    .find(|c| c["physical_fields"] == json!(["UnlockedBy"]))
                    .unwrap();
                column["schema"]["references"]["table"] = json!("ClientStrings");
            }
        }
        assert!(
            project(&mut f, &p, &old, &r, &extra).is_err(),
            "mode {mode}"
        );
    }
}

#[test]
fn requirement_and_unknown_context_never_become_unlock_predicates() {
    for field in ["Requirement", "Opaque"] {
        let (mut f, p, old, r, extra) = unlock_fixture();
        f.values("PassiveSkills", 2)[field] = json!(99);
        let error = project(&mut f, &p, &old, &r, &extra).unwrap_err();
        assert!(
            error.contains("unsupported source context change"),
            "{field}: {error}"
        );
    }
}

#[test]
fn source_unlock_ownership_never_waives_unrepresentable_variant_context() {
    for field in ["UnlockedBy", "VisibleForAscendancy"] {
        let (mut f, p, old, r, extra) = unlock_fixture();
        f.values("PassiveSkills", 5)[field] = if field == "UnlockedBy" {
            json!([0])
        } else {
            json!(0)
        };
        let error = project(&mut f, &p, &old, &r, &extra).unwrap_err();
        assert!(
            error.contains("variant unlock context cannot be represented"),
            "{field}: {error}"
        );
    }
}
#[test]
fn source_names_parent_node_and_override_values_propagate() {
    let (mut f, p, old, r, mut extra) = fixture();
    value(&mut extra, "Ascendancy", 0)["Name"] = json!("Renamed Lich");
    value(&mut extra, "Ascendancy", 0)["Character"] = json!(0);
    f.values("PassiveSkills", 5)["Stat1Value"] = json!(17);
    f.values("PassiveSkills", 5)["Name"] = json!("Source variant");
    let (tree, meta, receipt) = project(&mut f, &p, &old, &r, &extra).unwrap();
    assert_eq!(tree[2]["ascendancy_id"], "Witch3");
    assert_eq!(
        tree[2]["variants"][0],
        json!({"class":"Renamed Lich","variant_skill":606,"name":"Source variant","stats":["+17% to Fire Resistance"],"future":7})
    );
    assert!(tree[2]["native_stats"].is_null());
    assert!(meta["classes"][0]["ascendancies"].is_null());
    assert_eq!(
        meta["classes"][1]["ascendancies"][0],
        json!({"id":"Witch3","name":"Renamed Lich","future":17})
    );
    assert_eq!(
        receipt["ascendancy"]["relationships"]
            .as_array()
            .unwrap()
            .len(),
        1
    );
}
#[test]
fn relationship_removal_and_new_source_member_are_real() {
    let (mut f, p, old, r, mut extra) = fixture();
    let doc = extra
        .documents
        .get_mut("tables/AscendancyPassiveSkillOverrides.json")
        .unwrap();
    doc["rows"] = json!([]);
    doc["validation"]["rows"] = json!(0);
    doc["validation"]["actual_row_bytes"] = json!(0);
    let doc = extra.documents.get_mut("tables/Ascendancy.json").unwrap();
    doc["rows"].as_array_mut().unwrap().push(json!({"_row":1,"values":{"Id":"NewAsc","Name":"Source new member","Character":0,"Disabled":false,"BaseAscendancy":null}}));
    doc["validation"]["rows"] = json!(2);
    f.values("PassiveSkills", 2)["Ascendancy"] = json!(1);
    let (tree, meta, _) = project(&mut f, &p, &old, &r, &extra).unwrap();
    assert_eq!(tree[2]["ascendancy_id"], "NewAsc");
    assert!(tree[2]["variants"].is_null());
    assert_eq!(meta["classes"][1]["ascendancies"][0]["id"], "NewAsc");
}
#[test]
fn changed_unrenderable_replacement_never_inherits_previous_text() {
    let (mut f, p, old, r, mut extra) = fixture();
    value(&mut extra, "AscendancyPassiveSkillOverrides", 0)["Override"] = json!(1);
    let error = project(&mut f, &p, &old, &r, &extra).unwrap_err();
    assert!(error.contains("no complete compatibility text"), "{error}");
}
#[test]
fn dangling_or_duplicate_relationships_and_unavailable_nodes_reject() {
    for mode in 0..5 {
        let (mut f, p, old, r, mut extra) = fixture();
        match mode {
            0 => value(&mut extra, "Ascendancy", 0)["Character"] = json!(100),
            1 => value(&mut extra, "AscendancyPassiveSkillOverrides", 0)["Override"] = json!(100),
            2 => value(&mut extra, "Ascendancy", 0)["Disabled"] = json!(true),
            3 => f.values("PassiveSkills", 2)["Ascendancy"] = json!(100),
            _ => {
                let doc = extra
                    .documents
                    .get_mut("tables/AscendancyPassiveSkillOverrides.json")
                    .unwrap();
                let mut row = doc["rows"][0].clone();
                row["_row"] = json!(1);
                doc["rows"].as_array_mut().unwrap().push(row);
                doc["validation"]["rows"] = json!(2);
            }
        }
        assert!(
            project(&mut f, &p, &old, &r, &extra).is_err(),
            "mode {mode}"
        );
    }
}
#[test]
fn exact_placeholder_exclusion_cannot_hide_changed_or_removed_source() {
    let (mut f, mut p, old, r, mut extra) = fixture();
    let raw = json!({"Id":"Unused","Name":"[DNT-UNUSED] Placeholder","Character":0,"Disabled":false,"BaseAscendancy":null});
    p["ascendancy"]["excluded"]["Unused"] = json!({"definition_sha256":sha256_hex(&reader::json_bytes(&raw).unwrap()),"reason":"fixed placeholder"});
    let doc = extra.documents.get_mut("tables/Ascendancy.json").unwrap();
    doc["rows"]
        .as_array_mut()
        .unwrap()
        .push(json!({"_row":1,"values":raw}));
    doc["validation"]["rows"] = json!(2);
    project(&mut f, &p, &old, &r, &extra).unwrap();
    value(&mut extra, "Ascendancy", 1)["Name"] = json!("Now released");
    assert!(
        project(&mut f, &p, &old, &r, &extra)
            .unwrap_err()
            .contains("changed ascendancy eligibility")
    );
}
