//! Rejections of the facts envelope verifier, on the synthetic `items-actors-bc` envelope.
//!
//! Each case changes one field and reseals every hash that does not belong to the
//! check under test, so the expected check (not an earlier pin) rejects it.

use std::path::{Path, PathBuf};

use serde_json::{Value, json};

use super::super::json_bytes;
use super::super::testing::Scratch;
use super::verify_selection;
use crate::raw_source::sha256_hex;

const SELECTED: &[&str] = &["Stats"];

struct Envelope {
    manifest: Value,
    lock: Value,
    stats: Value,
}

impl Envelope {
    fn new() -> Self {
        let bundle: Value = serde_json::from_slice(include_bytes!(
            "../../../tests/fixtures/native-facts/items-actors-bc-synthetic.json"
        ))
        .unwrap();
        Self {
            manifest: bundle["manifest"].clone(),
            lock: bundle["documents"]["source-lock.json"].clone(),
            stats: json!({"table":"Stats","rows":[]}),
        }
    }

    fn source(&mut self) -> &mut Value {
        &mut self.lock["sources"]["fixture"]
    }

    /// Write the envelope with consistent lock, selected-source and payload pins.
    fn write(&mut self, dir: &Path) -> (PathBuf, String) {
        let lock = json_bytes(&self.lock).unwrap();
        let identity = &mut self.manifest["source_identity"];
        identity["source_lock_sha256"] = json!(sha256_hex(&lock));
        identity["selected_source_sha256"] = json!(sha256_hex(
            &json_bytes(&self.lock["sources"]["fixture"]).unwrap()
        ));
        std::fs::create_dir_all(dir.join("tables")).unwrap();
        for (path, bytes) in [
            ("source-lock.json", lock),
            ("tables/Stats.json", json_bytes(&self.stats).unwrap()),
        ] {
            self.manifest["files"][path] =
                json!({"bytes": bytes.len(), "sha256": sha256_hex(&bytes)});
            std::fs::write(dir.join(path), bytes).unwrap();
        }
        let manifest = json_bytes(&self.manifest).unwrap();
        std::fs::write(dir.join("manifest.json"), &manifest).unwrap();
        (dir.join("source-lock.json"), sha256_hex(&manifest))
    }
}

fn verify(envelope: &mut Envelope) -> Result<(), String> {
    let scratch = Scratch::new();
    let (lock, pin) = envelope.write(&scratch.0);
    verify_selection(&scratch.0, &pin, &lock, SELECTED).map(|_| ())
}

#[test]
fn accepts_the_untampered_envelope_and_reads_only_the_selection() {
    let scratch = Scratch::new();
    let (lock, pin) = Envelope::new().write(&scratch.0);
    let facts = verify_selection(&scratch.0, &pin, &lock, SELECTED).unwrap();
    assert_eq!(
        facts.documents.keys().collect::<Vec<_>>(),
        ["source-lock.json", "tables/Stats.json"]
    );
    assert_eq!(facts.lock_bytes, std::fs::read(&lock).unwrap());
}

#[test]
fn producer_receipt_accepts_a_new_producer_and_requires_the_supported_schema() {
    let mut envelope = Envelope::new();
    envelope.manifest["producer"] = json!({"RePoE/native/facts.py":"a".repeat(64)});
    assert_eq!(
        verify(&mut envelope).unwrap_err(),
        "producer identity mismatch"
    );
    envelope.manifest["producer_receipt"] = json!("repoe-export-receipt/v1");
    verify(&mut envelope).unwrap();
    for value in [
        json!("repoe-export-receipt/v2"),
        Value::Null,
        json!(false),
        json!(1),
        json!([]),
        json!({}),
    ] {
        envelope.manifest["producer_receipt"] = value;
        assert_eq!(
            verify(&mut envelope).unwrap_err(),
            "unsupported producer_receipt"
        );
    }
    envelope.manifest["producer_receipt"] = json!("repoe-export-receipt/v1");
    envelope.manifest["extra"] = json!(true);
    assert_eq!(
        verify(&mut envelope).unwrap_err(),
        "unexpected or missing JSON object keys"
    );
}

