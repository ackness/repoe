"""Seven-table crafting joins, physical preservation and fail-closed publication."""

from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from RePoE import native_crafting_facts as crafting


def fixture():
    values = {
        "BaseItemTypes": [{"Id": "Metadata/Currency/Neutral", "Unknown0": [-9, None, 0, -0.0]}],
        "ItemClasses": [{"Id": "ClassB"}, {"Id": "ClassA"}],
        "Stats": [{"Id": "stat_zero"}, {"Id": "stat_other"}],
        "Essences": [{"BaseItemType": 0, "Unknown0": None}],
        "EssenceTargetItemCategories": [{"Id": "Category", "ItemClasses": [1, 0, 1]}],
        "EssenceMods": [
            {
                "Essence": 0,
                "TargetItemCategory": 0,
                "Mod": 0,
                "DisplayMod": 1,
                "OutcomeMods": [1, 0, 1],
                "OutcomeModWeights": [0, -2],
                "Unknown0": "unconsumed",
            },
            {
                "Essence": 0,
                "TargetItemCategory": 0,
                "Mod": None,
                "DisplayMod": None,
                "OutcomeMods": [],
                "OutcomeModWeights": [],
                "Unknown0": None,
            },
        ],
        "Mods": [],
    }
    for index in range(2):
        mod = {"Id": f"Mod{index}", "Level": 0, "HasHardmodeStatValues": False, "Unknown0": [None, 0]}
        for slot in range(1, 9):
            mod.update(
                {
                    f"Stat{slot}": 0 if slot in {1, 5, 8} else None,
                    f"Stat{slot}Min": -slot,
                    f"Stat{slot}Max": 0,
                    f"Stat{slot}MinHardmode": 17,
                    f"Stat{slot}MaxHardmode": 23,
                }
            )
        values["Mods"].append(mod)
    references = {
        ("Essences", "BaseItemType"): "BaseItemTypes",
        ("EssenceTargetItemCategories", "ItemClasses"): "ItemClasses",
        **{
            ("EssenceMods", field): target
            for field, target in [
                ("Essence", "Essences"),
                ("TargetItemCategory", "EssenceTargetItemCategories"),
                ("Mod", "Mods"),
                ("DisplayMod", "Mods"),
                ("OutcomeMods", "Mods"),
            ]
        },
        **{("Mods", f"Stat{slot}"): "Stats" for slot in range(1, 9)},
    }
    tables = {}
    for name in crafting.TABLES:
        fields = list(values[name][0])
        columns = []
        for index, field in enumerate(fields):
            target = references.get((name, field))
            columns.append(
                {
                    "source_column": index,
                    "physical_fields": [field],
                    "schema": {
                        "name": field,
                        "type": "foreignrow" if target else "i32",
                        "array": isinstance(values[name][0][field], list),
                        "references": {"table": target} if target else None,
                    },
                }
            )
        tables[name] = {
            "table": name,
            "raw_resource": f"Data/Balance/{name}.datc64",
            "row_key": "zero-based physical source row",
            "physical_fields": fields,
            "columns": columns,
            "rows": [{"_row": index, "values": row} for index, row in enumerate(values[name])],
            "validation": {"rows": len(values[name]), "actual_row_bytes": 1, "schema_row_bytes": 1, "warnings": []},
        }
    return tables


