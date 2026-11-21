//! Portable synthetic source-boundary regressions; no real client archive is required.
//!
//! `player-synthetic.json` is a synthetic player package and sparse parent fixture. It
//! keeps the 99 real metadata key names, but its metadata, resources, physical rows,
//! glossary and bonus are not client or gameplay evidence.

use std::collections::BTreeMap;

use pobr_data::catalog::native_player::*;
use serde_json::{Value, json};

use super::super::testing::Scratch;
use super::super::{json_bytes, player, trust};
use crate::raw_source::sha256_hex;

fn fixture() -> (NativePlayerContextDef, trust::VerifiedInput) {
    let fixture: Value = serde_json::from_slice(include_bytes!(
        "../../../tests/fixtures/native-facts/player-synthetic.json"
    ))
    .unwrap();
    let context = serde_json::from_value(fixture["context"].clone()).unwrap();
    let mut documents = BTreeMap::new();
    for (path, selected) in fixture["parent_rows"].as_object().unwrap() {
        let mut rows = Vec::new();
        for (i, values) in selected.as_object().unwrap() {
            let i = i.parse::<usize>().unwrap();
            rows.resize(rows.len().max(i + 1), json!({"values":{}}));
            rows[i] = json!({"values":values});
        }
        for (i, row) in rows.iter_mut().enumerate() {
            row["_row"] = i.into();
        }
        documents.insert(path.clone(),json!({"table":path.trim_start_matches("tables/").trim_end_matches(".json"),"rows":rows}));
    }
    let manifest = fixture["parent_manifest"].clone();
    let input = trust::VerifiedInput {
        manifest_bytes: pretty(&manifest),
        manifest,
        lock_bytes: fixture["parent_lock"].as_str().unwrap().as_bytes().to_vec(),
        bytes: BTreeMap::new(),
        documents,
    };
    (context, input)
}

fn pretty(value: &Value) -> Vec<u8> {
    let mut b = serde_json::to_vec_pretty(value).unwrap();
    b.push(b'\n');
    b
}

fn package(c: &NativePlayerContextDef) -> (Scratch, player::Args) {
    let scratch = Scratch::new();
    for (name, text) in &c.source_archive {
        std::fs::write(scratch.0.join(name), text).unwrap();
    }
    let args = player::Args {
        root: scratch.0.clone(),
        manifest_sha256: c.source_manifest_sha256.clone(),
        source_lock_sha256: c.source_lock_sha256.clone(),
    };
    (scratch, args)
}

#[test]
fn player_package_pins_inventory_and_separate_parent_are_required() {
    let (c, parent) = fixture();
    let (_scratch, mut args) = package(&c);
    assert_eq!(player::verify(&args, &parent).unwrap().context, c);
    args.manifest_sha256 = "0".repeat(64);
    assert!(
        player::verify(&args, &parent)
            .err()
            .unwrap()
            .contains("sha256 mismatch")
    );
    args.manifest_sha256 = c.source_manifest_sha256.clone();
    args.source_lock_sha256 = "0".repeat(64);
    assert!(
        player::verify(&args, &parent)
            .err()
            .unwrap()
            .contains("source lock mismatch")
    );
    args.source_lock_sha256 = c.source_lock_sha256.clone();
    let mut changed_parent = parent;
    changed_parent.manifest_bytes.push(b' ');
    assert!(
        player::verify(&args, &changed_parent)
            .err()
            .unwrap()
            .contains("parent mismatch")
    );
    std::fs::write(args.root.join("extra.json"), b"{}").unwrap();
    assert!(
        player::verify(&args, &changed_parent)
            .err()
            .unwrap()
            .contains("inventory")
    );
}

#[test]
fn player_producer_receipt_accepts_a_new_producer_and_requires_the_supported_schema() {
    let (c, parent) = fixture();
    let (_scratch, mut args) = package(&c);
    for (field, expected) in [
        (None, Some("player producer identity mismatch")),
        (Some(json!("repoe-export-receipt/v1")), None),
        (
            Some(json!("repoe-export-receipt/v2")),
            Some("unsupported producer_receipt"),
        ),
        (Some(Value::Null), Some("unsupported producer_receipt")),
    ] {
        let mut m: Value = serde_json::from_str(&c.source_archive["manifest.json"]).unwrap();
        m["producer"] = json!({"RePoE/native/player.py":"a".repeat(64)});
        if let Some(value) = field {
            m["producer_receipt"] = value;
        }
        let bytes = json_bytes(&m).unwrap();
        args.manifest_sha256 = sha256_hex(&bytes);
        std::fs::write(args.root.join("manifest.json"), bytes).unwrap();
        let result = player::verify(&args, &parent);
        if let Some(error) = expected {
            assert_eq!(result.err().unwrap(), error);
        } else {
            assert_eq!(result.unwrap().context.facts, c.facts);
        }
    }
}

