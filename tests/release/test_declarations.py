"""Offline declaration replay and staged-input preflight; never writes real release/."""

import contextlib
import copy
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from RePoE.release import assets, build, declarations, inputs
from RePoE.release.pins import decode, pin
from tests.client.test_export_receipt import candidate
from tests.release.test_build import zip_bytes
from tests.release.test_inputs import receipted


class ReplayTest(unittest.TestCase):
    def test_real_replay_matches_bytes_after_three_h_markers_and_committed_expect(self):
        fixture = decode((build.ROOT / "tests/release/fixtures/declaration-replay-0.5.5.8.json").read_bytes())
        self.assertEqual(set(fixture["sources"]), {"entries", "facts_identity", "previous"})
        self.assertIn("Release", fixture["sources"]["entries"])
        self.assertIn("verified", fixture["sources"]["previous"])
        predecessor = build.ROOT / fixture["transition"]["from"]
        lock = decode((predecessor / "inputs.lock.json").read_bytes())
        frozen = decode((predecessor / "frozen-inputs.json").read_bytes())
        before = copy.deepcopy((lock, frozen, fixture))
        result, new_frozen, report = declarations.derive(
            lock,
            frozen,
            predecessor.name,
            fixture["entries"],
            {"root": "facts", "sha256": fixture["facts_identity"]},
            fixture["previous"],
            fixture["transition"]["patch"],
            {"intl_text"},
            carry={"legacy"},
        )
        self.assertEqual((lock, frozen, fixture), before)
        self.assertTrue(report["expect_absent"])
        self.assertNotIn("expect", result)
        self.assertEqual(
            {tuple(item["path"][2:]) for item in report["review"] if item.get("kind") == "staged-marker"},
            {("ordinary", "publication"), ("intl_text", "publication"), ("crafting", "publication_status")},
        )
        self.assertEqual(
            [
                (item["path"][-2:], item["value"])
                for item in report["review"]
                if item.get("kind") == "carried-publication"
            ],
            [(["legacy", "publication"], "published")],
        )
        expected = (build.ROOT / "release/0.5.5.8/inputs.lock.json").read_bytes()
        expected_without_expect = decode(expected)
        expected_without_expect.pop("expect")
        marked = copy.deepcopy(result)
        marked["packages"]["ordinary"]["publication"] = "pending"
        marked["packages"]["intl_text"]["publication"] = "pending"
        marked["packages"]["crafting"]["publication_status"] = "pending"
        self.assertEqual(build.runtime_encoded(marked), build.runtime_encoded(expected_without_expect))
        result["packages"]["ordinary"]["publication"] = "pending"
        result["packages"]["intl_text"]["publication"] = "pending"
        result["packages"]["crafting"]["publication_status"] = "pending"
        result["expect"] = decode(expected)["expect"]
        differences = declarations.changed_fields(decode(expected), result)
        self.assertEqual(build.runtime_encoded(result), expected, f"Differing JSON paths: {differences}")
        expected_frozen = (build.ROOT / "release/0.5.5.8/frozen-inputs.json").read_bytes()
        differences = declarations.changed_fields(decode(expected_frozen), new_frozen)
        self.assertEqual(build.runtime_encoded(new_frozen), expected_frozen, f"Differing JSON paths: {differences}")


