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

#[test]
fn forward_publication_isolates_gems_with_shared_business_id_and_strict_messages() {
    for (row, value, kind, expected, action) in [
        (
            0,
            json!([0, 0]),
            "gem-effects-count",
            Some("SkillGems/0: multiple GemEffects"),
            "quarantined",
        ),
        (
            0,
            json!([]),
            "gem-effects-count",
            Some("SkillGems/0: normal gem requires GemEffects"),
            "quarantined",
        ),
        (
            0,
            json!([null]),
            "gem-invalid-field",
            Some("SkillGems/0: invalid type: null, expected usize"),
            "quarantined",
        ),
        (
            1,
            json!([1, 1]),
            "gem-effects-count",
            Some("SkillGems/1: multiple GemEffects"),
            "listed",
        ),
        (1, json!([]), "gem-effects-count", None, "listed"),
        (
            1,
            json!([null]),
            "gem-invalid-field",
            Some("SkillGems/1: invalid type: null, expected usize"),
            "listed",
        ),
    ] {
        let mut f = publication_fixture();
        f.values("BaseItemTypes", row)["Id"] = json!("BCompound");
        f.values("SkillGems", row)["GemEffects"] = value;
        reseal(&mut f);
        if let Some(expected) = expected {
            assert_eq!(run(args(&f)).unwrap_err(), expected);
        }
        run(Args {
            mode: AdapterMode::Forward,
            ..args(&f)
        })
        .unwrap();
        let receipt = read(&f, "producer-receipt.json");
        assert_eq!(receipt.as_object().unwrap().len(), 10);
        assert_eq!(receipt["files"].as_object().unwrap().len(), 5);
        let issues = receipt["conversion"]["coverage"]["issues"]
            .as_array()
            .unwrap();
        assert_eq!(issues.len(), 1);
        assert_eq!(issues[0]["kind"], kind);
        assert_eq!(issues[0]["entity"], "BCompound");
        assert_eq!(issues[0]["action"], action);
        let owners = receipt["conversion"]["publication"]["owners"]
            .as_object()
            .unwrap();
        assert!(owners.values().all(|owner| {
            owner["gem_links"]
                .as_array()
                .unwrap()
                .iter()
                .all(|link| link["gem_id"] != "BCompound")
        }));
        if row == 0
            && kind == "gem-effects-count"
            && !issues[0]["observed"]["fields"]["GemEffects"]
                .as_array()
                .unwrap()
                .is_empty()
        {
            assert!(
                read(&f, "overlay/gem_quality_stats.json")["effects"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .any(|effect| effect["effect_id"] == "z_attack")
            );
        }
    }
    let mut f = publication_fixture();
    f.values("GemEffects", 0)["GrantedEffect"] = json!(null);
    reseal(&mut f);
    assert_eq!(
        run(args(&f)).unwrap_err(),
        "SkillGems/0: normal gem requires primary GrantedEffect"
    );
    assert_eq!(
        run(Args {
            mode: AdapterMode::Forward,
            ..args(&f)
        })
        .unwrap_err(),
        "SkillGems/0: normal gem requires primary GrantedEffect"
    );
    assert!(!f.root.join("out").exists());
    f.values("SkillGems", 0)["GemEffects"] = json!([null, 0]);
    reseal(&mut f);
    assert_eq!(
        run(Args {
            mode: AdapterMode::Forward,
            ..args(&f)
        })
        .unwrap_err(),
        "SkillGems/0: normal gem requires primary GrantedEffect"
    );
    assert!(!f.root.join("out").exists());
}

#[test]
fn forward_publication_lists_missing_reviews_and_disappeared_exclusions_without_guessing() {
    let f = publication_fixture();
    let mut p = policy(&f);
    p["compatibility"]["effects"] = json!(["a_non_gem_support", "GoneEnabled"]);
    p["compatibility"]["excluded_effects"] = json!({"excluded":"fixture","GoneExcluded":"removed"});
    write_policy(&f, &p);
    run(Args {
        mode: AdapterMode::Forward,
        ..args(&f)
    })
    .unwrap();
    let receipt = read(&f, "producer-receipt.json");
    let issues = receipt["conversion"]["coverage"]["issues"]
        .as_array()
        .unwrap();
    assert_eq!(issues.len(), 3);
    assert_eq!(issues[0]["entity"], "GoneEnabled");
    assert_eq!(issues[1]["entity"], "GoneExcluded");
    assert_eq!(issues[2]["entity"], "z_attack");
    assert_eq!(issues[2]["kind"], "unreviewed-quality");
    assert_eq!(
        read(&f, "overlay/gem_quality_stats.json")["effects"]
            .as_array()
            .unwrap()
            .len(),
        1
    );
    let owners = receipt["conversion"]["publication"]["owners"]
        .as_object()
        .unwrap();
    assert!(!owners.contains_key("GoneEnabled"));
    assert!(!owners.contains_key("GoneExcluded"));
}

#[test]
fn forward_publication_keeps_dangling_references_and_invalid_partitions_fatal() {
    for value in [json!([0, 999]), json!([null, 999]), json!([999, null])] {
        let mut f = publication_fixture();
        f.values("SkillGems", 0)["GemEffects"] = value;
        reseal(&mut f);
        assert!(
            run(Args {
                mode: AdapterMode::Forward,
                ..args(&f)
            })
            .unwrap_err()
            .contains("dangling GemEffects 999")
        );
        assert!(!f.root.join("out").exists());
    }
    let mut f = publication_fixture();
    f.values("GemEffects", 0)["AdditionalGrantedEffects"] = json!([2]);
    f.values("SkillGems", 1)["GemEffects"] = json!([null]);
    reseal(&mut f);
    assert!(
        run(Args {
            mode: AdapterMode::Forward,
            ..args(&f)
        })
        .unwrap_err()
        .contains("except verified DNT-only")
    );
}

#[test]
fn own_gem_fields_match_skills_isolation_in_quality_publication() {
    use crate::ordinary_facts::gem_effects::tests::{add_own_field, own_field_cases};

    for (field, value, expected) in own_field_cases() {
        for (row, id, action) in [(0, "real_gem", "quarantined"), (1, "placeholder", "listed")] {
            let mut f = publication_fixture();
            add_own_field(&mut f, field);
            f.values("SkillGems", row)[field] = value.clone();
            reseal(&mut f);
            assert!(run(args(&f)).unwrap_err().contains(expected));
            run(Args {
                mode: AdapterMode::Forward,
                ..args(&f)
            })
            .unwrap();
            let receipt = read(&f, "producer-receipt.json");
            let issues = receipt["conversion"]["coverage"]["issues"]
                .as_array()
                .unwrap();
            assert_eq!(issues.len(), 1);
            assert_eq!(issues[0]["kind"], "gem-invalid-field");
            assert_eq!(issues[0]["entity"], id);
            assert_eq!(issues[0]["action"], action);
            assert!(
                receipt["conversion"]["publication"]["owners"]
                    .as_object()
                    .unwrap()
                    .values()
                    .all(|owner| owner["gem_links"]
                        .as_array()
                        .unwrap()
                        .iter()
                        .all(|link| link["gem_id"] != id))
            );
        }
    }
    for mode in [AdapterMode::Strict, AdapterMode::Forward] {
        let mut f = publication_fixture();
        add_own_field(&mut f, "ItemExperienceType");
        f.values("SkillGems", 0)["ItemExperienceType"] = json!(999);
        reseal(&mut f);
        assert!(
            run(Args { mode, ..args(&f) })
                .unwrap_err()
                .contains("unresolved physical row ItemExperienceTypes/999")
        );
        assert!(!f.root.join("out").exists());
    }
}
