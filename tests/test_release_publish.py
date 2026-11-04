"""Offline tests for RePoE.release.publish: staging, SHA256SUMS, sequence numbers, preflight, release body."""

import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

from RePoE.data_publication import encoded, pin
from RePoE.release import build, publish

TARGET = {"game": "poe2", "game_patch": "9.9", "realm": "international"}
COMMIT = "c" * 40
CONTRACT = {"repository": "ackness/pobr", "version": 1, "tag": "contract/1.0", "commit": "d" * 40}


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout.decode()


class StageTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.build_dir = self.root / "build"
        self.build_dir.mkdir()
        build.write_zip(self.build_dir / "game-build-part.zip", {"manifest.json": b"{}\n", "data/a.json": b"[]\n"})
        self.receipt = {
            "schema": build.RECEIPT,
            "target": TARGET,
            "producer": {"repository": "ackness/repoe", "commit": COMMIT, "dirty": False, "contract": CONTRACT},
            "summary": {"generated-identical": 2, "frozen": 1, "passthrough-identical": 1},
            "provenance": {"generated": 2, "passthrough": 1, "frozen": 1},
            "reference": {"package": "previous", "members_identical": True},
        }
        self.write_build()

    def tearDown(self):
        self.temporary.cleanup()

    def write_build(self, receipt=None):
        receipt_raw = encoded(receipt or self.receipt)
        (self.build_dir / "receipt.json").write_bytes(receipt_raw)
        package = {
            "schema": build.PACKAGE,
            "target": TARGET,
            "receipt": {"path": "receipt.json", **pin(receipt_raw)},
            "manifest": {"class": "retained-reference-manifest", **pin(b"{}\n")},
            "package": {
                "path": "game-build-part.zip",
                **build.file_pin(self.build_dir / "game-build-part.zip"),
                "identical_to_reference": True,
            },
        }
        (self.build_dir / "package.json").write_bytes(encoded(package))

    def test_stages_the_three_assets_under_their_release_names(self):
        staged = publish.stage(self.build_dir, self.root / "stage")
        assets = self.root / "stage" / "assets"
        self.assertEqual(sorted(p.name for p in assets.iterdir()), ["SHA256SUMS", "pobr-game-9.9.zip", "receipt.json"])
        self.assertEqual(list(staged["assets"]), ["SHA256SUMS", "pobr-game-9.9.zip", "receipt.json"])
        zip_raw = (self.build_dir / "game-build-part.zip").read_bytes()
        self.assertEqual((assets / "pobr-game-9.9.zip").read_bytes(), zip_raw)
        self.assertEqual((assets / "receipt.json").read_bytes(), (self.build_dir / "receipt.json").read_bytes())
        receipt_sha = hashlib.sha256((assets / "receipt.json").read_bytes()).hexdigest()
        self.assertEqual(
            (assets / "SHA256SUMS").read_text(),
            f"{hashlib.sha256(zip_raw).hexdigest()}  pobr-game-9.9.zip\n{receipt_sha}  receipt.json\n",
        )
        for name in ("pobr-game-9.9.zip", "receipt.json"):
            self.assertEqual(staged["assets"][name], build.file_pin(assets / name))

    def test_sha256sums_is_gnu_format_sorted_by_name(self):
        text = publish.sha256sums({"z.zip": "1" * 64, "a.json": "2" * 64})
        self.assertEqual(text, f"{'2' * 64}  a.json\n{'1' * 64}  z.zip\n")
        # The output checks with sha256sum -c.
        staged = publish.stage(self.build_dir, self.root / "stage")
        result = subprocess.run(
            ["sha256sum", "--check", "--strict", "SHA256SUMS"],
            cwd=staged["directory"] / "assets",
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_staging_rejects_a_build_that_does_not_match_its_package_pins(self):
        (self.build_dir / "receipt.json").write_bytes(b"{}\n")
        with self.assertRaisesRegex(ValueError, "receipt.json differs"):
            publish.stage(self.build_dir, self.root / "stage")
        self.write_build()
        with zipfile.ZipFile(self.build_dir / "game-build-part.zip", "a") as archive:
            archive.writestr("extra.json", b"{}")
        with self.assertRaisesRegex(ValueError, "differs from package.json"):
            publish.stage(self.build_dir, self.root / "stage")

    def test_staging_requires_the_contract_in_the_receipt(self):
        producer = {k: v for k, v in self.receipt["producer"].items() if k != "contract"}
        self.write_build({**self.receipt, "producer": producer})
        with self.assertRaisesRegex(ValueError, "PoBR contract"):
            publish.stage(self.build_dir, self.root / "stage")

    def test_staging_replaces_only_its_own_directory(self):
        foreign = self.root / "foreign"
        foreign.mkdir()
        (foreign / "keep.txt").write_text("x")
        with self.assertRaisesRegex(ValueError, "non-publish directory"):
            publish.stage(self.build_dir, foreign)
        publish.stage(self.build_dir, self.root / "stage")
        publish.stage(self.build_dir, self.root / "stage")  # its own: replaced

    def test_release_body(self):
        staged = publish.stage(self.build_dir, self.root / "stage")
        body = publish.release_body(staged, "game/9.9-3", 3)
        zip_pin = staged["assets"]["pobr-game-9.9.zip"]
        for expected in (
            "poe2 9.9 (international), sequence 3",
            f"`ackness/repoe@{COMMIT}` (the commit `game/9.9-3` names)",
            "`pobr_data::CONTRACT_VERSION` 1, built against `ackness/pobr` `contract/1.0`",
            f"{zip_pin['bytes']} bytes, SHA-256 `{zip_pin['sha256']}`",
            "Members: 2 generated, 1 passthrough, 1 frozen; root manifest: retained-reference-manifest",
            "Classes: frozen 1, generated-identical 2, passthrough-identical 1",
            "`mise run data:bump ackness/repoe game/9.9-3`",
        ):
            self.assertIn(expected, body)
        self.assertEqual(body, publish.release_body(staged, "game/9.9-3", 3))
        message = publish.tag_message(staged, "game/9.9-3")
        self.assertIn(f"{zip_pin['sha256']}  pobr-game-9.9.zip\n", message)
        steps = publish.commands(staged, "game/9.9-3", COMMIT)
        self.assertEqual(steps[0][-2:], ["game/9.9-3", COMMIT])
        self.assertEqual(steps[1], ["git", "push", "origin", "refs/tags/game/9.9-3"])
        self.assertEqual(
            [Path(a).name for a in steps[2] if a.startswith(str(staged["directory"] / "assets"))],
            ["SHA256SUMS", "pobr-game-9.9.zip", "receipt.json"],
        )
        self.assertIn("--verify-tag", steps[2])


class SequenceTest(unittest.TestCase):
    def test_next_sequence(self):
        self.assertEqual(publish.next_sequence([], "0.5.5.5"), 1)
        tags = [
            "game/0.5.5.5-1",
            "game/0.5.5.5-10",
            "game/0.5.5.5-2",
            "game/0.5.5.5.1-40",  # another patch
            "game/0.5.5-99",  # another patch
            "game/0.5.5.5-03",  # not a sequence number
            "game/0.5.5.5-4-rc",
            "locale/0.5.5.5-50",
            "handoff/rollback-0.5.5.4.2-20261101",
        ]
        self.assertEqual(publish.next_sequence(tags, "0.5.5.5"), 11)
        self.assertEqual(publish.next_sequence(tags, "0.5.5.5.1"), 41)
        self.assertEqual(publish.next_sequence(tags, "0.6.0"), 1)

    def test_remote_tags_peel_annotated_tags(self):
        output = (
            f"{'1' * 40}\trefs/tags/game/9.9-1\n"
            f"{'2' * 40}\trefs/tags/game/9.9-1^{{}}\n"
            f"{'3' * 40}\trefs/tags/game/9.9-2\n"
        )
        self.assertEqual(publish.remote_tags(output), {"game/9.9-1": "2" * 40, "game/9.9-2": "3" * 40})


class PreflightTest(unittest.TestCase):
    """Temporary repositories: ``origin`` is a local bare repository."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.origin, self.repo = root / "origin.git", root / "repo"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "master", str(self.origin)], check=True)
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.repo)], check=True, capture_output=True)
        git(self.repo, "config", "user.email", "test@example.invalid")
        git(self.repo, "config", "user.name", "test")
        git(self.repo, "checkout", "-q", "-b", "master")
        self.commit("a.txt")
        git(self.repo, "push", "-q", "origin", "master")

    def tearDown(self):
        self.temporary.cleanup()

    def commit(self, name):
        (self.repo / name).write_text(name)
        git(self.repo, "add", name)
        git(self.repo, "commit", "-q", "-m", name)
        return git(self.repo, "rev-parse", "HEAD").strip()

    def test_clean_commit_on_master_passes(self):
        commit, problems, warnings = publish.preflight(self.repo)
        self.assertEqual((commit, problems, warnings), (git(self.repo, "rev-parse", "HEAD").strip(), [], []))

    def test_refuses_a_dirty_tree(self):
        (self.repo / "a.txt").write_text("changed")
        self.assertRegex(publish.preflight(self.repo)[1][0], "working tree is not clean")
        git(self.repo, "checkout", "a.txt")
        (self.repo / "untracked.txt").write_text("x")
        self.assertRegex(publish.preflight(self.repo)[1][0], "working tree is not clean.*untracked.txt")

    def test_refuses_a_commit_not_on_origin_master(self):
        commit = self.commit("b.txt")
        self.assertEqual(publish.preflight(self.repo)[1], [f"HEAD {commit} is not on origin/master"])
        # The check uses the fetched remote state, not a stale local ref.
        git(self.repo, "push", "-q", "origin", "master")
        git(self.repo, "update-ref", "refs/remotes/origin/master", "HEAD~1")
        self.assertEqual(publish.preflight(self.repo)[1], [])
        self.assertEqual(publish.preflight(self.repo, fetch=False)[1], [])

    def test_unreachable_remote_is_a_warning(self):
        git(self.repo, "remote", "set-url", "origin", str(Path(self.temporary.name) / "missing.git"))
        commit, problems, warnings = publish.preflight(self.repo)
        self.assertEqual(problems, [])
        self.assertRegex(warnings[0], "could not fetch origin/master")
        self.assertIsNone(publish.list_remote_tags(self.repo))
        sequence, problems = publish.plan_sequence(self.repo, "9.9", commit, None)
        self.assertIsNone(sequence)
        self.assertRegex(problems[0], "could not be listed")

    def test_sequence_from_remote_tags(self):
        first = git(self.repo, "rev-parse", "HEAD").strip()
        self.assertEqual(publish.list_remote_tags(self.repo), {})
        git(self.repo, "tag", "-a", "-m", "one", "game/9.9-1")
        git(self.repo, "push", "-q", "origin", "refs/tags/game/9.9-1")
        tags = publish.list_remote_tags(self.repo)
        self.assertEqual(tags, {"game/9.9-1": first})
        self.assertEqual(
            publish.plan_sequence(self.repo, "9.9", first, tags), (2, ["HEAD is already published as game/9.9-1"])
        )
        second = self.commit("b.txt")
        self.assertEqual(publish.plan_sequence(self.repo, "9.9", second, tags), (2, []))
        git(self.repo, "tag", "game/9.9-2")  # local only
        self.assertRegex(publish.plan_sequence(self.repo, "9.9", second, tags)[1][0], "local tag game/9.9-2")


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    unittest.main()