#[test]
fn another_patch_must_match_the_target_version() {
    let scratch = Scratch::new();
    let mut envelope = Envelope::new();
    envelope.manifest["producer_receipt"] = json!("repoe-export-receipt/v1");
    envelope.manifest["producer"] = json!({"RePoE/native/facts.py":"a".repeat(64)});
    envelope.manifest["source_identity"]["game_patch"] = json!("0.5.5.8");
    envelope.source()["game_patch"] = json!("0.5.5.8");
    let (_, pin) = envelope.write(&scratch.0);
    let open = |version| super::super::reader::open(&scratch.0, &pin, version, SELECTED);
    let facts = open("0.5.5.8").unwrap();
    assert_eq!(facts.manifest["source_identity"]["game_patch"], "0.5.5.8");
    assert_eq!(
        open("9.9.9.9").err().unwrap(),
        "target version differs from facts game_patch"
    );
}

#[test]
fn rejects_each_changed_manifest_lock_and_payload_field() {
    type Change = fn(&mut Envelope);
    let cases: [(&str, Change); 25] = [
        ("invalid manifest profile", |e| {
            e.manifest["profile"] = json!("gems-constraints-a1")
        }),
        ("unexpected or missing JSON object keys", |e| {
            e.manifest.as_object_mut().unwrap().remove("summary");
        }),
        ("invalid manifest format", |e| {
            e.manifest["format"] = json!("repoe-native-facts/v3")
        }),
        ("invalid manifest status", |e| {
            e.manifest["status"] = json!("complete")
        }),
        ("never production_ready", |e| {
            e.manifest["production_ready"] = json!(true)
        }),
        ("invalid acquisition status", |e| {
            e.manifest["source_identity"]["acquisition"]["status"] = json!("approved")
        }),
        ("empty acquisition evidence", |e| {
            e.manifest["source_identity"]["acquisition"]["evidence"] = json!([])
        }),
        ("source-lock game_patch mismatch", |e| {
            e.manifest["source_identity"]["game_patch"] = json!("0.5.5.4")
        }),
        ("producer identity mismatch", |e| {
            e.manifest["producer"]["RePoE/native_items.py"] = json!("0".repeat(64))
        }),
        ("schema identity mismatch", |e| {
            e.manifest["schema"]["sha256"] = json!("0".repeat(64))
        }),
        ("decoder identity mismatch", |e| {
            e.manifest["decoder"]["pypoe_revision"] = json!("0".repeat(40))
        }),
        ("decoder source fingerprint mismatch: __init__.py", |e| {
            e.manifest["decoder"]["sources"]["__init__.py"] = json!("0".repeat(64))
        }),
        ("unsupported source-lock schema", |e| {
            e.lock["schema_version"] = json!(2)
        }),
        ("source-lock profile mismatch", |e| {
            e.source()["profile"] = json!("gems-constraints-a1")
        }),
        ("source-lock acquisition mismatch", |e| {
            e.source()["acquisition"]["status"] = json!("reviewed-source-input")
        }),
        ("source-lock game mismatch", |e| {
            e.source()["game"] = json!("poe1")
        }),
        ("source-lock decoder revision mismatch", |e| {
            e.source()["decoder"]["revision"] = json!("0".repeat(40))
        }),
        ("unexpected or missing JSON object keys", |e| {
            let resources = e.source()["resources"].as_object_mut().unwrap();
            resources.remove("Data/Balance/Stats.datc64");
        }),
        (
            "raw resource Data/Balance/Stats.datc64 bytes mismatch",
            |e| e.source()["resources"]["Data/Balance/Stats.datc64"]["bytes"] = json!(1),
        ),
        (
            "raw resource Metadata/PassiveSkillGraph.psg sha256 mismatch",
            |e| {
                e.manifest["source_identity"]["raw_resources"]["Metadata/PassiveSkillGraph.psg"]["sha256"] =
                    json!("0".repeat(64))
            },
        ),
        ("invalid positive byte size", |e| {
            for raw in [
                &mut e.manifest["source_identity"]["raw_resources"],
                &mut e.lock["sources"]["fixture"]["resources"],
            ] {
                raw["Data/Balance/Stats.datc64"]["bytes"] = json!(0);
            }
        }),
        ("unexpected or missing JSON object keys", |e| {
            let files = e.manifest["files"].as_object_mut().unwrap();
            files.remove("tables/Mods.json");
        }),
        ("source-lock bytes mismatch", |e| {
            // A changed lock under the original lock pin.
            e.lock["sources"]["unrelated"] = json!({});
            e.manifest["files"]["force-stale-lock-pin"] = json!(true);
        }),
        ("selected source-lock entry mismatch", |e| {
            e.manifest["files"]["force-stale-source-pin"] = json!(true);
        }),
        ("invalid lowercase sha256", |e| {
            e.manifest["source_identity"]["acquisition"]["evidence"][0]["sha256"] =
                json!("A".repeat(64));
            e.source()["acquisition"]["evidence"][0]["sha256"] = json!("A".repeat(64));
        }),
    ];
    for (expected, change) in cases {
        let mut envelope = Envelope::new();
        change(&mut envelope);
        let error = verify_stale_aware(&mut envelope).err().unwrap();
        assert!(error.contains(expected), "{expected}: got {error}");
    }
}

