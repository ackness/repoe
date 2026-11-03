"""Historical selector regressions; fixtures do not require Lua or a client."""

import copy
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from RePoE import data_publication as package
from RePoE import pobr_historical_trees as trees
from RePoE import publication_index as pub

TARGET = {"game": "poe2", "game_patch": "9.1", "realm": "international"}
POLICY_PATH = trees.ROOT / "tools/pobr-data-adapter/policies/passive-tree/historical-attributes-v1.json"


def fixture():
    return [
        {
            "skill": 1200,
            "id": "1200",
            "name": "Attribute",
            "kind": "normal",
            "stats": ["+5 to Strength"],
            "unknown": {"preserve": [None, False, "é"]},
        },
        {"skill": 11741, "id": "11741", "name": "Attribute", "kind": "normal", "stats": ["+5 to Strength"]},
        # Identical text is not evidence of a selectable node.
        {"skill": 10, "id": "fixed", "name": "Strength", "kind": "normal", "stats": ["+5 to Strength"]},
        {"skill": 11, "id": "mixed", "stats": ["+5 to Strength", "+5 to Intelligence"]},
        {"skill": 12, "id": "layout", "unknown": None},
        {"skill": 13, "id": "notable", "name": "Brutal", "kind": "notable", "stats": ["+10 to Strength"]},
    ]


def binding(raw, selectors=(1200, 11741)):
    return {
        "input": package.pin(raw),
        "nodes": len(package.decode(raw)),
        "selectors": len(selectors),
        "selector_ids": package.pin(package.encoded(sorted(selectors))),
    }


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.nodes = fixture()
        self.raw = trees.runtime_encoded(self.nodes)
        self.binding = binding(self.raw)

    def test_selectors_preserve_identity_and_every_other_field_fixed_nodes_stay_fixed(self):
        raw, receipt = trees.project(self.raw, self.binding)
        actual = json.loads(raw)
        self.assertEqual(actual[0]["stats"], ["+5 to any Attribute"])
        self.assertEqual(actual[1]["stats"], ["+5 to any Attribute"])
        for original, node in zip(self.nodes, actual):
            expected = copy.deepcopy(original)
            if original["skill"] in (1200, 11741):
                expected["stats"] = ["+5 to any Attribute"]
            self.assertEqual(node, expected)
        self.assertEqual(actual[2]["stats"], ["+5 to Strength"])
        self.assertEqual(receipt["selector_ids"], [1200, 11741])
        self.assertEqual(receipt["unchanged_nodes"], 4)
        self.assertEqual(receipt["input"], package.pin(self.raw))
        self.assertEqual(receipt["output"], package.pin(raw))
        self.assertEqual((raw, receipt), trees.project(self.raw, self.binding))
        self.assertEqual(self.nodes, json.loads(self.raw), "projection must not mutate its input")

    def test_no_text_only_name_only_or_count_only_reclassification(self):
        for change in ("new_name", "new_id", "swapped_identity", "different_amount", "already_fixed"):
            nodes = copy.deepcopy(self.nodes)
            if change == "new_name":
                nodes[2].update(name="Attribute", id="10")
            elif change == "new_id":
                nodes[0].update(skill=200, id="200")
            elif change == "swapped_identity":
                nodes[0]["name"] = "Strength"
                nodes[2].update(name="Attribute", id="10")
            elif change == "different_amount":
                nodes[0]["stats"] = ["+10 to Strength"]
            else:
                nodes[0]["stats"] = ["+5 to any Attribute"]
            raw = trees.runtime_encoded(nodes)
            # Even rebinding a changed file cannot silently change reviewed IDs.
            review = {**self.binding, "input": package.pin(raw)}
            with self.subTest(change=change), self.assertRaises(ValueError):
                trees.project(raw, review)

    def test_shape_identity_inventory_and_raw_pin_guards(self):
        for key, value in (
            ("kind", "notable"),
            ("id", "not-the-reviewed-slug"),
            ("native_stats", {"flat": 5}),
            ("variants", [{"class": "Warrior", "stats": []}]),
            ("ascendancy_id", "Warrior1"),
            ("apply_to_armour", True),
            ("stats", ["+5 to Strength", "an extra effect"]),
            ("skill", True),
            ("skill", 11741),
        ):
            nodes = copy.deepcopy(self.nodes)
            nodes[0][key] = value
            raw = trees.runtime_encoded(nodes)
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                trees.project(raw, {**self.binding, "input": package.pin(raw)})
        with self.assertRaisesRegex(ValueError, "Byte pin"):
            trees.project(self.raw + b"\n", self.binding)
        with self.assertRaisesRegex(ValueError, "inventory"):
            trees.project(self.raw, {**self.binding, "nodes": 99})

    def test_duplicate_json_keys_fail_closed(self):
        raw = self.raw.replace(b'"skill": 1200', b'"skill": 99, "skill": 1200')
        with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
            trees.project(raw, {**self.binding, "input": package.pin(raw)})


