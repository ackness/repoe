"""Regression tests for fixed tool bytes, hostile DAT pointers and candidate acceptance."""

import copy
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
from unittest.mock import patch

from RePoE import native_facts as facts, native_validate, schema_candidate
from RePoE.native_tools import PIN
import test_native_facts as fixture


def run_producer(test, out, *, pythonpath=None, code=None, executable=None):
    arguments = ["--source-lock", str(test.lock), "--source", "fixture", "--raw", str(test.raw), "--out", str(out)]
    entry = ["-m", "RePoE.native_facts"] if code is None else ["-c", code]
    return subprocess.run(
        [executable or sys.executable, "-B", *entry, *arguments],
        cwd=schema_candidate.ROOT,
        env={**os.environ, "PYTHONPATH": pythonpath or str(schema_candidate.ROOT)},
        capture_output=True,
        text=True,
        timeout=10,
    )


class NativeToolPinTests(fixture.NativeFactsFixture):
    def test_symlink_venv_uses_the_same_pinned_sources_and_candidate(self):
        alias = self.root / "venv-alias"
        alias.symlink_to(sys.prefix, target_is_directory=True)
        direct = self.root / "direct-candidate"
        for executable, out in ((sys.executable, direct), (alias / "bin" / Path(sys.executable).name, self.out)):
            result = run_producer(self, out, executable=executable)
            self.assertEqual(result.returncode, 0, result.stderr)
        direct_files = {path.relative_to(direct): path.read_bytes() for path in direct.rglob("*") if path.is_file()}
        alias_files = {path.relative_to(self.out): path.read_bytes() for path in self.out.rglob("*") if path.is_file()}
        self.assertEqual(alias_files, direct_files)

    def copy_install(self):
        package = importlib.metadata.distribution("PyPoE")
        site = self.root / "site"
        shutil.copytree(package.locate_file("PyPoE"), site / "PyPoE", ignore=shutil.ignore_patterns("__pycache__"))
        metadata = next(file for file in package.files if file.name == "direct_url.json")
        shutil.copytree(package.locate_file(metadata.parent), site / metadata.parent.name)
        return site

    def test_modified_tool_bytes_with_unchanged_direct_url_rejected_before_import(self):
        site = self.copy_install()
        marker = self.root / "executed"
        for i, name in enumerate(
            (
                "__init__.py",
                "poe/file/dat.py",
                "poe/file/psg2.py",
                "poe/file/specification/generation/import_dat_schema.py",
                "poe/file/specification/generation/template.py",
                "poe/file/specification/data/stable.py",
            )
        ):
            with self.subTest(name=name):
                path = site / "PyPoE" / name
                original = path.read_bytes()
                if name == "poe/file/dat.py":
                    changed = original.replace(
                        b"            return value\n        except Exception:",
                        b'            return 999 if specification.name == "Stat5Value" else value\n        except Exception:',
                    )
                    self.assertNotEqual(changed, original)
                else:
                    changed = original + f"\nfrom pathlib import Path\nPath({str(marker)!r}).touch()\n".encode()
                try:
                    path.write_bytes(changed)
                    out = self.root / f"mutation-{i}"
                    result = run_producer(self, out, pythonpath=f"{site}{os.pathsep}{schema_candidate.ROOT}")
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn("trusted Git pin", result.stderr)
                    self.assertFalse(out.exists())
                    self.assertFalse(marker.exists())
                finally:
                    path.write_bytes(original)

    def test_shadow_package_is_rejected_without_executing_its_init(self):
        shadow = self.root / "shadow/PyPoE"
        shadow.mkdir(parents=True)
        marker = self.root / "executed"
        (shadow / "__init__.py").write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
        result = run_producer(self, self.out, pythonpath=f"{shadow.parent}{os.pathsep}{schema_candidate.ROOT}")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("import path", result.stderr)
        self.assertFalse(marker.exists())
        self.assertFalse(self.out.exists())

    def test_git_ident_forms_and_poisoned_bytecode_use_verified_source(self):
        from importlib._bootstrap_external import _code_to_timestamp_pyc

        site = self.copy_install()
        pin = json.loads(PIN.read_bytes())
        for name, allowed in pin["sources"].items():
            path = site / "PyPoE" / name
            raw = re.sub(rb"\$Id: [a-f0-9]{40} \$", b"$Id$", path.read_bytes())
            self.assertIn(schema_candidate._sha(raw), allowed)
            path.write_bytes(raw)
        path = site / "PyPoE/__init__.py"
        marker = self.root / "bytecode-executed"
        code = compile(f"from pathlib import Path\nPath({str(marker)!r}).touch()", str(path), "exec")
        bytecode = Path(importlib.util.cache_from_source(str(path)))
        bytecode.parent.mkdir()
        bytecode.write_bytes(_code_to_timestamp_pyc(code, int(path.stat().st_mtime), path.stat().st_size))
        result = run_producer(self, self.out, pythonpath=f"{site}{os.pathsep}{schema_candidate.ROOT}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.exists())
        self.assertEqual(self.load("passives.json")["definitions"][0]["stats"][4]["value"], 10)

    def test_preloaded_decoder_is_not_reused_and_is_restored_after_native_operation(self):
        from PyPoE.poe.file.dat import DatReader

        with patch.object(DatReader, "read", side_effect=AssertionError("unverified preloaded decoder")) as read:
            self.create()
            from PyPoE.poe.file.dat import DatReader as restored

            self.assertIs(restored, DatReader)
            self.assertIs(restored.read, read)
        self.assertEqual(self.load("passives.json")["definitions"][0]["stats"][4]["value"], 10)


class NativeBoundsTests(fixture.NativeFactsFixture):
    def replace_passives(self, raw):
        name = "Data/Balance/PassiveSkills.datc64"
        (self.raw / name).write_bytes(raw)
        self.source["resources"][name] = {"bytes": len(raw), "sha256": schema_candidate._sha(raw)}
        self.write_lock()

    def test_invalid_strings_and_list_spans_reject_end_to_end_with_timeout(self):
        from PyPoE.poe.file.dat import DatReader

        raw = (self.raw / "Data/Balance/PassiveSkills.datc64").read_bytes()
        reader = DatReader("PassiveSkills.datc64", specification=self.spec, x64=True)
        boundary = 4 + 4 * reader.cast_size
        at = 4
        offsets = {}
        for field, casts in reader.cast_spec:
            offsets[field.name] = at
            at += casts[0][1]
        variants = []
        for pointer in (4501, 0, 0x1111111111111110):
            changed = bytearray(raw)
            struct.pack_into("<Q", changed, offsets["Id"], pointer)
            variants.append(changed)
        for suffix in (b"X\0", b"X\0Y\0Z\0"):
            changed = bytearray(raw + suffix)
            struct.pack_into("<Q", changed, offsets["Id"], len(raw) - boundary)
            variants.append(changed)
        for length, pointer in ((1, len(raw)), (2**63, 8), (1, 0)):
            changed = bytearray(raw)
            struct.pack_into("<QQ", changed, offsets["Stats"], length, pointer)
            variants.append(changed)
        for i, changed in enumerate(variants):
            with self.subTest(variant=i):
                self.replace_passives(changed)
                out = self.root / f"bad-pointer-{i}"
                result = run_producer(self, out)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertRegex(result.stderr, "bounds|unterminated")
                self.assertFalse(out.exists())

    def test_string_list_pointer_and_empty_sentinel_offsets(self):
        table = copy.deepcopy(self.schema_tables["PassiveSkills"])
        column = copy.deepcopy(table["columns"][0])
        column.update(name="Strings", type="string", array=True, interval=False, references=None)
        table.update(name="Proof", validFor=2, columns=[column])
        schema = {"version": 7, "tables": [table], "enumerations": []}
        _, specification = schema_candidate._native_specification(facts._json(schema))
        raw = fixture.dat_bytes(specification, "Proof", [{"Strings": ["hello", ""]}])
        self.assertEqual(
            facts._decode_dat("Proof", raw, specification, table)["rows"][0]["values"]["Strings"], ["hello", ""]
        )
        boundary = 20
        changed = bytearray(raw)
        pointer = struct.unpack_from("<Q", raw, 12)[0]
        struct.pack_into("<Q", changed, boundary + pointer, 0x1111111111111110)
        with self.assertRaisesRegex(ValueError, "bounds"):
            facts._decode_dat("Proof", changed, specification, table)
        struct.pack_into("<QQ", changed, 4, 0, 0xFEFEFEFEFEFEFEFE)
        self.assertEqual(
            facts._decode_dat("Proof", bytes(changed), specification, table)["rows"][0]["values"]["Strings"], []
        )

    def test_no_terminator_anywhere_is_bounded_before_decoder(self):
        # The original find(-1) alignment loop never terminated for this input.
        code = """
import json, struct
from RePoE import native_facts as f, schema_candidate as s
schema = json.loads((s.ROOT / 'schema/poe2.json').read_bytes())
table = next(t for t in schema['tables'] if t['name'] == 'PassiveSkills').copy()
table.update(name='Proof', columns=[table['columns'][0]])
_, spec = s._native_specification(f._json(dict(schema, tables=[table])))
raw = struct.pack('<IQ', 1, 0x1111111111111110) + b'\\xbb'*8 + b'A\\0'
try:
    f._decode_dat('Proof', raw, spec, table)
except ValueError as error:
    assert 'bounds' in str(error)
else:
    raise AssertionError('invalid pointer accepted')
"""
        result = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 0, result.stderr)


