use std::collections::BTreeMap;
use std::fs;

use pobr_data::catalog::stat_map::SkillStatMapDef;
use serde_json::{Value, json};

use super::super::coverage::AdapterMode;
use super::super::stat_set_codec::tests::table;
use super::super::tests::Fixture;
use super::super::{Args, BranchCodecArgs, CodecArgs, Domain, parse_args, reader, run};
use crate::raw_source::sha256_hex;

const MAP: &str = "map/source.json";
const CODEC: &str = "branch/source.json";
const POLICY: &str = "policy/policy.json";

pub(in crate::ordinary_facts) fn fixture() -> Fixture {
    let mut f = Fixture::new();
    let old: Vec<_> = f
        .documents
        .keys()
        .filter(|p| p.starts_with("tables/"))
        .cloned()
        .collect();
    f.documents.retain(|p, _| p == "source-lock.json");
    for (name, doc) in [
        (
            "Stats",
            table(
                "Stats",
                &[
                    ("Id", "string", false, None),
                    ("Unused", "i32", false, None),
                ],
                json!([
                    {"Id":"zPresent","Unused":-2},{"Id":"aPresent","Unused":0},{"Id":"u/~present","Unused":9}
                ]),
            ),
        ),
        (
            "GrantedEffects",
            table(
                "GrantedEffects",
                &[
                    ("Id", "string", false, None),
                    (
                        "StatSet",
                        "foreignrow",
                        false,
                        Some("GrantedEffectStatSets"),
                    ),
                    (
                        "AdditionalStatSets",
                        "foreignrow",
                        true,
                        Some("GrantedEffectStatSets"),
                    ),
                    ("_index", "i32", false, None),
                    ("IsSupport", "bool", false, None),
                ],
                json!([
                    {"Id":"ZOwner","StatSet":1,"AdditionalStatSets":[0,0,0],"_index":999,"IsSupport":false},
                    {"Id":"AOwner","StatSet":1,"AdditionalStatSets":[],"_index":998,"IsSupport":false},
                    {"Id":"UnusedOwner","StatSet":999,"AdditionalStatSets":[],"_index":997,"IsSupport":false},
                    {"Id":"NoCodecGem","StatSet":1,"AdditionalStatSets":[],"_index":996,"IsSupport":false},
                    {"Id":"UnusedGhost","StatSet":1,"AdditionalStatSets":[],"_index":995,"IsSupport":false},
                    {"Id":"SupportGem","StatSet":1,"AdditionalStatSets":[],"_index":994,"IsSupport":true},
                    {"Id":"AdditionalOnlyGem","StatSet":1,"AdditionalStatSets":[],"_index":993,"IsSupport":false},
                    {"Id":"SupportActiveGem","StatSet":1,"AdditionalStatSets":[],"_index":992,"IsSupport":false},
                    {"Id":"DntOnlyGem","StatSet":1,"AdditionalStatSets":[],"_index":991,"IsSupport":false},
                    {"Id":"UnlinkedGem","StatSet":1,"AdditionalStatSets":[],"_index":990,"IsSupport":false},
                    {"Id":"NoBaseGem","StatSet":1,"AdditionalStatSets":[],"_index":989,"IsSupport":false},
                    {"Id":"BlankNameGem","StatSet":1,"AdditionalStatSets":[],"_index":988,"IsSupport":false}
                ]),
            ),
        ),
        (
            "GrantedEffectStatSets",
            table(
                "GrantedEffectStatSets",
                &[("Id", "string", false, None)],
                json!([
                    {"Id":"Additional"},{"Id":"Primary"},{"Id":"Unowned"}
                ]),
            ),
        ),
        (
            "GemEffects",
            table(
                "GemEffects",
                &[
                    ("Id", "string", false, None),
                    ("GrantedEffect", "foreignrow", false, Some("GrantedEffects")),
                    (
                        "AdditionalGrantedEffects",
                        "foreignrow",
                        true,
                        Some("GrantedEffects"),
                    ),
                ],
                json!([
                    {"Id":"GemZ","GrantedEffect":0,"AdditionalGrantedEffects":[3,0,3,5]},
                    {"Id":"GemA","GrantedEffect":1,"AdditionalGrantedEffects":[]},
                    {"Id":"GemNoCodec","GrantedEffect":3,"AdditionalGrantedEffects":[4,3]},
                    {"Id":"GemSupport","GrantedEffect":5,"AdditionalGrantedEffects":[7]},
                    {"Id":"GemNoPrimary","GrantedEffect":null,"AdditionalGrantedEffects":[6,6]},
                    {"Id":"GemDnt","GrantedEffect":8,"AdditionalGrantedEffects":[]},
                    {"Id":"GemUnlinked","GrantedEffect":9,"AdditionalGrantedEffects":[]},
                    {"Id":"GemNoBase","GrantedEffect":10,"AdditionalGrantedEffects":[]},
                    {"Id":"GemBlankName","GrantedEffect":11,"AdditionalGrantedEffects":[]}
                ]),
            ),
        ),
        (
            "SkillGems",
            table(
                "SkillGems",
                &[
                    ("BaseItemType", "foreignrow", false, Some("BaseItemTypes")),
                    ("GemEffects", "foreignrow", true, Some("GemEffects")),
                    ("GemType", "i32", false, None),
                ],
                json!([
                    {"BaseItemType":0,"GemEffects":[0,1,0],"GemType":0},
                    {"BaseItemType":2,"GemEffects":[2],"GemType":0},
                    {"BaseItemType":3,"GemEffects":[3],"GemType":1},
                    {"BaseItemType":4,"GemEffects":[4],"GemType":0},
                    {"BaseItemType":5,"GemEffects":[5],"GemType":0},
                    {"BaseItemType":null,"GemEffects":[7],"GemType":0},
                    {"BaseItemType":6,"GemEffects":[8],"GemType":0}
                ]),
            ),
        ),
        (
            "BaseItemTypes",
            table(
                "BaseItemTypes",
                &[
                    ("Id", "string", false, None),
                    ("Name", "string", false, None),
                ],
                json!([
                    {"Id":"NormalZ","Name":"Normal Z"},
                    {"Id":"NormalA","Name":"Normal A"},
                    {"Id":"NormalNoCodec","Name":"Normal without codec"},
                    {"Id":"Support","Name":"Support"},
                    {"Id":"NormalAdditional","Name":"Normal additional"},
                    {"Id":"Dnt","Name":"[DNT] Hidden gem"},
                    {"Id":"BlankName","Name":""}
                ]),
            ),
        ),
    ] {
        f.documents.insert(format!("tables/{name}.json"), doc);
    }
    f.seal();
    for path in old {
        if !f.documents.contains_key(&path) {
            fs::remove_file(f.root.join("input").join(path)).unwrap();
        }
    }
    for dir in ["map", "branch", "policy"] {
        fs::create_dir(f.root.join(dir)).unwrap();
    }
    let mut policy: Value = serde_json::from_slice(include_bytes!(
        "../../../policies/skill-stat-map/0.5.5.5-legacy-policy.json"
    ))
    .unwrap();
    policy["absent_target_stat_ids"] = json!(["missing"]);
    policy["unbound_scopes"] = json!([{"skill":"GhostOwner","set_index":1,"codec_present":false,"target_effect_present":false,"action":"preserve unchanged/unbound; do not infer an index or retarget"}]);
    let unsupported = json!({"mods":[{"kind":"group","scalar":"UnknownMultiplier","mods":[
        {"kind":"future_kind","name":"NeverMappedName","value":{"nested":[true,"opaque",-2]},"tags":[{"type":"FutureTag","limit":false}],"unknown_constructor":{"nullable":null}}
    ]}],"unknown_entry":[null,5,"preserve"]});
    write(
        &f,
        MAP,
        &json!({"_meta":policy["source"]["metadata"],"future_top_level":{"x":null},
        "global":{"zPresent":unsupported,"missing":{"_unextractable":true,"reason":"literal function retained marker"},"u/~present":{"_unextractable":true}},
        "per_stat_set":{
            "ZOwner":{"7":{"zPresent":{"div":1000,"mods":[]},"missing":{"skill_flag":"unknown"}},"3":{"aPresent":{"value":0}}},
            "AOwner":{"4":{"aPresent":{"mult":-1,"base":0}}},"GhostOwner":{"1":{"missing":{"mods":[]}}}
        }}),
    );
    write(
        &f,
        CODEC,
        &json!({"_meta":policy["branch_codec"]["metadata"],"labels":[
            {"skill":"ZOwner","set_id":"Additional","set_index":7,"label":""},
            {"skill":"ZOwner","set_id":"Primary","set_index":3,"label":"Primary label"},
            {"skill":"AOwner","set_id":"Primary","set_index":4,"label":"Alias"},
            {"skill":"UnusedGhost","set_id":"UnacquiredSet","set_index":9,"label":"Uncertified archive"}
        ]}),
    );
    write(&f, POLICY, &policy);
    reseal(&mut f);
    f
}