#[test]
fn another_player_patch_must_match_the_verified_parent() {
    for patch in ["0.5.5.8", "9.9.9.9"] {
        let (mut c, mut parent) = fixture();
        parent.manifest["source_identity"]["game_patch"] = json!("0.5.5.8");
        parent.manifest_bytes = pretty(&parent.manifest);

        let mut m: Value = serde_json::from_str(&c.source_archive["manifest.json"]).unwrap();
        m["producer_receipt"] = json!("repoe-export-receipt/v1");
        m["producer"] = json!({"RePoE/native/player.py":"a".repeat(64)});
        let mut lock: Value = serde_json::from_str(&c.source_archive["source-lock.json"]).unwrap();
        let source = m["source_identity"]["source"].as_str().unwrap().to_owned();
        lock["sources"][&source]["game_patch"] = json!(patch);
        let lock_bytes = json_bytes(&lock).unwrap();
        c.source_lock_sha256 = sha256_hex(&lock_bytes);
        m["source_identity"]["game_patch"] = json!(patch);
        m["source_identity"]["source_lock_sha256"] = json!(c.source_lock_sha256);
        m["source_identity"]["selected_source_sha256"] =
            json!(sha256_hex(&json_bytes(&lock["sources"][&source]).unwrap()));
        m["parent"]["manifest_sha256"] = json!(sha256_hex(&parent.manifest_bytes));
        m["parent"]["source_identity"] = parent.manifest["source_identity"].clone();
        for (name, bytes) in [
            ("parent-manifest.json", parent.manifest_bytes.clone()),
            ("source-lock.json", lock_bytes),
        ] {
            m["files"][name] = json!({"bytes":bytes.len(),"sha256":sha256_hex(&bytes)});
            c.source_archive
                .insert(name.into(), String::from_utf8(bytes).unwrap());
        }
        let bytes = json_bytes(&m).unwrap();
        c.source_manifest_sha256 = sha256_hex(&bytes);
        c.source_archive
            .insert("manifest.json".into(), String::from_utf8(bytes).unwrap());
        let (_scratch, args) = package(&c);
        let result = player::verify(&args, &parent);
        if patch == "0.5.5.8" {
            assert_eq!(result.unwrap().context.game_patch, patch);
        } else {
            assert_eq!(result.err().unwrap(), "player/parent game_patch mismatch");
        }
    }
}

#[test]
fn player_manifest_checks_fixed_all14_producer_and_117_decoder_sources() {
    let (c, parent) = fixture();
    for pointer in [
        "/producer/RePoE~1native_player.py",
        "/producer/RePoE~1native_metadata.py",
        "/decoder/sources/poe~1file~1dat.py",
        "/source_identity/realm",
        "/source_identity/game_patch",
    ] {
        let (scratch, mut args) = package(&c);
        let mut m: Value = serde_json::from_str(&c.source_archive["manifest.json"]).unwrap();
        *m.pointer_mut(pointer).unwrap() = "wrong".into();
        let bytes = json_bytes(&m).unwrap();
        args.manifest_sha256 = sha256_hex(&bytes);
        std::fs::write(scratch.0.join("manifest.json"), bytes).unwrap();
        assert!(
            player::verify(&args, &parent).is_err(),
            "accepted {pointer}"
        );
    }
}

