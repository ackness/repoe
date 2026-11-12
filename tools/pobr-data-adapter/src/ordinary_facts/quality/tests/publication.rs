use super::*;
use crate::ordinary_facts::coverage::{AdapterMode, Coverage};

fn publication_fixture() -> Fixture {
    let mut f = fixture();
    for (name, columns, values) in [
        (
            "BaseItemTypes",
            vec![
                ("Id", "string", false, None),
                ("Name", "string", false, None),
            ],
            json!([{"Id":"real_gem","Name":"Real gem"},{"Id":"placeholder","Name":"[DNT] Placeholder"}]),
        ),
        (
            "SkillGems",
            vec![
                ("BaseItemType", "foreignrow", false, Some("BaseItemTypes")),
                ("GemEffects", "foreignrow", true, Some("GemEffects")),
            ],
            json!([{"BaseItemType":0,"GemEffects":[0]},{"BaseItemType":1,"GemEffects":[1]}]),
        ),
        (
            "GemEffects",
            vec![
                ("GrantedEffect", "foreignrow", false, Some("GrantedEffects")),
                (
                    "AdditionalGrantedEffects",
                    "foreignrow",
                    true,
                    Some("GrantedEffects"),
                ),
            ],
            json!([{"GrantedEffect":0,"AdditionalGrantedEffects":[]},{"GrantedEffect":2,"AdditionalGrantedEffects":[]}]),
        ),
    ] {
        f.documents
            .insert(format!("tables/{name}.json"), table(name, &columns, values));
    }
    let mut p = policy(&f);
    p["schema"] = json!("pobr-ordinary-quality-policy/v2");
    p["target_applicability"]["kind"] = json!("complete-quality-owners-except-dnt-only-gems");
    write_policy(&f, &p);
    reseal(&mut f);
    f
}

#[test]
fn publication_includes_unlinked_support_and_preserves_both_channels_and_dnt_evidence() {
    let f = publication_fixture();
    run(args(&f)).unwrap();
    let doc = read(&f, "overlay/gem_quality_stats.json");
    assert_eq!(doc["effects"][0]["effect_id"], "a_non_gem_support");
    assert_eq!(doc["effects"][0]["stats"].as_array().unwrap().len(), 4);
    assert_eq!(
        doc["_meta"]["unapplied_stat_set_scopes"]["excluded"],
        json!({"main":[0],"alt":[2]})
    );
    assert_eq!(doc["_meta"]["inputs"].as_object().unwrap().len(), 6);
    let receipt = read(&f, "producer-receipt.json");
    let owners = &receipt["conversion"]["publication"]["owners"];
    assert_eq!(owners.as_object().unwrap().len(), 3);
    assert_eq!(owners["a_non_gem_support"]["gem_links"], json!([]));
    assert_eq!(owners["excluded"]["decision"], "excluded-dnt-only");
    assert_eq!(
        owners["excluded"]["gem_links"][0]["name"],
        "[DNT] Placeholder"
    );
}

#[test]
fn publication_never_excludes_real_mixed_additional_or_unlinked_quality_owners() {
    for case in [
        "real-primary",
        "real-additional",
        "mixed",
        "unlinked",
        "missing-base",
        "unused-not-dnt",
    ] {
        let mut f = publication_fixture();
        match case {
            "real-primary" => f.values("BaseItemTypes", 1)["Name"] = json!("Playable gem"),
            "real-additional" => {
                f.values("GemEffects", 1)["GrantedEffect"] = json!(0);
                f.values("GemEffects", 0)["AdditionalGrantedEffects"] = json!([2]);
            }
            "mixed" => f.values("GemEffects", 0)["AdditionalGrantedEffects"] = json!([2]),
            "unlinked" => f.values("GemEffects", 1)["GrantedEffect"] = json!(0),
            "missing-base" => f.values("SkillGems", 1)["BaseItemType"] = json!(null),
            "unused-not-dnt" => {
                f.values("BaseItemTypes", 1)["Name"] = json!("[UNUSED] Placeholder")
            }
            _ => unreachable!(),
        }
        reseal(&mut f);
        rejects(&f, "except verified DNT-only");
    }
}

#[test]
fn publication_cannot_hide_bad_links_or_incomplete_owner_decisions() {
    for (table, row, field, value, expected) in [
        (
            "GemEffects",
            1,
            "GrantedEffect",
            json!(999),
            "dangling GrantedEffect",
        ),
        (
            "GemEffects",
            1,
            "AdditionalGrantedEffects",
            json!([999]),
            "dangling GrantedEffect",
        ),
        (
            "GemEffects",
            1,
            "AdditionalGrantedEffects",
            json!([null]),
            "invalid type",
        ),
        (
            "SkillGems",
            1,
            "BaseItemType",
            json!(999),
            "dangling BaseItemType",
        ),
        (
            "SkillGems",
            1,
            "GemEffects",
            json!([999]),
            "dangling GemEffects",
        ),
        (
            "SkillGems",
            0,
            "GemEffects",
            json!([]),
            "normal gem requires",
        ),
        (
            "GemEffects",
            0,
            "GrantedEffect",
            json!(null),
            "normal gem requires",
        ),
    ] {
        let mut f = publication_fixture();
        f.values(table, row)[field] = value;
        reseal(&mut f);
        rejects(&f, expected);
    }
    for case in ["extra", "missing", "publish-dnt"] {
        let f = publication_fixture();
        let mut p = policy(&f);
        match case {
            "extra" => p["compatibility"]["effects"]
                .as_array_mut()
                .unwrap()
                .push(json!("unknown")),
            "missing" => {
                p["compatibility"]["effects"].as_array_mut().unwrap().pop();
            }
            "publish-dnt" => {
                p["compatibility"]["excluded_effects"] = json!({});
                p["compatibility"]["effects"]
                    .as_array_mut()
                    .unwrap()
                    .push(json!("excluded"));
            }
            _ => unreachable!(),
        }
        write_policy(&f, &p);
        rejects(
            &f,
            match case {
                "extra" => "disappeared",
                "missing" => "no reviewed",
                _ => "except verified DNT-only",
            },
        );
    }
}

