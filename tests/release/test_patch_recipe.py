"""Strict, offline contracts for local prepare-patch recipes."""

import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from RePoE.native import facts
from RePoE.release import patch_recipe
from RePoE.release.pins import encoded, pin


class PatchRecipeTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "recipe"
        self.root.mkdir()
        self.path = self.root / "prepare.json"
        self.lock = self.root / "inputs" / "sources.lock.json"
        self.lock.parent.mkdir()
        self.decoder_lock = self.root / "decoder.lock"
        self.decoder_lock.write_bytes(b"version = 1\n")
        self.retained = self.root / "retained.json"
        self.retained.write_bytes(b'{"retained":true}\n')
        self.sources = {
            "full": self.source(
                [f"Data/Balance/{table}.datc64" for table in facts.profile_tables(facts.ITEMS_ACTORS_PROFILE)]
                + [facts.PSG],
                profile=facts.ITEMS_ACTORS_PROFILE,
            ),
            "tables": self.source(["Data/Balance/Stats.datc64"]),
            "localized": self.source(["Data/Balance/Simplified Chinese/Stats.datc64"], language="Simplified Chinese"),
            "descriptions": self.source(["Metadata/StatDescriptions/stat_descriptions.txt"]),
            "inheritance": self.source(["Metadata/Items/fixture.it"]),
        }
        self.recipe = {
            "schema": patch_recipe.SCHEMA,
            "target": {"game": "poe2", "realm": "international", "game_patch": "9.9.9"},
            "source_lock": {},
            "decoder": {
                "python": sys.executable,
                "lock": {"path": "decoder.lock", **pin(self.decoder_lock.read_bytes())},
            },
            "exports": [
                {
                    "id": "tables-before",
                    "kind": "tables",
                    "source": "tables",
                    "package": "display",
                    "destination": "tables/default",
                    "language": "English",
                },
                {
                    "id": "facts",
                    "kind": "facts",
                    "source": "full",
                    "package": "ordinary",
                    "destination": "facts",
                    "profile": facts.ITEMS_ACTORS_PROFILE,
                },
                {
                    "id": "localized",
                    "kind": "tables",
                    "source": "localized",
                    "package": "display",
                    "destination": "tables/zh-cn",
                    "language": "Simplified Chinese",
                },
                {
                    "id": "descriptions",
                    "kind": "descriptions",
                    "source": "descriptions",
                    "package": "descriptions",
                    "destination": "stat-descriptions/default",
                },
                {
                    "id": "inheritance",
                    "kind": "item-inheritance",
                    "source": "inheritance",
                    "package": "inheritance",
                    "destination": "items",
                },
                {
                    "id": "tables-again",
                    "kind": "tables",
                    "source": "tables",
                    "package": "display",
                    "destination": "tables/other",
                    "language": "English",
                },
                {"id": "crafting", "kind": "crafting", "facts": "facts", "package": "crafting", "destination": "."},
            ],
            "retained": [
                {
                    "path": "retained.json",
                    "package": "legacy",
                    "destination": "nested/manifest.json",
                    **pin(self.retained.read_bytes()),
                }
            ],
        }
        self.save_sources()

    def source(self, resources, **extra):
        return {
            "kind": "official-client-resource-candidate",
            "game": "poe2",
            "realm": "international",
            "game_patch": "9.9.9",
            "base_url": "https://patch-poe2.poecdn.com/9.9.9/",
            "acquisition": {
                "status": "unreviewed-acquisition-draft",
                "evidence": [{"kind": "test-acquisition", "sha256": "1" * 64}],
            },
            "resources": {
                name: {
                    "bytes": 1,
                    "sha256": "2" * 64,
                    "uncompressed_offset": 0,
                    "uncompressed_length": 1,
                    "bundle_url": "https://patch-poe2.poecdn.com/9.9.9/Bundles2/fixture.bundle.bin",
                }
                for name in resources
            },
            **extra,
        }

    def save_sources(self):
        raw = encoded({"schema_version": 1, "sources": self.sources})
        self.lock.write_bytes(raw)
        self.recipe["source_lock"] = {"path": "inputs/sources.lock.json", **pin(raw)}

    def load(self, recipe=None):
        raw = encoded(self.recipe if recipe is None else recipe)
        self.path.write_bytes(raw)
        return patch_recipe.load_recipe(self.path, pin(raw)["sha256"])

    def record(self, recipe, section):
        if section == "decoder":
            return recipe["decoder"]["lock"]
        if section == "retained":
            return recipe["retained"][0]
        return recipe["source_lock"]

    def test_positive_return_contract_and_read_only_source_validation(self):
        before = {path: path.read_bytes() for path in (self.lock, self.decoder_lock, self.retained)}
        with mock.patch.object(patch_recipe._client, "load_source", wraps=patch_recipe._client.load_source) as loader:
            result = self.load()
        expected = copy.deepcopy(self.recipe)
        expected["source_lock"]["path"] = self.lock
        expected["decoder"]["lock"]["path"] = self.decoder_lock
        expected["decoder"]["python"] = Path(sys.executable).absolute()
        expected["retained"][0]["path"] = self.retained
        expected.update(
            pin=pin(self.path.read_bytes()),
            source_names=["tables", "full", "localized", "descriptions", "inheritance"],
            sources={
                name: self.sources[name] for name in ("tables", "full", "localized", "descriptions", "inheritance")
            },
            packages=["crafting", "descriptions", "display", "inheritance", "legacy", "ordinary"],
        )
        self.assertEqual(result, expected)
        self.assertEqual(loader.call_args_list, [mock.call(self.lock, name) for name in expected["source_names"]])
        self.assertEqual({path: path.read_bytes() for path in before}, before)
        self.assertEqual(self.path.read_bytes(), encoded(self.recipe))

    def test_empty_retained_and_unselected_invalid_source_are_allowed(self):
        self.recipe["retained"] = []
        self.sources["unused"] = {"invalid": True}
        self.save_sources()
        result = self.load()
        self.assertNotIn("legacy", result["packages"])
        self.assertNotIn("unused", result["sources"])

    def test_absolute_inputs_and_symlinked_python_keep_their_spelling(self):
        python = self.root / "venv" / "bin" / "python"
        python.parent.mkdir(parents=True)
        python.symlink_to(sys.executable)
        self.recipe["decoder"]["python"] = str(python)
        for section, path in (("source", self.lock), ("decoder", self.decoder_lock), ("retained", self.retained)):
            self.record(self.recipe, section)["path"] = str(path)
        result = self.load()
        self.assertEqual(result["decoder"]["python"], python)
        self.assertNotEqual(result["decoder"]["python"], python.resolve())
        self.assertEqual(result["source_lock"]["path"], self.lock)
        self.assertEqual(result["decoder"]["lock"]["path"], self.decoder_lock)
        self.assertEqual(result["retained"][0]["path"], self.retained)

    def test_external_recipe_pin_is_required_and_exact(self):
        raw = encoded(self.recipe)
        self.path.write_bytes(raw)
        for digest in (None, True, 12, [], "", "0" * 63, "F" * 64, "0" * 64):
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                patch_recipe.load_recipe(self.path, digest)
        self.path.write_bytes(raw + b" ")
        with self.assertRaisesRegex(ValueError, "Recipe SHA-256 mismatch"):
            patch_recipe.load_recipe(self.path, pin(raw)["sha256"])

    def test_invalid_and_duplicate_json_are_rejected(self):
        duplicate = encoded(self.recipe).rstrip()[:-1] + b',"schema":"repoe-prepare-patch/v1"}'
        for raw in (b"{", b"\xff", b"[]", b"true", duplicate, b'{"schema":NaN}', b'{"schema":Infinity}'):
            with self.subTest(raw=raw[:80]), self.assertRaises(ValueError):
                self.path.write_bytes(raw)
                patch_recipe.load_recipe(self.path, pin(raw)["sha256"])

    def test_every_recipe_object_has_exact_fields(self):
        base = self.recipe
        sections = [(), ("target",), ("source_lock",), ("decoder",), ("decoder", "lock"), ("retained", 0)]
        sections.extend(("exports", position) for position in range(len(base["exports"])))
        for section in sections:
            original = base
            for key in section:
                original = original[key]
            for field in (None, *original):
                with self.subTest(section=section, field=field), self.assertRaises(ValueError):
                    recipe = copy.deepcopy(base)
                    record = recipe
                    for key in section:
                        record = record[key]
                    if field is None:
                        record["command"] = ["sh", "-c", "false"]
                    else:
                        del record[field]
                    self.load(recipe)

    def test_shapes_and_value_types_are_strict(self):
        cases = [
            ("schema", None),
            ("schema", "repoe-prepare-patch/v2"),
            ("target", []),
            ("source_lock", []),
            ("decoder", []),
            ("exports", {}),
            ("exports", [None]),
            ("exports", []),
            ("retained", {}),
            ("retained", [None]),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.load({**self.recipe, field: value})
        for field in ("id", "kind", "source", "package", "destination", "language"):
            for value in (None, True, [], {}, 1):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    recipe = copy.deepcopy(self.recipe)
                    recipe["exports"][0][field] = value
                    self.load(recipe)

    def test_target_is_exact_and_numeric(self):
        cases = [("game", "poe1"), ("realm", "china")]
        cases.extend(("game_patch", value) for value in (None, 999, True, "", "9", "latest", "9.x", "9.9/9", "９.９"))
        for field, value in cases:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                recipe = copy.deepcopy(self.recipe)
                recipe["target"][field] = value
                self.load(recipe)

    def test_all_file_pins_are_typed_and_exact(self):
        cases = [("bytes", value) for value in (None, True, -1, 1.0, "1", 0)]
        cases.extend(("sha256", value) for value in (None, True, [], "", "F" * 64, "0" * 64))
        for section in ("source", "decoder", "retained"):
            for field, value in cases:
                with self.subTest(section=section, field=field, value=value), self.assertRaises(ValueError):
                    recipe = copy.deepcopy(self.recipe)
                    self.record(recipe, section)[field] = value
                    self.load(recipe)

    def test_pins_cover_complete_file_bytes(self):
        for path in (self.lock, self.decoder_lock, self.retained):
            raw = path.read_bytes()
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "Byte pin mismatch"):
                path.write_bytes(raw + b"\n")
                self.load()
            path.write_bytes(raw)

    def test_input_paths_are_typed_and_cannot_traverse_parents(self):
        for section in ("source", "decoder", "retained"):
            for value in (None, True, [], "", "bad\x00path", "inputs/../retained.json"):
                with self.subTest(section=section, value=value), self.assertRaises(ValueError):
                    recipe = copy.deepcopy(self.recipe)
                    self.record(recipe, section)["path"] = value
                    self.load(recipe)

    def test_json_and_retained_symlinks_are_rejected_including_parents(self):
        raw = encoded(self.recipe)
        self.path.write_bytes(raw)
        alias = self.root / "recipe-alias.json"
        alias.symlink_to(self.path)
        parent = self.root.parent / "recipe-alias"
        parent.symlink_to(self.root, target_is_directory=True)
        for path in (alias, parent / self.path.name):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "Symlink"):
                patch_recipe.load_recipe(path, pin(raw)["sha256"])
        for section, path in (("source", self.lock), ("decoder", self.decoder_lock), ("retained", self.retained)):
            for directory in (False, True):
                with self.subTest(section=section, directory=directory), self.assertRaisesRegex(ValueError, "Symlink"):
                    alias = self.root / f"{section}-{directory}"
                    alias.symlink_to(path.parent if directory else path, target_is_directory=directory)
                    recipe = copy.deepcopy(self.recipe)
                    self.record(recipe, section)["path"] = str(alias / path.name if directory else alias)
                    self.load(recipe)

    def test_directory_inputs_and_invalid_executables_are_rejected(self):
        with self.assertRaises(ValueError):
            patch_recipe.load_recipe(self.root, "0" * 64)
        for section in ("source", "decoder", "retained"):
            with self.subTest(section=section), self.assertRaises(ValueError):
                recipe = copy.deepcopy(self.recipe)
                self.record(recipe, section)["path"] = str(self.root)
                self.load(recipe)
        nonexecutable = self.root / "not-executable"
        nonexecutable.write_bytes(b"not a command")
        nonexecutable.chmod(0o600)
        for python in (None, [], "python", "./python", str(self.root), str(nonexecutable), str(self.root / "missing")):
            with self.subTest(python=python), self.assertRaises(ValueError):
                recipe = copy.deepcopy(self.recipe)
                recipe["decoder"]["python"] = python
                self.load(recipe)

    def test_json_and_retained_file_size_caps(self):
        cap = 2 * 1024 * 1024
        raw = b" " * (cap + 1)
        self.path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, "bounded regular file"):
            patch_recipe.load_recipe(self.path, pin(raw)["sha256"])
        for section, path in (("source", self.lock), ("decoder", self.decoder_lock), ("retained", self.retained)):
            original = path.read_bytes()
            size = 64 * 1024 * 1024 if section == "retained" else cap
            with self.subTest(section=section), self.assertRaisesRegex(ValueError, "bounded regular file"):
                with path.open("wb") as stream:
                    stream.truncate(size + 1)
                self.load()
            path.write_bytes(original)
            with self.subTest(section=section, declared=True), self.assertRaisesRegex(ValueError, "byte bound"):
                recipe = copy.deepcopy(self.recipe)
                self.record(recipe, section)["bytes"] = size + 1
                self.load(recipe)

    def test_json_size_limits_are_inclusive(self):
        cap = 2 * 1024 * 1024
        for section, path in (("source", self.lock), ("decoder", self.decoder_lock)):
            raw = path.read_bytes().ljust(cap, b" ")
            path.write_bytes(raw)
            self.record(self.recipe, section).update(pin(raw))
        raw = encoded(self.recipe).ljust(cap, b" ")
        self.path.write_bytes(raw)
        result = patch_recipe.load_recipe(self.path, pin(raw)["sha256"])
        self.assertEqual(result["pin"]["bytes"], cap)
        self.assertEqual(result["source_lock"]["bytes"], cap)
        self.assertEqual(result["decoder"]["lock"]["bytes"], cap)

    def test_retained_count_and_aggregate_caps(self):
        record = self.recipe["retained"][0]
        self.recipe["retained"] = [{**record, "destination": f"retained/{number}.json"} for number in range(512)]
        self.assertEqual(len(self.load()["retained"]), 512)
        self.recipe["retained"].append({**record, "destination": "retained/513.json"})
        with self.assertRaisesRegex(ValueError, "512"):
            self.load()
        self.recipe["retained"] = [
            {**record, "bytes": 64 * 1024 * 1024, "destination": f"retained/{number}.json"} for number in range(5)
        ]
        with self.assertRaisesRegex(ValueError, "total exceeds byte bound"):
            self.load()

    def test_retained_size_boundaries_with_small_caps(self):
        self.retained.write_bytes(b"{}\n ")
        record = {**self.recipe["retained"][0], **pin(self.retained.read_bytes())}
        self.recipe["retained"] = [{**record, "destination": f"retained/{number}.json"} for number in range(2)]
        with mock.patch.multiple(patch_recipe, _MAX_RETAINED_BYTES=4, _MAX_TOTAL_RETAINED_BYTES=8):
            self.assertEqual(len(self.load()["retained"]), 2)
            self.recipe["retained"].append({**record, "destination": "retained/third.json"})
            with self.assertRaisesRegex(ValueError, "total exceeds byte bound"):
                self.load()

    def test_export_count_and_identifier_constraints(self):
        original = copy.deepcopy(self.recipe)
        for number in range(32 - len(self.recipe["exports"])):
            self.recipe["exports"].append(
                {**self.recipe["exports"][0], "id": f"extra-{number}", "destination": f"extra/{number}"}
            )
        self.assertEqual(len(self.load()["exports"]), 32)
        self.recipe["exports"].append({**self.recipe["exports"][0], "id": "overflow", "destination": "overflow"})
        with self.assertRaisesRegex(ValueError, "32"):
            self.load()
        for identifier in ("", "Upper", "1first", "has_under", "has.dot", "a" * 65, "facts"):
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                recipe = copy.deepcopy(original)
                recipe["exports"][0]["id"] = identifier
                self.load(recipe)
        original["exports"][0]["id"] = "a" * 64
        self.assertEqual(self.load(original)["exports"][0]["id"], "a" * 64)

    def test_exactly_one_facts_and_following_crafting_reference(self):
        for kind in ("facts", "crafting"):
            for duplicate in (False, True):
                with self.subTest(kind=kind, duplicate=duplicate), self.assertRaises(ValueError):
                    recipe = copy.deepcopy(self.recipe)
                    export = next(export for export in recipe["exports"] if export["kind"] == kind)
                    if duplicate:
                        recipe["exports"].append({**export, "id": "duplicate", "destination": "duplicate"})
                    else:
                        recipe["exports"].remove(export)
                    self.load(recipe)
        recipe = copy.deepcopy(self.recipe)
        recipe["exports"].insert(0, recipe["exports"].pop())
        with self.assertRaisesRegex(ValueError, "follow and reference"):
            self.load(recipe)
        for field, value in (("facts", "missing"), ("facts", []), ("package", "other"), ("destination", "nested")):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                recipe = copy.deepcopy(self.recipe)
                recipe["exports"][-1][field] = value
                self.load(recipe)

    def test_packages_and_crafting_exclusivity(self):
        for package in (
            "",
            ".",
            "inputs.name",
            "bad-name",
            "previous",
            "Previous",
            "x/y",
            "crafting",
            "Crafting",
            "CON",
            "nul",
            "Prn",
            "AUX",
            "COM1",
            "lpt9",
        ):
            for retained in (False, True):
                with self.subTest(package=package, retained=retained), self.assertRaises(ValueError):
                    recipe = copy.deepcopy(self.recipe)
                    record = recipe["retained"][0] if retained else recipe["exports"][0]
                    record["package"] = package
                    self.load(recipe)
        for package in ("Valid_package1", "_valid_package"):
            self.recipe["retained"][0]["package"] = package
            self.assertIn(package, self.load()["packages"])

    def test_case_different_package_names_are_rejected_even_without_path_collisions(self):
        for section in ("exports", "retained"):
            with self.subTest(section=section), self.assertRaisesRegex(ValueError, "Case-collision"):
                recipe = copy.deepcopy(self.recipe)
                recipe[section][0]["package"] = "Ordinary"
                self.load(recipe)
        recipe = copy.deepcopy(self.recipe)
        recipe["retained"].append({**recipe["retained"][0], "package": "Legacy", "destination": "separate.json"})
        with self.assertRaisesRegex(ValueError, "Case-collision"):
            self.load(recipe)

    def test_destinations_are_safe_portable_and_not_root_manifests(self):
        destinations = (
            "",
            ".",
            "..",
            "/absolute",
            "a/../b",
            "a/./b",
            "a//b",
            "a/",
            "a\\b",
            "C:drive",
            ".hidden",
            "a/.hidden/file",
            "a/file.",
            "a/file ",
            "a/*",
            "a/?",
            "a/<file>",
            "a/file|name",
            "a/CON.txt",
            "a/lpt1",
            "a\nfile",
            "manifest.json",
            "MANIFEST.JSON",
            "manifest.json/inside.json",
            "MANIFEST.JSON/inside.json",
        )
        for destination in destinations:
            for retained in (False, True):
                with self.subTest(destination=destination, retained=retained), self.assertRaises(ValueError):
                    recipe = copy.deepcopy(self.recipe)
                    record = recipe["retained"][0] if retained else recipe["exports"][0]
                    record["destination"] = destination
                    self.load(recipe)
        for destination in (
            "script.py",
            "nested/SCRIPT.PY",
            "shell.sh",
            "raw.bin",
            "table.datc64",
            "FILE.JSON",
            "json",
        ):
            with self.subTest(destination=destination), self.assertRaisesRegex(ValueError, "must end in .json"):
                recipe = copy.deepcopy(self.recipe)
                recipe["retained"][0]["destination"] = destination
                self.load(recipe)

    def test_retained_inputs_require_object_or_array_json_regardless_of_source_filename(self):
        cache = self.root / "opaque-cache-hash"
        self.recipe["retained"][0]["path"] = cache.name
        for raw in (b"{}", b"[]", b'{"nested":[1,true,null]}', b'["official", 1]'):
            with self.subTest(raw=raw):
                cache.write_bytes(raw)
                self.recipe["retained"][0].update(pin(raw))
                self.assertEqual(self.load()["retained"][0]["path"], cache)
        for raw in (b"", b"raw bytes", b"\xff", b'"text"', b"1", b"null", b"true", b'{"key":1,"key":2}', b"[NaN]"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                cache.write_bytes(raw)
                self.recipe["retained"][0].update(pin(raw))
                self.load()

    def test_export_directories_and_receipt_siblings_collide_in_both_orders(self):
        for destination in (
            "facts",
            "facts/nested",
            "FACTS/NESTED",
            "facts.export-receipt.json",
            "facts.export-receipt.json/nested",
        ):
            for reverse in (False, True):
                with (
                    self.subTest(destination=destination, reverse=reverse),
                    self.assertRaisesRegex(ValueError, "collision"),
                ):
                    recipe = copy.deepcopy(self.recipe)
                    recipe["exports"][0].update(package="ordinary", destination=destination)
                    if reverse:
                        recipe["exports"][0], recipe["exports"][1] = recipe["exports"][1], recipe["exports"][0]
                    self.load(recipe)

    def test_retained_files_cannot_overlap_directories_receipts_or_other_files(self):
        for destination in ("facts/file.json", "FACTS.export-receipt.json", "facts.export-receipt.json/file.json"):
            with self.subTest(destination=destination), self.assertRaisesRegex(ValueError, "collision"):
                recipe = copy.deepcopy(self.recipe)
                recipe["retained"][0].update(package="ordinary", destination=destination)
                self.load(recipe)
        recipe = copy.deepcopy(self.recipe)
        recipe["exports"][1]["destination"] = "parent.json/facts"
        recipe["retained"][0].update(package="ordinary", destination="parent.json")
        with self.assertRaisesRegex(ValueError, "collision"):
            self.load(recipe)
        for first, second in (
            ("file.json", "file.json"),
            ("file.json", "FILE.json/nested.json"),
            ("FILE.json/nested.json", "file.json"),
            ("File.json", "file.json"),
        ):
            with self.subTest(first=first, second=second), self.assertRaisesRegex(ValueError, "collision"):
                recipe = copy.deepcopy(self.recipe)
                record = recipe["retained"][0]
                recipe["retained"] = [
                    {**record, "destination": first},
                    {**record, "destination": second},
                ]
                self.load(recipe)

    def test_same_destinations_in_distinct_packages_are_allowed(self):
        self.recipe["exports"][0]["destination"] = "facts.json"
        self.recipe["retained"][0]["destination"] = "facts.json"
        self.load()

    def test_sources_must_exist_and_pass_acquisition_resource_validation(self):
        self.recipe["exports"][0]["source"] = "missing"
        with self.assertRaisesRegex(ValueError, "missing selected source"):
            self.load()
        self.recipe["exports"][0]["source"] = "tables"
        original = copy.deepcopy(self.sources["tables"])
        for field, value in (("kind", "stripped"), ("resources", {}), ("resources", [])):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.sources["tables"] = {**original, field: value}
                self.save_sources()
                self.load()
        for field, value in (
            ("bytes", True),
            ("bytes", 0),
            ("sha256", "bad"),
            ("uncompressed_offset", -1),
            ("bundle_url", "https://evil.invalid/file"),
        ):
            with self.subTest(resource_field=field), self.assertRaises(ValueError):
                self.sources["tables"] = copy.deepcopy(original)
                self.sources["tables"]["resources"]["Data/Balance/Stats.datc64"][field] = value
                self.save_sources()
                self.load()

    def test_source_lock_shape_and_schema_are_validated(self):
        for lock in ({}, [], {"schema_version": True, "sources": self.sources}, {"schema_version": 1, "sources": []}):
            with self.subTest(lock_type=type(lock)), self.assertRaises(ValueError):
                raw = encoded(lock)
                self.lock.write_bytes(raw)
                self.recipe["source_lock"].update(pin(raw))
                self.load()

    def test_sources_match_target_profile_and_exact_facts_resource_closure(self):
        original = copy.deepcopy(self.sources["full"])
        for field, value in (
            ("game", "poe1"),
            ("realm", "china"),
            ("game_patch", "9.9.8"),
            ("profile", "base-v1"),
            ("profile", None),
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.sources["full"] = copy.deepcopy(original)
                self.sources["full"][field] = value
                if field == "game_patch":
                    self.sources["full"]["base_url"] = "https://patch-poe2.poecdn.com/9.9.8/"
                    for resource in self.sources["full"]["resources"].values():
                        resource["bundle_url"] = resource["bundle_url"].replace("9.9.9", "9.9.8")
                self.save_sources()
                self.load()
        for resource in (facts.PSG, "Data/Balance/Stats.datc64", "Data/Balance/Extra.datc64"):
            with self.subTest(resource=resource), self.assertRaisesRegex(ValueError, "resource closure"):
                self.sources["full"] = copy.deepcopy(original)
                resources = self.sources["full"]["resources"]
                if resource in resources:
                    del resources[resource]
                else:
                    resources[resource] = copy.deepcopy(next(iter(resources.values())))
                self.save_sources()
                self.load()

    def test_acquisition_status_and_evidence_are_required_without_promotion(self):
        original = copy.deepcopy(self.sources["tables"])
        acquisition = original["acquisition"]
        invalid = [None, {}, {"status": "reviewed-source-input"}, {**acquisition, "status": []}]
        invalid.extend({**acquisition, "status": status} for status in ("reviewed", "unknown", None))
        invalid.extend({**acquisition, "evidence": evidence} for evidence in (None, {}, [], [None], [{}]))
        invalid.extend(
            {**acquisition, "evidence": [evidence]}
            for evidence in (
                {"kind": "", "sha256": "1" * 64},
                {"kind": [], "sha256": "1" * 64},
                {"kind": "test", "sha256": "F" * 64},
                {"kind": "test", "sha256": "1" * 64, "command": "false"},
            )
        )
        for value in invalid:
            with self.subTest(acquisition=value), self.assertRaises(ValueError):
                self.sources["tables"] = {**original, "acquisition": value}
                self.save_sources()
                self.load()
        for status in ("unreviewed-acquisition-draft", "reviewed-source-input"):
            self.sources["tables"] = {**original, "acquisition": {**acquisition, "status": status}}
            self.save_sources()
            self.assertEqual(self.load()["sources"]["tables"]["acquisition"]["status"], status)

    def test_facts_profile_and_table_language_are_explicit_and_matching(self):
        for profile in (None, [], "base-v1", "unknown"):
            with self.subTest(profile=profile), self.assertRaisesRegex(ValueError, "facts profile"):
                recipe = copy.deepcopy(self.recipe)
                recipe["exports"][1]["profile"] = profile
                self.load(recipe)
        for language in (None, [], "French", "Traditional Chinese"):
            with self.subTest(language=language), self.assertRaises(ValueError):
                recipe = copy.deepcopy(self.recipe)
                recipe["exports"][0]["language"] = language
                self.load(recipe)
        self.sources["tables"]["language"] = None
        self.save_sources()
        with self.assertRaisesRegex(ValueError, "language differs"):
            self.load()
        self.sources["tables"]["language"] = "Traditional Chinese"
        self.recipe["exports"][0]["language"] = "Traditional Chinese"
        self.recipe["exports"][5]["language"] = "Traditional Chinese"
        self.save_sources()
        self.load()

    def test_source_lock_cannot_change_between_pin_and_entry_validation(self):
        with mock.patch.object(patch_recipe._client, "load_source", return_value=(self.sources["tables"], "0" * 64)):
            with self.assertRaisesRegex(ValueError, "changed after pin verification"):
                self.load()


if __name__ == "__main__":
    unittest.main()