class CraftingFactsTests(unittest.TestCase):
    def setUp(self):
        cache = crafting.ROOT / ".cache"
        cache.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="crafting-test-", dir=cache)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.input = self.root / "input"
        (self.input / "tables").mkdir(parents=True)
        self.tables = fixture()
        self.manifest = {
            "format": "repoe-native-facts/v4",
            "profile": "items-actors-bc",
            "status": "partial-candidate",
            "production_ready": False,
            "schema": deepcopy(crafting.SCHEMA),
            "source_identity": {
                "kind": "official-client-resource-candidate",
                "game": "poe2",
                "game_patch": "0.5.5.5",
                "realm": "international",
                "source": "synthetic",
                "source_lock_sha256": "a" * 64,
                "selected_source_sha256": "b" * 64,
                "acquisition": {
                    "status": "unreviewed-acquisition-draft",
                    "evidence": [{"kind": "synthetic", "sha256": "c" * 64}],
                },
                "raw_resources": {
                    f"Data/Balance/{name}.datc64": {"bytes": 1, "sha256": "d" * 64} for name in crafting.TABLES
                },
            },
            "decoder": {
                "pypoe_revision": "66d1d7442c5718260e1a8efd24989d22987e91af",
                "python": "synthetic",
                "trusted_source_pin_sha256": "e" * 64,
                "sources": {"synthetic": "f" * 64},
            },
            "producer": {"synthetic": "a" * 64},
            "files": {},
        }
        self.pin()

    def pin(self):
        for name, table in self.tables.items():
            raw = crafting.env._json(table)
            path = f"tables/{name}.json"
            (self.input / path).write_bytes(raw)
            self.manifest["files"][path] = crafting._pin(raw)
        raw = crafting.env._json(self.manifest)
        (self.input / "manifest.json").write_bytes(raw)
        self.expected = crafting.env._sha(raw)

    def create(self, name="candidate"):
        return crafting.create_candidate(facts=self.input, expected_manifest_sha256=self.expected, out=self.root / name)

    def test_eight_slots_raw_null_zero_hardmode_duplicates_and_distinct_relations(self):
        before = deepcopy(self.tables)
        result = crafting.project(self.tables)
        self.assertEqual(self.tables, before)
        mod = result["mods"][0]
        self.assertEqual([slot["slot"] for slot in mod["slots"]], list(range(1, 9)))
        self.assertEqual(mod["slots"][7]["stat"], {"table": "Stats", "row": 0, "id": "stat_zero"})
        self.assertEqual(mod["slots"][7]["min_raw"], -8)
        self.assertEqual(mod["slots"][7]["max_raw"], 0)
        self.assertEqual(mod["slots"][7]["min_hardmode_raw"], 17)
        self.assertIsNone(mod["slots"][1]["stat"])
        row = result["essence_mods"][0]
        self.assertEqual(row["mod"]["id"], "Mod0")
        self.assertEqual(row["display_mod"]["id"], "Mod1")
        self.assertEqual([v["target"]["id"] for v in row["outcome_mods"]], ["Mod1", "Mod0", "Mod1"])
        self.assertEqual([v["source_slot"] for v in row["outcome_mods"]], [0, 1, 2])
        self.assertEqual([v["target"]["id"] for v in row["item_classes"]], ["ClassA", "ClassB", "ClassA"])
        self.assertEqual(row["outcome_mod_weights_raw"], [0, -2])
        self.assertEqual(result["diagnostics"][0]["code"], "outcome_weight_alignment_unresolved")
        self.assertIsNone(result["essence_mods"][1]["mod"])
        self.assertEqual(result["essence_mods"][1]["outcome_mods"], [])
        # Repeated physical relationship rows are retained, not merged by ID.
        table = self.tables["EssenceMods"]
        table["rows"].append({"_row": 2, "values": deepcopy(table["rows"][0]["values"])})
        table["validation"]["rows"] = 3
        self.assertEqual(len(crafting.project(self.tables)["essence_mods"]), 3)

    def test_null_and_empty_joins_remain_distinct_without_fallback(self):
        self.tables["Essences"]["rows"][0]["values"]["BaseItemType"] = None
        self.tables["EssenceTargetItemCategories"]["rows"][0]["values"]["ItemClasses"] = []
        row = self.tables["EssenceMods"]["rows"][1]["values"]
        row["Essence"], row["TargetItemCategory"] = None, None
        result = crafting.project(self.tables)
        self.assertIsNone(result["essence_mods"][0]["currency"])
        self.assertEqual(result["essence_mods"][0]["item_classes"], [])
        self.assertIsNone(result["essence_mods"][1]["item_classes"])
        self.assertEqual(result["summary"]["diagnostics"]["null_join_reference"], 1)

    def test_ranges_preserve_null_and_inversion_without_reordering(self):
        row = self.tables["Mods"]["rows"][0]["values"]
        row["Stat5Min"], row["Stat5Max"] = 9, -3
        row["Stat8MinHardmode"] = None
        result = crafting.project(self.tables)
        slot = result["mods"][0]["slots"][4]
        self.assertEqual((slot["min_raw"], slot["max_raw"]), (9, -3))
        self.assertIsNone(result["mods"][0]["slots"][7]["min_hardmode_raw"])
        self.assertEqual(result["summary"]["diagnostics"]["inverted_raw_interval"], 1)

    def test_selected_fk_invalid_types_ranges_and_missing_fields_reject_before_output(self):
        original = deepcopy(self.tables)
        for field, invalid in [
            ("Essence", -1),
            ("Mod", True),
            ("DisplayMod", 2),
            ("OutcomeMods", [0, 99]),
            ("TargetItemCategory", "0"),
        ]:
            with self.subTest(field=field):
                self.tables = deepcopy(original)
                self.tables["EssenceMods"]["rows"][0]["values"][field] = invalid
                self.pin()
                with self.assertRaisesRegex(ValueError, "Unresolved selected reference"):
                    self.create()
                self.assertFalse((self.root / "candidate").exists())
        self.tables = deepcopy(original)
        del self.tables["Mods"]["rows"][0]["values"]["Stat8Min"]
        self.pin()
        with self.assertRaisesRegex(ValueError, "physical row"):
            self.create()

    def test_physical_row_stable_identity_and_relation_schema_failures(self):
        mutations = [
            lambda t: t["Mods"]["rows"][0].update(_row=1),
            lambda t: t["Mods"]["rows"][0].update(_row=False),
            lambda t: t["Stats"]["rows"][1]["values"].update(Id="stat_zero"),
            lambda t: t["Stats"]["rows"][1]["values"].update(Id=None),
            lambda t: t["EssenceMods"]["columns"][0]["schema"].update(references={"table": "Mods"}),
            lambda t: t["Mods"].update(raw_resource="Data/Balance/Other.datc64"),
        ]
        for mutate in mutations:
            tables = fixture()
            mutate(tables)
            with self.assertRaises((ValueError, KeyError)):
                crafting.project(tables)

    def test_leaf_references_and_eighth_stat_are_checked(self):
        for name, field, invalid in [
            ("Essences", "BaseItemType", 1),
            ("EssenceTargetItemCategories", "ItemClasses", [0, 2]),
            ("Mods", "Stat8", 2),
        ]:
            with self.subTest(table=name, field=field):
                tables = fixture()
                tables[name]["rows"][0]["values"][field] = invalid
                with self.assertRaisesRegex(ValueError, "Unresolved selected reference"):
                    crafting.project(tables)

    def test_manifest_payload_and_declared_identity_pin_failures(self):
        self.expected = "0" * 64
        with self.assertRaisesRegex(ValueError, "manifest differs"):
            self.create()
        self.pin()
        (self.input / "tables/Stats.json").write_bytes(b"{}")
        with self.assertRaisesRegex(ValueError, "payload differs"):
            self.create()
        for key, value in [
            ("realm", None),
            ("game_patch", "unknown"),
            ("language", "Simplified Chinese"),
            ("source_lock_sha256", None),
        ]:
            with self.subTest(key=key):
                saved = deepcopy(self.manifest)
                self.manifest["source_identity"][key] = value
                self.pin()
                with self.assertRaisesRegex(ValueError, "identity required"):
                    self.create()
                self.manifest = saved
        self.assertFalse((self.root / "candidate").exists())

    def test_missing_seventh_input_and_wrong_native_schema_reject(self):
        (self.input / "tables/EssenceMods.json").unlink()
        with self.assertRaises(ValueError):
            self.create()
        self.manifest["schema"]["compatibility_views"] = 1
        self.pin()
        with self.assertRaisesRegex(ValueError, "native schema"):
            self.create()

    def test_exact_raw_copies_output_pins_and_fresh_process_determinism(self):
        manifest = self.create()
        candidate = self.root / "candidate"
        for name in crafting.TABLES:
            self.assertEqual(
                (candidate / f"{name}.json").read_bytes(), (self.input / f"tables/{name}.json").read_bytes()
            )
        self.assertEqual((candidate / "input-manifest.json").read_bytes(), (self.input / "manifest.json").read_bytes())
        for name, pin in manifest["files"].items():
            self.assertEqual(crafting._pin((candidate / name).read_bytes()), pin)
        self.assertFalse(manifest["production_ready"])
        self.assertEqual(manifest["source_identity"], self.manifest["source_identity"])
        command = [
            sys.executable,
            "-B",
            "-m",
            "RePoE.native_crafting_facts",
            "--facts",
            str(self.input),
            "--expected-manifest-sha256",
            self.expected,
            "--out",
            str(self.root / "second"),
        ]
        result = subprocess.run(command, cwd=crafting.ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((candidate / "manifest.json").read_bytes(), (self.root / "second/manifest.json").read_bytes())
        self.assertEqual((candidate / "crafting.json").read_bytes(), (self.root / "second/crafting.json").read_bytes())

    def test_existing_symlink_and_noncache_outputs_refused(self):
        self.create()
        with self.assertRaises(FileExistsError):
            self.create()
        with self.assertRaisesRegex(ValueError, "checkout's .cache"):
            crafting.create_candidate(
                facts=self.input, expected_manifest_sha256=self.expected, out=crafting.ROOT / "forbidden"
            )
        (self.root / "link").symlink_to(self.root / "candidate", target_is_directory=True)
        with self.assertRaises(FileExistsError):
            self.create("link")
        (self.input / "tables/Stats.json").unlink()
        (self.input / "tables/Stats.json").symlink_to(self.root / "candidate/Stats.json")
        with self.assertRaisesRegex(ValueError, "Symlink input"):
            self.create("second")

    def test_changed_input_during_projection_rejected_without_output(self):
        original = crafting.project

        def change(tables):
            result = original(tables)
            (self.input / "tables/Stats.json").write_bytes(b"{}")
            return result

        with patch.object(crafting, "project", side_effect=change):
            with self.assertRaisesRegex(ValueError, "input changed"):
                self.create()
        self.assertFalse((self.root / "candidate").exists())

    def test_interrupted_publication_never_leaves_completion_manifest(self):
        original = crafting.env.os.open

        def fail(path, *args, **kwargs):
            if path == "crafting.json":
                raise OSError("synthetic write failure")
            return original(path, *args, **kwargs)

        with patch.object(crafting.env.os, "open", side_effect=fail):
            with self.assertRaisesRegex(OSError, "synthetic write failure"):
                self.create()
        self.assertFalse((self.root / "candidate/manifest.json").exists())
        with self.assertRaises(FileExistsError):
            self.create()

    def test_duplicate_json_keys_and_nonfinite_json_rejected(self):
        path = self.input / "tables/Stats.json"
        for raw in [b'{"rows":[],"rows":[]}', b'{"unknown":NaN}']:
            path.write_bytes(raw)
            self.manifest["files"]["tables/Stats.json"] = crafting._pin(raw)
            manifest_raw = crafting.env._json(self.manifest)
            (self.input / "manifest.json").write_bytes(manifest_raw)
            self.expected = crafting.env._sha(manifest_raw)
            with self.assertRaises(ValueError):
                self.create()
        self.assertFalse((self.root / "candidate").exists())


if __name__ == "__main__":
    unittest.main()
