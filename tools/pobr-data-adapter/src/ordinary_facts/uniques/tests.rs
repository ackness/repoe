use super::*;
use crate::ordinary_facts::{
    Args, CodecArgs, Domain, parse_args, run, stat_set_codec::tests::table, tests::Fixture,
};
use std::fs;

const VENDOR_REV: &str = "bb52d6b368307457eb9c54bb13f1829993d390b1";

fn fixture() -> (Fixture, Value) {
    let mut f = Fixture::new();
    f.documents.insert(
        "tables/BaseItemTypes.json".into(),
        table(
            "BaseItemTypes",
            &[
                ("Id", "string", false, None),
                ("Name", "string", false, None),
                ("ItemClass", "foreignrow", false, Some("ItemClasses")),
            ],
            json!([
                {"Id":"Metadata/Items/Amulets/Amulet12","Name":"Stellar Amulet","ItemClass":0},
                {"Id":"Metadata/Items/BodyArmours/BodyStr15","Name":"Sacrificial Regalia","ItemClass":1},
                {"Id":"Metadata/Items/Rings/Ring10","Name":"Ruby Ring","ItemClass":2},
                {"Id":"Metadata/Items/Rings/Ring10B","Name":"Ruby Ring","ItemClass":2},
                {"Id":"Metadata/Items/Rings/Ring11","Name":"Crimson Amulet","ItemClass":0}
            ]),
        ),
    );
    f.documents.insert(
        "tables/ItemClasses.json".into(),
        table(
            "ItemClasses",
            &[("Id", "string", false, None)],
            json!([{"Id":"Amulets"},{"Id":"BodyArmours"},{"Id":"Rings"}]),
        ),
    );
    f.seal();
    let old = json!({
        "_meta": {
            "schema": "uniques/v1",
            "generator": "sync-pob-catalog extract-lua",
            "vendor": "PathOfBuilding-PoE2",
            "vendor_commit": VENDOR_REV,
            "custom": {"kept": true}
        },
        "uniques": [
            {
                "name": "Astramentis",
                "base": "Stellar Amulet",
                "item_type": "amulet",
                "variants": ["Pre 0.2.0", "Current"],
                "league": "Test League",
                "source": "Drops from unique{Xesht} in normal{Twisted Domain}",
                "raw": concat!(
                    "Astramentis\n",
                    "Stellar Amulet\n",
                    "Variant: Pre 0.2.0\n",
                    "Variant: Current\n",
                    "League: Test League\n",
                    "Source: Drops from unique{Xesht} in normal{Twisted Domain}\n",
                    "Sockets: S S\n",
                    "Requires Level 55\n",
                    "Implicits: 1\n",
                    "{tags:life}+(5-7) to maximum Life\n",
                    "{variant:1}{tags:attribute}+(80-100) to all Attributes\n",
                    "{variant:2}+(50-100) to all Attributes\n",
                    "{tags:physical,attack}-4 Physical Damage taken from Attack Hits\n",
                    "Grants Skill: Level (1-20) Lightning Bolt\n"
                )
            },
            {
                "name": "Atziri's Splendour",
                "base": "Sacrificial Regalia",
                "item_type": "body",
                "variants": ["Helmet", "Gloves"],
                "raw": concat!(
                    "Atziri's Splendour\n",
                    "Sacrificial Regalia\n",
                    "Has Alt Variant: true\n",
                    "Has Alt Variant Two: true\n",
                    "Selected Variant: 1\n",
                    "Selected Alt Variant: 5\n",
                    "Selected Alt Variant Two: 3\n",
                    "Selected Variant Group: 2=9\n",
                    "Allow Duplicate Variants: true\n",
                    "Variant: Helmet\n",
                    "Variant: Gloves\n",
                    "Implicits: 1\n",
                    "+1 to Level of all Corrupted Skill Gems\n",
                    "{variant:1}{group:1}Helmet bonus\n",
                    "{variant:2}{group:2}(-20--10)% reduced Armour\n",
                    "{desecrated}{custom}Only Soul Cores can be Socketed\n",
                    "{weird:7}{novel}Unmodelled annotation line\n"
                )
            },
            {
                "name": "Copy Ring",
                "base": "Ruby Ring",
                "item_type": "ring",
                "raw": "Copy Ring\nRuby Ring\n+(0.1-0.4) to something\nGrants Skill: Raise Shield\n"
            },
            {
                "name": "Nameless",
                "base": "Imaginary Staff",
                "item_type": "staff",
                "raw": "Nameless\nImaginary Staff\n+1 to nothing\n"
            },
            {
                "name": "Odd",
                "base": "Wrong Base",
                "item_type": "amulet",
                "variants": ["Only"],
                "raw": "Odd\nCrimson Amulet\nVariant: Only\nVersion: Legacy\nVersion: Current\n{version:1}{variant:1}+5 to X\n"
            }
        ]
    });
    (f, old)
}

