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

from RePoE.client import export_receipt
from RePoE.release.pins import decode, encoded, pin
from RePoE.release import assets, build, crafting_catalog, inputs, publish
from tests.client.test_export_receipt import DIRTY, candidate, receipt_for
from tests.release.test_build import serve, zip_bytes
from tests.release.test_crafting_catalog import crafting_package, fixture as crafting_fixture
from tests.release.test_publish import GitRepoCase, Runner, git

TARGET = {"game": "poe2", "game_patch": "9.9", "realm": "international"}


def tree(root, files):
    for name, raw in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(raw)
    return root


def receipted(files, **identity):
    """``files`` plus the export receipt beside each candidate directory, exported from ``identity``."""
    receipts = {
        export_receipt.receipt_name(name.rpartition("/")[0]): receipt_for(raw, **identity)
        for name, raw in files.items()
        if name.endswith("/manifest.json")
    }
    return {**files, **receipts}


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
        files[f"{directory}/manifest.json"] = candidate(
            format_, {**TARGET, "realm": "china"}, files={name: pin(raw) for name, raw in payloads.items()}
        )
    return receipted(files)


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
        expected, raw = crafting_package(
            facts, target=TARGET, producers=crafting_catalog.CURRENT_PRODUCERS, receipted=True
        )
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        source = tree(self.root / "crafting", files)
        beside = source.with_name(export_receipt.receipt_name(source.name))
        beside.write_bytes(encoded(expected["export_receipt"]))
        staged = inputs.stage({"crafting": source}, TARGET, self.root / "crafting-stage", tag="inputs/9.9-1")
        entry = json.loads((staged["directory"] / "lock.json").read_text())["crafting"]
        assets.validate(entry)
        for key in ("publication", "producer", "input_manifest", "manifest", "expanded_bytes", "export_receipt"):
            self.assertEqual(entry[key], expected[key])
        self.assertEqual(staged["receipts"], {"crafting:export_receipt": expected["export_receipt"]})
        archive_path = staged["directory"] / "assets" / entry["asset"]
        with zipfile.ZipFile(archive_path) as archive:
            self.assertEqual(set(archive.namelist()), set(files))
            self.assertEqual(archive.read("manifest.json"), files["manifest.json"])
            self.assertEqual(crafting_catalog.facts_document(archive, entry, TARGET), facts)
        build.write_new(self.root / "cache/downloads" / entry["sha256"], archive_path.read_bytes())
        opened = build.open_package(None, "crafting", entry, self.root / "cache", False)
        self.assertEqual(decode(opened.read("crafting.json")), facts)
        beside.unlink()
        with self.assertRaises(FileNotFoundError):
            inputs.stage({"crafting": source}, TARGET, self.root / "missing-crafting-receipt")
        beside.write_bytes(encoded(expected["export_receipt"]))
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
        for depth in (0, 1, 2):
            for member, format_ in manifests:
                for key, actual in (("game_patch", "8.8"), ("realm", "china"), ("game_patch", None)):
                    with self.subTest(depth=depth, member=member, key=key, actual=actual):
                        source = tree(self.root / "candidates", {"keep.json": b"{}"})
                        identity = {**TARGET, key: actual}
                        if actual is None:
                            del identity[key]
                        raw = encoded({"format": format_, "source_identity": identity})
                        if depth:
                            path = source / "ordinary-input.ZIP"
                            members = {member: raw}
                            for _ in range(depth - 1):
                                members = {"inner.zip": zip_bytes(members)}
                            build.write_zip(path, members)
                            expected_file = f"{path}!" + "inner.zip!" * (depth - 1) + member
                        else:
                            tree(source, {member: raw})
                            expected_file = str(source / member)
                        with self.assertRaises(ValueError) as error:
                            inputs.stage({"ordinary": source}, TARGET, self.root / "candidate-stage")
                        self.assertIn(expected_file, str(error.exception))
                        self.assertIn(f"expected {TARGET[key]!r}, actual {actual!r}", str(error.exception))
                        if depth:
                            path.unlink()
                        else:
                            (source / member).unlink()
        # All supported candidates can share one target, including additional packages.
        good = receipted({member: candidate(format_) for member, format_ in manifests})
        source = tree(self.root / "valid-candidates", good)
        staged = inputs.stage({"ordinary": self.source, "supplements": source}, TARGET, self.root / "valid-stage")
        self.assertEqual(
            sorted(staged["receipts"]),
            sorted(f"supplements:{name}" for name in good if name.endswith(export_receipt.SUFFIX)),
        )

    def test_a_new_candidate_needs_the_field_and_the_receipt_that_pins_its_manifest(self):
        member, beside = "facts/manifest.json", "facts.export-receipt.json"
        manifest = candidate("repoe-native-facts/v4")
        files = {
            member: manifest,
            beside: receipt_for(manifest),
            # Embedded copies are payloads; a historical envelope zip keeps its frozen producer identity.
            "player/parent-manifest.json": manifest,
            "player/input-manifest.json": encoded({"format": "repoe-native-facts/v4", "source_identity": TARGET}),
        }
        stripped = encoded({"format": "repoe-native-facts/v4", "source_identity": TARGET})
        # The pairing rule itself is tested in tests/client/test_export_receipt.py; here, that packaging applies it
        # with the exporters' formats, so a new export stripped of the field is not taken for a historical one.
        for number, (message, change) in enumerate(
            (
                (f"ordinary: {member}: no export receipt {beside}", {beside: None}),
                (f"ordinary: {member}: candidate manifest lacks producer_receipt", {member: stripped}),
            )
        ):
            with self.subTest(message=message):
                changed = {name: raw for name, raw in {**files, **change}.items() if raw is not None}
                with self.assertRaisesRegex(ValueError, message):
                    inputs.stage({"ordinary": tree(self.root / f"case-{number}", changed)}, TARGET, self.root / "out")
        # Staging accepts a rehearsal, so it can be built and served locally; publishing it is refused.
        rehearsal = {**files, beside: receipt_for(manifest, rehearsal=True, dirty_paths=DIRTY)}
        staged = inputs.stage({"ordinary": tree(self.root / "rehearsal", rehearsal)}, TARGET, self.root / "out")
        self.assertEqual(publish.unpublishable(staged["receipts"]), [f"ordinary:{beside} is a rehearsal"])

    def test_every_export_format_requires_a_receipt_including_inside_an_archive(self):
        for index, format_ in enumerate(sorted(export_receipt.FORMATS)):
            for nested in (False, True):
                with self.subTest(format=format_, nested=nested):
                    raw = encoded({"format": format_, "source_identity": TARGET})
                    source = self.root / f"stripped-{index}-{nested}"
                    files = {"candidate/manifest.json": raw}
                    if nested:
                        source.mkdir()
                        build.write_zip(source / "envelope.ZIP", files)
                    else:
                        tree(source, files)
                    with self.assertRaisesRegex(ValueError, "candidate/manifest.json: no export receipt"):
                        inputs.stage({"ordinary": source}, TARGET, self.root / "stripped-stage")
        # A copied receipt keeps its rehearsal flag through archive packaging.
        manifest = candidate()
        source = self.root / "nested-rehearsal"
        source.mkdir()
        build.write_zip(source / "envelope.zip", receipted({"candidate/manifest.json": manifest}, rehearsal=True))
        staged = inputs.stage({"ordinary": source}, TARGET, self.root / "nested-stage")
        self.assertEqual(
            publish.unpublishable(staged["receipts"]),
            ["ordinary:envelope.zip!candidate.export-receipt.json is a rehearsal"],
        )
        # A bare candidate at an archive root is not a release package manifest.
        (source / "envelope.zip").unlink()
        build.write_zip(source / "envelope.zip", {"manifest.json": manifest})
        with self.assertRaisesRegex(ValueError, "envelope.zip!manifest.json: candidate manifest must be inside"):
            inputs.stage({"ordinary": source}, TARGET, self.root / "bare-stage")

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
        tree(source, china_files())
        # One export receipt per candidate directory, derived from the candidate list.
        for directory in inputs.CHINA_CANDIDATES:
            beside = source / export_receipt.receipt_name(directory)
            original = beside.read_bytes()
            beside.unlink()
            with self.assertRaisesRegex(ValueError, f"missing derived file {directory}.export-receipt.json"):
                inputs.collect(source, "china_text")
            beside.write_bytes(original.replace(b'"china"', b'"international"'))
            with self.assertRaisesRegex(ValueError, f"china_text: {directory}/manifest.json: receipt target differs"):
                inputs.stage({"china_text": source}, {**TARGET, "realm": "china"}, self.root / "refused")
            beside.write_bytes(original)


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

    def test_export_receipts_must_be_clean_and_from_a_commit_on_origin_master(self):
        manifest = candidate("repoe-native-facts/v4")
        beside = self.source / "facts.export-receipt.json"
        tree(self.source, {"facts/manifest.json": manifest})
        unpushed = self.commit("unpushed.txt")
        git(self.repo, "reset", "-q", "--hard", self.head)
        for expected, identity in (
            ("ordinary:facts.export-receipt.json is a rehearsal", {"rehearsal": True, "dirty_paths": DIRTY}),
            ("ordinary:facts.export-receipt.json is a rehearsal", {"rehearsal": True}),
            (f"export commit {unpushed} is not on origin/master (1 receipts", {"commit": unpushed}),
            (f"export commit {'e' * 40} cannot be checked against origin/master", {"commit": "e" * 40}),
        ):
            with self.subTest(expected=expected):
                beside.write_bytes(receipt_for(manifest, **{"commit": self.head, **identity}))
                for mode in ((), ("--yes",)):
                    code, output, runner = self.run_main(*mode)
                    self.assertEqual(code, 1, output)
                    self.assertIn("publish refused:", output)
                    self.assertIn(expected, output)
                    self.assertEqual([c for c in runner.commands() if c != "gh auth status"], [])
        self.assertEqual(git(self.repo, "tag", "--list"), "")
        beside.write_bytes(receipt_for(manifest, commit=self.head))
        code, output, runner = self.run_main("--yes")
        self.assertEqual(code, 0, output)
        self.assertIn("gh release create", runner.commands())

    def test_crafting_receipt_reaches_the_existing_publication_and_ancestry_gates(self):
        _, raw = crafting_package(
            crafting_fixture(), target=TARGET, producers=crafting_catalog.CURRENT_PRODUCERS, receipted=True
        )
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            source = tree(self.stage.parent / "crafting", {name: archive.read(name) for name in archive.namelist()})
        beside = source.with_name(export_receipt.receipt_name(source.name))
        manifest = (source / "manifest.json").read_bytes()
        for changes, reason in (
            ({"rehearsal": True, "dirty_paths": DIRTY}, "crafting:export_receipt is a rehearsal"),
            ({"rehearsal": True}, "crafting:export_receipt is a rehearsal"),
            ({"commit": "e" * 40}, "cannot be checked against origin/master"),
            ({}, None),
        ):
            beside.write_bytes(receipt_for(manifest, **{"commit": self.head, **changes}))
            for mode in ((), ("--yes",)) if reason else ((),):
                with self.subTest(changes=changes, mode=mode):
                    code, output, runner = self.run_main("--package", f"crafting={source}", *mode)
                    self.assertEqual(code, 1 if reason else 0, output)
                    if reason:
                        self.assertIn(reason, output)
                    self.assertEqual([c for c in runner.commands() if c != "gh auth status"], [])
        self.assertEqual(git(self.repo, "tag", "--list"), "")

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
