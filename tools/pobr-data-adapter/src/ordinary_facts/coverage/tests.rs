use std::fs;

use serde_json::{Value, json};

use super::super::tests::Fixture;
use super::super::{Args, Domain, parse_args, run};
use super::*;

const FLAGS: [&str; 8] = [
    "--ordinary-facts",
    "facts",
    "--facts-manifest-sha256",
    "pin",
    "--version",
    "0.5.5.5",
    "--out",
    "fresh",
];

fn parse(extra: &[&str]) -> Result<Args, String> {
    parse_args(FLAGS.iter().chain(extra).map(|flag| flag.to_string()))
}

#[test]
fn is_forward_reports_the_selected_mode_without_recording_an_issue() {
    for mode in [AdapterMode::Strict, AdapterMode::Forward] {
        let coverage = Coverage::new(mode, "passive-tree");
        assert_eq!(coverage.is_forward(), mode == AdapterMode::Forward);
        assert!(coverage.issues.is_empty());
    }
}

#[test]
fn mode_defaults_to_strict_and_rejects_unknown_or_repeated_values() {
    assert_eq!(parse(&[]).unwrap().mode, AdapterMode::Strict);
    assert_eq!(
        parse(&["--mode", "strict"]).unwrap().mode,
        AdapterMode::Strict
    );
    assert_eq!(
        parse(&["--mode", "forward"]).unwrap().mode,
        AdapterMode::Forward
    );
    assert_eq!(
        parse(&["--mode", "lenient"]).err().unwrap(),
        "unsupported adapter mode: lenient"
    );
    assert_eq!(
        parse(&["--mode", "forward", "--mode", "forward"])
            .err()
            .unwrap(),
        "missing value or duplicate argument: --mode"
    );
    assert_eq!(parse(&["--mode"]).err().unwrap(), "--mode needs a value");
    assert_eq!(
        parse(&["--mode", "--out", "fresh"]).err().unwrap(),
        "missing value or duplicate argument: --mode"
    );
}

fn issue(kind: &'static str, entity: &str, action: Action) -> Issue {
    Issue::new(kind, entity, action, format!("{kind}: {entity} failed"))
}

#[test]
fn strict_returns_the_exact_message_and_records_nothing() {
    let mut coverage = Coverage::new(AdapterMode::Strict, "gem-effects");
    let message = "gem-effects: codec gem Fireball has no target GemEffects row";
    assert_eq!(
        coverage
            .decide(Issue::new(
                "codec-gem-absent",
                "Fireball",
                Action::Quarantined,
                message
            ))
            .unwrap_err(),
        message
    );
    coverage.note(issue("new-gem", "Ice", Action::Listed));
    assert!(coverage.issues.is_empty());
    let mut conversion = json!({"kept":true});
    coverage.finish(&mut conversion).unwrap();
    assert_eq!(conversion, json!({"kept":true}));
}

#[test]
fn forward_records_every_issue_in_sorted_order_with_counts_per_action() {
    let mut coverage = Coverage::new(AdapterMode::Forward, "gem-effects");
    coverage
        .decide(
            issue("tuple-mismatch", "Zap", Action::EmittedWithGap)
                .observed("rows".to_owned(), 2)
                .observed("candidate_lines", json!(["a", "b"]))
                .observed("context", json!({"z":true,"a":1})),
        )
        .unwrap();
    coverage
        .decide(issue("codec-gem-absent", "Zap", Action::Quarantined))
        .unwrap();
    coverage.note(issue("new-gem", "Ice", Action::Listed));
    coverage
        .decide(issue("codec-gem-absent", "Arc", Action::Quarantined))
        .unwrap();
    for message in ["z: changed gem", "a: removed gem"] {
        coverage
            .decide(Issue::new(
                "codec-gem-absent",
                "Zap",
                Action::Listed,
                message,
            ))
            .unwrap();
    }
    coverage
        .decide(issue("codec-gem-absent", "Zap", Action::RetainedLegacy))
        .unwrap();
    let issues = coverage.issues.clone();
    let mut conversion = json!({"kept":true});
    coverage.finish(&mut conversion).unwrap();
    assert_eq!(
        conversion,
        json!({"kept":true, "coverage":{
        "format":"pobr-adapter-coverage/v1",
        "counts":{"emitted-with-gap":1, "listed":3, "quarantined":2, "retained-legacy":1},
        "issues":[
            {"domain":"gem-effects","kind":"codec-gem-absent","entity":"Arc","action":"quarantined",
             "message":"codec-gem-absent: Arc failed"},
            {"domain":"gem-effects","kind":"codec-gem-absent","entity":"Zap","action":"listed",
             "message":"a: removed gem"},
            {"domain":"gem-effects","kind":"codec-gem-absent","entity":"Zap","action":"listed",
             "message":"z: changed gem"},
            {"domain":"gem-effects","kind":"codec-gem-absent","entity":"Zap","action":"quarantined",
             "message":"codec-gem-absent: Zap failed"},
            {"domain":"gem-effects","kind":"codec-gem-absent","entity":"Zap","action":"retained-legacy",
             "message":"codec-gem-absent: Zap failed"},
            {"domain":"gem-effects","kind":"new-gem","entity":"Ice","action":"listed",
             "message":"new-gem: Ice failed"},
            {"domain":"gem-effects","kind":"tuple-mismatch","entity":"Zap","action":"emitted-with-gap",
             "message":"tuple-mismatch: Zap failed",
             "observed":{"candidate_lines":["a","b"],"context":{"a":1,"z":true},"rows":2}}
        ]}})
    );
    let mut reversed = Coverage::new(AdapterMode::Forward, "gem-effects");
    for mut issue in issues.into_iter().rev() {
        let observed = std::mem::take(&mut issue.observed);
        for (field, value) in observed.into_iter().rev() {
            issue = issue.observed(field, value);
        }
        reversed.decide(issue).unwrap();
    }
    let mut replay = json!({"kept":true});
    reversed.finish(&mut replay).unwrap();
    assert_eq!(
        serde_json::to_vec(&conversion).unwrap(),
        serde_json::to_vec(&replay).unwrap()
    );
}

