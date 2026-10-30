"""Synthetic physical fixtures; no game downloads or dependency on a sibling checkout."""

import copy
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings

from RePoE import native_facts as facts
from RePoE import schema_candidate


def dat_bytes(specification, name, rows):
    """Encode tiny physical fixtures, including null sentinels and ordered arrays."""
    data = bytearray(b"\xbb" * 8)
    formats = {"int": "i", "uint": "I", "ushort": "H", "float": "f", "bool": "?", "byte": "b"}

    def encode(kind, value):
        if kind.startswith("ref|list|"):
            items = b"".join(encode(kind[9:], item) for item in value or [])
            offset = len(data)
            data.extend(items)
            return struct.pack("<QQ", len(value or []), offset)
        if kind == "ref|string":
            offset = len(data)
            data.extend((value or "").encode("utf-16-le") + b"\0\0\0\0")
            return struct.pack("<Q", offset)
        if kind in ("ref|out", "ref|generic"):
            value = 0xFEFEFEFEFEFEFEFE if value is None else value
            return struct.pack("<QQ", value, 0) if kind == "ref|out" else struct.pack("<Q", value)
        return struct.pack("<" + formats[kind], value or 0)

    records = b"".join(
        b"".join(encode(field.type, row.get(key)) for key, field in specification[name + ".dat"].fields.items())
        for row in rows
    )
    return struct.pack("<I", len(rows)) + records + data


def psg_bytes():
    return (
        struct.pack("<BBBBB", 3, 0, 2, 1, 6)
        + struct.pack("<III", 1, 10, 0)
        + struct.pack("<IffIIbI", 1, 1.25, -2.5, 5, 29, -1, 1)
        + struct.pack("<IIII", 10, 1, 4, 1)
        + struct.pack("<Ii", 10, -7)
    )


class NativeFactsFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs, cls.schema = schema_candidate._inputs(schema_candidate.ROOT)
        _, cls.spec = schema_candidate._native_specification(cls.schema)
        cls.schema_tables = {t["name"]: t for t in json.loads(cls.schema)["tables"]}

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="repoe-facts-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.raw = self.root / "raw"
        self.out = self.root / "out"
        self.lock = self.root / "sources.lock.json"
        passive = {
            "Id": "full",
            "PassiveSkillGraphId": 10,
            "Stats": list(range(7)),
            "IsAttribute": True,
            "UnlockedBy": [1],
            "VisibleForAscendancy": 0,
            "NodeFrameArt": 0,
            "Unknown7": -33,
        }
        passive.update({f"Stat{i}Value": value for i, value in enumerate([1, 0, -3, 4, 10, 6, 7], 1)})
        self.rows = {
            "Characters": [{"Id": "Druid", "Name": "Druid"}],
            "Stats": [{"Id": f"stat{i}"} for i in range(7)],
            "PassiveSkills": [
                passive,
                {"Id": "base_outside", "PassiveSkillGraphId": 20},
                {"Id": "replacement", "PassiveSkillGraphId": 30},
                {"Id": "source_placeholder", "PassiveSkillGraphId": 65535, "Unknown7": -99},
            ],
            "ClassPassiveSkillOverrides": [
                {"CharacterToOverrideFor": 0, "SkillToOverride": i, "Override": 2} for i in (0, 1)
            ],
            "PassiveSkillTrees": [
                {"Id": "Default", "PassiveSkillGraph": "Metadata/PassiveSkillGraph"},
                {"Id": "Other", "PassiveSkillGraph": "Metadata/Other"},
            ],
            "GrantedEffectStatSets": [
                {"Id": f"set{i}", "Label": 0, "ConstantStats": [0], "ConstantStatsValues": [0]} for i in range(3)
            ],
            "GrantedEffects": [{"Id": "ScopedEffect", "StatSet": 0, "AdditionalStatSets": [1, 2]}],
            "GrantedEffectQualityStats": [
                {
                    "GrantedEffect": 0,
                    "Stats": [0],
                    "StatsValuesPermille": [-200],
                    "ApplyToStatSets": [1, 2, 3],
                    "AltStats": [1, 6],
                    "AltStatValuesPermille": [0, 1000],
                    "AltApplyToStatSets": [0],
                }
            ],
        }
        self.source = {
            "kind": "official-client-resource-candidate",
            "game": "poe2",
            "game_patch": "0.5.5.5",
            "realm": "international",
            "decoder": {
                "revision": facts.PYPOE,
                "dat_schema_revision": facts.SCHEMA,
                "schema_sha256": facts.SCHEMA_SHA,
            },
            "resources": {},
        }
        self.write_inputs()

    def write_inputs(self):
        for name, rows in self.rows.items():
            path = self.raw / f"Data/Balance/{name}.datc64"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(dat_bytes(self.spec, name, rows))
        path = self.raw / facts.PSG
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(psg_bytes())
        for name in (*(f"Data/Balance/{name}.datc64" for name in self.rows), facts.PSG):
            raw = (self.raw / name).read_bytes()
            self.source["resources"][name] = {"bytes": len(raw), "sha256": schema_candidate._sha(raw)}
        self.write_lock()

    def write_lock(self):
        self.lock.write_bytes(facts._json({"schema_version": 1, "sources": {"fixture": self.source}}))

    def create(self):
        return facts.create_candidate(source_lock=self.lock, source="fixture", raw=self.raw, out=self.out)

    def load(self, name):
        return json.loads((self.out / name).read_bytes())


