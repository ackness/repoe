"""Bounded locale resealing with synthetic immutable inputs, without a client."""

import copy
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

from RePoE import data_publication as pack
from RePoE import pobr_locale_reseal as reseal

TARGET = {"game": "poe2", "game_patch": "9.1", "realm": "international"}
LOCALE_PATH = "i18n/zh-CN/stat_lines.json"
SNAPSHOT_PATH = "data/9.1/manifest.json"


class ResealTests(unittest.TestCase):
    def setUp(self):
        (reseal.ROOT / ".cache").mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="locale-reseal-test-", dir=reseal.ROOT / ".cache")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "--quiet")
        old, new = b'["retained"]\n', b'["retained", "alias"]\n'
        self.language_members = {LOCALE_PATH: new, "i18n/zh-TW/skills.json": b"{}\n", "evidence/input.json": b"null\n"}
        self.locale = {
            "schema": "poe2-retained-locale-publication/v1",
            "target": TARGET,
            "files": {name: pack.pin(raw) for name, raw in self.language_members.items()},
        }
        self.snapshot = {
            "schema_version": 3,
            "poe_version": "9.1",
            "unknown": {"client": None, "limits": ["historical"], "padding": "synthetic " * 200},
            "files": {
                "base/stats.json": pack.pin(b"{}\n")["sha256"],
                LOCALE_PATH: pack.pin(old)["sha256"],
                "i18n/zh-TW/skills.json": pack.pin(b"{}\n")["sha256"],
            },
        }
        self.changes = {LOCALE_PATH: {"before": pack.pin(old)["sha256"], "after": pack.pin(new)["sha256"]}}
        self.members = {
            SNAPSHOT_PATH: reseal.runtime_encoded(self.snapshot),
            "data/9.1/base/stats.json": b"{}\n",
            "data/overlay-common/retained.json": b'{"source": null}\n',
        }
        self.manifest = {
            "schema": "pobr-build-data-part/v1",
            "kind": "game",
            "target": TARGET,
            "production_ready": False,
            "provenance": {"unknown": None, "source": "historical"},
            "limits": ["not fresh"],
            "files": {name: pack.pin(raw) for name, raw in self.members.items()},
        }
        self.plan_path = self.root / "plan.json"

    def git(self, *args):
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Synthetic fixture",
            "GIT_AUTHOR_EMAIL": "test@repoe.invalid",
            "GIT_COMMITTER_NAME": "Synthetic fixture",
            "GIT_COMMITTER_EMAIL": "test@repoe.invalid",
        }
        return subprocess.check_output(["git", "-C", str(self.repo), *args], env=env).decode().strip()

    def inputs(self):
        manifest_raw = pack.encoded(self.manifest)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, raw in {**self.members, "manifest.json": manifest_raw}.items():
                archive.writestr(name, raw)
        self.old_zip = buffer.getvalue()
        (self.repo / "game.zip").write_bytes(self.old_zip)
        locale_raw = pack.encoded(self.locale)
        for name, raw in {**self.language_members, "manifest.json": locale_raw}.items():
            path = self.repo / "locale" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "Synthetic owner inputs")
        revision = self.git("rev-parse", "HEAD")
        return {
            "schema": reseal.SCHEMA,
            "target": TARGET,
            "game_input": {
                "repository": "ackness/repoe",
                "publication": "published",
                "revision": revision,
                "path": "game.zip",
                **pack.pin(self.old_zip),
                "manifest": pack.pin(manifest_raw),
                "expanded_bytes": len(manifest_raw) + sum(map(len, self.members.values())),
            },
            "language_manifest": {
                "repository": reseal.LANGUAGE_OWNER,
                "revision": revision,
                "path": "locale/manifest.json",
                **pack.pin(locale_raw),
            },
            "changes": self.changes,
        }

    def assemble(self, plan, name="out", digest=None):
        raw = pack.encoded(plan)
        self.plan_path.write_bytes(raw)
        return reseal.assemble(
            self.repo, self.repo, self.plan_path, digest or pack.pin(raw)["sha256"], "test-locale", self.root / name
        )

    def test_exact_manifest_delta_all_other_members_and_ownership_unchanged(self):
        plan = self.inputs()
        result = self.assemble(plan)
        self.assertEqual(result, self.assemble(plan, "repeat"))
        self.assertEqual((self.root / "out/data.zip").read_bytes(), (self.root / "repeat/data.zip").read_bytes())
        with zipfile.ZipFile(self.root / "out/data.zip") as archive:
            _, manifest = pack.archive_manifest(archive, result)
            actual = {name: archive.read(name) for name in archive.namelist()}
            for name, expected in manifest["files"].items():
                pack.pinned(actual[name], expected)
        expected_snapshot = copy.deepcopy(self.snapshot)
        expected_snapshot["files"][LOCALE_PATH] = self.changes[LOCALE_PATH]["after"]
        self.assertEqual(actual[SNAPSHOT_PATH], reseal.runtime_encoded(expected_snapshot))
        self.assertEqual(set(actual), {*self.members, "manifest.json"})
        for name, raw in self.members.items():
            if name != SNAPSHOT_PATH:
                self.assertEqual(actual[name], raw)
        receipt = manifest.pop("locale_reseals")
        manifest["files"][SNAPSHOT_PATH] = self.manifest["files"][SNAPSHOT_PATH]
        self.assertEqual(manifest, self.manifest)
        self.assertEqual(receipt[0]["retained_game_input"], plan["game_input"])
        self.assertEqual(receipt[0]["language_manifest"], plan["language_manifest"])
        handoff = pack.git_handoff(self.root / "out")
        self.assertEqual(handoff["publication"], "local-only")
        self.assertEqual(handoff["ref"], "refs/tags/handoff/test-locale")

    def test_rejects_undeclared_missing_added_wrong_or_nonlocale_bindings(self):
        for case in ("missing", "added", "undeclared", "wrong-before", "nonlocale", "noop", "schema", "target"):
            locale, changes, snapshot = (
                copy.deepcopy(self.locale),
                copy.deepcopy(self.changes),
                copy.deepcopy(self.snapshot),
            )
            if case == "missing":
                del locale["files"]["i18n/zh-TW/skills.json"]
            elif case == "added":
                locale["files"]["i18n/zh-CN/extra.json"] = pack.pin(b"extra")
            elif case == "undeclared":
                locale["files"]["i18n/zh-TW/skills.json"] = pack.pin(b"changed")
            elif case == "wrong-before":
                changes[LOCALE_PATH]["before"] = "0" * 64
            elif case == "nonlocale":
                changes["base/stats.json"] = changes.pop(LOCALE_PATH)
            elif case == "noop":
                changes = {}
            elif case == "schema":
                snapshot["schema_version"] = 2
            else:
                locale["target"]["game_patch"] = "9.2"
            with self.subTest(case=case), self.assertRaises(ValueError):
                reseal.rebind_snapshot(reseal.runtime_encoded(snapshot), TARGET, locale, changes)

    def test_pinned_inputs_ignore_checkout_and_fail_closed(self):
        plan = self.inputs()
        (self.repo / "locale" / LOCALE_PATH).write_bytes(b"dirty checkout is not an input")
        self.assemble(plan)
        for case in ("plan", "language-pin", "game-pin", "owner"):
            changed = copy.deepcopy(plan)
            if case == "language-pin":
                changed["language_manifest"]["sha256"] = "0" * 64
            elif case == "game-pin":
                changed["game_input"]["sha256"] = "0" * 64
            elif case == "owner":
                changed["language_manifest"]["repository"] = "wrong/owner"
            with self.subTest(case=case), self.assertRaises(ValueError):
                self.assemble(changed, case, "0" * 64 if case == "plan" else None)
            self.assertFalse((self.root / case).exists())

    def test_language_and_game_member_pins_are_verified(self):
        self.language_members[LOCALE_PATH] = b"corrupt language"
        plan = self.inputs()
        with self.assertRaisesRegex(ValueError, "Git blob size mismatch|Git blob pin mismatch"):
            self.assemble(plan)
        self.assertFalse((self.root / "out").exists())

    def test_corrupt_game_member_is_rejected(self):
        self.members["data/9.1/base/stats.json"] = b"corrupt game"
        plan = self.inputs()
        with self.assertRaisesRegex(ValueError, "Member size mismatch|Byte pin mismatch"):
            self.assemble(plan)
        self.assertFalse((self.root / "out").exists())


if __name__ == "__main__":
    unittest.main()