class PresentationTest(unittest.TestCase):
    def test_values_are_bounded_one_line_summaries(self):
        self.assertEqual(
            declarations.display_value({"tag": "inputs/0.6-1", "sha256": "a" * 64, "secret": [1, 2]}),
            "tag=inputs/0.6-1, sha256=" + "a" * 64,
        )
        self.assertEqual(
            declarations.display_value({"category": "compat", "bytes": 3, "reason": "long"}), "category=compat, bytes=3"
        )
        self.assertEqual(declarations.display_value([{"large": "value"}]), "list (1 items)")
        self.assertEqual(declarations.display_value({"nested": {"value": "large"}}), "object keys: nested")
        self.assertEqual(len(declarations.display_value("x" * 200)), 120)
        self.assertEqual(declarations.display_value("first\nsecond"), "first second")
        self.assertEqual(declarations.display_value(5), "5")

    def test_frozen_rename_and_shared_provenance_collapse_without_changing_report(self):
        entry = {"category": "compat", "bytes": 3, "sha256": "a" * 64}
        before = {
            "target": {"game_patch": "0.5"},
            "members": {
                "data/0.5/value.json": entry,
                "data/overlay-common/shared.json": {**entry, "carried_from": {"tag": "old"}},
            },
        }
        after = {
            "target": {"game_patch": "0.6"},
            "members": {
                "data/0.6/value.json": {**entry, "carried_from": {"tag": "latest"}},
                "data/overlay-common/shared.json": {**entry, "carried_from": {"tag": "latest"}},
                "data/0.6/new.json": entry,
            },
        }
        changes = declarations.changed_fields(before, after, ("frozen-inputs.json",))
        original = copy.deepcopy(changes)
        lines = declarations.change_lines(changes)
        self.assertEqual(changes, original)
        self.assertEqual(lines[0], "frozen-inputs.json: 1 field changes, 2 carried members, 1 additions, 0 removals")
        self.assertIn("frozen member data/0.5/value.json -> data/0.6/value.json (carried)", lines)
        self.assertIn("frozen member data/overlay-common/shared.json (carried)", lines)
        self.assertIn("None -> category=compat, bytes=3", "\n".join(lines))
        self.assertNotIn("None -> {", "\n".join(lines))

    def test_changed_payload_is_not_hidden_as_a_carry(self):
        before = {
            "target": {"game_patch": "0.5"},
            "members": {"data/0.5/value.json": {"bytes": 1, "category": "compat"}},
        }
        after = {
            "target": {"game_patch": "0.6"},
            "members": {"data/0.6/value.json": {"bytes": 2, "category": "compat"}},
        }
        lines = declarations.change_lines(declarations.changed_fields(before, after, ("frozen-inputs.json",)))
        self.assertEqual(lines[0], "frozen-inputs.json: 1 field changes, 0 carried members, 1 additions, 1 removals")
        self.assertFalse(any("(carried)" in line for line in lines))


class NextPatchTest(unittest.TestCase):
    def setUp(self):
        config = build.ROOT / "release/0.5.5.8"
        self.lock = decode((config / "inputs.lock.json").read_bytes())
        self.frozen = decode((config / "frozen-inputs.json").read_bytes())
        self.identity = "9" * 64
        self.entries = {
            name: {
                "repository": "ackness/repoe",
                "tag": "inputs/0.5.5.9-1",
                "asset": f"repoe-input-{name}-0.5.5.9.zip",
                **pin(name.encode()),
            }
            for name in ("ordinary", "crafting", "intl_text")
        }
        self.entries["crafting"]["input_manifest"] = {"bytes": 1, "sha256": self.identity}
        self.previous = {
            "tag": "game/0.5.5.8-1",
            "manifest": pin(b"synthetic manifest"),
            "expanded_bytes": 123,
            "game_patch": "0.5.5.8",
        }

    def derive(self, carry):
        return declarations.derive(
            self.lock,
            self.frozen,
            "0.5.5.8",
            self.entries,
            {"root": "new-facts", "sha256": self.identity},
            self.previous,
            "0.5.5.9",
            carry=carry,
        )

    def test_next_real_patch_replaces_entries_and_overwrites_every_provenance_hop(self):
        before = copy.deepcopy((self.lock, self.frozen, self.entries))
        lock, frozen, _ = self.derive({"legacy"})
        self.assertEqual((self.lock, self.frozen, self.entries), before)
        self.assertNotIn("expect", lock)
        self.assertEqual(lock["packages"]["previous"]["tag"], "game/0.5.5.8-1")
        self.assertEqual(
            lock["facts"],
            {
                "package": "ordinary",
                "root": "new-facts",
                "identities": {"original": self.identity, "rebound": self.identity},
            },
        )
        self.assertEqual(list(lock["facts"]), ["package", "root", "identities"])
        for name, spec in self.entries.items():
            self.assertEqual(lock["packages"][name], spec)
            for field in ("publication", "publication_status"):
                self.assertNotIn(field, lock["packages"][name])
        for member, old in self.frozen["members"].items():
            self.assertIn("carried_from", old)
            renamed = member.replace("data/0.5.5.8/", "data/0.5.5.9/", 1)
            self.assertEqual(
                frozen["members"][renamed]["carried_from"],
                {
                    "package": self.frozen["source"],
                    "member": member,
                    "game_patch": "0.5.5.8",
                    "tag": "game/0.5.5.8-1",
                },
            )

    def test_omitted_intl_text_requires_carry_and_reports_its_pending_publication(self):
        del self.entries["intl_text"]
        with self.assertRaisesRegex(ValueError, r"unconfirmed-carry: use --carry for \['intl_text'\]"):
            self.derive({"legacy"})
        lock, _, report = self.derive({"legacy", "intl_text"})
        self.assertEqual(lock["packages"]["intl_text"], self.lock["packages"]["intl_text"])
        self.assertEqual(list(lock["packages"]), list(self.lock["packages"]))
        self.assertEqual(lock["packages"]["intl_text"]["publication"], "pending")
        item = next(
            item
            for item in report["review"]
            if item["path"] == ["inputs.lock.json", "packages", "intl_text", "publication"]
        )
        self.assertEqual(item["value"], "pending")
        self.assertEqual(item["kind"], "carried-publication")


class DeclarationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.releases = self.root / "release"
        self.releases.mkdir()
        releases = mock.patch.object(build, "RELEASES", self.releases)
        releases.start()
        self.addCleanup(releases.stop)
        self.config = self.releases / "0.5-3"
        self.out = self.releases / "0.6"
        self.cache = self.root / "cache"
        self.old_target = {"game": "poe2", "game_patch": "0.5", "realm": "international"}
        self.target = {**self.old_target, "game_patch": "0.6"}
        files = {"native/value.json": b"{}\n"}
        files["native/manifest.json"] = candidate(
            "repoe-native-facts/v4",
            self.target,
            status="partial-candidate",
            production_ready=False,
            files={"value.json": pin(files["native/value.json"])},
        )
        self.facts = {"root": "native", "sha256": pin(files["native/manifest.json"])["sha256"]}
        self.stage = self.make_stage("new", receipted(files))
        self.entries = decode((self.stage / "lock.json").read_bytes())
        # A synthetic crafting lock entry uses an ordinary input zip: only its identity
        # cross-check is relevant to this command; crafting payloads are validated by inputs.
        self.entries["crafting"] = {**self.entries["ordinary"], "input_manifest": pin(files["native/manifest.json"])}
        self.write_stage()
        manifest = build.runtime_encoded({"target": self.old_target, "files": {"data/0.5/value.json": pin(b"old")}})
        self.game_zip = zip_bytes({"manifest.json": manifest, "data/0.5/value.json": b"old"})
        self.previous = {
            "tag": "game/0.5-3",
            "manifest": pin(manifest),
            "expanded_bytes": len(manifest) + 3,
            "game_patch": "0.5",
        }
        self.lock = {
            "schema": build.SCHEMAS["inputs.lock.json"],
            "target": self.old_target,
            "packages": {
                "ordinary": {"revision": "c" * 40, "path": "old.zip", "publication": "pending"},
                "legacy": {**self.entries["ordinary"], "publication": "published"},
                "crafting": {"revision": "d" * 40, "path": "stale.zip", "publication": "pending"},
                "previous": self.entries["ordinary"],
            },
            "reference": "previous",
            "facts": {"package": "ordinary", "archive": "old.zip", "handoff": "old.json"},
            "expect": {"package": pin(self.game_zip)},
        }
        entry = {
            **pin(b"old"),
            "category": "compatibility",
            "origin": "curated",
            "reason": "review required",
            "exit": "replace producer",
            "unchanged_since_0.5.5.4.2": True,
            "carried_from": {"tag": "game/ancient-1"},
        }
        self.frozen = {
            "schema": build.SCHEMAS["frozen-inputs.json"],
            "target": self.old_target,
            "source": "previous",
            "categories": {"compatibility": "Historical compatibility bytes"},
            "members": {"data/0.5/value.json": entry, "data/overlay-common/shared.json": copy.deepcopy(entry)},
        }
        self.domains = {
            "schema": build.SCHEMAS["domains.json"],
            "target": self.target,
            "jobs": [],
            "manifest": {"mode": "fresh"},
        }
        self.write_config()
        build.write_new(self.out / "domains.json", build.runtime_encoded(self.domains))
        build.write_new(self.cache / "downloads" / pin(self.game_zip)["sha256"], self.game_zip)
        self.tag = mock.patch.object(build, "tag_commit", return_value="a" * 40)
        self.tag.start()
        self.addCleanup(self.tag.stop)

    def make_stage(self, name, files, target=None):
        source = self.root / (name + "-source")
        for member, raw in files.items():
            build.write_new(source / member, raw)
        out = self.root / (name + "-stage")
        inputs.stage({"ordinary": source}, target or self.target, out, tag="inputs/0.6-1")
        return out

    def write_stage(self):
        (self.stage / "lock.json").write_bytes(build.runtime_encoded(self.entries))

    def write_config(self):
        self.config.mkdir(exist_ok=True)
        for name, document in (("inputs.lock.json", self.lock), ("frozen-inputs.json", self.frozen)):
            (self.config / name).write_bytes(build.runtime_encoded(document))

    def derive(self, **kwargs):
        arguments = dict(
            lock=self.lock,
            frozen=self.frozen,
            directory=self.config.name,
            entries=self.entries,
            facts_identity=self.facts,
            previous=self.previous,
            patch="0.6",
            carry={"legacy"},
        )
        return declarations.derive(**{**arguments, **kwargs})

    def declare(self, **kwargs):
        arguments = dict(
            config=self.config, staged=self.stage, patch="0.6", out=self.out, cache=self.cache, carry={"legacy"}
        )
        return declarations.declare(**{**arguments, **kwargs})

    def assert_no_outputs(self):
        for name in ("inputs.lock.json", "frozen-inputs.json"):
            self.assertFalse((self.out / name).exists())

    def test_replace_carry_append_order_and_no_stale_fields(self):
        self.entries = {"text_b": self.entries["ordinary"], **self.entries, "text_a": self.entries["ordinary"]}
        result, frozen, report = self.derive(added={"text_a", "text_b"})
        self.assertEqual(list(result["packages"]), ["ordinary", "legacy", "crafting", "previous", "text_b", "text_a"])
        for name, entry in self.entries.items():
            self.assertEqual(result["packages"][name], entry)
            self.assertFalse({"revision", "path", "publication"} & result["packages"][name].keys())
        self.assertEqual(result["packages"]["legacy"], self.lock["packages"]["legacy"])
        self.assertEqual(report["carried_packages"], ["legacy"])
        self.assertEqual(
            result["facts"],
            {
                "package": "ordinary",
                "root": "native",
                "identities": {"original": self.facts["sha256"], "rebound": self.facts["sha256"]},
            },
        )
        self.assertEqual(list(result["facts"]["identities"]), ["original", "rebound"])
        self.assertNotIn("expect", result)
        self.assertEqual(list(frozen["members"]), ["data/0.6/value.json", "data/overlay-common/shared.json"])
        for member, old in self.frozen["members"].items():
            new = frozen["members"][member.replace("data/0.5/", "data/0.6/", 1)]
            self.assertEqual(
                {k: v for k, v in new.items() if k != "carried_from"},
                {k: v for k, v in old.items() if k != "carried_from"},
            )
            self.assertEqual(
                new["carried_from"], {"package": "previous", "member": member, "game_patch": "0.5", "tag": "game/0.5-3"}
            )
            self.assertEqual(list(new["carried_from"]), ["package", "member", "game_patch", "tag"])
        counts = [item["count"] for item in report["review"] if "count" in item]
        self.assertEqual(counts, [2] * 5)

    def test_nested_output_refuses_before_writing_or_opening_packages(self):
        nested = self.config / "0.6"
        before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        with (
            mock.patch.object(declarations.policy_rebinding, "staged_packages") as packages,
            self.assertRaisesRegex(ValueError, "invalid-output: new declaration must be a direct child of release/"),
        ):
            self.declare(out=nested)
        packages.assert_not_called()
        self.assertFalse(nested.exists())
        self.assertEqual({path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}, before)

    def test_overlapping_and_release_caches_refuse_before_any_write(self):
        before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        for cache in (
            self.config,
            self.config / "cache",
            self.stage / "cache",
            self.stage,
            self.out,
            self.out / "cache",
            self.releases / "cache",
            self.releases,
            self.root,
        ):
            with (
                self.subTest(cache=cache),
                mock.patch.object(declarations.policy_rebinding, "staged_packages") as packages,
                self.assertRaisesRegex(ValueError, "invalid-cache"),
            ):
                self.declare(cache=cache)
            packages.assert_not_called()
            self.assert_no_outputs()
            self.assertEqual({path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}, before)

    def test_cache_symlink_refuses_before_any_write(self):
        cache = self.root / "symlink-cache"
        cache.symlink_to(self.cache, target_is_directory=True)
        with (
            mock.patch.object(declarations.policy_rebinding, "staged_packages") as packages,
            self.assertRaisesRegex(ValueError, "Symlink"),
        ):
            self.declare(cache=cache)
        packages.assert_not_called()
        self.assert_no_outputs()

    def test_cache_internal_symlinks_refuse_without_touching_target(self):
        digest = self.entries["ordinary"]["sha256"]
        previous_digest = self.lock["expect"]["package"]["sha256"]
        paths = (
            "downloads",
            "packages",
            f"downloads/{digest}",
            f"packages/{digest}",
            f"packages/{digest}.partial",
            f"downloads/.{previous_digest}.{os.getpid()}.partial",
        )
        stage_before = {path: path.read_bytes() for path in self.stage.rglob("*") if path.is_file()}
        for index, relative_path in enumerate(paths):
            with self.subTest(path=relative_path):
                cache = self.root / f"unsafe-cache-{index}"
                victim = self.root / f"victim-{index}"
                sentinel = victim / digest / "sentinel"
                build.write_new(sentinel, b"preserve victim")
                link = cache / relative_path
                link.parent.mkdir(parents=True, exist_ok=True)
                target = victim / "absent" if relative_path.startswith("downloads/") else victim
                link.symlink_to(target, target_is_directory=True)
                with (
                    mock.patch.object(declarations.policy_rebinding, "staged_packages") as packages,
                    self.assertRaisesRegex(ValueError, "Symlink"),
                ):
                    self.declare(cache=cache)
                packages.assert_not_called()
                self.assert_no_outputs()
                self.assertEqual(sentinel.read_bytes(), b"preserve victim")
                self.assertFalse((victim / "absent").exists())
                self.assertEqual(
                    {path: path.read_bytes() for path in self.stage.rglob("*") if path.is_file()}, stage_before
                )

    def test_previous_from_expect_and_zip_and_full_trio_loads(self):
        with mock.patch.object(assets, "download", side_effect=AssertionError("offline")):
            report = self.declare()
        _, lock, _, frozen, _ = build.load_config(self.out)
        self.assertTrue(report["changes"])
        previous = lock["packages"]["previous"]
        self.assertEqual(
            previous,
            {
                "repository": "ackness/repoe",
                "tag": "game/0.5-3",
                "asset": "pobr-game-0.5.zip",
                **pin(self.game_zip),
                "manifest": self.previous["manifest"],
                "expanded_bytes": self.previous["expanded_bytes"],
            },
        )
        self.assertEqual(
            list(previous), ["repository", "tag", "asset", "bytes", "sha256", "manifest", "expanded_bytes"]
        )
        self.assertEqual(list(lock["packages"]["ordinary"]), list(self.entries["ordinary"]))
        self.assertEqual(frozen["target"], self.target)

    def test_pure_refusals(self):
        cases = [
            ({"patch": "0.5"}, "unchanged-patch"),
            ({"patch": "../0.6"}, "invalid-patch"),
            ({"directory": "wrong"}, "invalid-predecessor"),
            ({"previous": {**self.previous, "game_patch": "0.4"}}, "target-mismatch"),
            ({"previous": {**self.previous, "tag": "game/0.5-1"}}, "target-mismatch"),
            ({"added": {"ordinary"}}, "invalid-added-package"),
            ({"carry": set()}, r"unconfirmed-carry: use --carry for \['legacy'\]"),
            ({"carry": {"legacy", "previous"}}, "invalid-carry"),
            ({"carry": {"legacy", "ordinary"}}, "invalid-carry"),
            ({"carry": {"legacy", "missing"}}, "invalid-carry"),
            ({"facts_identity": {"root": "../bad", "sha256": self.facts["sha256"]}}, "Unsafe"),
            ({"facts_identity": {"root": "facts", "sha256": "f" * 64}}, "crafting-input-mismatch"),
            ({"entries": {**self.entries, "new": self.entries["ordinary"]}}, "unadded-package"),
            ({"entries": {**self.entries, "previous": self.entries["ordinary"]}}, "reference-package"),
            ({"entries": {"crafting": self.entries["crafting"]}}, "missing-counterpart"),
            ({"entries": {}}, "missing-inputs"),
        ]
        for arguments, message in cases:
            with self.subTest(arguments=arguments), self.assertRaisesRegex(ValueError, message):
                self.derive(**arguments)
        for tag in ("inputs/0.6-<n>", "inputs/<patch>-<n>", "inputs/0.6-0", "inputs/0.7-1"):
            entries = copy.deepcopy(self.entries)
            entries["ordinary"]["tag"] = tag
            with self.subTest(tag=tag), self.assertRaisesRegex(ValueError, "invalid.*tag"):
                self.derive(entries=entries)

    def test_predecessor_reference_and_frozen_source_must_be_previous(self):
        for reference, source in (("legacy", "previous"), ("previous", "legacy"), ("legacy", "legacy")):
            with self.subTest(reference=reference, source=source):
                self.lock["reference"] = reference
                self.frozen["source"] = source
                self.write_config()
                with (
                    mock.patch.object(declarations.policy_rebinding, "staged_packages") as packages,
                    self.assertRaisesRegex(ValueError, "invalid-predecessor"),
                ):
                    self.declare()
                packages.assert_not_called()
                self.assert_no_outputs()

    def test_missing_expect_and_crafting_cross_check_refuse_before_writes(self):
        del self.lock["expect"]
        self.write_config()
        with self.assertRaisesRegex(ValueError, "missing-expect"):
            self.declare()
        self.assert_no_outputs()
        self.lock["expect"] = {"package": pin(self.game_zip)}
        self.write_config()
        self.entries["crafting"]["input_manifest"]["sha256"] = "e" * 64
        self.write_stage()
        with self.assertRaisesRegex(ValueError, "crafting-input-mismatch"):
            self.declare()
        self.assert_no_outputs()

    def test_missing_domains_and_wrong_target_and_invalid_trio_refuse(self):
        path = self.out / "domains.json"
        path.unlink()
        with self.assertRaisesRegex(ValueError, "missing-domains"):
            self.declare()
        self.assert_no_outputs()
        for document, message in (
            ({**self.domains, "target": self.old_target}, "target-mismatch"),
            ({**self.domains, "schema": "wrong"}, "expected schema"),
        ):
            path.write_bytes(build.runtime_encoded(document))
            with self.assertRaisesRegex(ValueError, message):
                self.declare()
            self.assert_no_outputs()

    def test_existing_outputs_and_symlinks_refuse(self):
        for filename in ("inputs.lock.json", "frozen-inputs.json"):
            path = self.out / filename
            path.write_bytes(b"keep")
            with self.assertRaisesRegex(ValueError, "existing-output"):
                self.declare()
            self.assertEqual(path.read_bytes(), b"keep")
            path.unlink()
            path.symlink_to(self.root / "absent")
            with self.assertRaisesRegex(ValueError, "Symlink"):
                self.declare()
            path.unlink()
        alternate = self.root / "0.7"
        alternate.symlink_to(self.out, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "Symlink"):
            self.declare(out=alternate)
        self.assert_no_outputs()

    def test_local_tag_required_even_with_fetch(self):
        with (
            mock.patch.object(build, "tag_commit", return_value=None),
            self.assertRaisesRegex(ValueError, "missing-tag"),
        ):
            self.declare(fetch=True)
        self.assert_no_outputs()

    def test_previous_zip_mismatch_and_target_refuse(self):
        cache_file = self.cache / "downloads" / pin(self.game_zip)["sha256"]
        cache_file.write_bytes(b"wrong")
        with self.assertRaisesRegex(ValueError, "Corrupt cache"):
            self.declare()
        self.assert_no_outputs()
        wrong = zip_bytes({"manifest.json": build.runtime_encoded({"target": self.target, "files": {}})})
        self.lock["expect"]["package"] = pin(wrong)
        self.write_config()
        build.write_new(self.cache / "downloads" / pin(wrong)["sha256"], wrong)
        with self.assertRaisesRegex(ValueError, "target-mismatch: previous"):
            self.declare()
        self.assert_no_outputs()

    def test_carry_refuses_before_writing_and_cli_accepts_repeated_names(self):
        with self.assertRaisesRegex(ValueError, "unconfirmed-carry"):
            self.declare(carry=())
        self.assert_no_outputs()
        self.lock["packages"]["other"] = {
            **self.entries["ordinary"],
            "publication": "pending",
            "publication_status": "pending",
        }
        self.write_config()
        with self.assertRaisesRegex(ValueError, "unconfirmed-carry"):
            self.declare()
        self.assert_no_outputs()
        with self.assertRaisesRegex(ValueError, "invalid-carry"):
            self.declare(carry={"legacy", "other", "previous"})
        self.assert_no_outputs()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            declarations.main(
                [
                    "--config",
                    str(self.config),
                    "--staged",
                    str(self.stage),
                    "--patch",
                    "0.6",
                    "--out",
                    str(self.out),
                    "--cache",
                    str(self.cache),
                    "--carry",
                    "legacy",
                    "--carry",
                    "other",
                ]
            )
        lock = build.load_config(self.out)[1]
        self.assertEqual(lock["packages"]["other"], self.lock["packages"]["other"])
        for field in ("publication", "publication_status"):
            self.assertIn(
                f"H /inputs.lock.json/packages/other/{field}: review carried publication; carried value: pending",
                output.getvalue(),
            )

    def test_added_packages_require_opt_in_at_io_and_cli_accepts_repeated_flags(self):
        self.entries["extra"] = copy.deepcopy(self.entries["ordinary"])
        self.entries["text"] = copy.deepcopy(self.entries["ordinary"])
        self.write_stage()
        with self.assertRaisesRegex(ValueError, "unadded-package"):
            self.declare()
        self.assert_no_outputs()
        before = {path: path.read_bytes() for path in self.config.iterdir()}
        domains_before = (self.out / "domains.json").read_bytes()
        with contextlib.redirect_stdout(io.StringIO()):
            declarations.main(
                [
                    "--config",
                    str(self.config),
                    "--staged",
                    str(self.stage),
                    "--patch",
                    "0.6",
                    "--out",
                    str(self.out),
                    "--cache",
                    str(self.cache),
                    "--carry",
                    "legacy",
                    "--add-package",
                    "extra",
                    "--add-package",
                    "text",
                ]
            )
        lock = build.load_config(self.out)[1]
        self.assertEqual(list(lock["packages"])[-2:], ["extra", "text"])
        self.assertEqual({path: path.read_bytes() for path in self.config.iterdir()}, before)
        self.assertEqual((self.out / "domains.json").read_bytes(), domains_before)

    def test_uncached_previous_refuses_offline_and_fetch_downloads_only_pinned_zip(self):
        (self.cache / "downloads" / pin(self.game_zip)["sha256"]).unlink()
        with self.assertRaisesRegex(ValueError, "rerun with --fetch"):
            self.declare()
        self.assert_no_outputs()
        with mock.patch.object(assets, "https", return_value=self.game_zip) as download:
            self.declare(fetch=True)
        self.assertEqual(download.call_count, 1)
        self.assertEqual(download.call_args.args[0]["tag"], "game/0.5-3")

    def test_staged_target_mismatch_refuses(self):
        stage = self.make_stage("wrong-target", {"value.json": b"{}"}, self.old_target)
        entries = decode((stage / "lock.json").read_bytes())
        entries["crafting"] = copy.deepcopy(entries["ordinary"])
        (stage / "lock.json").write_bytes(build.runtime_encoded(entries))
        with self.assertRaisesRegex(ValueError, "target-mismatch: staged crafting"):
            self.declare(staged=stage)
        self.assert_no_outputs()

    def test_carried_crafting_is_cross_checked_against_new_facts(self):
        entries = {"ordinary": self.entries["ordinary"]}
        with self.assertRaisesRegex(ValueError, "crafting-input-mismatch"):
            self.derive(entries=entries, carry={"legacy", "crafting"})
        self.lock["packages"]["crafting"]["input_manifest"] = {"sha256": self.facts["sha256"]}
        lock, _, report = self.derive(entries=entries, carry={"legacy", "crafting"})
        self.assertEqual(lock["packages"]["crafting"], self.lock["packages"]["crafting"])
        self.assertIn("crafting", report["carried_packages"])

    def test_fresh_facts_source_identity_mismatch_refuses(self):
        files = receipted(
            {
                "facts/manifest.json": candidate(
                    "repoe-native-facts/v4",
                    self.old_target,
                    status="partial-candidate",
                    production_ready=False,
                    files={},
                )
            }
        )
        raw = zip_bytes(
            {
                "manifest.json": build.runtime_encoded(
                    {"target": self.target, "files": {name: pin(value) for name, value in files.items()}}
                ),
                **files,
            }
        )
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            spec = {
                "repository": "ackness/repoe",
                "tag": "inputs/0.6-1",
                "asset": "facts.zip",
                **pin(raw),
                "manifest": pin(archive.read("manifest.json")),
                "expanded_bytes": sum(info.file_size for info in archive.infolist()),
            }
        self.entries["ordinary"] = spec
        self.write_stage()
        (self.stage / "assets/facts.zip").write_bytes(raw)
        with self.assertRaisesRegex(ValueError, "target-mismatch: staged facts target"):
            self.declare()
        self.assert_no_outputs()

    def test_corrupt_staged_asset_refuses(self):
        (self.stage / "assets" / self.entries["ordinary"]["asset"]).write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "Byte pin mismatch"):
            self.declare()
        self.assert_no_outputs()

    def test_missing_and_ambiguous_facts_roots_refuse(self):
        raw = candidate(
            "repoe-native-facts/v4", self.target, status="partial-candidate", production_ready=False, files={}
        )
        for name, files in (
            ("missing", {"value.json": b"{}"}),
            ("ambiguous", receipted({"a/manifest.json": raw, "b/manifest.json": raw})),
        ):
            stage = self.make_stage(name, files)
            entries = decode((stage / "lock.json").read_bytes())
            entries["crafting"] = {
                **entries["ordinary"],
                "input_manifest": {"bytes": 0, "sha256": self.facts["sha256"]},
            }
            (stage / "lock.json").write_bytes(build.runtime_encoded(entries))
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "facts-root"):
                self.declare(staged=stage)
            self.assert_no_outputs()

    def test_write_failure_rolls_back_and_exclusive_race_preserves_other_file(self):
        original = declarations.source_io.write_new
        second = self.out / "frozen-inputs.json"
        for race in (False, True):

            def fail(path, raw):
                if path == second:
                    if race:
                        path.write_bytes(b"concurrent")
                    else:
                        raise OSError("synthetic failure")
                return original(path, raw)

            with mock.patch.object(declarations.source_io, "write_new", fail), self.assertRaises(OSError):
                self.declare()
            self.assertFalse((self.out / "inputs.lock.json").exists())
            if race:
                self.assertEqual(second.read_bytes(), b"concurrent")
            else:
                self.assertFalse(second.exists())

    def test_cli_lists_fields_carries_review_counts_and_expect_absent(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            declarations.main(
                [
                    "--config",
                    str(self.config),
                    "--staged",
                    str(self.stage),
                    "--patch",
                    "0.6",
                    "--out",
                    str(self.out),
                    "--cache",
                    str(self.cache),
                    "--carry",
                    "legacy",
                ]
            )
        text = stdout.getvalue()
        for fragment in (
            "/target/game_patch: 0.5 -> 0.6",
            "Carried packages: legacy",
            "H /inputs.lock.json/packages/ordinary/publication",
            "(2 members)",
            "expect absent",
        ):
            self.assertIn(fragment, text)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as error:
            declarations.main(
                ["--config", str(self.config), "--staged", str(self.stage), "--patch", "0.6", "--out", str(self.out)]
            )
        self.assertEqual(error.exception.code, 1)
        self.assertIn("release:declare: existing-output", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
