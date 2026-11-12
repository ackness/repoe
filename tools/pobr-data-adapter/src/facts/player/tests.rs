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
