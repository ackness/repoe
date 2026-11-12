use super::*;
use crate::ordinary_facts::coverage::AdapterMode;
use serde_json::{Value, json};

fn effects() -> Vec<IndexedId> {
    rows(json!([{"_index": 9, "Id": "TestSkill"}, {"_index": 42, "Id": "UnreviewedSkill"}]))
}

fn stats() -> Vec<IndexedId> {
    rows(json!([{"_index": 11, "Id": "damage"}, {"_index": 3, "Id": "cost"}]))
}

fn quality() -> Value {
    json!([
        {"GrantedEffect": 9, "Stats": [11, 3, 11], "StatsValuesPermille": [550, -50, 250],
         "ApplyToStatSets": [0, 2], "AltStats": [3], "AltStatValuesPermille": [100], "AltApplyToStatSets": [1]},
        {"GrantedEffect": 42, "Stats": [11], "StatsValuesPermille": [1000],
         "ApplyToStatSets": [], "AltStats": [], "AltStatValuesPermille": [], "AltApplyToStatSets": []}
    ])
}

fn compatibility() -> Value {
    json!({
        "reference_vendor_commit":"synthetic", "reference_sha256":"synthetic",
        "scope_policy":"preserve_effect_wide_quality", "effects":["TestSkill"],
        "excluded_effects":{"UnreviewedSkill":"Not supported by the fixture"}
    })
}

fn rows<T: for<'de> Deserialize<'de>>(value: Value) -> T {
    serde_json::from_value(value).unwrap()
}

fn convert(quality: Value, compatibility: Value) -> Result<Converted, String> {
    let effects = index(effects(), "GrantedEffects")?;
    let stats = index(stats(), "Stats")?;
    convert_rows(
        &effects,
        &stats,
        rows(quality),
        &rows(compatibility),
        &mut Coverage::new(AdapterMode::Strict, "gem-quality"),
    )
}

#[test]
fn resolves_sparse_ids_preserves_order_duplicates_alt_and_scope_diagnostics() {
    let converted = convert(quality(), compatibility()).unwrap();
    assert_eq!(
        serde_json::to_value(&converted.effects).unwrap(),
        json!([{"effect_id":"TestSkill","stats":[
            {"stat":"damage","per_quality_rate":0.55},
            {"stat":"cost","per_quality_rate":-0.05},
            {"stat":"damage","per_quality_rate":0.25},
            {"stat":"cost","per_quality_rate":0.1,"alt":true}
        ]}])
    );
    assert_eq!(
        serde_json::to_value(&converted.scopes["TestSkill"]).unwrap(),
        json!({"main":[0,2],"alt":[1]})
    );
}

#[test]
fn reviewed_inputs_still_require_valid_relationships_and_complete_scope() {
    for (field, value, error) in [
        ("Stats", json!([11]), "length mismatch"),
        ("Stats", json!([11, 999, 11]), "dangling stat"),
        ("GrantedEffect", json!(999), "dangling GrantedEffect"),
        ("AltStatValuesPermille", json!([]), "length mismatch"),
    ] {
        let mut rows = quality();
        rows[0][field] = value;
        let error_text = convert(rows, compatibility()).err().unwrap();
        assert!(error_text.contains(error), "{field}: {error_text}");
    }
    let mut source = compatibility();
    source["excluded_effects"] = json!({});
    assert!(
        convert(quality(), source.clone())
            .err()
            .unwrap()
            .contains("no reviewed compatibility decision")
    );
    source["excluded_effects"] = json!({"UnreviewedSkill":"pending","RemovedSkill":"pending"});
    assert!(
        convert(quality(), source)
            .err()
            .unwrap()
            .contains("disappeared")
    );
}

#[test]
fn rejects_duplicate_ids_effects_and_invalid_decisions() {
    let mut rows = quality();
    let first = rows[0].clone();
    rows.as_array_mut().unwrap().push(first);
    assert!(
        convert(rows, compatibility())
            .err()
            .unwrap()
            .contains("duplicate effect")
    );
    let duplicate = self::rows(json!([{"_index":11,"Id":"damage"},{"_index":11,"Id":"cost"}]));
    assert!(
        index(duplicate, "Stats")
            .unwrap_err()
            .contains("duplicate ID / row index")
    );
    for effects in [
        json!(["TestSkill", "TestSkill"]),
        json!(["UnreviewedSkill"]),
    ] {
        let mut source = compatibility();
        source["effects"] = effects;
        assert!(
            convert(quality(), source)
                .err()
                .unwrap()
                .contains("overlapping quality compatibility scope")
        );
    }
}

#[test]
fn forward_lists_every_unreviewed_and_disappeared_effect_without_hiding_integrity_errors() {
    let effects = index(effects(), "GrantedEffects").unwrap();
    let stats = index(stats(), "Stats").unwrap();
    let mut policy = compatibility();
    policy["excluded_effects"] = json!({"GoneExcluded":"removed"});
    policy["effects"] = json!(["TestSkill", "GoneEnabled"]);
    let mut source = quality();
    source[1]["ApplyToStatSets"] = json!([3]);
    let mut coverage = Coverage::new(AdapterMode::Forward, "gem-quality");
    let converted = convert_rows(
        &effects,
        &stats,
        rows(source.clone()),
        &rows(policy.clone()),
        &mut coverage,
    )
    .unwrap();
    assert_eq!(converted.effects.len(), 1);
    assert_eq!(converted.effects[0].effect_id, "TestSkill");
    assert!(!converted.scopes.contains_key("UnreviewedSkill"));
    let mut receipt = json!({});
    coverage.finish(&mut receipt).unwrap();
    let issues = receipt["coverage"]["issues"].as_array().unwrap();
    assert_eq!(issues.len(), 3);
    assert_eq!(
        issues
            .iter()
            .map(|issue| (
                issue["kind"].as_str().unwrap(),
                issue["entity"].as_str().unwrap()
            ))
            .collect::<Vec<_>>(),
        [
            ("reviewed-quality-gone", "GoneEnabled"),
            ("reviewed-quality-gone", "GoneExcluded"),
            ("unreviewed-quality", "UnreviewedSkill")
        ]
    );
    for (field, value, expected) in [
        (
            "Stats",
            json!([999]),
            "quality UnreviewedSkill: dangling stat 999",
        ),
        (
            "AltStats",
            json!([999]),
            "quality UnreviewedSkill: stat/value length mismatch (alt=true)",
        ),
    ] {
        let mut bad = source.clone();
        bad[1][field] = value;
        let error = convert_rows(
            &effects,
            &stats,
            rows(bad),
            &rows(policy.clone()),
            &mut Coverage::new(AdapterMode::Forward, "gem-quality"),
        )
        .err()
        .unwrap();
        assert_eq!(error, expected);
    }
    let mut duplicate = source;
    let repeated = duplicate[1].clone();
    duplicate.as_array_mut().unwrap().push(repeated);
    assert!(
        convert_rows(
            &effects,
            &stats,
            rows(duplicate),
            &rows(policy),
            &mut Coverage::new(AdapterMode::Forward, "gem-quality")
        )
        .err()
        .unwrap()
        .contains("duplicate effect")
    );
}
