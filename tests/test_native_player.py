"""Player context production from portable physical DAT and lexical metadata."""

import json
from pathlib import Path
import tempfile
import unittest

from RePoE import native_player as player
from RePoE import schema_candidate
from RePoE.native_tools import pinned_pypoe
from tests.test_native_facts import dat_bytes


class NativePlayerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with pinned_pypoe():
            _, schema = schema_candidate._inputs(schema_candidate.ROOT)
            _, cls.spec = schema_candidate._native_specification(schema)

    def setUp(self):
        cache = player.ROOT / ".cache"
        cache.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="player-tests-", dir=cache)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.raw, self.parent = self.root / "raw", self.root / "parent"
        self.raw.mkdir()
        (self.parent / "tables").mkdir(parents=True)
        values = {
            "Characters": [
                {"Id": "other", "AOFile": "Metadata/Other.ao", "StartingPassive": 0},
                {"Id": "selected", "BaseClass": "other", "AOFile": "Metadata/Selected.ao", "StartingPassive": 0},
            ],
            "PassiveSkills": [{"Id": "first_option"}, {"Id": "second_option"}],
            "Stats": [{"Id": "base_critical_hit_damage_bonus"}],
            "ClassPassiveSkillOverrides": [{"CharacterToOverrideFor": 0, "SkillToOverride": 0, "Override": 1}],
        }
        parent_files = {}
        for name, rows in values.items():
            data = player.io._json({"table": name, "rows": [{"_row": i, "values": v} for i, v in enumerate(rows)]})
            path = self.parent / "tables" / f"{name}.json"
            path.write_bytes(data)
            parent_files[f"tables/{name}.json"] = {"bytes": len(data), "sha256": player._sha(data)}
        self.parent_manifest = {
            "format": "repoe-native-facts/v4",
            "profile": "items-actors-bc",
            "production_ready": False,
            "source_identity": {"game": "poe2", "realm": "international", "game_patch": "synthetic"},
            "files": parent_files,
        }
        (self.parent / "manifest.json").write_bytes(player.io._json(self.parent_manifest))
        resources = {}
        tables = {
            "StartingPassiveSkills": [{"Id": "start", "PassiveSkills": [0, 1]}],
            "KeywordPopups": [
                {
                    "Id": "CriticalDamageBonus",
                    "Term": "Critical Damage Bonus",
                    "Definition": "Default value is +100%, twice as much damage.",
                }
            ],
        }
        for name, rows in tables.items():
            resources[f"Data/Balance/{name}.datc64"] = dat_bytes(self.spec, name, rows)
        for name, text in {
            "Metadata/Selected.ao": 'extends "Metadata/Parent"\nActor\n{\n opaque = 1\n}\n',
            "Metadata/Parent.ao": 'extends "nothing"\n',
            "Metadata/Character.ot": 'extends "nothing"\nStats\n{\n base_critical_hit_damage_bonus = 100\n unknown_key = -9\n}\n',
        }.items():
            resources[name] = b"\xff\xfe" + text.encode("utf-16-le")
        for name, data in resources.items():
            path = self.raw / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.source = {
            "kind": "official-client-resource-candidate",
            "profile": "player-context-a2",
            "game": "poe2",
            "realm": "international",
            "game_patch": "synthetic",
            "character_id": "selected",
            "metadata_roots": {"character_ao": "Metadata/Selected.ao", "generic_stats_ot": "Metadata/Character.ot"},
            "decoder": {
                "revision": player.facts.PYPOE,
                "dat_schema_revision": player.facts.SCHEMA,
                "schema_sha256": player.facts.SCHEMA_SHA,
            },
            "acquisition": {
                "status": "unreviewed-acquisition-draft",
                "evidence": [{"kind": "synthetic-raw-fixture", "sha256": "0" * 64}],
            },
            "resources": {name: {"bytes": len(data), "sha256": player._sha(data)} for name, data in resources.items()},
        }
        self.lock = self.root / "source-lock.json"
        self.out = self.root / "candidate"
        self.seal()

    def seal(self):
        self.lock.write_bytes(player.io._json({"schema_version": 1, "sources": {"fixture": self.source}}))

    def create(self, **overrides):
        return player.create_candidate(
            **{
                "source_lock": self.lock,
                "source": "fixture",
                "raw": self.raw,
                "out": self.out,
                "expected_source_lock_sha256": player._sha(self.lock.read_bytes()),
                "parent_facts": self.parent,
                "expected_parent_manifest_sha256": player._sha((self.parent / "manifest.json").read_bytes()),
                **overrides,
            }
        )

    def test_complete_context_preserves_raw_scopes_and_uses_exact_character(self):
        originals = {str(p): p.read_bytes() for root in [self.raw, self.parent] for p in root.rglob("*") if p.is_file()}
        manifest = self.create()
        self.assertFalse(manifest["production_ready"])
        self.assertEqual(manifest["summary"]["starting_option_references"], 2)
        context = json.loads((self.out / "player_context.json").read_bytes())
        self.assertEqual(context["character"]["source"]["row"], 1)
        self.assertEqual(context["character"]["values"]["BaseClass"], "other")
        self.assertEqual(context["selected_class_overrides"], [])
        self.assertEqual([r["id"] for r in context["starting_relation"]["options"]], ["first_option", "second_option"])
        self.assertEqual([r["value_raw"] for r in context["metadata_stats"]], ["100", "-9"])
        self.assertIsNone(context["metadata_stats"][1]["stat"])
        self.assertTrue(context["binding_policy"].startswith("none;"))
        self.assertTrue(context["allocation_policy"].startswith("none;"))
        references = [context["character"]["source"]]
        for relation in context["all_starting_relations"]:
            references.extend([relation["source"], *relation["options"]])
        references.extend(context["selected_class_overrides"])
        references.extend(item["stat"] for item in context["metadata_stats"] if item["stat"] is not None)
        self.assertEqual({ref["origin"] for ref in references}, {"player", "parent"})
        for ref in references:
            package = self.out if ref["origin"] == "player" else self.parent
            document = json.loads((package / ref["payload"]).read_bytes())
            values = document["rows"][ref["row"]]["values"]
            self.assertEqual(values.get("Id"), ref["id"])
            self.assertEqual(ref["pointer"], f"/rows/{ref['row']}/values")
        for name, fp in manifest["files"].items():
            data = (self.out / name).read_bytes()
            self.assertEqual(fp, {"bytes": len(data), "sha256": player._sha(data)})
        self.assertEqual(
            {str(p): p.read_bytes() for root in [self.raw, self.parent] for p in root.rglob("*") if p.is_file()},
            originals,
        )

    def test_wrong_pins_or_corrupted_raw_never_reserve_output(self):
        for kwargs in [{"expected_source_lock_sha256": "0" * 64}, {"expected_parent_manifest_sha256": "0" * 64}]:
            with self.assertRaisesRegex(ValueError, "pin"):
                self.create(**kwargs)
            self.assertFalse(self.out.exists())
        path = self.raw / "Metadata/Character.ot"
        changed = bytearray(path.read_bytes())
        changed[20] ^= 1
        path.write_bytes(changed)
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            self.create()
        self.assertFalse(self.out.exists())

    def test_literal_missing_parent_and_wrong_actor_do_not_fall_back(self):
        self.source["character_id"] = "missing"
        self.seal()
        with self.assertRaisesRegex(ValueError, "exact stable ID"):
            self.create()
        self.source["character_id"] = "selected"
        path = self.raw / "Metadata/Selected.ao"
        data = b"\xff\xfe" + 'extends "Metadata/Missing"\n'.encode("utf-16-le")
        path.write_bytes(data)
        self.source["resources"]["Metadata/Selected.ao"] = {"bytes": len(data), "sha256": player._sha(data)}
        self.seal()
        with self.assertRaisesRegex(ValueError, "Missing literal"):
            self.create()
        self.assertFalse(self.out.exists())

    def test_parent_patch_mismatch_and_existing_output_are_preserved(self):
        self.parent_manifest["source_identity"]["game_patch"] = "other"
        (self.parent / "manifest.json").write_bytes(player.io._json(self.parent_manifest))
        with self.assertRaisesRegex(ValueError, "game_patch mismatch"):
            self.create()
        self.out.mkdir()
        (self.out / "sentinel").write_bytes(b"unchanged")
        with self.assertRaises(FileExistsError):
            self.create()
        self.assertEqual((self.out / "sentinel").read_bytes(), b"unchanged")