fn args(f: &Fixture, old: &Value) -> Args {
    let dir = f.root.join("legacy");
    fs::create_dir_all(&dir).unwrap();
    let pol = f.root.join("policy");
    fs::create_dir_all(&pol).unwrap();
    let bytes = super::super::pretty_bytes(old).unwrap();
    fs::write(dir.join("old.json"), &bytes).unwrap();
    let mut policy: Value = serde_json::from_slice(include_bytes!(
        "../../../policies/uniques/0.5.5.5-relations-policy.json"
    ))
    .unwrap();
    policy["source_sha256"] = json!(sha256_hex(&bytes));
    policy["source"]["bytes"] = json!(bytes.len());
    let pb = super::super::pretty_bytes(&policy).unwrap();
    fs::write(pol.join("policy.json"), &pb).unwrap();
    Args {
        domain: Domain::Uniques,
        codec: Some(CodecArgs {
            source: dir.join("old.json"),
            source_sha256: sha256_hex(&bytes),
            policy: pol.join("policy.json"),
            policy_sha256: sha256_hex(&pb),
        }),
        ..f.args()
    }
}

fn read(f: &Fixture, file: &str) -> Value {
    crate::read_json(&f.root.join("out").join(file)).unwrap()
}

#[test]
fn relations_structure_ownership_and_archives() {
    let (f, old) = fixture();
    let a = args(&f, &old);
    let legacy = fs::read(&a.codec.as_ref().unwrap().source).unwrap();
    let policy_bytes = fs::read(&a.codec.as_ref().unwrap().policy).unwrap();
    run(a).unwrap();
    let doc = read(&f, "overlay/unique_relations.json");
    assert_eq!(doc["_meta"]["schema"], "unique_relations/v1");
    assert_eq!(doc["_meta"]["legacy_metadata"], old["_meta"]);
    assert_eq!(doc["uniques"].as_array().unwrap().len(), 5);

    let astr = &doc["uniques"][0];
    assert_eq!(astr["name"], "Astramentis");
    assert_eq!(astr["item_type"], "amulet");
    assert_eq!(astr["raw"], old["uniques"][0]["raw"]);
    assert_eq!(
        astr["bases"],
        json!([{
            "source_line": 1,
            "name": "Stellar Amulet",
            "base_items": [{
                "row": 0,
                "id": "Metadata/Items/Amulets/Amulet12",
                "item_class": "Amulets"
            }],
            "resolution": "resolved"
        }])
    );
    assert_eq!(
        astr["selection"]["variants"],
        json!(["Pre 0.2.0", "Current"])
    );
    assert_eq!(astr["implicit_count"], 1);
    let mods = astr["mods"].as_array().unwrap();
    assert_eq!(mods.len(), 5);
    assert_eq!(mods[0]["text"], "+(5-7) to maximum Life");
    assert_eq!(mods[0]["implicit"], true);
    assert_eq!(mods[0]["tags"], json!(["life"]));
    assert_eq!(mods[0]["rolls"], json!([{"min":5,"max":7,"sign":"+"}]));
    assert_eq!(mods[1]["variants"], json!([1]));
    assert_eq!(mods[1]["rolls"], json!([{"min":80,"max":100,"sign":"+"}]));
    assert_eq!(mods[2]["implicit"], false);
    let grant = &mods[4];
    assert_eq!(grant["kind"], "grants_skill");
    assert_eq!(
        grant["grants_skill"],
        json!({"level":{"min":1,"max":20},"skill_name":"Lightning Bolt"})
    );
    let kinds: Vec<_> = astr["directives"]
        .as_array()
        .unwrap()
        .iter()
        .map(|d| d["kind"].as_str().unwrap().to_string())
        .collect();
    assert_eq!(kinds, ["league", "source", "sockets", "requires"]);

    let atziri = &doc["uniques"][1];
    let sel = &atziri["selection"]["selected"];
    assert_eq!(sel["variant"]["value"], 1);
    assert_eq!(sel["alt_variant_0"]["value"], 5);
    assert_eq!(sel["alt_variant_1"]["value"], 3);
    assert_eq!(
        sel["variant_groups"],
        json!([{"group":2,"variant":9,"source_line":7}])
    );
    assert_eq!(sel["allow_duplicate_variants"]["value"], true);
    assert_eq!(atziri["selection"]["alt_variant_slots"], json!([0, 1]));
    assert_eq!(atziri["selection"]["groups"], json!([1, 2]));
    let amods = atziri["mods"].as_array().unwrap();
    assert_eq!(amods[0]["implicit"], true);
    assert_eq!(amods[1]["variants"], json!([1]));
    assert_eq!(amods[1]["groups"], json!([1]));
    assert_eq!(
        amods[2]["rolls"],
        json!([{"min":-20,"max":-10,"sign":null}])
    );
    assert_eq!(amods[3]["flags"], json!(["desecrated", "custom"]));
    assert_eq!(
        amods[4]["annotations"],
        json!([{"key":"weird","value":"7"},{"key":"novel","value":null}])
    );

    // The ambiguous duplicate-name base keeps all candidates, not a guess.
    let ring = &doc["uniques"][2];
    assert_eq!(ring["bases"][0]["resolution"], "ambiguous");
    assert_eq!(ring["bases"][0]["base_items"].as_array().unwrap().len(), 2);
    assert_eq!(
        ring["mods"][0]["rolls"],
        json!([{"min":0.1,"max":0.4,"sign":"+"}])
    );
    // Vendor grants without an explicit Level prefix carry skill_name alone.
    assert_eq!(
        ring["mods"][1]["grants_skill"],
        json!({"skill_name":"Raise Shield"})
    );

    // Unmatched vendor base text stays a mod line plus diagnostics.
    let diag = &doc["_meta"]["diagnostics"];
    assert_eq!(
        diag["no_bases"],
        json!([{"unique_index":3,"name":"Nameless"}])
    );
    assert_eq!(
        diag["unresolved_bases"].as_array().unwrap().len(),
        2 // "Imaginary Staff" and "Wrong Base"
    );
    assert_eq!(diag["ambiguous_bases"].as_array().unwrap().len(), 1);
    assert_eq!(
        diag["base_column_mismatches"],
        json!([{
            "unique_index": 4,
            "name": "Odd",
            "index_base": "Wrong Base",
            "first_base_line": "Crimson Amulet"
        }])
    );
    let odd = &doc["uniques"][4];
    assert_eq!(odd["selection"]["versions"], json!(["Legacy", "Current"]));
    assert_eq!(odd["mods"][0]["versions"], json!([1]));
    assert_eq!(odd["mods"][0]["variants"], json!([1]));
    assert_eq!(diag["counts"]["uniques"], 5);
    assert!(
        diag["index_column_mismatches"]
            .as_array()
            .unwrap()
            .is_empty()
    );

    assert_eq!(
        fs::read(f.root.join("out/legacy-uniques.json")).unwrap(),
        legacy
    );
    assert_eq!(
        fs::read(f.root.join("out/codec-policy.json")).unwrap(),
        policy_bytes
    );
    let receipt = read(&f, "producer-receipt.json");
    assert_eq!(receipt["conversion"]["uniques"], 5);
    assert_eq!(receipt["complete_runtime"], false);
    assert_eq!(
        read(&f, "_domain_candidate.json")["domain"],
        "ordinary-uniques"
    );
    assert!(!f.root.join("out/base").exists());
}

