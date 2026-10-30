import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from RePoE import schema_candidate as candidate
from RePoE.parser.util import create_relational_reader


class SchemaCandidateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="repoe-schema-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in ["pyproject.toml", "uv.lock", "RePoE/schema_candidate.py", "schema/source.json"]:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(candidate.ROOT / name, path)
        real = json.loads((candidate.ROOT / "schema/poe2.json").read_bytes())
        sample = copy.deepcopy(next(table for table in real["tables"] if table["name"] == "Stats")["columns"][0])
        sample.update(
            name="Value", type="i32", array=False, interval=False, references=None, unique=False, file=None, files=None
        )
        self.schema = {
            "version": real["version"],
            "createdAt": 0,
            "enumerations": [],
            "tables": [{"name": "Proof", "validFor": 2, "columns": [sample]}],
        }
        self.write_schema()
        self.output = self.root / ".cache/candidate"

    def write_schema(self):
        raw = json.dumps(self.schema).encode()
        (self.root / "schema/poe2.json").write_bytes(raw)
        (self.root / "schema/SHA256SUMS").write_text(hashlib.sha256(raw).hexdigest() + "  schema/poe2.json\n")

    def test_native_conversion_never_loads_legacy_adaptation(self):
        from PyPoE.poe.file import specification

        with patch.object(specification, "load", side_effect=AssertionError("Legacy spec was read")):
            receipt = candidate.create_candidate(self.output, root=self.root)
            spec = candidate.load_candidate(self.output, root=self.root)
        self.assertEqual(receipt["mode"], "client-native")
        self.assertEqual(receipt["validation"]["compatibility_views"], 0)
        self.assertEqual(list(spec["Proof.dat"].fields), ["Value"])
        self.assertIn("blocked", receipt["publication"])

    def test_real_relational_reader_decodes_using_the_candidate(self):
        candidate.create_candidate(self.output, root=self.root)
        spec = candidate.load_candidate(self.output, root=self.root)
        data = self.root / "client/Data/Balance"
        data.mkdir(parents=True)
        (data / "Proof.datc64").write_bytes(struct.pack("<Ii", 1, -42) + b"\xbb" * 8)
        reader = create_relational_reader(str(self.root / "client"), "English", True, schema_spec=spec)
        self.assertIs(reader.specification, spec)
        self.assertEqual(reader["Proof.dat64"][0]["Value"], -42)
        with self.assertRaisesRegex(ValueError, "PoE2"):
            create_relational_reader(str(self.root / "client"), "English", False, schema_spec=spec)

    def test_corrupted_source_fails_without_publishing(self):
        with (self.root / "schema/poe2.json").open("ab") as file:
            file.write(b"\n")
        with self.assertRaisesRegex(ValueError, "checksum"):
            candidate.create_candidate(self.output, root=self.root)
        self.assertFalse(self.output.exists())

    def test_native_reader_rejects_a_dangling_runtime_foreign_key(self):
        from PyPoE.poe.file.specification.errors import SpecificationError

        column = self.schema["tables"][0]["columns"][0]
        target_column = copy.deepcopy(column)
        column.update(type="foreignrow", references={"table": "Target"})
        self.schema["tables"].append({"name": "Target", "validFor": 2, "columns": [target_column]})
        self.write_schema()
        candidate.create_candidate(self.output, root=self.root)
        spec = candidate.load_candidate(self.output, root=self.root)
        data = self.root / "client/Data/Balance"
        data.mkdir(parents=True)
        (data / "Proof.datc64").write_bytes(struct.pack("<IQ", 1, 7) + b"\xbb" * 8)
        (data / "Target.datc64").write_bytes(struct.pack("<Ii", 1, 42) + b"\xbb" * 8)
        reader = create_relational_reader(str(self.root / "client"), "English", True, schema_spec=spec)
        with self.assertRaises(SpecificationError):
            reader["Proof.dat64"]

    def test_failed_completion_link_cannot_produce_a_loadable_candidate(self):
        with patch.object(candidate.os, "link", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                candidate.create_candidate(self.output, root=self.root)
        self.assertFalse((self.output / "candidate.json").exists())
        with self.assertRaises(FileNotFoundError):
            candidate.load_candidate(self.output, root=self.root)

    def test_installed_dependency_must_match_the_git_pin(self):
        path = self.root / "pyproject.toml"
        path.write_text(path.read_text().replace("66d1d7442c5718260e1a8efd24989d22987e91af", "0" * 40))
        with self.assertRaisesRegex(ValueError, "Git pin"):
            candidate.create_candidate(self.output, root=self.root)
        self.assertFalse(self.output.exists())

    def test_existing_empty_output_and_non_cache_paths_are_preserved(self):
        self.output.mkdir(parents=True)
        with self.assertRaises(FileExistsError):
            candidate.create_candidate(self.output, root=self.root)
        self.assertTrue(self.output.is_dir())
        with self.assertRaisesRegex(ValueError, ".cache"):
            candidate.create_candidate(self.root / "schema/new", root=self.root)

    def test_foreign_key_validation_failure_does_not_publish(self):
        from PyPoE.poe.file.specification.errors import SpecificationError

        column = self.schema["tables"][0]["columns"][0]
        column.update(type="foreignrow", references={"table": "Absent"})
        self.write_schema()
        with self.assertRaises(SpecificationError):
            candidate.create_candidate(self.output, root=self.root)
        self.assertFalse(self.output.exists())

    def test_duplicate_physical_fields_cannot_be_silently_collapsed(self):
        self.schema["tables"][0]["columns"] *= 2
        self.write_schema()
        with self.assertRaisesRegex(ValueError, "lost columns"):
            candidate.create_candidate(self.output, root=self.root)
        self.assertFalse(self.output.exists())

    def test_changed_inputs_during_generation_do_not_publish(self):
        original = candidate._native_specification

        def concurrent_change(raw):
            result = original(raw)
            path = self.root / "schema/source.json"
            document = json.loads(path.read_bytes())
            document["scope"] = "concurrent edit"
            path.write_text(json.dumps(document))
            return result

        with patch.object(candidate, "_native_specification", concurrent_change):
            with self.assertRaisesRegex(ValueError, "changed during"):
                candidate.create_candidate(self.output, root=self.root)
        self.assertFalse(self.output.exists())

    def test_forged_payload_and_receipt_cannot_execute_python(self):
        candidate.create_candidate(self.output, root=self.root)
        marker = self.root / "must-not-exist"
        payload = f"from pathlib import Path\nPath({str(marker)!r}).touch()\n".encode()
        (self.output / "specification.py").write_bytes(payload)
        path = self.output / "candidate.json"
        document = json.loads(path.read_bytes())
        document["files"]["specification.py"] = hashlib.sha256(payload).hexdigest()
        path.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, "provenance"):
            candidate.load_candidate(self.output, root=self.root)
        self.assertFalse(marker.exists())

    def test_payload_tampering_is_rejected_even_with_original_receipt(self):
        candidate.create_candidate(self.output, root=self.root)
        with (self.output / "specification.py").open("ab") as file:
            file.write(b"\n")
        with self.assertRaisesRegex(ValueError, "content"):
            candidate.load_candidate(self.output, root=self.root)


class RealSchemaReplayTests(unittest.TestCase):
    def test_fixed_real_inputs_replay_across_processes_without_changing_pypoe(self):
        import PyPoE

        cache = candidate.ROOT / ".cache"
        cache.mkdir(exist_ok=True)
        installed = Path(PyPoE.__file__).parent / "poe/file/specification/data/poe2.py"
        before = installed.read_bytes()
        with tempfile.TemporaryDirectory(dir=cache, prefix="schema-replay-") as temporary:
            outputs = []
            for index, seed in enumerate(["1", "49"]):
                output = Path(temporary) / str(index)
                result = subprocess.run(
                    [sys.executable, "-m", "RePoE.schema_candidate", "--out", str(output)],
                    cwd=candidate.ROOT,
                    env={**os.environ, "PYTHONHASHSEED": seed},
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                outputs.append({p.name: p.read_bytes() for p in output.iterdir()})
                candidate.load_candidate(output)
            self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(installed.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