class NativeAcceptanceTests(fixture.NativeFactsFixture):
    def validate(self):
        return native_validate.validate_candidate(
            source_lock=self.lock, source="fixture", raw=self.raw, candidate=self.out
        )

    def rewrite(self, name, document):
        raw = facts._json(document)
        (self.out / name).write_bytes(raw)
        manifest = self.load("manifest.json")
        manifest["files"][name] = {"bytes": len(raw), "sha256": schema_candidate._sha(raw)}
        (self.out / "manifest.json").write_bytes(facts._json(manifest))

    def test_full_instance_fields_and_inventory_rejected_despite_rehashed_manifest(self):
        self.create()
        self.assertEqual(self.validate()["complete_graph_instances_checked"], 1)
        good = self.load("passives.json")
        for field, value in (
            ("group", 999999),
            ("radius", 999999),
            ("position", 999999),
            ("connections", []),
            ("splines", []),
            ("definition", {"row": 1, "id": "base_outside"}),
            ("graph_id", 20),
            ("group", False),
        ):
            with self.subTest(field=field, value=value):
                document = copy.deepcopy(good)
                document["default_graph_instances"][0][field] = value
                self.rewrite("passives.json", document)
                with self.assertRaisesRegex(ValueError, "default_graph_instances"):
                    self.validate()
        for instances in ([], good["default_graph_instances"] * 2):
            self.rewrite("passives.json", dict(good, default_graph_instances=instances))
            with self.assertRaisesRegex(ValueError, "default_graph_instances"):
                self.validate()

    def test_raw_authority_rejects_synchronized_graph_projection_and_definition_forgery(self):
        self.create()
        graph, passives = self.load("graph.json"), self.load("passives.json")
        graph["groups"][0]["nodes"][0]["radius"] = 999999
        passives["default_graph_instances"][0]["radius"] = 999999
        self.rewrite("graph.json", graph)
        self.rewrite("passives.json", passives)
        with self.assertRaisesRegex(ValueError, "PSG fields"):
            self.validate()

    def test_order_and_definition_join_checked_independently_of_producer(self):
        self.create()
        table = self.load("tables/PassiveSkills.json")
        graph = self.load("graph.json")
        passives = self.load("passives.json")
        # Add a second real fixture node, then derive the valid instance once.
        raw = bytearray(fixture.psg_bytes())
        struct.pack_into("<I", raw, 38, 2)
        raw.extend(struct.pack("<IIII", 20, 2, 5, 0))
        framed = facts._frame_psg(raw)
        graph.update(framed)
        passives["definitions"][1]["in_default_graph"] = True
        second = {**framed["groups"][0]["nodes"][1], "group": 0, "definition": {"row": 1, "id": "base_outside"}}
        passives["default_graph_instances"].append(second)
        self.assertEqual(native_validate.validate_graph_instances(raw, table, graph, passives), 2)
        passives["default_graph_instances"].reverse()
        with self.assertRaisesRegex(ValueError, "inventory/order/fields"):
            native_validate.validate_graph_instances(raw, table, graph, passives)
        passives["default_graph_instances"].reverse()
        passives["definitions"][0]["definition"]["id"] = "forged"
        with self.assertRaisesRegex(ValueError, "definition identity"):
            native_validate.validate_graph_instances(raw, table, graph, passives)
