"""Offline tests for RePoE.release.inputs: deterministic input packages, lock entries and the publish plan."""

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from RePoE.release.pins import decode, pin
from RePoE.release import assets, build, inputs, publish
from tests.release.test_build import serve
from tests.release.test_publish import GitRepoCase, Runner, git

TARGET = {"game": "poe2", "game_patch": "9.9", "realm": "international"}


def tree(root, files):
    for name, raw in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(raw)
    return root


class PackageTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.files = {"facts/a.json": b"{}\n", "supplement/b/c.json": b"[1]\n"}
        self.source = tree(self.root / "source", self.files)

    def tearDown(self):
        self.temporary.cleanup()

    def test_package_bytes_depend_only_on_the_files(self):
        first = inputs.stage({"ordinary": self.source}, TARGET, self.root / "one")
        os.utime(self.source / "facts/a.json", (1, 1))
        copy = tree(self.root / "copy", self.files)
        second = inputs.stage({"ordinary": copy}, TARGET, self.root / "two")
        self.assertEqual(first["assets"], second["assets"])
        spec = first["packages"]["ordinary"]
        self.assertEqual(spec["asset"], "repoe-input-ordinary-9.9.zip")
        self.assertEqual(list(first["assets"]), ["SHA256SUMS", "repoe-input-ordinary-9.9.zip"])
        with zipfile.ZipFile(self.root / "one/assets" / spec["asset"]) as archive:
            self.assertEqual(archive.namelist(), ["facts/a.json", "manifest.json", "supplement/b/c.json"])
            manifest = decode(archive.read("manifest.json"))
        self.assertEqual(manifest["schema"], "repoe-release-input/v1")
        self.assertEqual(manifest["files"], {name: pin(raw) for name, raw in self.files.items()})
        with zipfile.ZipFile(self.root / "one/assets" / spec["asset"]) as archive:
            self.assertEqual(spec["manifest"], pin(archive.read("manifest.json")))
            self.assertEqual(spec["expanded_bytes"], sum(info.file_size for info in archive.infolist()))

    def test_lock_entries_open_as_release_packages(self):
        staged = inputs.stage({"ordinary": self.source}, TARGET, self.root / "stage")
        (entry,) = inputs.lock_entries(staged, "inputs/9.9-1").values()
        self.assertEqual((entry["repository"], entry["tag"]), ("ackness/repoe", "inputs/9.9-1"))
        raw = (self.root / "stage/assets" / entry["asset"]).read_bytes()
        host = self.root / "host/ackness/repoe/releases/download/inputs/9.9-1"
        host.mkdir(parents=True)
        (host / entry["asset"]).write_bytes(raw)
        with mock.patch.dict(os.environ, {"REPOE_RELEASE_BASE_URL": serve(self, self.root / "host", redirect=True)}):
            package = build.open_package(None, "ordinary", entry, self.root / "cache", True)
        self.assertEqual(package.read("supplement/b/c.json"), b"[1]\n")
        # open_package downloaded through assets.fetch; the cache holds the verified bytes.
        self.assertEqual((self.root / "cache/downloads" / entry["sha256"]).read_bytes(), raw)

    def test_refuses_dot_files_unreadable_directories_and_overlapping_stages(self):
        (self.source / ".complete").write_text("x")
        with self.assertRaisesRegex(ValueError, "Dot file in an input"):
            inputs.collect(self.source)
        (self.source / ".complete").unlink()
        (self.source / ".git").mkdir()
        with self.assertRaisesRegex(ValueError, "Dot directory in an input"):
            inputs.collect(self.source)
        (self.source / ".git").rmdir()
        with mock.patch.object(os, "scandir", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                inputs.collect(self.source)
        with self.assertRaisesRegex(ValueError, "is inside the input"):
            inputs.stage({"ordinary": self.source}, TARGET, self.source / "stage")
        with self.assertRaisesRegex(ValueError, "is inside the stage"):
            inputs.stage({"ordinary": self.root / "stage/source"}, TARGET, self.root / "stage")
        # Through a symlink too (resolved paths).
        (self.root / "alias").symlink_to(self.source)
        with self.assertRaisesRegex(ValueError, "is inside the input"):
            inputs.stage({"ordinary": self.root / "alias"}, TARGET, self.source / "stage")

    def test_refuses_symlinks_and_a_reserved_manifest(self):
        (self.source / "link.json").symlink_to(self.source / "facts/a.json")
        with self.assertRaisesRegex(ValueError, "Not a regular file"):
            inputs.collect(self.source)
        (self.source / "link.json").unlink()
        (self.source / "manifest.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "reserved"):
            inputs.collect(self.source)
        with self.assertRaisesRegex(ValueError, "Invalid input package name"):
            inputs.package("bad-name", self.source, TARGET, self.root)


class MainTest(GitRepoCase):
    def setUp(self):
        super().setUp()
        self.head = git(self.repo, "rev-parse", "HEAD").strip()
        self.source = tree(Path(self.temporary.name) / "source", {"a.json": b"{}\n"})
        self.stage = Path(self.temporary.name) / "stage"

    def run_main(self, *extra, runner=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        runner = runner or Runner(self.repo)
        argv = ["--repo", str(self.repo), "--stage", str(self.stage), "--patch", "9.9"]
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                inputs.main([*argv, "--package", f"ordinary={self.source}", *extra], runner=runner)
                code = 0
            except SystemExit as exit:
                code = exit.code
        return code, stdout.getvalue() + stderr.getvalue(), runner

    def test_dry_run_stages_and_prints_the_lock_entries(self):
        code, output, runner = self.run_main()
        self.assertEqual(code, 0, output)
        self.assertIn(f"tag: inputs/9.9-1 -> {self.head}", output)
        self.assertIn("dry run: nothing was tagged", output)
        self.assertEqual(runner.calls, [])
        lock = json.loads((self.stage / "inputs-poe2-international-9.9/lock.json").read_text())
        self.assertEqual(lock["ordinary"]["tag"], "inputs/9.9-1")
        assets.validate(lock["ordinary"])

    def test_yes_publishes_with_the_next_number_and_never_reuses_one(self):
        git(self.repo, "tag", "-a", "-m", "earlier", "inputs/9.9-1", "HEAD")
        git(self.repo, "push", "-q", "origin", "refs/tags/inputs/9.9-1")
        self.commit("b.txt")
        git(self.repo, "push", "-q", "origin", "master")
        code, output, runner = self.run_main("--yes")
        self.assertEqual(code, 0, output)
        self.assertEqual(
            runner.commands(), ["gh auth status", "git tag --annotate", "git push origin", "gh release create"]
        )
        self.assertIn("inputs/9.9-2", runner.calls[-1])
        notes = (self.stage / "inputs-poe2-international-9.9/release-notes.md").read_text()
        self.assertIn('"tag": "inputs/9.9-2"', notes)
        # The game tags are another sequence: the remote's inputs/9.9-* tags do not advance game/9.9-<n>.
        tags = publish.list_remote_tags(self.repo, prefix="")
        self.assertIn("inputs/9.9-1", tags)
        self.assertIn("inputs/9.9-2", tags)
        head = git(self.repo, "rev-parse", "HEAD").strip()
        self.assertEqual(publish.plan(self.repo, "9.9", head, tags)["sequence"], 1)

    def test_yes_refuses_a_dirty_tree(self):
        (self.repo / "a.txt").write_text("changed")
        code, output, runner = self.run_main("--yes")
        self.assertEqual(code, 1)
        self.assertIn("refusing to publish", output)
        self.assertEqual(runner.commands(), ["gh auth status"])


if __name__ == "__main__":
    unittest.main()
