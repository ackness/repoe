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

from RePoE.release.pins import decode, encoded, pin
from RePoE.release import assets, build, crafting_catalog, inputs, publish
from tests.release.test_build import serve
from tests.release.test_crafting_catalog import crafting_package, fixture as crafting_fixture
from tests.release.test_publish import GitRepoCase, Runner, git

TARGET = {"game": "poe2", "game_patch": "9.9", "realm": "international"}


def tree(root, files):
    for name, raw in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(raw)
    return root


def china_files():
    """The documented descriptions:candidate / tables:candidate layout, without any raw resources."""
    files = {
        "capture/capture-receipt.json": encoded({"schema": "repoe-client-capture-receipt/v1"}),
        "capture/request.json": encoded({"schema": "repoe-client-capture-request/v1", "resources": []}),
        "capture/SHA256SUMS": b"a" * 64 + b"  Bundles2/_.index.bin\n",
    }
    candidates = {
        "stat-descriptions/china": (
            "repoe-native-descriptions/v1",
            {"descriptions.json": b"{}\n", "diagnostics.json": b"{}\n"},
        ),
        "display-tables/default": ("repoe-native-tables/v1", {"tables.json": b"{}\n"}),
        "display-tables/simplified-chinese": ("repoe-localized-tables/v1", {"tables.json": b"{}\n"}),
    }
    for directory, (format_, payloads) in candidates.items():
        payloads = {**payloads, "source-lock.json": b'{"schema_version": 1}\n'}
        files.update({f"{directory}/{name}": raw for name, raw in payloads.items()})
        files[f"{directory}/manifest.json"] = encoded(
            {
                "format": format_,
                "source_identity": {**TARGET, "realm": "china"},
                "files": {name: pin(raw) for name, raw in payloads.items()},
            }
        )
    return files


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

    def test_crafting_export_keeps_its_manifest_and_supplies_the_build_lock_fields(self):
        facts = crafting_fixture()
        expected, raw = crafting_package(facts, target=TARGET, producers=crafting_catalog.CURRENT_PRODUCERS)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        source = tree(self.root / "crafting", files)
        staged = inputs.stage({"crafting": source}, TARGET, self.root / "crafting-stage", tag="inputs/9.9-1")
        entry = json.loads((staged["directory"] / "lock.json").read_text())["crafting"]
        assets.validate(entry)
        for key in ("publication", "producer", "input_manifest", "manifest", "expanded_bytes"):
            self.assertEqual(entry[key], expected[key])
        archive_path = staged["directory"] / "assets" / entry["asset"]
        with zipfile.ZipFile(archive_path) as archive:
            self.assertEqual(archive.read("manifest.json"), files["manifest.json"])
            self.assertEqual(crafting_catalog.facts_document(archive, entry, TARGET), facts)
        build.write_new(self.root / "cache/downloads" / entry["sha256"], archive_path.read_bytes())
        opened = build.open_package(None, "crafting", entry, self.root / "cache", False)
        self.assertEqual(decode(opened.read("crafting.json")), facts)
        (source / "crafting.json").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "Member size mismatch|Byte pin mismatch"):
            inputs.stage({"crafting": source}, TARGET, self.root / "refused-crafting")

    def test_candidate_patch_and_realm_are_checked_in_every_package_and_envelope(self):
        manifests = (
            ("facts/manifest.json", "repoe-native-facts/v4"),
            ("base-items/supplement/manifest.json", "repoe-item-inheritance/v1"),
            ("passive-tree/supplement/manifest.json", "repoe-native-tables/v1"),
            ("stat-descriptions/item-descriptions/manifest.json", "repoe-native-descriptions/v1"),
            ("display-tables/traditional-chinese/manifest.json", "repoe-localized-tables/v1"),
        )
        for nested in (False, True):
            for member, format_ in manifests:
                for key, actual in (("game_patch", "8.8"), ("realm", "china"), ("game_patch", None)):
                    with self.subTest(nested=nested, member=member, key=key, actual=actual):
                        source = tree(self.root / "candidates", {"keep.json": b"{}"})
                        identity = {**TARGET, key: actual}
                        if actual is None:
                            del identity[key]
                        raw = encoded({"format": format_, "source_identity": identity})
                        if nested:
                            path = source / "ordinary-input.zip"
                            with zipfile.ZipFile(path, "w") as archive:
                                archive.writestr(member, raw)
                            expected_file = f"{path}!{member}"
                        else:
                            tree(source, {member: raw})
                            expected_file = str(source / member)
                        with self.assertRaises(ValueError) as error:
                            inputs.stage({"ordinary": source}, TARGET, self.root / "candidate-stage")
                        self.assertIn(expected_file, str(error.exception))
                        self.assertIn(f"expected {TARGET[key]!r}, actual {actual!r}", str(error.exception))
                        if nested:
                            path.unlink()
                        else:
                            (source / member).unlink()
        # All supported candidates can share one target, including additional packages.
        good = {member: encoded({"format": format_, "source_identity": TARGET}) for member, format_ in manifests}
        source = tree(self.root / "valid-candidates", good)
        inputs.stage({"ordinary": self.source, "supplements": source}, TARGET, self.root / "valid-stage")

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

    def test_china_text_accepts_the_current_derived_package_layout(self):
        files = china_files()
        source = tree(self.root / "china-text", files)
        staged = inputs.stage({"china_text": source}, {**TARGET, "realm": "china"}, self.root / "china-stage")
        spec = staged["packages"]["china_text"]
        with zipfile.ZipFile(staged["directory"] / "assets" / spec["asset"]) as archive:
            self.assertEqual(set(archive.namelist()), {*files, "manifest.json"})
            self.assertEqual(decode(archive.read("manifest.json"))["files"], {n: pin(r) for n, r in files.items()})

    def test_china_text_refuses_a_capture_directory_before_staging(self):
        source = tree(
            self.root / "capture",
            {
                "raw/Data/StatDescriptions/gem_stat_descriptions.csd": b"raw CSD",
                "raw/Data/Balance/GemEffects.datc64": b"raw DAT",
                "capture-receipt.json": b"{}\n",
                "source-lock.json": b"{}\n",
            },
        )
        out = self.root / "refused-stage"
        with self.assertRaisesRegex(ValueError, r"china_text: unexpected file capture-receipt.json"):
            inputs.stage({"china_text": source}, TARGET, out)
        self.assertFalse(out.exists())

    def test_china_text_refuses_any_extra_member_and_names_it(self):
        for number, member in enumerate(
            (
                "raw/Data/StatDescriptions/gem_stat_descriptions.csd",
                "display-tables/default/GemEffects.datc64",
                "capture/Bundles2/_.index.bin",
                "capture/capture.json",
                "stat-descriptions/china/unknown.json",
            )
        ):
            with self.subTest(member=member):
                source = tree(self.root / f"unsafe-{number}", {**china_files(), member: b"raw client bytes"})
                with self.assertRaises(ValueError) as error:
                    inputs.package("china_text", source, TARGET, self.root)
                self.assertIn(f"china_text: unexpected file {member};", str(error.exception))
                self.assertFalse((self.root / inputs.asset_name("china_text", TARGET["game_patch"])).exists())

    def test_china_text_requires_complete_pinned_candidates_and_receipts(self):
        source = tree(self.root / "china-text", china_files())
        member = "display-tables/default/tables.json"
        (source / member).unlink()
        with self.assertRaisesRegex(ValueError, f"missing derived file {member}"):
            inputs.collect(source, "china_text")
        (source / member).write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "derived file pins differ in display-tables/default/manifest.json"):
            inputs.collect(source, "china_text")
        tree(source, china_files())
        (source / "capture/capture-receipt.json").write_bytes(b"not JSON")
        with self.assertRaisesRegex(ValueError, "invalid derived file capture/capture-receipt.json"):
            inputs.collect(source, "china_text")


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
        self.assertIn(build.runtime_encoded(lock).decode().rstrip(), output)
        assets.validate(lock["ordinary"])

    def test_failed_packaging_keeps_the_previous_successful_stage(self):
        code, output, _ = self.run_main()
        self.assertEqual(code, 0, output)
        directory = self.stage / "inputs-poe2-international-9.9"
        before = {p.relative_to(directory): p.read_bytes() for p in directory.rglob("*") if p.is_file()}
        (self.source / "a.json").write_bytes(b"new ordinary bytes")
        invalid = tree(self.stage.parent / "invalid", {"manifest.json": b"{}"})
        code, output, _ = self.run_main("--package", f"later={invalid}")
        self.assertEqual(code, 1)
        self.assertIn("manifest.json is reserved", output)
        after = {p.relative_to(directory): p.read_bytes() for p in directory.rglob("*") if p.is_file()}
        self.assertEqual(after, before)
        for owner, function, error in (
            (inputs, "release_body", OSError("notes failed")),
            (publish, "release_steps", ValueError("Release assets differ")),
        ):
            with self.subTest(function=function), mock.patch.object(owner, function, side_effect=error):
                code, output, _ = self.run_main()
                self.assertEqual(code, 1)
                self.assertIn(str(error), output)
                self.assertEqual(
                    {p.relative_to(directory): p.read_bytes() for p in directory.rglob("*") if p.is_file()}, before
                )
        rename = Path.rename

        def fail_swap(path, target):
            if path.name == "pending":
                raise OSError("swap failed")
            return rename(path, target)

        with mock.patch.object(Path, "rename", fail_swap):
            code, output, _ = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("swap failed", output)
        self.assertEqual(
            {p.relative_to(directory): p.read_bytes() for p in directory.rglob("*") if p.is_file()}, before
        )
        code, output, _ = self.run_main()
        self.assertEqual(code, 0, output)
        self.assertNotEqual((directory / "lock.json").read_bytes(), before[Path("lock.json")])

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