/// `write` reseals the lock and selected-source pins; the two cases that test
/// those pins mark the manifest so that the stale pin is restored afterwards.
fn verify_stale_aware(envelope: &mut Envelope) -> Result<(), String> {
    let files = envelope.manifest["files"].as_object_mut().unwrap();
    let stale_lock = files.remove("force-stale-lock-pin").is_some();
    let stale_source = files.remove("force-stale-source-pin").is_some();
    if !stale_lock && !stale_source {
        return verify(envelope);
    }
    let scratch = Scratch::new();
    let original = envelope.manifest["source_identity"].clone();
    let (lock, _) = envelope.write(&scratch.0);
    let identity = &mut envelope.manifest["source_identity"];
    if stale_lock {
        identity["source_lock_sha256"] = original["source_lock_sha256"].clone();
    }
    if stale_source {
        identity["selected_source_sha256"] = json!("0".repeat(64));
    }
    let manifest = json_bytes(&envelope.manifest).unwrap();
    std::fs::write(scratch.0.join("manifest.json"), &manifest).unwrap();
    verify_selection(&scratch.0, &sha256_hex(&manifest), &lock, SELECTED).map(|_| ())
}

#[test]
fn rejects_wrong_pins_payloads_embedded_lock_and_selection() {
    // External manifest pin.
    let scratch = Scratch::new();
    let (lock, _) = Envelope::new().write(&scratch.0);
    let error = verify_selection(&scratch.0, &"0".repeat(64), &lock, SELECTED)
        .err()
        .unwrap();
    assert!(
        error.contains("external manifest sha256 mismatch"),
        "{error}"
    );
    assert!(
        verify_selection(&scratch.0, "not-a-sha", &lock, SELECTED)
            .err()
            .unwrap()
            .contains("invalid lowercase sha256")
    );

    // Adding the field cannot turn a package under its historical pin into a receipted export.
    let mut envelope = Envelope::new();
    let (lock, historical_pin) = envelope.write(&scratch.0);
    envelope.manifest["producer_receipt"] = json!("repoe-export-receipt/v1");
    envelope.write(&scratch.0);
    assert_eq!(
        verify_selection(&scratch.0, &historical_pin, &lock, SELECTED)
            .err()
            .unwrap(),
        "external manifest sha256 mismatch"
    );

    // A payload changed after sealing.
    let scratch = Scratch::new();
    let (lock, pin) = Envelope::new().write(&scratch.0);
    std::fs::write(scratch.0.join("tables/Stats.json"), b"{}\n").unwrap();
    let error = verify_selection(&scratch.0, &pin, &lock, SELECTED)
        .err()
        .unwrap();
    assert!(
        error.contains("payload fingerprint mismatch: tables/Stats.json"),
        "{error}"
    );

    // The embedded lock differs from the external lock the manifest pins.
    let scratch = Scratch::new();
    let mut envelope = Envelope::new();
    let (embedded, _) = envelope.write(&scratch.0);
    let external = scratch.0.join("external-lock.json");
    let mut bytes = std::fs::read(&embedded).unwrap();
    bytes.insert(0, b' ');
    std::fs::write(&external, &bytes).unwrap();
    envelope.manifest["source_identity"]["source_lock_sha256"] = json!(sha256_hex(&bytes));
    let manifest = json_bytes(&envelope.manifest).unwrap();
    std::fs::write(scratch.0.join("manifest.json"), &manifest).unwrap();
    let error = verify_selection(&scratch.0, &sha256_hex(&manifest), &external, SELECTED)
        .err()
        .unwrap();
    assert!(
        error.contains("embedded source-lock bytes mismatch"),
        "{error}"
    );

    // Selections outside the profile, empty or repeated.
    let scratch = Scratch::new();
    let (lock, pin) = Envelope::new().write(&scratch.0);
    for selected in [&["NotATable"][..], &[], &["Stats", "Stats"]] {
        let error = verify_selection(&scratch.0, &pin, &lock, selected)
            .err()
            .unwrap();
        assert!(
            error.contains("invalid selected physical tables"),
            "{error}"
        );
    }
}