#[test]
fn annotations_and_rolls_match_consumer_grammar() {
    let (f, _) = fixture();
    // Parity with pobr-item's parse_mod_line on the shared keys.
    let (ann, stripped) =
        annotations("{variant:1,3}{tags:life,physical}{desecrated}+(40-50) to Life").unwrap();
    assert_eq!(ann.variants, vec![1, 3]);
    assert_eq!(ann.tags, vec!["life", "physical"]);
    assert_eq!(ann.flags, vec!["desecrated"]);
    assert_eq!(stripped, "+(40-50) to Life");
    let (pobr_ann, pobr_text) = pobr_item::annotations::parse_mod_line(
        "{variant:1,3}{tags:life,physical}{desecrated}+(40-50) to Life",
    );
    assert_eq!(pobr_ann.variants, Some(vec![1, 3]));
    assert_eq!(
        pobr_ann.tags,
        vec!["life".to_string(), "physical".to_string()]
    );
    assert!(pobr_ann.desecrated);
    assert_eq!(pobr_text, stripped);

    // range/corruptedRange parse to dedicated numeric fields like the
    // consumer's ModLineAnnotations; unparseable values are preserved verbatim.
    let (ann, stripped) = annotations("{range:0.5}{corruptedRange:0.25}+1 to X").unwrap();
    assert!(ann.flags.is_empty());
    assert_eq!(ann.range, Some(0.5));
    assert_eq!(ann.corrupted_range, Some(0.25));
    assert!(ann.other.is_empty());
    assert_eq!(stripped, "+1 to X");
    let (ann, _) = annotations("{range:surely}+1 to X").unwrap();
    assert_eq!(ann.range, None);
    assert_eq!(ann.other, vec![json!({"key":"range","value":"surely"})]);

    // Roll grammar: optional sign, negative endpoints, decimals, multiple per line.
    assert_eq!(
        json!(rolls(
            "+(30-50) to A and -(-10-5) to B (no range) and (2.5-4.5)% more"
        )),
        json!([
            {"min":30,"max":50,"sign":"+"},
            {"min":-10,"max":5,"sign":"-"},
            {"min":2.5,"max":4.5,"sign":null}
        ])
    );
    assert!(rolls("(x-y) not numeric () (1-)").is_empty());
    let _ = f;
}