fn doc(f: &Fixture, path: &str) -> Value {
    crate::read_json(&f.root.join(path)).unwrap()
}
fn write(f: &Fixture, path: &str, value: &Value) {
    let mut b = b" \n\t".to_vec();
    b.extend(serde_json::to_vec(value).unwrap());
    b.extend(b"\n\n");
    fs::write(f.root.join(path), b).unwrap();
}
fn reseal(f: &mut Fixture) {
    f.seal();
    let mut p = doc(f, POLICY);
    p["target"]["facts_manifest_sha256"] = f.args().expected_manifest_sha256.into();
    p["source"]["sha256"] = sha256_hex(&fs::read(f.root.join(MAP)).unwrap()).into();
    p["branch_codec"]["sha256"] = sha256_hex(&fs::read(f.root.join(CODEC)).unwrap()).into();
    write(f, POLICY, &p);
}
pub(in crate::ordinary_facts) fn args(f: &Fixture) -> Args {
    Args {
        domain: Domain::SkillStatMap,
        codec: Some(CodecArgs {
            source: f.root.join(MAP),
            source_sha256: sha256_hex(&fs::read(f.root.join(MAP)).unwrap()),
            policy: f.root.join(POLICY),
            policy_sha256: sha256_hex(&fs::read(f.root.join(POLICY)).unwrap()),
        }),
        branch_codec: Some(BranchCodecArgs {
            path: f.root.join(CODEC),
            sha256: sha256_hex(&fs::read(f.root.join(CODEC)).unwrap()),
        }),
        ..f.args()
    }
}
fn read(f: &Fixture, file: &str) -> Value {
    doc(f, &format!("out/{file}"))
}
fn rejects(f: &Fixture, expected: &str) {
    let e = run(args(f)).unwrap_err();
    assert!(e.contains(expected), "expected {expected:?}, got {e:?}");
    assert!(!f.root.join("out").exists());
}
fn scope<'a>(r: &'a Value, skill: &str, index: u32) -> &'a Value {
    r["conversion"]["scope_records"]
        .as_array()
        .unwrap()
        .iter()
        .find(|r| r["skill"] == skill && r["set_index"] == index)
        .unwrap()
}