class AssemblyTests(unittest.TestCase):
    def setUp(self):
        (trees.ROOT / ".cache").mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="historical-tree-test-", dir=trees.ROOT / ".cache")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo.git"
        subprocess.run(["git", "init", "--bare", "--quiet", str(self.repo)], check=True)
        self.members = {"data/9.1/base/stats.json": b'{"unchanged": true}\n', "data/overlay-common/x.json": b"{}\n"}
        self.versions = {}
        for version in ("0_1", "0_2", "0_3", "0_4"):
            raw = trees.runtime_encoded(fixture())
            self.members[f"data/9.1/base/passive_trees/{version}.json"] = raw
            self.versions[version] = binding(raw)
        snapshot = {
            "schema_version": 3,
            "poe_version": "9.1",
            "original": {"unknown": None, "limits": ["keep"]},
            "files": {
                name.removeprefix("data/9.1/"): package.pin(raw)["sha256"]
                for name, raw in self.members.items()
                if name.startswith("data/9.1/")
            },
        }
        self.members["data/9.1/manifest.json"] = trees.runtime_encoded(snapshot)
        self.policy = {
            "schema": trees.POLICY,
            "target": TARGET,
            "game_input": self.game(),
            "versions": self.versions,
            "evidence": {"scope": "synthetic fixture; not game facts"},
        }
        self.policy_path = self.root / "policy.json"

    def git(self, *args, data=None):
        env = dict(
            os.environ,
            GIT_AUTHOR_NAME="Synthetic test",
            GIT_AUTHOR_EMAIL="test@example.invalid",
            GIT_COMMITTER_NAME="Synthetic test",
            GIT_COMMITTER_EMAIL="test@example.invalid",
            GIT_AUTHOR_DATE="2000-01-01T00:00:00Z",
            GIT_COMMITTER_DATE="2000-01-01T00:00:00Z",
        )
        return subprocess.check_output(["git", "-C", str(self.repo), *args], input=data, env=env).decode().strip()

    def game(self, target=TARGET):
        manifest = {
            "schema": trees.PART_SCHEMA,
            "kind": "game",
            "target": target,
            "unknown": None,
            "limits": ["historical-source-not-certified"],
            "files": {name: package.pin(raw) for name, raw in self.members.items()},
        }
        manifest_raw = package.encoded(manifest)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, raw in {**self.members, "manifest.json": manifest_raw}.items():
                archive.writestr(name, raw)
        raw = buffer.getvalue()
        blob = self.git("hash-object", "-w", "--stdin", data=raw)
        tree = self.git("mktree", data=f"100644 blob {blob}\tgame-build-part.zip\n".encode())
        revision = self.git("commit-tree", tree, "-m", "Synthetic immutable package")
        return {
            "repository": pub.OWNER,
            "publication": "published",
            "revision": revision,
            "path": "game-build-part.zip",
            **package.pin(raw),
            "manifest": package.pin(manifest_raw),
            "expanded_bytes": len(manifest_raw) + sum(map(len, self.members.values())),
        }

    def assemble(self, name="out"):
        raw = package.encoded(self.policy)
        self.policy_path.write_bytes(raw)
        return trees.assemble(
            self.repo, self.policy_path, package.pin(raw)["sha256"], "historical-test", self.root / name
        )

    def test_all_versions_replay_exactly_and_only_trees_and_snapshot_change(self):
        result = self.assemble()
        self.assertEqual(result, self.assemble("replay"))
        raw = (self.root / "out/data.zip").read_bytes()
        self.assertEqual(raw, (self.root / "replay/data.zip").read_bytes())
        self.assertEqual(result["publication"], "local-only")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            _, manifest = package.archive_manifest(archive, result)
            self.assertFalse(manifest["production_ready"])
            self.assertEqual(manifest["retained_input_package"], self.policy["game_input"])
            self.assertEqual(manifest["retained_input_manifest"]["limits"], ["historical-source-not-certified"])
            self.assertIsNone(manifest["retained_input_manifest"]["unknown"])
            self.assertEqual(manifest["projection"]["policy"], self.policy)
            snapshot = json.loads(archive.read("data/9.1/manifest.json"))
            old = json.loads(self.members["data/9.1/manifest.json"])
            self.assertEqual(snapshot["original"], old["original"])
            self.assertEqual(set(manifest["files"]), set(self.members))
            for name, expected in manifest["files"].items():
                member = package.pinned(archive.read(name), expected)
                if "/passive_trees/" in name:
                    nodes = json.loads(member)
                    self.assertEqual(nodes[0]["stats"], ["+5 to any Attribute"])
                    self.assertEqual(nodes[1]["stats"], ["+5 to any Attribute"])
                    self.assertEqual(nodes[2:], fixture()[2:])
                    self.assertEqual(snapshot["files"][name.removeprefix("data/9.1/")], package.pin(member)["sha256"])
                elif not name.endswith("/manifest.json"):
                    self.assertEqual(member, self.members[name])

    def test_missing_unreviewed_or_stale_tree_and_snapshot_reject_without_output(self):
        original = copy.deepcopy(self.members)
        for case in (
            "missing",
            "extra_version",
            "stale_tree",
            "snapshot_pin",
            "snapshot_inventory",
            "snapshot_version",
        ):
            self.members = copy.deepcopy(original)
            path = "data/9.1/base/passive_trees/0_4.json"
            if case == "missing":
                del self.members[path]
            elif case == "extra_version":
                self.members["data/9.1/base/passive_trees/0_5.json"] = self.members[path]
            elif case == "stale_tree":
                self.members[path] += b"\n"
            else:
                snapshot = json.loads(self.members["data/9.1/manifest.json"])
                if case == "snapshot_pin":
                    snapshot["files"]["base/passive_trees/0_4.json"] = "0" * 64
                elif case == "snapshot_inventory":
                    del snapshot["files"]["base/passive_trees/0_4.json"]
                else:
                    snapshot["poe_version"] = "other"
                self.members["data/9.1/manifest.json"] = trees.runtime_encoded(snapshot)
            self.policy["game_input"] = self.game()
            with self.subTest(case=case), self.assertRaises(ValueError):
                self.assemble(case)
            self.assertFalse((self.root / case).exists())

    def test_wrong_policy_input_owner_publication_target_and_pins_reject(self):
        original = copy.deepcopy(self.policy)
        for case in ("owner", "publication", "zip_pin", "manifest_pin", "target"):
            self.policy = copy.deepcopy(original)
            game = self.policy["game_input"]
            if case == "owner":
                game["repository"] = "ackness/pobr"
            elif case == "publication":
                game["publication"] = "local-only"
            elif case == "zip_pin":
                game["sha256"] = "0" * 64
            elif case == "manifest_pin":
                game["manifest"]["sha256"] = "0" * 64
            else:
                game.update(self.game({**TARGET, "realm": "china"}))
            with self.subTest(case=case), self.assertRaises(ValueError):
                self.assemble(case)
            self.assertFalse((self.root / case).exists())
        self.policy_path.write_bytes(package.encoded(original))
        with self.assertRaisesRegex(ValueError, "Policy SHA"):
            trees.assemble(self.repo, self.policy_path, "0" * 64, "test", self.root / "bad-policy")
        self.assertFalse((self.root / "bad-policy").exists())

    def test_no_checkout_or_missing_input_fallback(self):
        self.policy["game_input"]["revision"] = "f" * 40
        # A convenient untracked snapshot cannot rescue a missing immutable input.
        (self.repo / "game-build-part.zip").write_bytes(b"not an immutable input")
        with self.assertRaisesRegex(ValueError, "Missing/invalid local Git metadata"):
            self.assemble()
        self.assertFalse((self.root / "out").exists())

    def test_existing_output_and_symlink_rejected(self):
        (self.root / "out").mkdir()
        with self.assertRaisesRegex(ValueError, "Fresh repository cache output"):
            self.assemble()
        (self.root / "linked").symlink_to(self.root / "out")
        with self.assertRaisesRegex(ValueError, "Symlink"):
            self.assemble("linked")

    def test_archive_failure_has_no_completion_marker(self):
        with patch.object(trees.zipfile.ZipFile, "writestr", side_effect=OSError("synthetic disk failure")):
            with self.assertRaisesRegex(OSError, "synthetic disk failure"):
                self.assemble()
        self.assertFalse((self.root / "out").exists())