class NativeFactsTests(NativeFactsFixture):
    def test_complete_physical_and_native_projections_without_legacy_or_network(self):
        from RePoE.native_tools import _SourceLoader

        execute = _SourceLoader.exec_module

        def forbid_legacy(loader, module):
            execute(loader, module)
            if module.__name__ == "PyPoE.poe.file.specification":
                module.load = lambda *a, **kw: self.fail("legacy specification load")

        with (
            patch.object(_SourceLoader, "exec_module", forbid_legacy),
            patch("socket.socket", side_effect=AssertionError("network")),
        ):
            manifest = self.create()
        self.assertEqual(manifest["format"], facts.FORMAT)
        self.assertFalse(manifest["production_ready"])
        self.assertEqual(len(manifest["files"]), 12)
        for name, identity in manifest["files"].items():
            raw = (self.out / name).read_bytes()
            self.assertEqual(identity, {"bytes": len(raw), "sha256": schema_candidate._sha(raw)})
        table = self.load("tables/PassiveSkills.json")
        self.assertEqual(len(table["rows"]), 4)
        self.assertEqual(table["rows"][0]["values"]["Unknown7"], -33)
        self.assertEqual(table["rows"][0]["values"]["UnlockedBy"], [1])
        self.assertTrue(table["rows"][0]["values"]["IsAttribute"])
        self.assertEqual(table["rows"][3]["values"]["Unknown7"], -99)
        p = self.load("passives.json")
        self.assertEqual([s["value"] for s in p["definitions"][0]["stats"]], [1, 0, -3, 4, 10, 6, 7])
        self.assertEqual(p["definitions"][0]["stats"][4]["slot"], 5)
        self.assertEqual(len(p["default_graph_instances"]), 1)
        self.assertEqual(len(p["class_overrides"]), 2)
        self.assertFalse(p["class_overrides"][1]["base_in_default_graph"])
        graph = self.load("graph.json")
        self.assertEqual((graph["groups"][0]["unknown1"], graph["groups"][0]["unknown2"]), (29, -1))
        self.assertEqual(graph["groups"][0]["nodes"][0]["splines"], [-7])
        quality = self.load("skills.json")["qualities"][0]
        self.assertEqual(quality["main"]["scope_raw"], [1, 2, 3])
        self.assertEqual(quality["alternate"]["stats"][0]["value_permille"], 0)
        self.assertEqual([s["stat_set"]["id"] for s in quality["ordered_stat_sets"]], ["set0", "set1", "set2"])
        diagnostics = self.load("diagnostics.json")["diagnostics"]
        label = next(d for d in diagnostics if d.get("field") == "Label")
        self.assertEqual(label["occurrences"][0]["value"], 0)
        scope = [d for d in diagnostics if d["code"].startswith("quality_scope")]
        self.assertEqual(len(scope), 1)
        self.assertEqual(scope[0]["value"], 3)
        self.assertFalse(any(key in graph for key in ("orbit_radii", "global_coordinates")))

    def test_native_intervals_keep_min_max_and_original_column_metadata(self):
        table = copy.deepcopy(self.schema_tables["ClassPassiveSkillOverrides"])
        column = copy.deepcopy(self.schema_tables["PassiveSkills"]["columns"][3])
        column.update(name="Stat8Value", interval=True)
        table["columns"] = [column]
        schema = {"version": 7, "tables": [dict(table, name="Proof", validFor=2)], "enumerations": []}
        _, specification = schema_candidate._native_specification(facts._json(schema))
        raw = dat_bytes(specification, "Proof", [{"Stat8Min": -25, "Stat8Max": 0}])
        result = facts._decode_dat("Proof", raw, specification, table)
        self.assertEqual(result["rows"][0]["values"], {"Stat8Min": -25, "Stat8Max": 0})
        self.assertEqual(result["columns"][0]["schema"]["name"], "Stat8Value")
        self.assertEqual(result["columns"][0]["physical_fields"], ["Stat8Min", "Stat8Max"])

    def test_corrupt_missing_forged_or_escaping_input_fails_before_output(self):
        path = self.raw / facts.PSG
        good = path.read_bytes()
        path.write_bytes(good + b"bad")
        with self.assertRaisesRegex(ValueError, "hash/size"):
            self.create()
        self.assertFalse(self.out.exists())
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.create()
        self.assertFalse(self.out.exists())
        external = self.root / "external.psg"
        external.write_bytes(good)
        path.symlink_to(external)
        with self.assertRaisesRegex(ValueError, "escapes"):
            self.create()
        self.assertFalse(self.out.exists())
        path.unlink()
        path.write_bytes(good)
        self.source["decoder"]["revision"] = "0" * 40
        self.write_lock()
        with self.assertRaisesRegex(ValueError, "pin mismatch"):
            self.create()
        self.assertFalse(self.out.exists())

    def test_wrong_patch_or_missing_resource_not_silently_narrowed(self):
        self.source["game_patch"] = "0.5.5.4.2"
        self.write_lock()
        with self.assertRaisesRegex(ValueError, "0.5.5.5"):
            self.create()
        self.source["game_patch"] = "0.5.5.5"
        del self.source["resources"][facts.PSG]
        self.write_lock()
        with self.assertRaisesRegex(ValueError, "exactly the selected profile"):
            self.create()
        self.assertFalse(self.out.exists())

    def test_authenticated_bad_framing_and_missing_required_join_fail_before_output(self):
        self.rows["PassiveSkills"][0]["Stats"] = [900]
        self.write_inputs()
        with self.assertRaisesRegex(ValueError, "dangling required Stats"):
            self.create()
        self.assertFalse(self.out.exists())
        self.rows["PassiveSkills"][0]["Stats"] = [0]
        self.write_inputs()
        path = self.raw / facts.PSG
        path.write_bytes(path.read_bytes() + b"\0")
        self.source["resources"][facts.PSG] = {
            "bytes": path.stat().st_size,
            "sha256": schema_candidate._sha(path.read_bytes()),
        }
        self.write_lock()
        with self.assertRaisesRegex(ValueError, "Trailing PSG"):
            self.create()
        self.assertFalse(self.out.exists())

    def test_exact_row_width_and_warnings_are_rejected(self):
        raw = dat_bytes(self.spec, "ClassPassiveSkillOverrides", self.rows["ClassPassiveSkillOverrides"])
        bad = raw[:100] + b"\0" * 2 + raw[100:]
        with self.assertRaisesRegex(ValueError, "width/framing"):
            facts._decode_dat(
                "ClassPassiveSkillOverrides", bad, self.spec, self.schema_tables["ClassPassiveSkillOverrides"]
            )
        decode = facts._decode_dat

        def warning_decoder(*args):
            # Patch the verified reader inside the isolated native operation.
            from PyPoE.poe.file.dat import DatReader

            original = DatReader.read

            def warn(reader, raw):
                original(reader, raw)
                warnings.warn("synthetic decoder warning")

            with patch.object(DatReader, "read", warn):
                return decode(*args)

        with (
            patch.object(facts, "_decode_dat", warning_decoder),
            self.assertRaisesRegex(ValueError, "decoder warnings"),
        ):
            self.create()
        self.assertFalse(self.out.exists())

    def test_existing_output_and_failed_completion_never_replace_a_candidate(self):
        self.out.mkdir()
        with self.assertRaises(FileExistsError):
            self.create()
        self.assertEqual(list(self.out.iterdir()), [])
        self.out.rmdir()
        with patch.object(facts.os, "link", side_effect=OSError("disk full")), self.assertRaises(OSError):
            self.create()
        self.assertFalse((self.out / "manifest.json").exists())

    def test_required_graph_topology_and_definition_identity_fail_closed(self):
        self.rows["PassiveSkills"][1]["PassiveSkillGraphId"] = 10
        self.write_inputs()
        with self.assertRaisesRegex(ValueError, "exactly one passive"):
            self.create()
        self.assertFalse(self.out.exists())
        with self.assertRaisesRegex(ValueError, "Truncated"):
            facts._decode_psg(psg_bytes()[:-1])

    def test_independent_process_replay_and_no_machine_paths(self):
        outputs = []
        for i, seed in enumerate(("3", "71")):
            output = self.root / f"replay-{i}"
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "RePoE.native_facts",
                    "--source-lock",
                    str(self.lock),
                    "--source",
                    "fixture",
                    "--raw",
                    str(self.raw),
                    "--out",
                    str(output),
                ],
                cwd=schema_candidate.ROOT,
                env={**os.environ, "PYTHONHASHSEED": seed},
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            outputs.append({path.relative_to(output).as_posix(): path.read_bytes() for path in output.rglob("*.json")})
        self.assertEqual(outputs[0], outputs[1])
        self.assertNotIn(str(self.root).encode(), b"".join(outputs[0].values()))
        self.assertNotIn(b"upstream_created_at", outputs[0]["manifest.json"])


if __name__ == "__main__":
    unittest.main()