#[test]
fn forward_reports_content_gaps_verbatim_and_strict_keeps_exact_messages() {
    for (case, message, expected) in [
        (
            "removed-skill",
            "scope AOwner/4: incomplete codec/target binding (codec_present=true, target_effect_present=false)",
            vec![("scope-skill-removed", "AOwner", "retained-legacy")],
        ),
        (
            "removed-stat",
            "absent stat exceptions mismatch: unlisted [\"aPresent\"]; stale []",
            vec![
                ("scope-stat-removed", "AOwner/aPresent", "retained-legacy"),
                ("scope-stat-removed", "ZOwner/aPresent", "retained-legacy"),
            ],
        ),
        (
            "incomplete",
            "scope AOwner/4: incomplete codec/target binding (codec_present=false, target_effect_present=true)",
            vec![("scope-binding-incomplete", "AOwner/4", "retained-legacy")],
        ),
        (
            "unowned",
            "scope AOwner/4: codec set Unowned is not target raw-owned",
            vec![("scope-binding-incomplete", "AOwner/4", "retained-legacy")],
        ),
        (
            "unbound-unlisted",
            "unlisted unbound scope: GhostOwner/1",
            vec![("scope-unbound-unlisted", "GhostOwner/1", "retained-legacy")],
        ),
        (
            "stale-matching",
            "stale unbound scope exception: GhostOwner/1 now matches",
            vec![("scope-unbound-stale", "GhostOwner/1", "retained-legacy")],
        ),
        (
            "stale-missing",
            "unused/stale unbound scope exception",
            vec![("scope-unbound-stale", "GhostOwner/1", "listed")],
        ),
        (
            "stale-partial",
            "scope GhostOwner/1: incomplete codec/target binding (codec_present=false, target_effect_present=true)",
            vec![
                (
                    "scope-binding-incomplete",
                    "GhostOwner/1",
                    "retained-legacy",
                ),
                ("scope-unbound-stale", "GhostOwner/1", "retained-legacy"),
            ],
        ),
        (
            "absent-global",
            "absent stat exceptions mismatch: unlisted [\"new_absent\"]; stale []",
            vec![("stat-absent-unlisted", "new_absent", "retained-legacy")],
        ),
        (
            "stale-stat-retained",
            "absent stat exceptions mismatch: unlisted []; stale [\"missing\"]",
            vec![("stat-absent-stale", "missing", "retained-legacy")],
        ),
        (
            "stale-stat-missing",
            "absent stat exceptions mismatch: unlisted []; stale [\"never_referenced\"]",
            vec![("stat-absent-stale", "never_referenced", "listed")],
        ),
        (
            "multiple",
            "scope AOwner/4: incomplete codec/target binding (codec_present=true, target_effect_present=false)",
            vec![
                ("scope-skill-removed", "AOwner", "retained-legacy"),
                ("scope-stat-removed", "AOwner/aPresent", "retained-legacy"),
                ("scope-stat-removed", "ZOwner/aPresent", "retained-legacy"),
                ("stat-absent-stale", "never_referenced", "listed"),
                ("stat-absent-unlisted", "new_absent", "retained-legacy"),
            ],
        ),
    ] {
        let mut f = fixture();
        let mut p = doc(&f, POLICY);
        let mut m = doc(&f, MAP);
        let mut c = doc(&f, CODEC);
        match case {
            "removed-skill" => f.values("GrantedEffects", 1)["Id"] = json!("NewAOwner"),
            "removed-stat" => f.values("Stats", 1)["Id"] = json!("ChangedStat"),
            "incomplete" => c["labels"][2]["set_index"] = json!(5),
            "unowned" => c["labels"][2]["set_id"] = json!("Unowned"),
            "unbound-unlisted" => p["unbound_scopes"] = json!([]),
            "stale-matching" => {
                f.values("GrantedEffects", 2)["Id"] = json!("GhostOwner");
                f.values("GrantedEffects", 2)["StatSet"] = json!(1);
                c["labels"][3] = json!({"skill":"GhostOwner","set_id":"Primary","set_index":1,"label":"now bound"});
            }
            "stale-missing" => {
                m["per_stat_set"]
                    .as_object_mut()
                    .unwrap()
                    .remove("GhostOwner");
            }
            "stale-partial" => {
                f.values("GrantedEffects", 2)["Id"] = json!("GhostOwner");
                f.values("GrantedEffects", 2)["StatSet"] = json!(1);
            }
            "absent-global" => m["global"]["new_absent"] = json!({"mods":[]}),
            "stale-stat-retained" => {
                f.values("Stats", 1)["Id"] = json!("missing");
                p["absent_target_stat_ids"] = json!(["missing", "aPresent"]);
            }
            "stale-stat-missing" => {
                p["absent_target_stat_ids"] = json!(["missing", "never_referenced"]);
            }
            "multiple" => {
                f.values("GrantedEffects", 1)["Id"] = json!("NewAOwner");
                f.values("Stats", 1)["Id"] = json!("ChangedStat");
                m["global"]["new_absent"] = json!({"mods":[]});
                m["per_stat_set"]["ZOwner"]["7"]["aPresent"] = json!({"mods":[]});
                p["absent_target_stat_ids"] = json!(["missing", "never_referenced"]);
            }
            _ => unreachable!(),
        }
        write(&f, MAP, &m);
        write(&f, CODEC, &c);
        write(&f, POLICY, &p);
        reseal(&mut f);
        assert_eq!(run(args(&f)).unwrap_err(), message, "{case}");
        assert!(!f.root.join("out").exists(), "{case}");
        run(Args {
            mode: AdapterMode::Forward,
            ..args(&f)
        })
        .unwrap();
        for (source, output) in [
            (MAP, "overlay/skill_stat_map.json"),
            (CODEC, "branch-codec.json"),
            (POLICY, "codec-policy.json"),
        ] {
            assert_eq!(
                fs::read(f.root.join(source)).unwrap(),
                fs::read(f.root.join("out").join(output)).unwrap(),
                "{case}: {source}",
            );
        }
        let r = read(&f, "producer-receipt.json");
        assert_eq!(r.as_object().unwrap().len(), 10);
        assert_eq!(r["files"].as_object().unwrap().len(), 6);
        let issues = r["conversion"]["coverage"]["issues"].as_array().unwrap();
        let actual: Vec<_> = issues
            .iter()
            .map(|issue| {
                assert_eq!(issue["domain"], "skill-stat-map");
                assert!(issue["observed"].is_object(), "{case}");
                (
                    issue["kind"].as_str().unwrap(),
                    issue["entity"].as_str().unwrap(),
                    issue["action"].as_str().unwrap(),
                )
            })
            .collect();
        assert_eq!(actual, expected, "{case}");
        assert_eq!(issues[0]["message"], message, "{case}");
        if matches!(
            case,
            "removed-skill" | "incomplete" | "unowned" | "multiple"
        ) {
            assert_eq!(scope(&r, "AOwner", 4)["binding"]["status"], "unresolved");
            assert_eq!(r["conversion"]["raw_owned_scopes"], 2);
        }
        if case == "multiple" {
            assert_eq!(
                r["conversion"]["coverage"]["counts"],
                json!({"listed":1,"retained-legacy":4,"emitted-with-gap":0,"quarantined":0}),
            );
            assert!(
                r["conversion"]["target_gem_effects_without_codec"]
                    .as_array()
                    .unwrap()
                    .contains(&json!("NoCodecGem"))
            );
            assert!(
                r["conversion"]["target_gem_effects_without_map_scope"]
                    .as_array()
                    .unwrap()
                    .contains(&json!("NoCodecGem"))
            );
        }
    }
}