#[test]
fn malformed_numeric_annotations_and_directives_reject() {
    for (line, expected) in [
        ("{variant:x}+1", "invalid {variant:} id list member"),
        ("{variant:1,}+1", "invalid {variant:} id list member"),
        ("{version:two}+1", "invalid {version:} id list member"),
        ("{group:g}+1", "invalid {group:} id list member"),
        ("Implicits: many", "invalid Implicits value"),
        ("Selected Variant: soon", "invalid Selected Variant value"),
        ("Selected Version: v", "invalid Selected Version value"),
        (
            "Selected Variant Group: 1",
            "invalid Selected Variant Group",
        ),
        ("Has Alt Variant: yes", "invalid Has Alt Variant value"),
        ("Has Alt Variant Nine: true", "invalid Has Alt Variant line"),
        (
            "Selected Alt Variant Nine: 1",
            "invalid Selected Alt Variant",
        ),
    ] {
        let (f, mut old) = fixture();
        old["uniques"][2]["raw"] = json!(format!("Copy Ring\nRuby Ring\n{line}\n"));
        let err = run(args(&f, &old)).unwrap_err();
        assert!(err.contains(expected), "{line}: {err}");
        assert!(err.contains("Copy Ring"), "{line}: {err}");
        assert!(!f.root.join("out").exists(), "{line}");
    }
}

#[test]
fn unexpected_legacy_fields_and_bad_json_reject() {
    let (f, mut old) = fixture();
    old["uniques"][0]["surprise"] = json!(1);
    let a = args(&f, &old);
    let bytes = super::super::pretty_bytes(&old).unwrap();
    fs::write(&a.codec.as_ref().unwrap().source, &bytes).unwrap();
    let mut a = a;
    a.codec.as_mut().unwrap().source_sha256 = sha256_hex(&bytes);
    assert!(run(a).unwrap_err().contains("unexpected field"));

    let (f, _) = fixture();
    let mut a = args(&f, &json!({"_meta":{},"uniques":[]}));
    // Repin source and policy to the malformed document.
    let bytes = super::super::pretty_bytes(&json!({"_meta":{},"uniques":"no"})).unwrap();
    fs::write(&a.codec.as_ref().unwrap().source, &bytes).unwrap();
    a.codec.as_mut().unwrap().source_sha256 = sha256_hex(&bytes);
    assert!(run(a).is_err());
}