#[test]
fn player_all_physical_projections_reject_origin_row_id_and_metadata_drift() {
    let (c, parent) = fixture();
    player::validate_projection(&c, &parent).unwrap();
    for pointer in [
        "/facts/character/source/origin",
        "/facts/starting_relation/options/0/origin",
        "/facts/all_starting_relations/2/options/0/id",
        "/facts/metadata_stats/0/stat/pointer",
        "/facts/metadata_stats/0/value_raw",
        "/facts/character/values/BaseIntelligence",
    ] {
        let mut v = serde_json::to_value(&c).unwrap();
        *v.pointer_mut(pointer).expect("fixture source selector") = if pointer.ends_with("/origin")
        {
            json!("player")
        } else {
            json!("changed")
        };
        let changed: Result<NativePlayerContextDef, _> = serde_json::from_value(v);
        assert!(
            changed.is_err() || player::validate_projection(&changed.unwrap(), &parent).is_err(),
            "accepted {pointer}"
        );
    }
    let mut changed = c.clone();
    changed
        .metadata
        .files
        .get_mut(NATIVE_GENERIC_OT)
        .unwrap()
        .assignments[0]
        .value_byte_start += 2;
    assert!(player::validate_projection(&changed, &parent).is_err());
    let mut changed = parent;
    changed.documents.get_mut("tables/Characters.json").unwrap()["rows"][7]["values"]["StartingPassive"] =
        1.into();
    assert!(player::validate_projection(&c, &changed).is_err());
}

#[test]
fn player_payload_missing_mutated_and_nonregular_files_fail_before_projection() {
    let (c, parent) = fixture();
    for mode in [0, 1, 2] {
        let (scratch, args) = package(&c);
        let path = scratch.0.join("StartingPassiveSkills.json");
        if mode == 0 {
            std::fs::remove_file(&path).unwrap();
        } else if mode == 1 {
            std::fs::write(&path, b"[]").unwrap();
        } else {
            std::fs::remove_file(&path).unwrap();
            std::fs::create_dir(&path).unwrap();
        }
        assert!(
            player::verify(&args, &parent).is_err(),
            "accepted invalid payload mode {mode}"
        );
    }
    let mut c = c;
    c.starting_passive_skills.rows[0].row = 1;
    assert!(
        player::validate_projection(&c, &parent)
            .unwrap_err()
            .contains("physical row/order")
    );
}

fn synthetic_metadata_file(
    path: &str,
    extends_literal: &str,
    extends_target: Option<&str>,
    stats: &[(&str, &str)],
) -> (NativeMetadataFile, Vec<u8>) {
    let mut raw_bytes = vec![0xffu8, 0xfe];
    let mut records = Vec::new();
    let mut assignments = Vec::new();
    let mut push_line = |literal: &str, scope: Value| -> (usize, usize, usize) {
        let line = records.len() + 1;
        let byte_start = raw_bytes.len();
        raw_bytes.extend(literal.encode_utf16().flat_map(u16::to_le_bytes));
        raw_bytes.extend("\r\n".encode_utf16().flat_map(u16::to_le_bytes));
        let byte_end = raw_bytes.len();
        records.push(json!({
            "line": line,
            "byte_start": byte_start,
            "byte_end": byte_end,
            "literal": literal,
            "scope": scope,
        }));
        (line, byte_start, byte_end)
    };
    push_line("version 3", json!([]));
    let (extends_line, _, _) = push_line(&format!("extends \"{extends_literal}\""), json!([]));
    if !stats.is_empty() {
        push_line("Stats", json!([]));
        let (open_line, _, _) = push_line("{", json!([]));
        let scope = json!([{"id": 1, "name_raw": "Stats", "open_line": open_line}]);
        for &(key, value) in stats {
            let prefix = format!("\t{key} = ");
            let literal = format!("{prefix}{value}");
            let (line, byte_start, _) = push_line(&literal, scope.clone());
            let value_byte_start = byte_start + prefix.encode_utf16().count() * 2;
            let value_byte_end = value_byte_start + value.encode_utf16().count() * 2;
            assignments.push(json!({
                "key_raw": key,
                "value_raw": value,
                "line": line,
                "scope": scope,
                "plain_stats_scope": true,
                "value_byte_start": value_byte_start,
                "value_byte_end": value_byte_end,
            }));
        }
        push_line("}", json!([]));
    }
    let file: NativeMetadataFile = serde_json::from_value(json!({
        "format": "repoe-native-metadata-lines/v1",
        "path": path,
        "bytes": raw_bytes.len(),
        "encoding": "BOM UTF-16LE",
        "merge_policy": "none; ordered lexical records only",
        "extends": [{
            "line": extends_line,
            "literal": extends_literal,
            "target": extends_target,
        }],
        "records": records,
        "assignments": assignments,
        "diagnostics": [],
    }))
    .unwrap();
    (file, raw_bytes)
}