#[test]
fn forward_still_rejects_integrity_errors_after_a_content_gap() {
    for case in ["pin", "duplicate", "column", "dangling"] {
        let mut f = fixture();
        // An incomplete scope must not hide a malformed target owner.
        let mut c = doc(&f, CODEC);
        c["labels"][2]["set_index"] = json!(5);
        match case {
            "duplicate" => c["labels"][1]["set_index"] = json!(7),
            "column" => {
                f.documents.get_mut("tables/GrantedEffects.json").unwrap()["columns"][1]["schema"]
                    ["type"] = json!("i32");
            }
            "dangling" => f.values("GrantedEffects", 1)["StatSet"] = json!(999),
            _ => {}
        }
        write(&f, CODEC, &c);
        reseal(&mut f);
        let mut a = args(&f);
        a.mode = AdapterMode::Forward;
        if case == "pin" {
            a.codec.as_mut().unwrap().source_sha256 = "0".repeat(64);
        }
        assert!(run(a).is_err(), "{case}");
        assert!(!f.root.join("out").exists(), "{case}");
    }
}

#[test]
fn target_gem_coverage_lists_sorted_distinct_normal_gem_primary_and_additional_effects() {
    let mut f = fixture();
    let mut map = doc(&f, MAP);
    map["per_stat_set"]["NoCodecGem"] = json!({});
    write(&f, MAP, &map);
    reseal(&mut f);
    run(args(&f)).unwrap();
    let r = read(&f, "producer-receipt.json");
    assert_eq!(r.as_object().unwrap().len(), 10);
    let c = &r["conversion"];
    assert_eq!(c["target_gem_effects"], 6);
    assert_eq!(
        c["target_gem_effects_without_codec"],
        json!(["AdditionalOnlyGem", "NoCodecGem", "SupportActiveGem"])
    );
    assert_eq!(c["target_gem_effects_without_codec_count"], 3);
    assert_eq!(
        c["target_gem_effects_without_map_scope"],
        json!([
            "AdditionalOnlyGem",
            "NoCodecGem",
            "SupportActiveGem",
            "UnusedGhost"
        ])
    );
    assert_eq!(c["target_gem_effects_without_map_scope_count"], 4);
    for (table, unused) in [
        ("GrantedEffects", vec![json!(["_index"])]),
        ("GemEffects", vec![json!(["Id"])]),
        ("SkillGems", vec![json!(["GemType"])]),
        ("BaseItemTypes", vec![]),
    ] {
        let unconsumed = c["unconsumed_source"]
            .as_array()
            .unwrap()
            .iter()
            .find(|entry| entry["table"] == table)
            .unwrap();
        assert_eq!(
            unconsumed["columns"]
                .as_array()
                .unwrap()
                .iter()
                .map(|column| column["physical_fields"].clone())
                .collect::<Vec<_>>(),
            unused
        );
        assert_eq!(
            unconsumed["source_row_range"]["end_exclusive"],
            f.documents[&format!("tables/{table}.json")]["rows"]
                .as_array()
                .unwrap()
                .len()
        );
    }
}

#[test]
fn target_gem_coverage_rejects_dangling_and_malformed_consumed_fields() {
    for (table, field, value, expected) in [
        (
            "GemEffects",
            "GrantedEffect",
            json!(999),
            "GemEffects/0.GrantedEffect",
        ),
        (
            "GemEffects",
            "AdditionalGrantedEffects",
            json!([5, 999]),
            "GemEffects/0.AdditionalGrantedEffects",
        ),
        (
            "GemEffects",
            "GrantedEffect",
            json!(-1),
            "physical reference",
        ),
        (
            "GemEffects",
            "AdditionalGrantedEffects",
            json!([null]),
            "physical reference",
        ),
        (
            "GemEffects",
            "AdditionalGrantedEffects",
            Value::Null,
            "expected array",
        ),
        (
            "GrantedEffects",
            "IsSupport",
            Value::Null,
            "boolean required",
        ),
        (
            "SkillGems",
            "BaseItemType",
            json!(999),
            "dangling BaseItemType",
        ),
        (
            "SkillGems",
            "GemEffects",
            json!([999]),
            "dangling GemEffects",
        ),
        ("SkillGems", "GemEffects", Value::Null, "SkillGems/0"),
        ("BaseItemTypes", "Name", Value::Null, "BaseItemTypes/0.Name"),
    ] {
        let mut f = fixture();
        f.values(table, 0)[field] = value;
        reseal(&mut f);
        rejects(&f, expected);
    }
    for (table, column) in [
        ("GrantedEffects", 4),
        ("GemEffects", 1),
        ("GemEffects", 2),
        ("SkillGems", 0),
        ("SkillGems", 1),
        ("BaseItemTypes", 0),
        ("BaseItemTypes", 1),
    ] {
        let mut f = fixture();
        let doc = f
            .documents
            .get_mut(&format!("tables/{table}.json"))
            .unwrap();
        doc["columns"][column]["schema"]["type"] = json!("invalid");
        reseal(&mut f);
        rejects(&f, "source schema type mismatch");
    }
    for (table, row, field, value, expected) in [
        (
            "SkillGems",
            4,
            "GemEffects",
            json!([999]),
            "dangling GemEffects",
        ),
        (
            "SkillGems",
            5,
            "GemEffects",
            json!([999]),
            "dangling GemEffects",
        ),
        (
            "GemEffects",
            6,
            "GrantedEffect",
            json!(999),
            "GemEffects/6.GrantedEffect",
        ),
    ] {
        let mut f = fixture();
        f.values(table, row)[field] = value;
        reseal(&mut f);
        rejects(&f, expected);
    }
}