@unittest.skipUnless(os.environ.get("REPOE_HISTORICAL_GAME_REPO"), "explicit pinned owner Git input not selected")
class PublishedReplayTests(unittest.TestCase):
    def test_all_published_versions_fixed_nodes_provenance_and_deterministic_replay(self):
        """Opt-in real-data test; never downloads or reads a PoBR snapshot/vendor."""
        repo = Path(os.environ["REPOE_HISTORICAL_GAME_REPO"])
        policy_raw = POLICY_PATH.read_bytes()
        policy = package.decode(policy_raw)
        game = policy["game_input"]
        original = pub.tree_blob(repo, game["revision"], game["path"], game)
        with tempfile.TemporaryDirectory(prefix="historical-real-", dir=trees.ROOT / ".cache") as root:
            out, replay = Path(root) / "out", Path(root) / "replay"
            first = trees.assemble(repo, POLICY_PATH, package.pin(policy_raw)["sha256"], "historical-test", out)
            second = trees.assemble(repo, POLICY_PATH, package.pin(policy_raw)["sha256"], "historical-test", replay)
            self.assertEqual(first, second)
            self.assertEqual((out / "data.zip").read_bytes(), (replay / "data.zip").read_bytes())
            with zipfile.ZipFile(io.BytesIO(original)) as old, zipfile.ZipFile(out / "data.zip") as new:
                _, previous = package.archive_manifest(old, game)
                _, manifest = package.archive_manifest(new, first)
                self.assertEqual(manifest["retained_input_manifest"], previous)
                changed = {name for name in previous["files"] if old.read(name) != new.read(name)}
                self.assertEqual(
                    changed,
                    {
                        "data/0.5.5.5/manifest.json",
                        *(f"data/0.5.5.5/base/passive_trees/{v}.json" for v in ("0_1", "0_2", "0_3", "0_4")),
                    },
                )
                self.assertEqual(set(manifest["files"]), set(previous["files"]))
                snapshot = json.loads(new.read("data/0.5.5.5/manifest.json"))
                for v, count in (("0_1", 288), ("0_2", 300), ("0_3", 293), ("0_4", 293)):
                    path = f"data/0.5.5.5/base/passive_trees/{v}.json"
                    before, after = json.loads(old.read(path)), json.loads(new.read(path))
                    self.assertEqual(len(before), len(after))
                    changed_nodes = 0
                    for a, b in zip(before, after):
                        expected = copy.deepcopy(a)
                        if a.get("name") == "Attribute":
                            expected["stats"] = ["+5 to any Attribute"]
                            changed_nodes += 1
                        self.assertEqual(b, expected)
                    self.assertEqual(changed_nodes, count)
                    self.assertEqual(manifest["projection"]["trees"][v]["selectors"], count)
                    nodes = {n["skill"]: n for n in after}
                    for skill in (1200, 11741):
                        self.assertEqual(nodes[skill]["stats"], ["+5 to any Attribute"])
                    self.assertIn("+10 to Strength", nodes[5710]["stats"], "Brutal is not a selector")
                    self.assertEqual(
                        snapshot["files"][f"base/passive_trees/{v}.json"], package.pin(new.read(path))["sha256"]
                    )
                for name, expected_pin in manifest["files"].items():
                    package.pinned(new.read(name), expected_pin)


if __name__ == "__main__":
    unittest.main()
