"""Offline unit tests for tools/pobr-data-adapter/tests/check_package_keystones.py."""

import importlib.util
from pathlib import Path
import tempfile
import unittest

from RePoE.release import build
from RePoE.release.pins import encoded

SCRIPT = build.ROOT / "tools" / "pobr-data-adapter" / "tests" / "check_package_keystones.py"
SPEC = importlib.util.spec_from_file_location("check_package_keystones", SCRIPT)
check_package_keystones = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_package_keystones)

CURRENT_SHA = "7dcb18ec41dff4deadfb3d9c9acfd128122c748ad1309d75bc301ccfecf0574a"
PREVIOUS_SHA = "7f8d343b53bbbffa221b750c42fa71da4eda6fde909426c130a07d5b4dd4a7c9"


class PublishedGamePackageTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.releases = Path(self.temporary.name) / "release"
        self.releases.mkdir()

    def write_policy(self, current: str, retired: list[str] | None = None):
        (self.releases / "ci.json").write_bytes(
            encoded({"schema": "repoe-release-ci/v1", "current": current, "retired": retired or []})
        )

    def write_declaration(self, name: str, patch: str, *, expect: dict | None = None):
        directory = self.releases / name
        directory.mkdir()
        lock = {
            "schema": "repoe-release-inputs/v1",
            "target": {"game": "poe2", "game_patch": patch, "realm": "international"},
            "packages": {
                "previous": {
                    "repository": "ackness/repoe",
                    "tag": "game/0.5.5.5-3",
                    "asset": "pobr-game-0.5.5.5.zip",
                    "bytes": 4611967,
                    "sha256": PREVIOUS_SHA,
                }
            },
            "reference": "previous",
        }
        if expect is not None:
            lock["expect"] = expect
        (directory / "inputs.lock.json").write_bytes(encoded(lock))
        (directory / "domains.json").write_bytes(encoded({}))
        (directory / "frozen-inputs.json").write_bytes(encoded({}))
        return directory

    def test_repository_current_resolves_to_published_0558_expect_package(self):
        pin, source = check_package_keystones.published_game_package()
        self.assertEqual(
            pin,
            {
                "repository": "ackness/repoe",
                "tag": "game/0.5.5.8-1",
                "asset": "pobr-game-0.5.5.8.zip",
                "bytes": 4614107,
                "sha256": CURRENT_SHA,
            },
        )
        self.assertEqual(source, "release/0.5.5.8/inputs.lock.json (current declaration '0.5.5.8' expect.package)")
        self.assertNotEqual(pin["tag"], "game/0.5.5.5-3")

    def test_stays_anchored_to_current_when_higher_unpublished_declaration_exists(self):
        self.write_declaration(
            "0.5.5.8",
            "0.5.5.8",
            expect={"package": {"bytes": 4614107, "sha256": CURRENT_SHA}},
        )
        self.write_declaration("0.5.5.9", "0.5.5.9")
        self.write_declaration(
            "1.0",
            "1.0",
            expect={"package": {"bytes": 9999, "sha256": "a" * 64}},
        )
        self.write_policy("0.5.5.8")

        self.assertEqual(build.default_config(self.releases), self.releases / "1.0")
        pin, source = check_package_keystones.published_game_package(releases=self.releases)
        self.assertEqual(
            pin,
            {
                "repository": "ackness/repoe",
                "tag": "game/0.5.5.8-1",
                "asset": "pobr-game-0.5.5.8.zip",
                "bytes": 4614107,
                "sha256": CURRENT_SHA,
            },
        )
        self.assertIn("0.5.5.8", source)

    def test_explicit_config_derives_sequenced_release_pin(self):
        config = self.write_declaration(
            "0.5.5.5-3",
            "0.5.5.5",
            expect={"package": {"bytes": 4611967, "sha256": PREVIOUS_SHA}},
        )
        pin, source = check_package_keystones.published_game_package(config)
        self.assertEqual(
            pin,
            {
                "repository": "ackness/repoe",
                "tag": "game/0.5.5.5-3",
                "asset": "pobr-game-0.5.5.5.zip",
                "bytes": 4611967,
                "sha256": PREVIOUS_SHA,
            },
        )
        self.assertIn("declaration '0.5.5.5-3' expect.package", source)

    def test_fails_cleanly_when_expect_package_is_missing_or_invalid(self):
        self.write_declaration("0.5.5.8", "0.5.5.8")
        self.write_policy("0.5.5.8")
        with self.assertRaises(SystemExit) as missing:
            check_package_keystones.published_game_package(releases=self.releases)
        self.assertIn("has no expect.package pin", str(missing.exception))

        broken = self.write_declaration("0.5.5.9", "0.5.5.9", expect={"package": {"bytes": 12, "sha256": "short"}})
        with self.assertRaises(SystemExit) as invalid:
            check_package_keystones.published_game_package(broken)
        self.assertIn("invalid expect.package pin", str(invalid.exception))

        mismatched = self.write_declaration(
            "0.5.6.0",
            "0.5.5.9",
            expect={"package": {"bytes": 12, "sha256": "b" * 64}},
        )
        with self.assertRaises(SystemExit) as bad_seq:
            check_package_keystones.published_game_package(mismatched)
        self.assertIn("does not declare a valid sequence", str(bad_seq.exception))


if __name__ == "__main__":
    unittest.main()