#[test]
fn original_dto_unknown_unsupported_and_all_auxiliary_bytes_are_preserved() {
    let f = fixture();
    run(args(&f)).unwrap();
    for (source, out) in [
        (MAP, "overlay/skill_stat_map.json"),
        (CODEC, "branch-codec.json"),
        (POLICY, "codec-policy.json"),
    ] {
        assert_eq!(
            fs::read(f.root.join(source)).unwrap(),
            fs::read(f.root.join("out").join(out)).unwrap()
        );
    }
    let dto: SkillStatMapDef =
        crate::read_json(&f.root.join("out/overlay/skill_stat_map.json")).unwrap();
    assert_eq!(dto.global.len(), 3);
    assert_eq!(dto.per_stat_set.len(), 3);
    let m = read(&f, "overlay/skill_stat_map.json");
    assert_eq!(m, doc(&f, MAP));
    assert_eq!(
        m["global"]["zPresent"]["mods"][0]["mods"][0]["kind"],
        "future_kind"
    );
    assert_eq!(
        m["global"]["zPresent"]["mods"][0]["scalar"],
        "UnknownMultiplier"
    );
    assert!(m["global"]["zPresent"]["unknown_entry"][0].is_null());
    let r = read(&f, "producer-receipt.json");
    let c = &r["conversion"];
    assert_eq!(c["global_entries"], 3);
    assert_eq!(c["scoped_entries"], 5);
    assert_eq!(c["scope_count"], 4);
    assert_eq!(c["raw_owned_scopes"], 3);
    assert_eq!(c["unbound_scopes"], 1);
    assert_eq!(c["absent_target_stat_ids"], json!(["missing"]));
    assert_eq!(c["unextractable_records"].as_array().unwrap().len(), 2);
    for entry in c["global_records"].as_array().unwrap().iter().chain(
        c["scope_records"]
            .as_array()
            .unwrap()
            .iter()
            .flat_map(|s| s["stats"].as_array().unwrap()),
    ) {
        let source = doc(&f, MAP);
        let original = source
            .pointer(entry["source_pointer"].as_str().unwrap())
            .unwrap();
        assert_eq!(
            entry["entry_sha256"],
            sha256_hex(&reader::json_bytes(original).unwrap())
        );
        if entry["stat_id"] == "missing" {
            assert!(entry["target_stat"].is_null());
        }
        if entry["stat_id"] == "zPresent" {
            assert_eq!(entry["target_stat"]["source_row"], 0);
        }
        if entry["stat_id"] == "u/~present" {
            assert_eq!(entry["source_pointer"], "/global/u~1~0present");
            assert_eq!(entry["target_stat"]["source_row"], 2);
        }
    }
    assert_eq!(c["legacy_source"]["snapshot_version"], "0.5.5.4.2");
    assert_eq!(
        c["branch_codec"]["metadata"]["schema"],
        "stat_set_labels/v1"
    );
    assert_eq!(
        c["unconsumed_source"][0]["columns"][0]["physical_fields"],
        json!(["Unused"])
    );
}

#[test]
fn scopes_use_exact_export_codec_keys_not_raw_order_labels_or_primary_fallback() {
    let f = fixture();
    run(args(&f)).unwrap();
    let r = read(&f, "producer-receipt.json");
    let additional = &scope(&r, "ZOwner", 7)["binding"];
    assert_eq!(additional["codec_source_row"], 0);
    assert_eq!(additional["codec_record"]["set_id"], "Additional");
    assert_eq!(additional["codec_record"]["label"], "");
    assert_eq!(additional["target_owner"]["effect_source_row"], 0);
    assert_eq!(
        additional["target_owner"]["primary"],
        json!({"source_row":1,"set_id":"Primary"})
    );
    assert_eq!(
        additional["target_owner"]["additional"],
        json!([
            {"source_row":0,"set_id":"Additional"},{"source_row":0,"set_id":"Additional"},{"source_row":0,"set_id":"Additional"}
        ])
    );
    assert_eq!(
        scope(&r, "AOwner", 4)["binding"]["target_owner"]["effect_source_row"],
        1
    );
    assert_eq!(scope(&r, "ZOwner", 3)["binding"]["codec_source_row"], 1);
    let ghost = &scope(&r, "GhostOwner", 1)["binding"];
    assert_eq!(ghost["status"], "policy-unbound");
    assert_eq!(ghost["codec_present"], false);
    assert!(ghost["target_owner"].is_null());
    assert_eq!(r["conversion"]["branch_codec"]["records"], 4); // unused archive row is kept without claiming raw ownership
    for bad in ["Unowned", "NoSuchSet"] {
        let mut f = fixture();
        let mut c = doc(&f, CODEC);
        c["labels"][0]["set_id"] = json!(bad);
        write(&f, CODEC, &c);
        reseal(&mut f);
        rejects(&f, "not target raw-owned");
    }
    let mut f = fixture();
    let mut m = doc(&f, MAP);
    let entries = m["per_stat_set"]["ZOwner"]
        .as_object_mut()
        .unwrap()
        .remove("7")
        .unwrap();
    m["per_stat_set"]["ZOwner"]["1"] = entries;
    write(&f, MAP, &m);
    reseal(&mut f);
    rejects(&f, "incomplete codec/target binding");
}