#[test]
fn policy_identity_source_pin_and_metadata_mismatches_reject() {
    for (pointer, value) in [
        ("/schema", json!("other")),
        ("/version", json!("0.0.0")),
        ("/source_sha256", json!("0".repeat(64))),
        ("/source/path", json!("elsewhere")),
        ("/source/member_of", json!("elsewhere")),
        ("/source/bytes", json!(1)),
        ("/vendor/repository", json!("other")),
        ("/vendor/revision", json!("0".repeat(40))),
        ("/source_metadata/schema", json!("other")),
        ("/statement", json!(" ")),
    ] {
        let (f, old) = fixture();
        let mut a = args(&f, &old);
        let c = a.codec.as_mut().unwrap();
        let mut p: Value = crate::read_json(&c.policy).unwrap();
        *p.pointer_mut(pointer).unwrap() = value;
        let pb = super::super::pretty_bytes(&p).unwrap();
        fs::write(&c.policy, &pb).unwrap();
        c.policy_sha256 = sha256_hex(&pb);
        assert!(run(a).is_err(), "{pointer}");
        assert!(!f.root.join("out").exists(), "{pointer}");
    }
    // Vendor metadata inside the source must match the policy identity.
    let (f, mut old) = fixture();
    old["_meta"]["vendor_commit"] = json!("0".repeat(40));
    let a = args(&f, &old);
    let bytes = super::super::pretty_bytes(&old).unwrap();
    fs::write(&a.codec.as_ref().unwrap().source, &bytes).unwrap();
    let mut a = a;
    a.codec.as_mut().unwrap().source_sha256 = sha256_hex(&bytes);
    assert!(run(a).unwrap_err().contains("metadata/vendor identity"));
    // A wrong source pin is checked before parsing.
    let (f, old) = fixture();
    let mut a = args(&f, &old);
    a.codec.as_mut().unwrap().source_sha256 = "0".repeat(64);
    assert!(run(a).unwrap_err().contains("SHA256 mismatch"));
}

#[test]
fn deterministic_output_and_cli_gating() {
    let (f, old) = fixture();
    run(args(&f, &old)).unwrap();
    let mut a2 = args(&f, &old);
    a2.out = f.root.join("out-again");
    run(a2).unwrap();
    for file in [
        "overlay/unique_relations.json",
        "producer-receipt.json",
        "legacy-uniques.json",
        "codec-policy.json",
        "_domain_candidate.json",
    ] {
        assert_eq!(
            fs::read(f.root.join("out").join(file)).unwrap(),
            fs::read(f.root.join("out-again").join(file)).unwrap(),
            "{file}"
        );
    }

    let base = [
        "--ordinary-facts",
        "/f",
        "--facts-manifest-sha256",
        "pin",
        "--version",
        "0.5.5.5",
        "--out",
        "/o",
        "--ordinary-domain",
        "uniques",
    ];
    assert!(parse_args(base.iter().map(|s| s.to_string())).is_err());
    let mut all = base.to_vec();
    all.extend([
        "--codec-source",
        "/s",
        "--codec-source-sha256",
        "p",
        "--codec-policy",
        "/p",
        "--codec-policy-sha256",
        "p",
    ]);
    assert_eq!(
        parse_args(all.iter().map(|s| s.to_string()))
            .unwrap()
            .domain,
        Domain::Uniques
    );
    for extra in [
        vec!["--supplement", "/s", "--supplement-manifest-sha256", "p"],
        vec!["--branch-codec", "/b", "--branch-codec-sha256", "p"],
        vec!["--quality-policy", "/q", "--quality-policy-sha256", "p"],
        vec!["--item-descriptions", "/d"],
        vec!["--catalog-policy", "/c", "--catalog-policy-sha256", "p"],
        vec!["--player-context", "/p", "--player-manifest-sha256", "p"],
    ] {
        let mut rejected = all.clone();
        rejected.extend(extra);
        assert!(parse_args(rejected.iter().map(|s| s.to_string())).is_err());
    }
}
