"""Draft unreviewed passive-tree policy entries from a forward build's coverage.

Observed hashes belong to the adapter. This command copies them without opening
facts, tree references or policies; reviewers must resolve every draft decision.
"""

import argparse
from collections import Counter
from pathlib import Path

from RePoE.client import source_io
from RePoE.release.pins import ROOT, decode, require, safe_path

ENTRY_TYPES = (
    "placement_rebase",
    "ascendancy_frames",
    "compatibility_bindings",
    "context_columns",
    "excluded",
    "excluded_removals",
)
BLOCKED_NOTE = "needs a newer official reference or an exclusion"


def unreviewed(**fields):
    return {**fields, "review": "unreviewed", "reason": ""}


def tree_issues(coverage):
    require(
        isinstance(coverage, dict) and coverage.get("format") == "pobr-build-coverage/v1",
        "Expected a forward build receipt with coverage",
    )
    require(isinstance(coverage.get("jobs"), dict), "Invalid coverage jobs")
    issues = []
    for job in coverage["jobs"].values():
        require(isinstance(job, dict) and isinstance(job.get("issues"), list), "Invalid job coverage")
        for issue in job["issues"]:
            require(isinstance(issue, dict), "Invalid coverage issue")
            if issue.get("domain") != "passive-tree":
                continue
            require(
                all(isinstance(issue.get(key), str) and issue[key] for key in ("kind", "entity", "action", "message"))
                and isinstance(issue.get("observed", {}), dict),
                "Invalid passive-tree issue",
            )
            issues.append(issue)
    return sorted(issues, key=lambda issue: (issue["kind"], issue["entity"], source_io.encoded(issue)))


def merge_entry(entries, key, fields):
    """Combine text and render-context issues without silently overwriting evidence."""
    entry = entries.setdefault(key, unreviewed())
    for field, value in fields.items():
        require(field not in entry or entry[field] == value, f"Conflicting draft evidence: {key}/{field}")
        entry[field] = value


def columns(fields, value_field):
    require(isinstance(fields, list), "Invalid context column list")
    names = [field["field"] if isinstance(field, dict) else field for field in fields]
    require(all(isinstance(name, str) and name for name in names), "Invalid context column name")
    require(len(names) == len(set(names)), "Duplicate context column")
    return [unreviewed(field=name, **{value_field: None}) for name in sorted(names)]


def draft_coverage(coverage):
    issues = tree_issues(coverage)
    document = {}
    drafted = 0
    for issue in issues:
        kind, entity = issue["kind"], issue["entity"]
        observed = issue.get("observed", {})
        # Coverage has no integrity-class discriminator. Never guess a closing
        # policy for an entity the adapter could not safely emit.
        if issue["action"] == "quarantined":
            document.setdefault("blocked", []).append(issue)
            document["blocked_note"] = BLOCKED_NOTE
            continue
        if kind == "placement-rebase":
            merge_entry(
                document,
                "placement_rebase",
                {
                    field: observed[field]
                    for field in ("reference_sha256", "legacy_source_sha256", "moved_skills_sha256", "moved_count")
                },
            )
        elif kind == "ascendancy-frame":
            merge_entry(
                document.setdefault("ascendancy_frames", {}),
                entity,
                {
                    **{
                        field: observed[field]
                        for field in ("start_skill", "reference_start_node_sha256", "member_skills_sha256")
                    },
                    "dx": None,
                    "dy": None,
                },
            )
        elif kind in ("text-unrenderable-new", "text-binding-missing", "text-binding-stale"):
            lines = observed.get("candidate_lines") or []
            require(isinstance(lines, list) and all(isinstance(line, str) for line in lines), "Invalid candidate lines")
            merge_entry(
                document.setdefault("compatibility_bindings", {}),
                entity,
                {
                    "context_sha256": observed["context_sha256"],
                    "stats_sha256": observed["stats_sha256"],
                    **(
                        {"render_context_sha256": observed["render_context_sha256"]}
                        if "render_context_sha256" in observed
                        else {}
                    ),
                    "lines": lines,
                    "origin": "official-reference" if lines else "manual",
                },
            )
        elif kind == "render-context-changed":
            merge_entry(
                document.setdefault("compatibility_bindings", {}),
                entity,
                {"render_context_sha256": observed["render_context_sha256"]},
            )
        elif kind == "context-columns-changed":
            merge_entry(
                document,
                "context_columns",
                {
                    "bound_fields_sha256": observed["bound_fields_sha256"],
                    "target_fields_sha256": observed["target_fields_sha256"],
                    "added": columns(observed["added"], "neutral_value"),
                    "removed": columns(observed["removed"], "constant_value"),
                },
            )
        elif kind == "excluded-definition":
            merge_entry(
                document.setdefault("excluded", {}), entity, {"definition_sha256": observed["definition_sha256"]}
            )
        elif kind == "stale-exclusion":
            merge_entry(document.setdefault("excluded_removals", {}), entity, {})
        else:
            document.setdefault("unhandled", []).append(issue)
            continue
        drafted += 1
    counts = {
        entry_type: (
            int(entry_type in document)
            if entry_type in ("placement_rebase", "context_columns")
            else len(document.get(entry_type, {}))
        )
        for entry_type in ENTRY_TYPES
    }
    summary = {
        "issues": len(issues),
        "drafted": drafted,
        "entries": sum(counts.values()),
        "by_kind": dict(Counter(issue["kind"] for issue in issues)),
        "by_entry_type": {
            **counts,
            "blocked": len(document.get("blocked", [])),
            "unhandled": len(document.get("unhandled", [])),
        },
    }
    return document, summary


def draft(*, receipt, out=None, repo=ROOT):
    """Exclusively create both outputs after checking coverage and destinations."""
    receipt = safe_path(receipt)
    repo = safe_path(repo)
    out = safe_path(out or repo / ".cache" / "release" / receipt.parent.name / "policy-draft")
    require(out.is_relative_to(repo / ".cache") or not out.is_relative_to(repo), "Output must be under .cache/")
    outputs = [safe_path(out / name) for name in ("passive-tree.draft.json", "summary.json")]
    for path in outputs:
        require(not path.exists(), f"existing-output: {path}")
    document = decode(receipt.read_bytes())
    require(isinstance(document, dict), "Expected a build receipt")
    policy, summary = draft_coverage(document.get("coverage"))
    created = []
    try:
        for path, value in zip(outputs, (policy, summary)):
            source_io.write_new(path, source_io.encoded(value))
            created.append(path)
    except BaseException:
        for path in created:
            path.unlink()
        raise
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path, help="Forward release:build receipt.json")
    parser.add_argument(
        "--out", type=Path, help="New output directory (default: .cache/release/<build id>/policy-draft)"
    )
    args = parser.parse_args(argv)
    try:
        summary = draft(**vars(args))
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, f"policy-draft: {error}\n")
    print(source_io.encoded(summary).decode(), end="")


if __name__ == "__main__":
    main()