#[test]
fn exact_absent_and_unbound_exceptions_reject_new_missing_and_stale_decisions() {
    for case in [
        "missing-stat-policy",
        "stale-stat-policy",
        "stat-now-present",
        "new-stat",
        "missing-unbound",
        "stale-unbound",
        "scope-now-matches",
        "partial-effect",
        "partial-codec",
    ] {
        let mut f = fixture();
        let mut p = doc(&f, POLICY);
        let mut m = doc(&f, MAP);
        let mut c = doc(&f, CODEC);
        match case {
            "missing-stat-policy" => p["absent_target_stat_ids"] = json!([]),
            "stale-stat-policy" => p["absent_target_stat_ids"]
                .as_array_mut()
                .unwrap()
                .push(json!("never_referenced")),
            "stat-now-present" => f.values("Stats", 1)["Id"] = json!("missing"),
            "new-stat" => m["global"]["new_absent"] = json!({"mods":[]}),
            "missing-unbound" => p["unbound_scopes"] = json!([]),
            "stale-unbound" => {
                m["per_stat_set"]
                    .as_object_mut()
                    .unwrap()
                    .remove("GhostOwner");
            }
            "scope-now-matches" => {
                f.values("GrantedEffects", 2)["Id"] = json!("GhostOwner");
                f.values("GrantedEffects", 2)["StatSet"] = json!(1);
                c["labels"][3] = json!({"skill":"GhostOwner","set_id":"Primary","set_index":1,"label":"now bound"});
            }
            "partial-effect" => f.values("GrantedEffects", 2)["Id"] = json!("GhostOwner"),
            _ => {
                c["labels"][3] = json!({"skill":"GhostOwner","set_id":"Primary","set_index":1,"label":"codec only"})
            }
        }
        write(&f, MAP, &m);
        write(&f, CODEC, &c);
        write(&f, POLICY, &p);
        reseal(&mut f);
        assert!(run(args(&f)).is_err(), "{case}");
        assert!(!f.root.join("out").exists());
    }
}

#[test]
fn malformed_scope_codec_keys_and_consumed_target_references_fail() {
    for index in [
        "0",
        "01",
        "+1",
        "-1",
        "1.0",
        "1e0",
        " 1",
        "１",
        "4294967296",
        "",
    ] {
        let mut f = fixture();
        let mut m = doc(&f, MAP);
        let entries = m["per_stat_set"]["GhostOwner"]
            .as_object_mut()
            .unwrap()
            .remove("1")
            .unwrap();
        m["per_stat_set"]["GhostOwner"][index] = entries;
        write(&f, MAP, &m);
        reseal(&mut f);
        rejects(&f, "scope index");
    }
    for case in [
        "duplicate-index",
        "duplicate-set",
        "zero-index",
        "float-index",
        "blank-skill",
        "blank-set",
        "noncanonical-skill",
        "noncanonical-stat",
        "physical-key",
        "duplicate-target-id",
        "bad-primary",
        "bad-additional",
        "null-additional",
        "metadata",
    ] {
        let mut f = fixture();
        let mut c = doc(&f, CODEC);
        let mut m = doc(&f, MAP);
        match case {
            "duplicate-index" => c["labels"][1]["set_index"] = json!(7),
            "duplicate-set" => c["labels"][1]["set_id"] = json!("Additional"),
            "zero-index" => c["labels"][3]["set_index"] = json!(0),
            "float-index" => c["labels"][3]["set_index"] = json!(1.0),
            "blank-skill" => c["labels"][3]["skill"] = json!(""),
            "blank-set" => c["labels"][3]["set_id"] = json!(""),
            "noncanonical-skill" => c["labels"][3]["skill"] = json!(" padded"),
            "noncanonical-stat" => m["global"][" padded"] = json!({}),
            "physical-key" => {
                f.documents.get_mut("tables/Stats.json").unwrap()["rows"][1]["_row"] = json!(0)
            }
            "duplicate-target-id" => f.values("Stats", 1)["Id"] = json!("zPresent"),
            "bad-primary" => f.values("GrantedEffects", 0)["StatSet"] = json!(999),
            "bad-additional" => {
                f.values("GrantedEffects", 0)["AdditionalStatSets"] = json!([0, null])
            }
            "null-additional" => f.values("GrantedEffects", 0)["AdditionalStatSets"] = json!(null),
            _ => {
                f.documents.get_mut("tables/GrantedEffects.json").unwrap()["columns"][2]["schema"]
                    ["references"]["table"] = json!("Stats")
            }
        }
        write(&f, CODEC, &c);
        write(&f, MAP, &m);
        reseal(&mut f);
        assert!(run(args(&f)).is_err(), "{case}");
        assert!(!f.root.join("out").exists());
    }
}