#[test]
fn empty_forward_coverage_is_present_with_zero_counts_and_never_overwrites() {
    let mut conversion = json!({});
    Coverage::new(AdapterMode::Forward, "skills")
        .finish(&mut conversion)
        .unwrap();
    assert_eq!(
        conversion["coverage"],
        json!({"format":FORMAT, "issues":[],
            "counts":{"quarantined":0, "emitted-with-gap":0, "retained-legacy":0, "listed":0}})
    );
    assert_eq!(
        Coverage::new(AdapterMode::Forward, "skills")
            .finish(&mut conversion)
            .unwrap_err(),
        "conversion receipt already has a coverage field"
    );
    assert!(
        Coverage::new(AdapterMode::Forward, "skills")
            .finish(&mut json!([]))
            .is_err()
    );
}

/// A domain with its existing fixture and argument helpers.
type Case = (Domain, fn() -> Fixture, fn(&Fixture) -> Args);

fn read(f: &Fixture, path: &str) -> Value {
    crate::read_json(&f.root.join(path)).unwrap()
}

/// Every domain whose converter takes `&mut Coverage`, on its existing fixture,
/// plus the default domain: forward output is byte-identical to strict, and the
/// receipt differs only by an empty `conversion.coverage`.
#[test]
fn forward_mode_on_existing_fixtures_matches_strict_with_zero_issues() {
    use super::super::{
        gem_effects, passive_tree, quality, skill_overrides, skill_stat_map, skills, stat_set_codec,
    };
    let cases: [Case; 8] = [
        (Domain::StatsMods, Fixture::new, Fixture::args),
        (Domain::Skills, skills::tests::fixture, skills::tests::args),
        (
            Domain::SkillStatMap,
            skill_stat_map::tests::fixture,
            skill_stat_map::tests::args,
        ),
        (
            Domain::SkillOverrides,
            skill_overrides::tests::fixture,
            skill_overrides::tests::args,
        ),
        (
            Domain::StatSetCodec,
            stat_set_codec::tests::fixture,
            stat_set_codec::tests::args,
        ),
        (
            Domain::GemEffects,
            gem_effects::tests::fixture,
            gem_effects::tests::args,
        ),
        (
            Domain::GemQuality,
            quality::tests::fixture,
            quality::tests::args,
        ),
        (
            Domain::PassiveTree,
            passive_tree::tests::fixture,
            passive_tree::tests::args,
        ),
    ];
    for (domain, fixture, args) in cases {
        let f = fixture();
        assert_eq!(args(&f).domain, domain);
        run(args(&f)).unwrap();
        run(Args {
            out: f.root.join("forward"),
            mode: AdapterMode::Forward,
            ..args(&f)
        })
        .unwrap();
        let strict = read(&f, "out/producer-receipt.json");
        assert!(
            !strict["conversion"]
                .as_object()
                .unwrap()
                .contains_key("coverage"),
            "{domain:?}"
        );
        let mut forward = read(&f, "forward/producer-receipt.json");
        let coverage = forward["conversion"]
            .as_object_mut()
            .unwrap()
            .remove("coverage")
            .unwrap();
        assert_eq!(coverage["issues"], json!([]), "{domain:?}");
        assert!(
            coverage["counts"]
                .as_object()
                .unwrap()
                .values()
                .all(|n| n == 0)
        );
        assert_eq!(forward, strict, "{domain:?}");
        for path in strict["files"].as_object().unwrap().keys() {
            assert_eq!(
                fs::read(f.root.join("out").join(path)).unwrap(),
                fs::read(f.root.join("forward").join(path)).unwrap(),
                "{domain:?}: {path}"
            );
        }
    }
}