#[test]
fn current_policy_partitions_every_historical_owner_without_losing_real_gem_quality() {
    let old: Value = serde_json::from_slice(include_bytes!(
        "../../../../policies/gem-quality/0.5.5.5-facts-policy.json"
    ))
    .unwrap();
    let new: Value = serde_json::from_slice(include_bytes!(
        "../../../../policies/gem-quality/0.5.5.5-publication-policy.json"
    ))
    .unwrap();
    let ids = |p: &Value| -> std::collections::BTreeSet<String> {
        p["compatibility"]["effects"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap().into())
            .chain(
                p["compatibility"]["excluded_effects"]
                    .as_object()
                    .unwrap()
                    .keys()
                    .cloned(),
            )
            .collect()
    };
    assert_eq!(ids(&old), ids(&new));
    assert_eq!(ids(&new).len(), 429);
    assert_eq!(
        new["compatibility"]["effects"].as_array().unwrap().len(),
        424
    );
    assert_eq!(
        new["compatibility"]["excluded_effects"]
            .as_object()
            .unwrap()
            .len(),
        5
    );
}

#[test]
fn all_429_real_source_vectors_retain_rates_order_channels_and_native_scopes() {
    use crate::skills::quality::{self, Compatibility, RawQuality};
    type Source = (
        String,
        Vec<(String, i32)>,
        Vec<u32>,
        Vec<(String, i32)>,
        Vec<u32>,
    );
    let sources: Vec<Source> = serde_json::from_slice(include_bytes!(
        "../../../../tests/fixtures/ordinary-facts/quality-source-vectors.json"
    ))
    .unwrap();
    let policy: Value = serde_json::from_slice(include_bytes!(
        "../../../../policies/gem-quality/0.5.5.5-publication-policy.json"
    ))
    .unwrap();
    let compatibility: Compatibility =
        serde_json::from_value(policy["compatibility"].clone()).unwrap();
    let effects = sources
        .iter()
        .enumerate()
        .map(|(i, s)| (i, s.0.clone()))
        .collect();
    let mut stats = BTreeMap::new();
    let mut rows = Vec::new();
    for (effect, source) in sources.iter().enumerate() {
        let mut channel = |pairs: &[(String, i32)]| {
            pairs
                .iter()
                .map(|(id, value)| {
                    let key = stats.len();
                    stats.insert(key, id.clone());
                    (key, *value)
                })
                .unzip()
        };
        let (main, values) = channel(&source.1);
        let (alt_stats, alt_values) = channel(&source.3);
        rows.push(RawQuality {
            effect,
            stats: main,
            values,
            sets: source.2.clone(),
            alt_stats,
            alt_values,
            alt_sets: source.4.clone(),
        });
    }
    let converted = quality::convert_rows(
        &effects,
        &stats,
        rows,
        &compatibility,
        &mut Coverage::new(AdapterMode::Strict, "gem-quality"),
    )
    .unwrap();
    assert_eq!(sources.len(), 429);
    assert_eq!(converted.effects.len(), 424);
    let published: BTreeMap<_, _> = converted
        .effects
        .iter()
        .map(|e| (e.effect_id.as_str(), &e.stats))
        .collect();
    for (id, main, main_sets, alt, alt_sets) in sources {
        if let Some(values) = published.get(id.as_str()) {
            let actual: Vec<_> = values
                .iter()
                .map(|v| (v.stat.clone(), v.per_quality_rate, v.alt))
                .collect();
            let expected: Vec<_> = main
                .into_iter()
                .map(|(id, n)| (id, f64::from(n) / 1000.0, false))
                .chain(
                    alt.into_iter()
                        .map(|(id, n)| (id, f64::from(n) / 1000.0, true)),
                )
                .collect();
            assert_eq!(actual, expected, "{id}");
        } else {
            assert!(
                compatibility.excluded_effects.contains_key(&id),
                "lost {id}"
            );
        }
        if !main_sets.is_empty() || !alt_sets.is_empty() {
            assert_eq!(converted.scopes[&id].main, main_sets, "{id}");
            assert_eq!(converted.scopes[&id].alt, alt_sets, "{id}");
        }
    }
    assert_eq!(converted.scopes["SnipePlayer"].main, [1, 2, 3]);
    assert_eq!(converted.scopes["SnipePlayer"].alt, [0]);
}