#[test]
fn policy_target_metadata_version_paths_and_exception_schema_are_strict() {
    for case in [
        "schema",
        "target-patch",
        "manifest",
        "source-pin",
        "branch-pin",
        "version",
        "path",
        "meta-schema",
        "vendor",
        "commit",
        "unknown",
        "empty-id",
        "duplicate-absent",
        "duplicate-unbound",
        "action",
        "presence",
    ] {
        let f = fixture();
        let mut p = doc(&f, POLICY);
        match case {
            "schema" => p["schema"] = json!("future"),
            "target-patch" => p["target"]["game_patch"] = json!("old"),
            "manifest" => p["target"]["facts_manifest_sha256"] = json!("0".repeat(64)),
            "source-pin" => p["source"]["sha256"] = json!("bad"),
            "branch-pin" => p["branch_codec"]["sha256"] = json!("0".repeat(64)),
            "version" => p["source"]["snapshot_version"] = json!("0.5.5.5"),
            "path" => {
                p["branch_codec"]["path"] = json!("data/0.5.5.5/overlay/stat_set_labels.json")
            }
            "meta-schema" => p["source"]["metadata"]["schema"] = json!("stat_set_labels/v1"),
            "vendor" => p["source"]["metadata"]["vendor"] = json!("new"),
            "commit" => p["branch_codec"]["metadata"]["vendor_commit"] = json!("bad"),
            "unknown" => p["unknown"] = json!(true),
            "empty-id" => p["absent_target_stat_ids"] = json!([""]),
            "duplicate-absent" => p["absent_target_stat_ids"] = json!(["missing", "missing"]),
            "duplicate-unbound" => {
                let x = p["unbound_scopes"][0].clone();
                p["unbound_scopes"].as_array_mut().unwrap().push(x);
            }
            "action" => p["unbound_scopes"][0]["action"] = json!("drop"),
            _ => p["unbound_scopes"][0]["codec_present"] = json!(true),
        }
        write(&f, POLICY, &p);
        assert!(run(args(&f)).is_err(), "{case}");
        assert!(!f.root.join("out").exists());
    }
    for path in [MAP, CODEC] {
        let mut f = fixture();
        let mut v = doc(&f, path);
        v["_meta"]["vendor_commit_subject"] = json!("changed");
        write(&f, path, &v);
        reseal(&mut f);
        rejects(&f, "metadata differs");
    }
}

