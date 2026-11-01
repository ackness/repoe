"""Selected-table input identity, strict decoding and fresh publication."""

import json
from pathlib import Path
import tempfile
import unittest

from RePoE import native_facts as facts
from RePoE import native_tables as producer
from RePoE import schema_candidate
from RePoE.native_tools import pinned_pypoe
from test_native_facts import dat_bytes


class SelectedTablesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with pinned_pypoe():
            _, schema = schema_candidate._inputs(schema_candidate.ROOT)
            _, cls.spec = schema_candidate._native_specification(schema)

    def setUp(self):
        cache = producer.ROOT / ".cache"
        cache.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="selected-tables-test-", dir=cache)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.raw = self.root / "raw"
        (self.raw / "Data/Balance").mkdir(parents=True)
        self.lock = self.root / "lock.json"
        self.source = {
            "kind": "official-client-resource-candidate",
            "game": "poe2",
            "game_patch": "0.5.5.5",
            "realm": "international",
            "acquisition": {
                "status": "unreviewed-acquisition-draft",
                "evidence": [{"kind": "synthetic", "sha256": "a" * 64}],
            },
            "decoder": {
                "repository": "https://github.com/repoe-fork/pypoe",
                "revision": facts.PYPOE,
                "dat_schema_repository": "https://github.com/poe-tool-dev/dat-schema",
                "dat_schema_revision": facts.SCHEMA,
                "schema_sha256": facts.SCHEMA_SHA,
            },
            "resources": {},
        }
        self.set_table(
            "ModEffectStats",
            [
                {
                    "Stat": 41,
                    "Tags": [9, 9],
                    "ApplyToExplicit": True,
                    "ApplyToImplicit": False,
                    "Unknown0": -17,
                    "Multiplier": -3,
                }
            ],
        )

    def set_table(self, name, rows, language="English"):
        raw = dat_bytes(self.spec, name, rows)
        prefix = "" if language == "English" else language + "/"
        resource = f"Data/Balance/{prefix}{name}.datc64"
        (self.raw / resource).parent.mkdir(parents=True, exist_ok=True)
        (self.raw / resource).write_bytes(raw)
        self.source["resources"][resource] = {"bytes": len(raw), "sha256": producer.envelope._sha(raw)}
        self.pin()

    def pin(self):
        self.lock.write_bytes(facts._json({"schema_version": 1, "sources": {"selected": self.source}}))
        self.expected = producer.envelope._sha(self.lock.read_bytes())

    def create(self, out="candidate", language="English"):
        return producer.create_candidate(
            source_lock=self.lock,
            source="selected",
            raw=self.raw,
            expected_source_lock_sha256=self.expected,
            out=self.root / out,
            language=language,
        )

    def test_localized_source_preserves_exact_resource_identity_and_text(self):
        self.source["resources"] = {}
        self.source["language"] = "Traditional Chinese"
        self.set_table("Ascendancy", [{"Id": "Witch1", "Name": "血法師"}], "Traditional Chinese")
        manifest = self.create(language="Traditional Chinese")
        self.assertEqual(manifest["format"], producer.LOCALIZED_FORMAT)
        self.assertEqual(manifest["source_identity"]["language"], "Traditional Chinese")
        table = json.loads((self.root / "candidate/tables.json").read_bytes())["Ascendancy"]
        self.assertEqual(table["raw_resource"], "Data/Balance/Traditional Chinese/Ascendancy.datc64")
        self.assertEqual(table["rows"][0]["values"]["Name"], "血法師")
        self.assertEqual(self.create("replay", language="Traditional Chinese"), manifest)
        self.set_table("Ascendancy", [{"Id": "Witch1", "Name": "新名"}], "Traditional Chinese")
        self.create("changed", language="Traditional Chinese")
        changed = json.loads((self.root / "changed/tables.json").read_bytes())["Ascendancy"]
        self.assertEqual(changed["rows"][0]["values"]["Name"], "新名")

    def test_locale_declaration_mismatch_and_english_fallback_reject(self):
        with self.assertRaisesRegex(ValueError, "source language"):
            self.create(language="Traditional Chinese")
        self.source["language"] = "Traditional Chinese"
        self.pin()
        with self.assertRaisesRegex(ValueError, "source language"):
            self.create()
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            self.create(language="Traditional Chinese")
        self.assertFalse((self.root / "candidate").exists())

    def test_mixed_locale_collision_and_unsupported_locale_reject(self):
        self.source["language"] = "Traditional Chinese"
        self.set_table("ModEffectStats", [{"Stat": 1}], "Traditional Chinese")
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            self.create(language="Traditional Chinese")
        self.source["language"] = "../escape"
        self.pin()
        with self.assertRaisesRegex(ValueError, "source language"):
            self.create(language="../escape")
        self.assertFalse((self.root / "candidate").exists())

    def test_preserves_unknown_negative_duplicate_null_and_external_references(self):
        manifest = self.create()
        table = json.loads((self.root / "candidate/tables.json").read_bytes())["ModEffectStats"]
        self.assertEqual(
            table["rows"][0]["values"],
            {
                "Stat": 41,
                "Tags": [9, 9],
                "ApplyToExplicit": True,
                "ApplyToImplicit": False,
                "Unknown0": -17,
                "Multiplier": -3,
            },
        )
        self.assertEqual(manifest["summary"]["tables"], {"ModEffectStats": 1})
        self.assertEqual(manifest["summary"]["checked_internal_references"], 0)
        self.assertEqual(len(manifest["summary"]["external_references"]), 2)
        self.assertFalse(manifest["production_ready"])
        self.assertEqual((self.root / "candidate/source-lock.json").read_bytes(), self.lock.read_bytes())

    def test_raw_value_and_membership_changes_propagate(self):
        self.create()
        self.set_table("ModEffectStats", [{"Stat": None, "Tags": [], "Multiplier": 35}, {"Stat": 1, "Multiplier": 7}])
        m = self.create("changed")
        rows = json.loads((self.root / "changed/tables.json").read_bytes())["ModEffectStats"]["rows"]
        self.assertEqual([r["values"]["Multiplier"] for r in rows], [35, 7])
        self.assertIsNone(rows[0]["values"]["Stat"])
        self.assertEqual(m["summary"]["tables"]["ModEffectStats"], 2)

    def test_available_foreign_target_is_checked_without_truncation(self):
        self.set_table("AlternateQualityTypes", [{"Id": "quality", "ModEffectStat": 1}])
        with self.assertRaisesRegex(ValueError, "Unresolved selected reference"):
            self.create()
        self.assertFalse((self.root / "candidate").exists())
        self.set_table("AlternateQualityTypes", [{"Id": "quality", "ModEffectStat": 0}])
        self.assertEqual(self.create()["summary"]["checked_internal_references"], 1)

    def test_raw_tamper_pin_or_schema_failure_writes_nothing(self):
        resource = self.raw / "Data/Balance/ModEffectStats.datc64"
        raw = resource.read_bytes()
        resource.write_bytes(raw + b"x")
        with self.assertRaisesRegex(ValueError, "(byte limit|fingerprint)"):
            self.create()
        resource.write_bytes(raw)
        self.expected = "b" * 64
        with self.assertRaisesRegex(ValueError, "external expected byte pin"):
            self.create()
        self.pin()
        self.source["decoder"]["schema_sha256"] = "b" * 64
        self.pin()
        with self.assertRaisesRegex(ValueError, "decoder pin mismatch"):
            self.create()
        self.assertFalse((self.root / "candidate").exists())

    def test_duplicate_keys_path_escape_and_symlinks_reject(self):
        original = self.lock.read_bytes()
        self.lock.write_bytes(original.replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1'))
        self.expected = producer.envelope._sha(self.lock.read_bytes())
        with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
            self.create()
        self.source["resources"]["Data/Balance/../bad.datc64"] = next(iter(self.source["resources"].values()))
        self.pin()
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            self.create()
        del self.source["resources"]["Data/Balance/../bad.datc64"]
        self.pin()
        path = self.raw / "Data/Balance/ModEffectStats.datc64"
        backup = self.root / "backup"
        path.rename(backup)
        path.symlink_to(backup)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.create()

    def test_replay_is_identical_existing_output_and_input_placement_reject(self):
        a = self.create()
        b = self.create("replay")
        self.assertEqual(a, b)
        for name in [*a["files"], "manifest.json"]:
            self.assertEqual((self.root / "candidate" / name).read_bytes(), (self.root / "replay" / name).read_bytes())
        with self.assertRaises(FileExistsError):
            self.create()
        with self.assertRaisesRegex(ValueError, "inside raw input"):
            self.create("raw/inside")


if __name__ == "__main__":
    unittest.main()