#[test]
fn shifted_non_0555_player_context_and_reviewed_acquisition_validate_cleanly() {
    let (mut c, mut parent) = fixture();
    let patch = "0.6.0.0";
    let character_row = 11usize;
    let selected_start = 0usize;
    let acquisition = json!({
        "status": "reviewed-source-input",
        "evidence": [{
            "kind": "reviewed-client-capture",
            "sha256": "1".repeat(64),
        }],
    });

    parent.manifest["source_identity"]["game_patch"] = json!(patch);
    parent.manifest["source_identity"]["acquisition"] = acquisition.clone();
    parent.manifest_bytes = pretty(&parent.manifest);

    // Shift IntFourb from row 7 to row 11 with StartingPassive = 0.
    let mut character_values =
        parent.documents["tables/Characters.json"]["rows"][7]["values"].clone();
    character_values["StartingPassive"] = json!(selected_start);
    let mut char_rows = Vec::new();
    for i in 0..=character_row {
        let values = if i == character_row {
            character_values.clone()
        } else {
            json!({"Id": format!("Metadata/Characters/Dummy{i}")})
        };
        char_rows.push(json!({"_row": i, "values": values}));
    }
    parent.documents.insert(
        "tables/Characters.json".into(),
        json!({"table": "Characters", "rows": char_rows}),
    );

    // Shift PassiveSkills rows to [10, 20, 30] instead of [2779, 1146].
    let mut passive_rows = Vec::new();
    for i in 0..=30 {
        let values = match i {
            10 => json!({"Id": "shifted_start_a"}),
            20 => json!({"Id": "shifted_start_b"}),
            30 => json!({"Id": "shifted_start_c"}),
            _ => json!({}),
        };
        passive_rows.push(json!({"_row": i, "values": values}));
    }
    parent.documents.insert(
        "tables/PassiveSkills.json".into(),
        json!({"table": "PassiveSkills", "rows": passive_rows}),
    );

    // Include one override for another character (row 0 -> char 1) and one for shifted char 11 (row 1 -> char 11).
    parent.documents.insert(
        "tables/ClassPassiveSkillOverrides.json".into(),
        json!({
            "table": "ClassPassiveSkillOverrides",
            "rows": [
                {"_row": 0, "values": {"CharacterToOverrideFor": 1}},
                {"_row": 1, "values": {"CharacterToOverrideFor": character_row}},
            ],
        }),
    );

    // Use 3 starting rows (5 total options) instead of 6 rows (12 total options).
    let mut starting_doc = serde_json::to_value(&c.starting_passive_skills).unwrap();
    starting_doc["rows"] = json!([
        {"_row": 0, "values": {"Id": "ShiftedStart0", "PassiveSkills": [10, 20, 30]}},
        {"_row": 1, "values": {"Id": "ShiftedStart1", "PassiveSkills": [10]}},
        {"_row": 2, "values": {"Id": "ShiftedStart2", "PassiveSkills": [20]}},
    ]);
    starting_doc["validation"]["rows"] = json!(3);
    c.starting_passive_skills = serde_json::from_value(starting_doc.clone()).unwrap();

    // Use 2 plain Stats assignments (instead of 99) backed by shifted Stats rows 3 and 4.
    parent.documents.insert(
        "tables/Stats.json".into(),
        json!({
            "table": "Stats",
            "rows": [
                {"_row": 0, "values": {"Id": "dummy_stat_0"}},
                {"_row": 1, "values": {"Id": "dummy_stat_1"}},
                {"_row": 2, "values": {"Id": "dummy_stat_2"}},
                {"_row": 3, "values": {"Id": "base_critical_hit_damage_bonus"}},
                {"_row": 4, "values": {"Id": "base_maximum_life"}},
            ],
        }),
    );

    let metadata_specs = [
        (
            NATIVE_PLAYER_AO,
            "Metadata/Characters/Character",
            Some("Metadata/Characters/Character.ao"),
            &[][..],
        ),
        (
            "Metadata/Characters/Character.ao",
            "Metadata/Parent",
            Some("Metadata/Parent.ao"),
            &[][..],
        ),
        ("Metadata/Parent.ao", "nothing", None, &[][..]),
        (
            NATIVE_GENERIC_OT,
            "nothing",
            None,
            &[
                ("base_critical_hit_damage_bonus", "100"),
                ("base_maximum_life", "28"),
            ][..],
        ),
    ];
    let mut metadata_files = BTreeMap::new();
    let mut raw_metadata_pins = BTreeMap::new();
    for (path, ext_lit, ext_target, stats) in metadata_specs {
        let (file, raw_bytes) = synthetic_metadata_file(path, ext_lit, ext_target, stats);
        raw_metadata_pins.insert(
            path.to_owned(),
            json!({"bytes": raw_bytes.len(), "sha256": sha256_hex(&raw_bytes)}),
        );
        metadata_files.insert(path.to_owned(), file);
    }
    c.metadata.files = metadata_files;

    let parent_ref = |table: &str, row: usize, id: Option<&str>| -> NativePlayerReference {
        NativePlayerReference {
            origin: NativePlayerOrigin::Parent,
            table: table.into(),
            row,
            id: id.map(String::from),
            payload: format!("tables/{table}.json"),
            pointer: format!("/rows/{row}/values"),
        }
    };
    let player_ref = |table: &str, row: usize, id: Option<&str>| -> NativePlayerReference {
        NativePlayerReference {
            origin: NativePlayerOrigin::Player,
            table: table.into(),
            row,
            id: id.map(String::from),
            payload: format!("{table}.json"),
            pointer: format!("/rows/{row}/values"),
        }
    };

    c.game_patch = patch.into();
    c.facts.character.source = parent_ref("Characters", character_row, Some(NATIVE_PLAYER_ID));
    c.facts.character.values = serde_json::from_value(character_values).unwrap();
    c.facts.all_starting_relations = vec![
        NativeStartingRelation {
            source: player_ref("StartingPassiveSkills", 0, Some("ShiftedStart0")),
            options: vec![
                parent_ref("PassiveSkills", 10, Some("shifted_start_a")),
                parent_ref("PassiveSkills", 20, Some("shifted_start_b")),
                parent_ref("PassiveSkills", 30, Some("shifted_start_c")),
            ],
        },
        NativeStartingRelation {
            source: player_ref("StartingPassiveSkills", 1, Some("ShiftedStart1")),
            options: vec![parent_ref("PassiveSkills", 10, Some("shifted_start_a"))],
        },
        NativeStartingRelation {
            source: player_ref("StartingPassiveSkills", 2, Some("ShiftedStart2")),
            options: vec![parent_ref("PassiveSkills", 20, Some("shifted_start_b"))],
        },
    ];
    c.facts.starting_relation = c.facts.all_starting_relations[selected_start].clone();
    c.facts.selected_class_overrides = vec![parent_ref("ClassPassiveSkillOverrides", 1, None)];
    let stats_scope = c.metadata.files[NATIVE_GENERIC_OT].assignments[0]
        .scope
        .clone();
    c.facts.metadata_stats = vec![
        NativePlayerMetadataStat {
            path: NATIVE_GENERIC_OT.into(),
            assignment: 0,
            key_raw: "base_critical_hit_damage_bonus".into(),
            value_raw: "100".into(),
            scope: stats_scope.clone(),
            stat: Some(parent_ref(
                "Stats",
                3,
                Some("base_critical_hit_damage_bonus"),
            )),
        },
        NativePlayerMetadataStat {
            path: NATIVE_GENERIC_OT.into(),
            assignment: 1,
            key_raw: "base_maximum_life".into(),
            value_raw: "28".into(),
            scope: stats_scope,
            stat: Some(parent_ref("Stats", 4, Some("base_maximum_life"))),
        },
    ];

    let mut m: Value = serde_json::from_str(&c.source_archive["manifest.json"]).unwrap();
    m["producer_receipt"] = json!("repoe-export-receipt/v1");
    m["producer"] = json!({"RePoE/native/player.py": "a".repeat(64)});
    let mut lock: Value = serde_json::from_str(&c.source_archive["source-lock.json"]).unwrap();
    let source = m["source_identity"]["source"].as_str().unwrap().to_owned();
    lock["sources"][&source]["game_patch"] = json!(patch);
    lock["sources"][&source]["acquisition"] = acquisition.clone();
    for (path, fp) in &raw_metadata_pins {
        lock["sources"][&source]["resources"][path] = fp.clone();
        m["source_identity"]["raw_resources"][path] = fp.clone();
    }
    let lock_bytes = json_bytes(&lock).unwrap();
    c.source_lock_sha256 = sha256_hex(&lock_bytes);
    m["source_identity"]["game_patch"] = json!(patch);
    m["source_identity"]["acquisition"] = acquisition;
    m["source_identity"]["source_lock_sha256"] = json!(c.source_lock_sha256);
    m["source_identity"]["selected_source_sha256"] =
        json!(sha256_hex(&json_bytes(&lock["sources"][&source]).unwrap()));
    m["parent"]["manifest_sha256"] = json!(sha256_hex(&parent.manifest_bytes));
    m["parent"]["source_identity"] = parent.manifest["source_identity"].clone();

    let starting_bytes = json_bytes(&starting_doc).unwrap();
    let metadata_bytes = json_bytes(&serde_json::to_value(&c.metadata).unwrap()).unwrap();
    let facts_bytes = json_bytes(&serde_json::to_value(&c.facts).unwrap()).unwrap();
    for (name, bytes) in [
        ("StartingPassiveSkills.json", starting_bytes),
        ("metadata.json", metadata_bytes),
        ("player_context.json", facts_bytes),
        ("parent-manifest.json", parent.manifest_bytes.clone()),
        ("source-lock.json", lock_bytes),
    ] {
        m["files"][name] = json!({"bytes": bytes.len(), "sha256": sha256_hex(&bytes)});
        c.source_archive
            .insert(name.into(), String::from_utf8(bytes).unwrap());
    }
    let manifest_bytes = json_bytes(&m).unwrap();
    c.source_manifest_sha256 = sha256_hex(&manifest_bytes);
    c.source_archive.insert(
        "manifest.json".into(),
        String::from_utf8(manifest_bytes).unwrap(),
    );

    let (_scratch, args) = package(&c);
    let verified = player::verify(&args, &parent).unwrap();
    assert_eq!(verified.context.game_patch, patch);
    assert_eq!(verified.context.facts.character.source.row, character_row);
    assert_eq!(verified.context.facts.all_starting_relations.len(), 3);
    assert_eq!(verified.context.facts.selected_class_overrides.len(), 1);
    assert_eq!(verified.context.facts.metadata_stats.len(), 2);

    // Wrong or missing class override for the shifted character row must fail.
    let mut wrong_override = verified.context.clone();
    wrong_override.facts.selected_class_overrides.clear();
    assert!(player::validate_projection(&wrong_override, &parent).is_err());
    wrong_override.facts.selected_class_overrides =
        vec![parent_ref("ClassPassiveSkillOverrides", 0, None)];
    assert!(player::validate_projection(&wrong_override, &parent).is_err());

    // Unsupported acquisition status must still fail.
    let (bad_scratch, mut bad_args) = package(&c);
    let mut bad_m = m;
    bad_m["source_identity"]["acquisition"]["status"] = json!("approved");
    let bad_bytes = json_bytes(&bad_m).unwrap();
    bad_args.manifest_sha256 = sha256_hex(&bad_bytes);
    std::fs::write(bad_scratch.0.join("manifest.json"), bad_bytes).unwrap();
    assert_eq!(
        player::verify(&bad_args, &parent).err().unwrap(),
        "invalid acquisition status"
    );
}

#[test]
fn payload_u64_max_size_returns_error_without_overflow() {
    let (c, parent) = fixture();
    for (target_file, bad_size) in [
        ("StartingPassiveSkills.json", json!(u64::MAX)),
        ("KeywordPopups.json", json!(u64::MAX)),
        ("StartingPassiveSkills.json", json!(0)),
    ] {
        let (scratch, mut args) = package(&c);
        let mut m: Value = serde_json::from_str(&c.source_archive["manifest.json"]).unwrap();
        m["files"][target_file]["bytes"] = bad_size;
        let bytes = json_bytes(&m).unwrap();
        args.manifest_sha256 = sha256_hex(&bytes);
        std::fs::write(scratch.0.join("manifest.json"), bytes).unwrap();
        assert_eq!(
            player::verify(&args, &parent).err().unwrap(),
            "player payload byte limit",
            "expected byte-limit error for {target_file}"
        );
    }
}
