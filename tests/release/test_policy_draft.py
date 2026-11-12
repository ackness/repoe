"""Policy drafting copies adapter observations and leaves every decision unreviewed."""

import contextlib
import copy
import io
from pathlib import Path
import random
import tempfile
import unittest
from unittest import mock

from RePoE.release import policy_draft
from RePoE.release.pins import decode, encoded


def issue(kind, entity="node", *, action="emitted-with-gap", **observed):
    return {
        "domain": "passive-tree",
        "kind": kind,
        "entity": entity,
        "action": action,
        "message": f"Needs review: {entity}",
        **({"observed": observed} if observed else {}),
    }


def coverage(issues):
    return {
        "format": "pobr-build-coverage/v1",
        "jobs": {"tree": {"counts": {}, "issues": issues}},
    }


class PolicyDraftTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.receipt = self.root / "build-id" / "receipt.json"
        self.receipt.parent.mkdir()
        self.out = self.root / "draft"

    def run_draft(self, issues=(), *, out=None):
        self.receipt.write_bytes(encoded({"coverage": coverage(list(issues))}))
        summary = policy_draft.draft(receipt=self.receipt, out=out or self.out, repo=self.repo)
        return decode(((out or self.out) / "passive-tree.draft.json").read_bytes()), summary

    def test_every_mapped_kind_and_summary(self):
        placement = {
            "reference_sha256": "reference copied verbatim",
            "legacy_source_sha256": "legacy copied verbatim",
            "moved_skills_sha256": "skills copied verbatim",
            "moved_count": 27,
        }
        frame = {
            "start_skill": 42,
            "reference_start_node_sha256": "start copied verbatim",
            "member_skills_sha256": "members copied verbatim",
        }
        text = {"context_sha256": "context", "stats_sha256": "stats"}
        issues = [
            issue("placement-rebase", "passive-tree", **placement, review="reviewed", reason="must not be copied"),
            issue("ascendancy-frame", "Druid2", **frame, dx=100, dy=-100),
            issue("text-unrenderable-new", "3", **text, candidate_lines=["Official line"]),
            issue("text-binding-missing", "1", **text, render_context_sha256="render", candidate_lines=[]),
            issue("text-binding-stale", "2", **text),
            issue("render-context-changed", "4", render_context_sha256="new render", bound_render_context_sha256="old"),
            issue(
                "context-columns-changed",
                "PassiveSkills",
                bound_fields_sha256="bound",
                target_fields_sha256="target",
                added=[{"field": "Z", "neutral_value": 12}, "A"],
                removed=[{"field": "Old", "constant_value": 42}],
            ),
            issue("excluded-definition", "excluded-node", definition_sha256="definition"),
            issue("stale-exclusion", "stale-node", definition_sha256="unchanged"),
        ]
        draft, summary = self.run_draft(issues)
        self.assertEqual(draft["placement_rebase"], {**placement, "review": "unreviewed", "reason": ""})
        self.assertEqual(
            draft["ascendancy_frames"]["Druid2"],
            {**frame, "dx": None, "dy": None, "review": "unreviewed", "reason": ""},
        )
        bindings = draft["compatibility_bindings"]
        self.assertEqual(
            bindings["3"],
            {**text, "lines": ["Official line"], "origin": "official-reference", "review": "unreviewed", "reason": ""},
        )
        self.assertEqual(
            bindings["1"],
            {
                **text,
                "render_context_sha256": "render",
                "lines": [],
                "origin": "manual",
                "review": "unreviewed",
                "reason": "",
            },
        )
        self.assertEqual(bindings["2"], {**text, "lines": [], "origin": "manual", "review": "unreviewed", "reason": ""})
        self.assertEqual(bindings["4"], {"render_context_sha256": "new render", "review": "unreviewed", "reason": ""})
        self.assertEqual(
            draft["context_columns"],
            {
                "bound_fields_sha256": "bound",
                "target_fields_sha256": "target",
                "added": [
                    {"field": field, "neutral_value": None, "review": "unreviewed", "reason": ""}
                    for field in ("A", "Z")
                ],
                "removed": [{"field": "Old", "constant_value": None, "review": "unreviewed", "reason": ""}],
                "review": "unreviewed",
                "reason": "",
            },
        )
        self.assertEqual(
            draft["excluded"]["excluded-node"],
            {"definition_sha256": "definition", "review": "unreviewed", "reason": ""},
        )
        self.assertEqual(draft["excluded_removals"]["stale-node"], {"review": "unreviewed", "reason": ""})
        self.assertEqual(
            summary,
            {
                "issues": 9,
                "drafted": 9,
                "entries": 9,
                "by_kind": {item["kind"]: 1 for item in issues},
                "by_entry_type": {
                    "placement_rebase": 1,
                    "ascendancy_frames": 1,
                    "compatibility_bindings": 4,
                    "context_columns": 1,
                    "excluded": 1,
                    "excluded_removals": 1,
                    "blocked": 0,
                    "unhandled": 0,
                },
            },
        )
        self.assertEqual(decode((self.out / "summary.json").read_bytes()), summary)
        self.assertEqual(
            len(issues),
            summary["drafted"] + summary["by_entry_type"]["blocked"] + summary["by_entry_type"]["unhandled"],
        )

    def test_issue_accounting_includes_merged_and_repeated_issues(self):
        text = issue("text-binding-missing", context_sha256="context", stats_sha256="stats")
        render = issue("render-context-changed", render_context_sha256="render")
        unknown = issue("future-kind", action="listed", nested={"preserve": [None, 2]})
        blocked = issue("placement-rebase", action="quarantined")
        issues = [text, render, copy.deepcopy(render), unknown, copy.deepcopy(unknown), blocked, copy.deepcopy(blocked)]
        original = copy.deepcopy(issues)
        draft, summary = self.run_draft(issues)
        self.assertEqual(summary["drafted"], 3)
        self.assertEqual(summary["entries"], 1)
        self.assertEqual(draft["unhandled"], [unknown, unknown])
        self.assertEqual(draft["blocked"], [blocked, blocked])
        self.assertEqual(
            len(issues),
            summary["drafted"] + len(draft["blocked"]) + len(draft["unhandled"]),
        )
        self.assertEqual(summary["issues"], len(issues))
        self.assertEqual(issues, original)

    def test_unknown_and_quarantined_issues_are_preserved_verbatim(self):
        unknown = issue("future-kind", nested={"unfamiliar": [1, None, {"keep": True}]})
        blocked = issue("reference-orbit-mismatch", action="quarantined", reference={"orbit": 4})
        quarantined_mapping = issue("text-unrenderable-new", "unsafe-node", action="quarantined")
        draft, summary = self.run_draft([unknown, blocked, quarantined_mapping])
        self.assertEqual(draft["unhandled"], [unknown])
        self.assertEqual(draft["blocked"], [blocked, quarantined_mapping])
        self.assertEqual(draft["blocked_note"], "needs a newer official reference or an exclusion")
        self.assertNotIn("compatibility_bindings", draft)
        self.assertEqual(summary["entries"], 0)
        self.assertEqual(summary["by_entry_type"]["blocked"], 2)
        self.assertEqual(summary["by_entry_type"]["unhandled"], 1)

    def test_only_coverage_is_read_and_other_domains_are_ignored(self):
        other = {**issue("text-binding-missing"), "domain": "gem-quality"}
        tree = issue("render-context-changed", render_context_sha256="verbatim observation")
        # These paths need not exist: the emitter must never follow them.
        self.receipt.write_bytes(
            encoded(
                {
                    "coverage": coverage([other, tree]),
                    "jobs": {"tree": {"receipt": "/missing/producer-receipt.json"}},
                    "inputs": {"facts": "/missing/facts", "tree": "/missing/tree.json"},
                }
            )
        )
        original = Path.read_bytes
        reads = []

        def read(path):
            reads.append(path)
            return original(path)

        with (
            mock.patch.object(Path, "read_bytes", read),
            mock.patch("hashlib.sha256", side_effect=AssertionError("The adapter owns hashes")),
        ):
            summary = policy_draft.draft(receipt=self.receipt, out=self.out, repo=self.repo)
        self.assertEqual(reads, [self.receipt])
        self.assertEqual(
            decode((self.out / "passive-tree.draft.json").read_bytes())["compatibility_bindings"]["node"],
            {"render_context_sha256": "verbatim observation", "review": "unreviewed", "reason": ""},
        )
        self.assertEqual(summary["issues"], 1)
        self.assertEqual(summary["drafted"], 1)
        self.assertEqual(summary["entries"], 1)
        self.assertEqual(summary["by_kind"], {"render-context-changed": 1})

    def test_cli_default_output_and_printed_summary(self):
        self.receipt.write_bytes(encoded({"coverage": coverage([])}))
        stdout = io.StringIO()
        original = policy_draft.draft
        with (
            contextlib.redirect_stdout(stdout),
            mock.patch.object(policy_draft, "draft", side_effect=lambda **args: original(**args, repo=self.repo)),
        ):
            policy_draft.main(["--receipt", str(self.receipt)])
        out = self.repo / ".cache/release/build-id/policy-draft"
        self.assertEqual(stdout.getvalue().encode(), (out / "summary.json").read_bytes())
        self.assertEqual((out / "passive-tree.draft.json").read_bytes(), b"{}\n")
        summary = decode(stdout.getvalue())
        self.assertEqual(summary["issues"], 0)
        self.assertEqual(summary["drafted"], 0)
        self.assertEqual(summary["entries"], 0)
        self.assertEqual(summary["by_kind"], {})
        self.assertTrue(all(count == 0 for count in summary["by_entry_type"].values()))

    def test_existing_either_output_is_refused_without_writing_the_other(self):
        for name in ("passive-tree.draft.json", "summary.json"):
            with self.subTest(name=name):
                out = self.out / name
                out.mkdir(parents=True)
                existing = out / name
                existing.write_bytes(b"keep")
                with self.assertRaisesRegex(ValueError, "existing-output"):
                    self.run_draft(out=out)
                self.assertEqual(existing.read_bytes(), b"keep")
                self.assertEqual(list(out.iterdir()), [existing])

    def test_outside_cache_in_repository_is_refused_even_for_untracked_paths(self):
        for name in ("", "release/new-policy", "tools/pobr-data-adapter/policies/new", "untracked", ".cache-adjacent"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "Output must be under .cache"):
                self.run_draft(out=self.repo / name)
        self.assertEqual(list(self.repo.iterdir()), [])

    def test_symlinks_cannot_bypass_output_guards(self):
        self.out.symlink_to(self.repo, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "Symlink"):
            self.run_draft()
        self.out.unlink()
        self.out.mkdir()
        output = self.out / "summary.json"
        output.symlink_to(self.root / "missing.json")
        with self.assertRaisesRegex(ValueError, "Symlink"):
            self.run_draft()
        self.assertFalse((self.out / "passive-tree.draft.json").exists())
        cache = self.repo / ".cache"
        cache.mkdir()
        (cache / "escape").symlink_to(self.repo, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "Symlink"):
            self.run_draft(out=cache / "escape" / "untracked")
        self.assertFalse((self.repo / "untracked").exists())

    def test_dot_dot_cannot_bypass_output_guards(self):
        paths = (
            self.repo / ".cache/../untracked",
            self.root / "outside/../repo/untracked",
            self.repo / ".cache/draft/../../release/new-policy",
            Path(".cache/../untracked"),
        )
        with contextlib.chdir(self.repo):
            for out in paths:
                with self.subTest(out=out), self.assertRaisesRegex(ValueError, "unsafe path"):
                    self.run_draft(out=out)
        self.assertEqual(list(self.repo.iterdir()), [])

    def test_issue_and_job_order_do_not_change_output_bytes(self):
        issues = [
            issue("text-binding-missing", "12", context_sha256="context", stats_sha256="stats"),
            issue("render-context-changed", "12", render_context_sha256="render"),
            issue(
                "ascendancy-frame",
                "Z",
                start_skill=42,
                reference_start_node_sha256="start",
                member_skills_sha256="members",
            ),
            issue(
                "ascendancy-frame",
                "A",
                start_skill=43,
                reference_start_node_sha256="other",
                member_skills_sha256="others",
            ),
            issue("future", nested={"z": 2, "a": 1}),
            issue("future", nested={"z": 3, "a": 1}),
            issue("no-reference", action="quarantined"),
            issue(
                "context-columns-changed",
                bound_fields_sha256="bound",
                target_fields_sha256="target",
                added=["Z", "A"],
                removed=["OldZ", "OldA"],
            ),
        ]
        original = copy.deepcopy(issues)
        self.run_draft(issues)
        baseline = [(self.out / name).read_bytes() for name in ("passive-tree.draft.json", "summary.json")]
        self.assertEqual(issues, original)
        random.Random(12).shuffle(issues)
        document = coverage([])
        document["jobs"] = {"z-job": {"issues": issues[::2]}, "a-job": {"issues": issues[1::2]}}
        for item in issues:
            if item["kind"] == "context-columns-changed":
                item["observed"]["added"].reverse()
                item["observed"]["removed"].reverse()
        self.receipt.write_bytes(encoded({"coverage": document}))
        out = self.root / "shuffled"
        policy_draft.draft(receipt=self.receipt, out=out, repo=self.repo)
        self.assertEqual([(out / name).read_bytes() for name in ("passive-tree.draft.json", "summary.json")], baseline)
        binding = decode(baseline[0])["compatibility_bindings"]["12"]
        self.assertEqual(binding["render_context_sha256"], "render")
        self.assertEqual(binding["context_sha256"], "context")

    def test_conflicting_evidence_and_missing_coverage_refuse_without_outputs(self):
        issues = [
            issue("render-context-changed", render_context_sha256="one"),
            issue("render-context-changed", render_context_sha256="two"),
        ]
        with self.assertRaisesRegex(ValueError, "Conflicting draft evidence"):
            self.run_draft(issues)
        self.assertFalse(self.out.exists())
        self.receipt.write_bytes(encoded({"jobs": {}}))
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as error:
            policy_draft.main(["--receipt", str(self.receipt), "--out", str(self.out)])
        self.assertEqual(error.exception.code, 1)
        self.assertIn("policy-draft: Expected a forward build receipt with coverage", stderr.getvalue())
        self.assertFalse(self.out.exists())

    def test_failed_second_write_removes_only_outputs_created_by_this_run(self):
        self.receipt.write_bytes(encoded({"coverage": coverage([])}))
        original = policy_draft.source_io.write_new
        destination = self.out / "summary.json"

        def fail(path, raw):
            if path == destination:
                raise OSError("synthetic write failure")
            return original(path, raw)

        with mock.patch.object(policy_draft.source_io, "write_new", fail), self.assertRaisesRegex(OSError, "synthetic"):
            policy_draft.draft(receipt=self.receipt, out=self.out, repo=self.repo)
        self.assertFalse((self.out / "passive-tree.draft.json").exists())
        self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