#[test]
fn all_three_auxiliary_pins_precede_strict_parsing_and_duplicate_keys_fail() {
    for path in [MAP, CODEC, POLICY] {
        let f = fixture();
        let a = args(&f);
        fs::write(f.root.join(path), b"not json").unwrap();
        let e = run(a).unwrap_err();
        assert!(e.contains("SHA256 mismatch"), "{e}");
        assert!(!f.root.join("out").exists());
        let mut f = fixture();
        fs::write(f.root.join(path), br#"{"_meta":{},"_meta":{}}"#).unwrap();
        if path != POLICY {
            reseal(&mut f);
        }
        rejects(&f, "duplicate");
    }
    let f = fixture();
    let expected_branch = doc(&f, POLICY)["branch_codec"]["sha256"]
        .as_str()
        .unwrap()
        .to_owned();
    fs::remove_file(f.root.join(CODEC)).unwrap();
    let mut a = f.args();
    a.domain = Domain::SkillStatMap;
    a.codec = Some(CodecArgs {
        source: f.root.join(MAP),
        source_sha256: sha256_hex(&fs::read(f.root.join(MAP)).unwrap()),
        policy: f.root.join(POLICY),
        policy_sha256: sha256_hex(&fs::read(f.root.join(POLICY)).unwrap()),
    });
    a.branch_codec = Some(BranchCodecArgs {
        path: f.root.join(CODEC),
        sha256: expected_branch,
    });
    assert!(run(a).is_err());
    assert!(!f.root.join("out").exists());
}

#[test]
fn seven_file_replay_keeps_legacy_metadata_and_separates_target_provenance() {
    let f = fixture();
    run(args(&f)).unwrap();
    run(Args {
        out: f.root.join("again"),
        ..args(&f)
    })
    .unwrap();
    let r = read(&f, "producer-receipt.json");
    assert_eq!(r["complete_runtime"], false);
    assert_eq!(r["adoption"], "not-adopted");
    assert_eq!(r["files"].as_object().unwrap().len(), 6);
    assert_eq!(
        r["input"]["selected_payloads"].as_object().unwrap().len(),
        7
    );
    assert_eq!(
        read(&f, "_domain_candidate.json")["domain"],
        "ordinary-skill-stat-map"
    );
    assert_eq!(r["target"]["version"], "0.5.5.5");
    for absent in [
        "base",
        "manifest.json",
        "legacy-gem-effects.json",
        "quality-policy.json",
    ] {
        assert!(!f.root.join("out").join(absent).exists());
    }
    for (path, pin) in r["files"].as_object().unwrap() {
        let b = fs::read(f.root.join("out").join(path)).unwrap();
        assert_eq!(pin["sha256"], sha256_hex(&b));
        assert_eq!(pin["bytes"], b.len());
        assert_eq!(b, fs::read(f.root.join("again").join(path)).unwrap());
    }
    assert_eq!(
        fs::read(f.root.join("out/producer-receipt.json")).unwrap(),
        fs::read(f.root.join("again/producer-receipt.json")).unwrap()
    );
}

#[test]
fn cli_requires_all_pins_and_exclusively_accepts_branch_flags_for_map() {
    let base = [
        "--ordinary-facts",
        "F",
        "--facts-manifest-sha256",
        "pin",
        "--version",
        "0.5.5.5",
        "--out",
        "fresh",
        "--ordinary-domain",
        "skill-stat-map",
        "--codec-source",
        "map",
        "--codec-source-sha256",
        "sha",
        "--codec-policy",
        "policy",
        "--codec-policy-sha256",
        "sha",
        "--branch-codec",
        "branch",
        "--branch-codec-sha256",
        "sha",
    ];
    assert!(matches!(
        crate::parse_args_from(base.into_iter().map(String::from)),
        Ok(crate::Mode::OrdinaryFacts(_))
    ));
    for index in (10..base.len()).step_by(2) {
        let mut args = base.to_vec();
        args.drain(index..index + 2);
        assert!(parse_args(args.into_iter().map(String::from)).is_err());
    }
    for pair in [
        ["--branch-codec", "duplicate"],
        ["--branch-codec-sha256", "duplicate"],
        ["--ordinary-domain", "skill-stat-map"],
        ["--quality-policy", "p"],
        ["--quality-policy-sha256", "p"],
        ["--raw", "old"],
        ["--native-facts", "F"],
    ] {
        assert!(parse_args(base.into_iter().chain(pair).map(String::from)).is_err());
    }
    assert!(parse_args(base.into_iter().chain(["--branch-codec"]).map(String::from)).is_err());
    for domain in [
        "stats-mods",
        "base-items",
        "skills",
        "gem-quality",
        "stat-set-codec",
        "gem-effects",
        "monster-resistances",
        "totem-varieties",
        "monster-scaling",
    ] {
        for pair in [
            ["--branch-codec", "branch"],
            ["--branch-codec-sha256", "sha"],
        ] {
            let e = parse_args(
                base[..8]
                    .iter()
                    .copied()
                    .chain(["--ordinary-domain", domain])
                    .chain(pair)
                    .map(String::from),
            )
            .err()
            .unwrap();
            assert!(e.contains("branch codec arguments"), "{domain}: {e}");
        }
    }
}

#[test]
fn fresh_leaf_protects_all_auxiliary_parents_and_source_data_paths() {
    let f = fixture();
    for parent in ["map", "branch", "policy", "input"] {
        let out = f.root.join(parent).join("forbidden");
        assert!(
            run(Args {
                out: out.clone(),
                ..args(&f)
            })
            .is_err()
        );
        assert!(!out.exists());
    }
    let out = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../release")
        .canonicalize()
        .unwrap()
        .join(format!(
            "stat-map-forbidden-{}",
            f.root.file_name().unwrap().to_string_lossy()
        ));
    assert!(
        run(Args {
            out: out.clone(),
            ..args(&f)
        })
        .is_err()
    );
    assert!(!out.exists());
    for kind in ["pin", "patch"] {
        let mut a = args(&f);
        if kind == "pin" {
            a.expected_manifest_sha256 = "0".repeat(64);
        } else {
            a.version = "old".into();
        }
        assert!(run(a).is_err());
        assert!(!f.root.join("out").exists());
    }
    std::os::unix::fs::symlink(f.root.join("absent"), f.root.join("out")).unwrap();
    assert!(run(args(&f)).is_err());
    fs::remove_file(f.root.join("out")).unwrap();
    run(args(&f)).unwrap();
    let before = fs::read(f.root.join("out/producer-receipt.json")).unwrap();
    assert!(run(args(&f)).is_err());
    assert_eq!(
        before,
        fs::read(f.root.join("out/producer-receipt.json")).unwrap()
    );
    let f = fixture();
    let a = args(&f);
    fs::write(f.root.join("input/tables/Stats.json"), b"{}").unwrap();
    assert!(run(a).is_err());
    assert!(!f.root.join("out").exists());
}

#[test]
fn previous_non_quality_domains_keep_bytes_and_shared_codec_behavior() {
    for (domain, bytes, count) in [
        (Domain::StatsMods, None, 5),
        (
            Domain::BaseItems,
            Some(
                include_bytes!("../../../tests/fixtures/ordinary-facts/base-item-tables.json")
                    .as_slice(),
            ),
            4,
        ),
        (
            Domain::Skills,
            Some(
                include_bytes!("../../../tests/fixtures/ordinary-facts/skill-tables.json")
                    .as_slice(),
            ),
            9,
        ),
        (Domain::StatSetCodec, None, 5),
        (Domain::GemEffects, None, 6),
        (Domain::MonsterResistances, None, 4),
        (Domain::TotemVarieties, None, 4),
        (Domain::MonsterScaling, None, 4),
    ] {
        let mut f = match domain {
            Domain::StatSetCodec => super::super::stat_set_codec::tests::fixture(),
            Domain::GemEffects => super::super::gem_effects::tests::fixture(),
            Domain::MonsterResistances => super::super::monster_resistances::tests::fixture(),
            Domain::TotemVarieties => super::super::totem_varieties::tests::fixture(),
            Domain::MonsterScaling => super::super::monster_scaling::tests::fixture(),
            _ => Fixture::new(),
        };
        if let Some(bytes) = bytes {
            let t: BTreeMap<String, Value> = serde_json::from_slice(bytes).unwrap();
            f.documents.retain(|p, _| p == "source-lock.json");
            f.documents
                .extend(t.into_iter().map(|(t, d)| (format!("tables/{t}.json"), d)));
            f.seal();
        }
        let a = || match domain {
            Domain::StatSetCodec => super::super::stat_set_codec::tests::args(&f),
            Domain::GemEffects => super::super::gem_effects::tests::args(&f),
            _ => Args { domain, ..f.args() },
        };
        run(a()).unwrap();
        let new = fixture();
        run(args(&new)).unwrap();
        run(Args {
            out: f.root.join("again"),
            ..a()
        })
        .unwrap();
        let r = read(&f, "producer-receipt.json");
        assert_eq!(r.as_object().unwrap().len(), 10);
        assert_eq!(r["files"].as_object().unwrap().len(), count);
        assert!(!f.root.join("out/branch-codec.json").exists());
        for path in r["files"]
            .as_object()
            .unwrap()
            .keys()
            .map(String::as_str)
            .chain(["producer-receipt.json"])
        {
            assert_eq!(
                fs::read(f.root.join("out").join(path)).unwrap(),
                fs::read(f.root.join("again").join(path)).unwrap()
            );
        }
    }
    // The old archival codec still checks all owners; the new map checks only used scopes.
    let mut f = super::super::stat_set_codec::tests::fixture();
    f.values("GrantedEffects", 2)["StatSet"] = json!(999);
    f.seal();
    let mut p = doc(&f, "policy/policy.json");
    p["target"]["facts_manifest_sha256"] = f.args().expected_manifest_sha256.into();
    write(&f, "policy/policy.json", &p);
    assert!(run(super::super::stat_set_codec::tests::args(&f)).is_err());
    assert!(!f.root.join("out").exists());
}
