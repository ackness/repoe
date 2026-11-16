"""Offline preparation, completion integrity, and the input-publication boundary."""

import contextlib
import copy
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

from RePoE.client import export_lock, export_receipt, sources
from RePoE.native import crafting_facts, descriptions, facts, item_inheritance, tables, validate
from RePoE.release import build, declarations, inputs, prepare_patch, publish
from RePoE.release.pins import decode, encoded, pin
from tests.client.test_export_receipt import DIRTY, identity, sibling
from tests.client import test_sources as source_fixtures
from tests.native import test_facts, test_items_actors
from tests.native.test_crafting_facts import fixture as crafting_tables


TARGET = {"game": "poe2", "game_patch": "0.5.5.8", "realm": "international"}


def write_tree(root, members):
    for name, raw in members.items():
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)


def snapshot(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


class PreparePatchTests(unittest.TestCase):
    def patch(self, target, name, **options):
        return self.context.enter_context(mock.patch.object(target, name, autospec=True, **options))

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="repoe-prepare-patch-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.repo = self.root / "repo"
        self.cache = self.repo / ".cache"
        self.cache.mkdir(parents=True)
        self.out = self.cache / "preparation"
        self.fixture_root = self.repo / "fixtures"
        self.recipe_path = self.fixture_root / "recipe.json"
        self.source_lock = self.fixture_root / "sources.json"
        self.decoder_lock = self.fixture_root / "decoder.lock"
        self.decoder_python = self.fixture_root / "bin/python"
        self.decoder_python.parent.mkdir(parents=True)
        self.decoder_python.symlink_to(sys.executable)
        self.decoder_lock.write_bytes(b"version = 1\n")
        write_tree(
            self.repo,
            {
                "fixtures/retained/rules.json": b'{"rule":"explicitly pinned"}\n',
                "fixtures/retained/legacy.json": b'{"legacy":"explicitly pinned"}\n',
                "fixtures/retained/unlisted.json": b'{"must_not_be_copied":true}\n',
                "release/0.5.5.5/inputs.lock.json": b'{"immutable":"input lock"}\n',
                "release/0.5.5.5/frozen-inputs.json": b'{"immutable":"declaration"}\n',
                "sources/sources.lock.json": b'{"immutable":"published source lock"}\n',
            },
        )
        for name in crafting_facts.PRODUCERS:
            write_tree(self.repo, {name: (build.ROOT / name).read_bytes()})
        self.exports = [
            {
                "id": "facts",
                "kind": "facts",
                "source": "facts-source",
                "package": "ordinary",
                "destination": "facts",
                "profile": facts.ITEMS_ACTORS_PROFILE,
            },
            {
                "id": "descriptions",
                "kind": "descriptions",
                "source": "text-source",
                "package": "ordinary",
                "destination": "stat-descriptions/item-descriptions",
            },
            {
                "id": "tables-one",
                "kind": "tables",
                "source": "tables-source",
                "package": "ordinary",
                "destination": "passive-tree/supplement",
                "language": "English",
            },
            {"id": "crafting", "kind": "crafting", "facts": "facts", "package": "crafting", "destination": "."},
            {
                "id": "tables-two",
                "kind": "tables",
                "source": "tables-source",
                "package": "ordinary",
                "destination": "minions/supplement",
                "language": "English",
            },
            {
                "id": "item-inheritance",
                "kind": "item-inheritance",
                "source": "items-source",
                "package": "ordinary",
                "destination": "base-items/supplement",
            },
        ]
        self.retained = [
            {
                "path": str(self.fixture_root / "retained/rules.json"),
                "package": "ordinary",
                "destination": "retained/rules.json",
            },
            {
                "path": str(self.fixture_root / "retained/legacy.json"),
                "package": "legacy",
                "destination": "rows.json",
            },
        ]
        self.raw_resources = {
            "facts-source": {f"Data/Balance/{name}.datc64": name.encode() for name in crafting_facts.TABLES},
            "text-source": {
                "Data/StatDescriptions/test.csd": b"\xff\xfe"
                + 'description\n1 test_stat\n1\n# "Value {0}"\n'.encode("utf-16-le")
            },
            "tables-source": {"Data/Balance/ModEffectStats.datc64": b"synthetic DAT"},
            "items-source": {
                "Metadata/Items/Test.it": b"\xff\xfe"
                + 'version 3\nextends "nothing"\nBase\n{\ntag = "test"\n}\n'.encode("utf-16-le")
            },
            "unused-source": {"Data/Balance/Unused.datc64": b"not selected"},
        }
        self.source_statuses = {}
        self.write_recipe()
        self.decoder_receipts = {
            name: {
                "test_decoder": "identity; not an ooz fixture",
                "identity_sha256": pin(encoded({"fixture_source": name, "version": "unittest-only"}))["sha256"],
            }
            for name in self.source_documents
        }
        self.events = []
        self.exported = []
        self.staged = []
        self.reservation = 0
        self.original_acquire = sources.acquire
        self.original_facts = facts.create_candidate
        self.original_validate = validate.validate_candidate
        self.original_tables = tables.create_candidate
        self.original_descriptions = descriptions.create_candidate
        self.original_inheritance = item_inheritance.create_candidate
        self.original_crafting = crafting_facts.create_candidate
        self.original_export_lock = export_lock.create
        self.original_stage = inputs.stage
        self.original_problems = inputs.receipt_problems
        self.original_loader = prepare_patch.patch_recipe.load_recipe
        self.context = contextlib.ExitStack()
        self.addCleanup(self.context.close)
        self.producer = identity()
        self.checkout = self.patch(export_receipt, "checkout_identity", return_value=self.producer)
        self.code = self.patch(prepare_patch, "tool_pins", return_value={"prepare.py": pin(b"checked implementation")})
        self.loader = self.patch(
            prepare_patch.patch_recipe,
            "load_recipe",
            side_effect=lambda path, expected: copy.deepcopy(self.recipe_data),
        )
        self.decoders = self.patch(sources, "ExternalDecoder", side_effect=self.decoder)
        self.acquisition = self.patch(sources, "acquire", side_effect=self.acquire)
        self.lock_export = self.patch(export_lock, "create", side_effect=self.derive_lock)
        self.facts_export = self.patch(facts, "create_candidate", side_effect=self.export_facts)
        self.validation = self.patch(validate, "validate_candidate", side_effect=self.validate_facts)
        self.tables_export = self.patch(tables, "create_candidate", side_effect=self.export_tables)
        self.descriptions_export = self.patch(descriptions, "create_candidate", side_effect=self.export_descriptions)
        self.inheritance_export = self.patch(item_inheritance, "create_candidate", side_effect=self.export_inheritance)
        self.crafting_export = self.patch(crafting_facts, "create_candidate", side_effect=self.export_crafting)
        self.staging = self.patch(inputs, "stage", side_effect=self.stage)
        self.problems = self.patch(inputs, "receipt_problems", return_value=[])
        self.context.enter_context(mock.patch.object(crafting_facts, "ROOT", self.repo))
        self.context.enter_context(mock.patch.object(descriptions, "ROOT", self.repo))
        for target, name in (
            (build, "git"),
            (build, "main"),
            (declarations, "declare"),
            (inputs, "main"),
            (publish, "main"),
            (publish, "carry_out"),
        ):
            self.patch(target, name, side_effect=AssertionError(f"Preparation must not call {target.__name__}.{name}"))
        for name in ("socket.socket", "urllib.request.build_opener", "subprocess.run", "subprocess.Popen"):
            self.context.enter_context(
                mock.patch(name, side_effect=AssertionError(f"Forbidden external operation: {name}"))
            )

    def write_recipe(self):
        decoder = {
            "repository": "https://github.com/repoe-fork/pypoe",
            "revision": facts.PYPOE,
            "dat_schema_repository": "https://github.com/poe-tool-dev/dat-schema",
            "dat_schema_revision": facts.SCHEMA,
            "schema_sha256": facts.SCHEMA_SHA,
        }
        self.source_documents = {}
        for name, resources in self.raw_resources.items():
            offset = 0
            records = {}
            for resource, raw in resources.items():
                records[resource] = {
                    **pin(raw),
                    "bundle_url": f"https://patch-poe2.poecdn.com/{TARGET['game_patch']}/Bundles2/{name}.bundle.bin",
                    "uncompressed_offset": offset,
                    "uncompressed_length": len(raw),
                }
                offset += len(raw)
            self.source_documents[name] = {
                "kind": "official-client-resource-candidate",
                **TARGET,
                "base_url": f"https://patch-poe2.poecdn.com/{TARGET['game_patch']}/",
                "decoder": decoder,
                "acquisition": {
                    "status": self.source_statuses.get(name, "reviewed-source-input"),
                    "evidence": [{"kind": "synthetic-offline-fixture", "sha256": "a" * 64}],
                },
                "resources": records,
            }
        self.source_documents["facts-source"]["profile"] = facts.ITEMS_ACTORS_PROFILE
        for name in ("text-source", "items-source"):
            self.source_documents[name]["roots"] = list(self.raw_resources[name])
        self.source_lock.write_bytes(encoded({"schema_version": 1, "sources": self.source_documents}))
        retained = [{**record, **build.file_pin(Path(record["path"]))} for record in self.retained]
        document = {
            "schema": "repoe-prepare-patch/v1",
            "target": TARGET,
            "source_lock": {"path": str(self.source_lock), **build.file_pin(self.source_lock)},
            "decoder": {
                "python": str(self.decoder_python),
                "lock": {"path": str(self.decoder_lock), **build.file_pin(self.decoder_lock)},
            },
            "exports": self.exports,
            "retained": retained,
        }
        self.recipe_path.write_bytes(encoded(document))
        self.recipe_data = copy.deepcopy(document)
        self.recipe_data["source_lock"]["path"] = self.source_lock
        self.recipe_data["decoder"]["python"] = self.decoder_python
        self.recipe_data["decoder"]["lock"]["path"] = self.decoder_lock
        for record in self.recipe_data["retained"]:
            record["path"] = Path(record["path"])
        names = list(dict.fromkeys(export["source"] for export in self.exports if "source" in export))
        self.recipe_data.update(
            pin=build.file_pin(self.recipe_path),
            source_names=names,
            sources={name: self.source_documents[name] for name in names},
            packages=sorted({record["package"] for record in [*self.exports, *self.retained]}),
        )

    def prepare(self, **options):
        arguments = {
            "recipe": self.recipe_path,
            "expected_recipe_sha256": self.recipe_data["pin"]["sha256"],
            "out": self.out,
            "repo": self.repo,
        }
        return prepare_patch.prepare(**(arguments | options))

    def decoder(self, python, lock_path, source):
        name = next(name for name, selected in self.source_documents.items() if selected == source)
        decoder = source_fixtures.FakeDecoder(python, lock_path, source)
        decoder.receipt = copy.deepcopy(self.decoder_receipts[name])
        return decoder

    def acquire(
        self,
        source_lock,
        source_key,
        cache_root,
        output,
        python,
        decoder_lock,
        mode,
        budget=0,
        request_cap=sources.MAX_RANGE,
    ):
        self.events.append(f"acquire:{source_key}")
        output.mkdir(parents=True)
        write_tree(output, self.raw_resources[source_key])
        receipt = {
            "schema": "pobr-client-sources/v1",
            "source": source_key,
            "source_lock_sha256": build.file_pin(source_lock)["sha256"],
            **TARGET,
            "mode": mode,
            "decoder": copy.deepcopy(self.decoder_receipts[source_key]),
            "network": {
                "requests": int(bool(self.reservation)),
                "body_bytes": self.reservation,
                "reserved_bytes": self.reservation,
                "budget_bytes": budget,
                "per_request_cap_bytes": request_cap,
            },
        }
        (output / sources.RECEIPT).write_bytes(encoded(receipt))
        return receipt

    def derive_lock(self, *, source_lock, expected_source_lock_sha256, out, sources=None):
        self.events.append("export-lock")
        return self.original_export_lock(
            source_lock=source_lock, expected_source_lock_sha256=expected_source_lock_sha256, out=out, sources=sources
        )

    def source_identity(self, source):
        selected = self.source_documents[source]
        return {
            **TARGET,
            "kind": selected["kind"],
            "source": source,
            "source_lock_sha256": build.file_pin(self.source_lock)["sha256"],
            "selected_source_sha256": pin(encoded(selected))["sha256"],
            "acquisition": copy.deepcopy(selected["acquisition"]),
            "raw_resources": {name: pin(raw) for name, raw in self.raw_resources[source].items()},
        }

    def candidate(self, out, manifest, payloads, exporter, rehearsal):
        self.exported.append(out)
        seal = export_receipt.begin(out, exporter, rehearsal=rehearsal)
        out.mkdir()
        write_tree(out, payloads)
        manifest = {
            "status": "partial-candidate",
            "production_ready": False,
            export_receipt.FIELD: export_receipt.SCHEMA,
            **manifest,
            "files": {name: pin(raw) for name, raw in payloads.items()},
        }
        raw = encoded(manifest)
        (out / "manifest.json").write_bytes(raw)
        seal(raw)
        return manifest

    def export_facts(self, *, source_lock, source, raw, out, profile=facts.BASE_PROFILE, rehearsal=False):
        self.events.append("facts")
        self.assertEqual(profile, facts.ITEMS_ACTORS_PROFILE)
        payloads = {f"tables/{name}.json": encoded(table) for name, table in crafting_tables().items()}
        payloads["source-lock.json"] = source_lock.read_bytes()
        return self.candidate(
            out,
            {
                "format": "repoe-native-facts/v4",
                "profile": profile,
                "schema": copy.deepcopy(crafting_facts.SCHEMA),
                "source_identity": self.source_identity(source),
                "decoder": {
                    "pypoe_revision": facts.PYPOE,
                    "python": "synthetic",
                    "trusted_source_pin_sha256": "b" * 64,
                    "sources": {"synthetic": "c" * 64},
                },
                "producer": {"RePoE/native/facts.py": "d" * 64},
            },
            payloads,
            "RePoE.native.facts",
            rehearsal,
        )

    def validate_facts(self, *, source_lock, source, raw, candidate, manifest_sha256=None, profile=facts.BASE_PROFILE):
        self.events.append("validate")
        self.assertEqual(source_lock, self.source_lock)
        self.assertEqual(manifest_sha256, build.file_pin(candidate / "manifest.json")["sha256"])
        self.assertEqual(profile, facts.ITEMS_ACTORS_PROFILE)
        return {"result": "passed", "manifest_sha256": manifest_sha256}

    def export_tables(
        self, *, source_lock, expected_source_lock_sha256, source, raw, out, language="English", rehearsal=False
    ):
        self.events.append("tables")
        self.assertEqual(expected_source_lock_sha256, build.file_pin(source_lock)["sha256"])
        self.assertEqual(language, "English")
        return self.candidate(
            out,
            {"format": tables.FORMAT, "source_identity": self.source_identity(source)},
            {"tables.json": b"{}\n", "source-lock.json": source_lock.read_bytes()},
            "RePoE.native.tables",
            rehearsal,
        )

    def export_descriptions(self, *, source_lock, source, raw, out, expected_source_lock_sha256, rehearsal=False):
        self.events.append("descriptions")
        self.assertEqual(expected_source_lock_sha256, build.file_pin(source_lock)["sha256"])
        return self.candidate(
            out,
            {"format": "repoe-native-descriptions/v1", "source_identity": self.source_identity(source)},
            {"descriptions.json": b"{}\n", "diagnostics.json": b"{}\n", "source-lock.json": source_lock.read_bytes()},
            "RePoE.native.descriptions",
            rehearsal,
        )

    def export_inheritance(self, *, source_lock, source, raw, out, expected_source_lock_sha256, rehearsal=False):
        self.events.append("item-inheritance")
        self.assertEqual(expected_source_lock_sha256, build.file_pin(source_lock)["sha256"])
        return self.candidate(
            out,
            {"format": item_inheritance.FORMAT, "source_identity": self.source_identity(source)},
            {"inheritance.json": b"{}\n", "source-lock.json": source_lock.read_bytes()},
            "RePoE.native.item_inheritance",
            rehearsal,
        )

    def export_crafting(self, *, facts, expected_manifest_sha256, out, rehearsal=False):
        self.events.append("crafting")
        self.exported.append(out)
        return self.original_crafting(
            facts=facts, expected_manifest_sha256=expected_manifest_sha256, out=out, rehearsal=rehearsal
        )

    def stage(self, packages, target, out, tag=None):
        self.events.append("stage")
        self.assertIsNone(tag)
        staged = self.original_stage(packages, target, out, tag=tag)
        self.staged.append(staged)
        return staged

    def test_pipeline_validates_lock_then_acquires_unique_sources_and_exports_in_recipe_order(self):
        report = self.prepare()
        self.assertEqual(
            self.events,
            [
                "export-lock",
                "acquire:facts-source",
                "acquire:text-source",
                "acquire:tables-source",
                "acquire:items-source",
                "facts",
                "validate",
                "descriptions",
                "tables",
                "crafting",
                "tables",
                "item-inheritance",
                "stage",
            ],
        )
        self.assertEqual(self.lock_export.call_args.kwargs["sources"], self.recipe_data["source_names"])
        export_path = self.lock_export.call_args.kwargs["out"]
        converted = decode(export_path.read_bytes())["sources"]
        self.assertEqual(set(converted), set(self.recipe_data["source_names"]))
        for source in converted.values():
            for resource in source["resources"].values():
                self.assertEqual(set(resource), {"bytes", "sha256"})
        self.assertEqual(self.facts_export.call_args.kwargs["source_lock"], self.source_lock)
        for exporter in (self.tables_export, self.descriptions_export, self.inheritance_export):
            for call in exporter.call_args_list:
                self.assertEqual(call.kwargs["source_lock"], export_path)
        self.assertEqual(self.validation.call_args.kwargs["candidate"], self.facts_export.call_args.kwargs["out"])
        self.assertEqual(self.crafting_export.call_args.kwargs["facts"], self.facts_export.call_args.kwargs["out"])
        self.assertEqual(report["schema"], "repoe-prepare-patch-report/v1")
        self.assertEqual(report["status"], "awaiting-input-publication")
        self.assertEqual(report["target"], TARGET)
        self.assertEqual(set(report["packages"]), {"crafting", "legacy", "ordinary"})
        self.assertTrue(Path(report["stage"]).is_absolute())
        self.assertEqual(decode((self.out / "report.json").read_bytes()), report)
        self.assertTrue(all(step["status"] == "complete" for step in report["steps"]))
        self.assertEqual(
            decode((self.out / "progress.json").read_bytes())["intent"]["decoder"]["identities"],
            {name: self.decoder_receipts[name]["identity_sha256"] for name in self.recipe_data["source_names"]},
        )
        self.assertFalse((self.out / ".running").exists())

    def test_assembly_copies_candidate_trees_sibling_receipts_and_only_explicit_retained_files(self):
        report = self.prepare()
        directories = {name: Path(path) for name, path in report["package_directories"].items()}
        for spec, source in zip(self.exports, self.exported, strict=True):
            destination = directories[spec["package"]] / spec["destination"]
            self.assertEqual(snapshot(destination), snapshot(source))
            self.assertEqual(sibling(destination).read_bytes(), sibling(source).read_bytes())
            receipt = export_receipt.verify(
                sibling(destination).read_bytes(), (destination / "manifest.json").read_bytes()
            )
            self.assertEqual(receipt["producer"], self.producer)
        for record in self.retained:
            destination = directories[record["package"]] / record["destination"]
            self.assertEqual(destination.read_bytes(), Path(record["path"]).read_bytes())
        self.assertEqual(set(snapshot(directories["legacy"])), {"rows.json"})
        for name, spec in report["packages"].items():
            archive_path = Path(report["stage"]) / "assets" / spec["asset"]
            self.assertEqual(build.file_pin(archive_path), {key: spec[key] for key in ("bytes", "sha256")})
            with zipfile.ZipFile(archive_path) as archive:
                self.assertNotIn("unlisted.json", {Path(member).name for member in archive.namelist()})
                self.assertNotIn(sources.RECEIPT, archive.namelist())
                self.assertFalse(any(member.startswith(("Data/", "Metadata/")) for member in archive.namelist()))
                if name == "crafting":
                    manifest = decode(archive.read("manifest.json"))
                    self.assertEqual(
                        manifest["input_package"]["manifest"],
                        build.file_pin(directories["ordinary"] / "facts/manifest.json"),
                    )
                    self.assertEqual(spec["export_receipt"], decode(sibling(directories[name]).read_bytes()))

    def test_preparation_never_promotes_claims_modifies_locks_declares_or_publishes(self):
        before = {path: path.read_bytes() for path in self.fixture_root.rglob("*") if path.is_file()}
        declarations_before = snapshot(self.repo / "release")
        sources_before = snapshot(self.repo / "sources")
        report = self.prepare()
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertEqual(snapshot(self.repo / "release"), declarations_before)
        self.assertEqual(snapshot(self.repo / "sources"), sources_before)
        self.assertFalse(report["production_ready"])
        self.assertFalse(report["published"])
        self.assertEqual(report["publication_problems"], [])
        self.assertEqual(
            report["source_review"],
            {name: self.source_documents[name]["acquisition"] for name in self.recipe_data["source_names"]},
        )
        for directory in self.exported:
            manifest = decode((directory / "manifest.json").read_bytes())
            self.assertFalse(manifest["production_ready"])
            self.assertEqual(manifest["status"], "partial-candidate")
            self.assertEqual(manifest["source_identity"]["acquisition"]["status"], "reviewed-source-input")
        self.assertEqual(list(self.out.rglob("lock.json")), [])
        for name in ("lock.json", "release-notes.md", "tag-message.txt"):
            self.assertFalse((Path(report["stage"]) / name).exists())

    def test_rehearsal_uses_real_receipts_and_remains_blocked_even_on_the_reviewed_branch(self):
        self.source_statuses = {name: "unreviewed-acquisition-draft" for name in self.recipe_data["source_names"]}
        self.write_recipe()
        before = self.source_lock.read_bytes()
        self.checkout.return_value = identity(dirty_paths=DIRTY)
        self.problems.side_effect = self.original_problems
        self.patch(publish, "off_branch", return_value=0)
        report = self.prepare(rehearsal=True)
        receipts = self.staged[-1]["receipts"]
        self.assertEqual(len(receipts), len(self.exports))
        self.assertTrue(all(receipt["rehearsal"] and receipt["producer"]["dirty"] for receipt in receipts.values()))
        self.assertEqual(report["publication_problems"], publish.unpublishable(receipts))
        self.assertTrue(all("is a rehearsal" in problem for problem in report["publication_problems"]))
        self.assertEqual(report["status"], "blocked-input-publication")
        self.assertFalse(report["production_ready"])
        self.assertFalse(report["published"])
        self.assertEqual(self.source_lock.read_bytes(), before)
        self.assertTrue(
            all(source["status"] == "unreviewed-acquisition-draft" for source in report["source_review"].values())
        )
        for directory in self.exported:
            manifest = decode((directory / "manifest.json").read_bytes())
            self.assertEqual(manifest["source_identity"]["acquisition"]["status"], "unreviewed-acquisition-draft")

    def test_each_unreviewed_selected_source_refuses_before_output_without_promoting_inputs(self):
        for source in self.recipe_data["source_names"]:
            with self.subTest(source=source):
                self.source_statuses = {source: "unreviewed-acquisition-draft"}
                self.write_recipe()
                before = snapshot(self.fixture_root)
                with self.assertRaisesRegex(ValueError, "source-not-reviewed"):
                    self.prepare()
                self.assertFalse(self.out.exists())
                self.assertEqual(snapshot(self.fixture_root), before)
                self.assertEqual(
                    decode(self.source_lock.read_bytes())["sources"][source]["acquisition"]["status"],
                    "unreviewed-acquisition-draft",
                )
        self.acquisition.assert_not_called()
        self.lock_export.assert_not_called()
        self.staging.assert_not_called()

    def test_unselected_unreviewed_source_does_not_block_reviewed_selected_sources(self):
        self.source_statuses = {"unused-source": "unreviewed-acquisition-draft"}
        self.write_recipe()
        report = self.prepare()
        self.assertEqual(report["status"], "awaiting-input-publication")
        self.assertNotIn("unused-source", report["source_review"])
        self.assertEqual(
            decode(self.source_lock.read_bytes())["sources"]["unused-source"]["acquisition"]["status"],
            "unreviewed-acquisition-draft",
        )

    def test_malformed_unselected_source_fails_export_conversion_before_any_acquisition(self):
        for corruption in ("missing-location", "invalid-digest", "invalid-source"):
            with self.subTest(corruption=corruption):
                self.write_recipe()
                self.out = self.cache / corruption
                unused = self.source_documents["unused-source"]
                record = next(iter(unused["resources"].values()))
                if corruption == "missing-location":
                    del record["bundle_url"]
                elif corruption == "invalid-digest":
                    record["sha256"] = "not-a-digest"
                else:
                    self.source_documents["unused-source"] = None
                self.source_lock.write_bytes(encoded({"schema_version": 1, "sources": self.source_documents}))
                source_pin = build.file_pin(self.source_lock)
                document = decode(self.recipe_path.read_bytes())
                document["source_lock"].update(source_pin)
                self.recipe_path.write_bytes(encoded(document))
                self.recipe_data["source_lock"].update(source_pin)
                self.recipe_data["pin"] = build.file_pin(self.recipe_path)
                self.assertNotIn("unused-source", self.recipe_data["source_names"])
                before = snapshot(self.fixture_root)
                events_before = len(self.events)
                with self.assertRaisesRegex(ValueError, "invalid-acquisition-lock: .*every entry"):
                    self.prepare()
                self.assertEqual(self.events[events_before:], ["export-lock"])
                self.assertEqual(snapshot(self.fixture_root), before)
                self.assertFalse((self.out / "report.json").exists())
                self.assertFalse((self.out / ".running").exists())
                state = decode((self.out / "progress.json").read_bytes())
                self.assertEqual(len(state["steps"]), 1)
                attempts = next(iter(state["steps"].values()))
                self.assertEqual(attempts[-1]["status"], "failed")
                self.assertIn("invalid-acquisition-lock", attempts[-1]["error"])
        self.acquisition.assert_not_called()
        self.facts_export.assert_not_called()
        self.staging.assert_not_called()

    def test_clean_receipts_from_an_unreviewed_commit_still_block_input_publication(self):
        self.problems.side_effect = self.original_problems
        self.patch(publish, "off_branch", return_value=1)
        report = self.prepare()
        self.assertEqual(report["status"], "blocked-input-publication")
        self.assertTrue(any("is not on origin/master" in problem for problem in report["publication_problems"]))
        self.assertFalse(report["published"])

    def test_dirty_checkout_requires_explicit_rehearsal_before_any_acquisition(self):
        self.checkout.return_value = identity(dirty_paths=DIRTY)
        with self.assertRaisesRegex(ValueError, "dirty"):
            self.prepare()
        self.acquisition.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_completed_resume_checks_all_outputs_without_rerunning_steps(self):
        report = self.prepare()
        before = snapshot(self.out)
        self.events.clear()
        resumed = self.prepare(resume=True)
        self.assertEqual(resumed, report)
        self.assertEqual(snapshot(self.out), before)
        self.assertEqual(self.events, [])
        self.assertEqual(self.acquisition.call_count, len(self.recipe_data["source_names"]))
        self.assertEqual(self.validation.call_count, 1)
        self.assertEqual(self.staging.call_count, 1)

    def test_completed_resume_rejects_modified_missing_added_empty_directory_and_symlink_outputs(self):
        for mutation in ("modified", "missing", "added", "empty-directory", "symlink"):
            with self.subTest(mutation=mutation):
                self.out = self.cache / mutation
                report = self.prepare()
                acquisition_step = next(step for step in report["steps"] if "acquire" in step["name"])
                step = self.out / acquisition_step["directory"]
                raw_root = Path(decode((step / "result.json").read_bytes())["directory"])
                resource = raw_root / next(iter(self.raw_resources["facts-source"]))
                if mutation == "modified":
                    resource.write_bytes(b"!" * resource.stat().st_size)
                elif mutation == "missing":
                    resource.unlink()
                elif mutation == "added":
                    (step / "unexpected.json").write_bytes(b"{}\n")
                elif mutation == "empty-directory":
                    (step / "unrecorded-directory").mkdir()
                else:
                    target = self.root / "symlink-target"
                    resource.rename(target)
                    resource.symlink_to(target)
                events = list(self.events)
                original_report = (self.out / "report.json").read_bytes()
                with self.assertRaises((ValueError, OSError)):
                    self.prepare(resume=True)
                self.assertEqual(self.events, events)
                self.assertEqual((self.out / "report.json").read_bytes(), original_report)
                self.assertFalse((self.out / ".running").exists())

    def test_completed_resume_rejects_a_rewritten_report(self):
        report = self.prepare()
        (self.out / "report.json").write_bytes(encoded({**report, "published": True}))
        self.events.clear()
        with self.assertRaisesRegex(ValueError, "report.*changed|changed.*report"):
            self.prepare(resume=True)
        self.assertEqual(self.events, [])

    def test_corrupt_progress_refuses_resume_without_rerunning_or_changing_evidence(self):
        self.prepare()
        progress_path = self.out / "progress.json"
        original = progress_path.read_bytes()
        state = decode(original)
        escaped = copy.deepcopy(state)
        next(iter(escaped["steps"].values()))[-1]["directory"] = "../../outside"
        inventory = copy.deepcopy(state)
        next(iter(inventory["steps"].values()))[-1]["inventory"] = {"files": {}, "directories": []}
        cases = {
            "missing": None,
            "invalid-json": b"{",
            "duplicate-key": b'{"schema":"first","schema":"second"}',
            "wrong-schema": encoded({**state, "schema": "unsupported"}),
            "invalid-steps": encoded({**state, "steps": []}),
            "escaped-directory": encoded(escaped),
            "changed-inventory": encoded(inventory),
        }
        evidence = {name: raw for name, raw in snapshot(self.out).items() if name != "progress.json"}
        self.events.clear()
        for name, raw in cases.items():
            with self.subTest(corruption=name):
                if raw is None:
                    progress_path.unlink()
                else:
                    progress_path.write_bytes(raw)
                with self.assertRaises((ValueError, OSError)):
                    self.prepare(resume=True)
                self.assertEqual(self.events, [])
                self.assertEqual(
                    {name: raw for name, raw in snapshot(self.out).items() if name != "progress.json"}, evidence
                )
                if raw is None:
                    self.assertFalse(progress_path.exists())
                else:
                    self.assertEqual(progress_path.read_bytes(), raw)
        progress_path.write_bytes(original)

    def test_failed_attempt_is_preserved_and_resume_uses_a_fresh_attempt(self):
        def fail_export(**arguments):
            output = arguments["out"]
            output.mkdir()
            (output / "partial.json").write_bytes(b"unfinished facts\n")
            print("preserve this failed export log")
            raise ValueError("synthetic export failure")

        self.facts_export.side_effect = fail_export
        with self.assertRaisesRegex(ValueError, "synthetic export failure"):
            self.prepare()
        state = decode((self.out / "progress.json").read_bytes())
        label, attempts = next(
            (label, attempts) for label, attempts in state["steps"].items() if attempts[-1]["status"] == "failed"
        )
        failed = self.out / attempts[-1]["directory"]
        before = snapshot(failed)
        self.assertIn(b"preserve this failed export log", (failed / "output.log").read_bytes())
        self.assertFalse((self.out / "report.json").exists())
        self.assertFalse((self.out / ".running").exists())
        self.staging.assert_not_called()
        self.facts_export.side_effect = self.export_facts
        report = self.prepare(resume=True)
        after = decode((self.out / "progress.json").read_bytes())["steps"][label]
        self.assertEqual([attempt["status"] for attempt in after], ["failed", "complete"])
        self.assertNotEqual(after[0]["directory"], after[1]["directory"])
        self.assertEqual(snapshot(failed), before)
        self.assertNotIn("candidate/partial.json", snapshot(self.out / after[1]["directory"]))
        self.assertEqual(self.acquisition.call_count, len(self.recipe_data["source_names"]))
        self.assertEqual(self.lock_export.call_count, 1)
        self.assertEqual(report["status"], "awaiting-input-publication")

    def test_failed_facts_validation_is_retried_before_crafting_without_reexporting(self):
        self.validation.side_effect = ValueError("raw replay differs")
        with self.assertRaisesRegex(ValueError, "raw replay differs"):
            self.prepare()
        self.crafting_export.assert_not_called()
        self.staging.assert_not_called()
        self.assertFalse((self.out / "report.json").exists())
        self.validation.side_effect = self.validate_facts
        self.prepare(resume=True)
        self.assertEqual(self.facts_export.call_count, 1)
        self.assertEqual(self.validation.call_count, 2)
        self.assertEqual(self.crafting_export.call_count, 1)
        self.assertLess(self.events.index("validate"), self.events.index("crafting"))

    def test_invalid_modes_and_implicit_unbounded_or_noninteger_online_budgets_fail_before_work(self):
        for mode, budget in (
            ("online", 0),
            ("online", -1),
            ("online", sources.MAX_NETWORK + 1),
            ("offline", 1),
            ("offline", -1),
            ("online", True),
            ("offline", False),
            ("online", "1024"),
            ("online", 1.5),
            ("automatic", 0),
        ):
            with self.subTest(mode=mode, budget=budget), self.assertRaises(ValueError):
                self.prepare(mode=mode, network_budget_bytes=budget)
        self.acquisition.assert_not_called()
        self.loader.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_explicit_online_budget_is_shared_across_unique_sources(self):
        self.reservation = 37
        budget = 512
        report = self.prepare(mode="online", network_budget_bytes=budget)
        for index, call in enumerate(self.acquisition.call_args_list):
            self.assertEqual(call.args[6:], ("online", budget - index * self.reservation))
            self.assertEqual(call.args[4], self.decoder_python)
        self.assertTrue(self.decoder_python.is_symlink())
        self.assertEqual(report["network_reserved_bytes"], len(self.recipe_data["source_names"]) * self.reservation)

    def test_failed_online_acquisition_cannot_reset_its_reserved_budget_on_resume(self):
        def fail_acquire(*arguments, **options):
            self.acquire(*arguments, **options)
            raise ValueError("interrupted bounded acquisition")

        self.acquisition.side_effect = fail_acquire
        with self.assertRaisesRegex(ValueError, "interrupted bounded acquisition"):
            self.prepare(mode="online", network_budget_bytes=512)
        state = decode((self.out / "progress.json").read_bytes())
        attempts = next(attempts for attempts in state["steps"].values() if attempts[-1]["status"] == "failed")
        failed = self.out / attempts[-1]["directory"]
        before = snapshot(failed)
        self.acquisition.side_effect = self.acquire
        with self.assertRaisesRegex(ValueError, "budget.*exhausted"):
            self.prepare(mode="online", network_budget_bytes=512, resume=True)
        self.assertEqual(self.acquisition.call_count, 1)
        self.assertEqual(snapshot(failed), before)
        self.lock_export.assert_called_once()
        self.assertFalse((self.out / ".running").exists())

    def test_output_must_be_a_strict_descendant_of_this_repositories_cache(self):
        for output in (
            self.cache,
            self.repo,
            self.root / "outside",
            self.repo / "release/new",
            self.repo / ".cache-sibling/run",
            self.cache / "../../escaped",
        ):
            with self.subTest(output=output), self.assertRaises(ValueError):
                self.prepare(out=output)
        self.acquisition.assert_not_called()

    def test_symlinked_output_ancestors_and_dangling_outputs_are_rejected(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "keep").write_bytes(b"untouched")
        alias = self.cache / "alias"
        alias.symlink_to(outside, target_is_directory=True)
        dangling = self.cache / "dangling"
        dangling.symlink_to(self.root / "does-not-exist", target_is_directory=True)
        other_repo = self.root / "other-repo"
        other_repo.mkdir()
        (other_repo / ".cache").symlink_to(self.cache, target_is_directory=True)
        for output, repo in (
            (alias, self.repo),
            (alias / "child", self.repo),
            (dangling, self.repo),
            (other_repo / ".cache/run", other_repo),
        ):
            with self.subTest(output=output), self.assertRaisesRegex(ValueError, "[Ss]ymlink"):
                self.prepare(out=output, repo=repo)
        self.assertEqual(snapshot(outside), {"keep": b"untouched"})
        self.assertFalse((self.root / "does-not-exist").exists())
        self.acquisition.assert_not_called()

    def test_output_cannot_enclose_recipe_source_lock_decoder_lock_or_retained_inputs(self):
        original = copy.deepcopy(self.recipe_data)
        for name in ("recipe", "source", "decoder", "retained"):
            with self.subTest(input=name):
                self.recipe_data = copy.deepcopy(original)
                output = self.cache / f"overlaps-{name}"
                protected = output / "input.json"
                protected.parent.mkdir()
                protected.write_bytes(b"protected input")
                options = {"out": output}
                if name == "recipe":
                    options["recipe"] = protected
                elif name == "source":
                    self.recipe_data["source_lock"]["path"] = protected
                elif name == "decoder":
                    self.recipe_data["decoder"]["lock"]["path"] = protected
                else:
                    self.recipe_data["retained"][0]["path"] = protected
                with self.assertRaisesRegex(ValueError, "overlaps-input"):
                    self.prepare(**options)
                self.assertEqual(protected.read_bytes(), b"protected input")
                self.assertEqual(set(snapshot(output)), {"input.json"})
        self.acquisition.assert_not_called()

    def test_explicit_range_cache_cannot_overlap_output_or_any_pinned_input(self):
        for cache in (
            self.out,
            self.out / "ranges",
            self.cache,
            self.recipe_path,
            self.source_lock,
            self.decoder_lock,
            self.fixture_root,
            Path(self.retained[0]["path"]),
        ):
            with self.subTest(cache=cache), self.assertRaisesRegex(ValueError, "range-cache"):
                self.prepare(range_cache=cache)
        self.acquisition.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_existing_output_needs_resume_and_running_lock_is_never_stolen(self):
        self.out.mkdir()
        (self.out / "keep").write_bytes(b"existing output")
        with self.assertRaisesRegex(ValueError, "existing-output|resume"):
            self.prepare()
        self.assertEqual(snapshot(self.out), {"keep": b"existing output"})
        self.acquisition.assert_not_called()
        self.out = self.cache / "complete"
        self.prepare()
        lock = self.out / ".running"
        lock.write_bytes(b"another process owns this run\n")
        before = snapshot(self.out)
        with self.assertRaises(FileExistsError):
            self.prepare(resume=True)
        self.assertEqual(snapshot(self.out), before)

    def test_resume_rejects_changed_recipe_producer_code_mode_cache_and_rehearsal(self):
        with self.assertRaises((ValueError, OSError)):
            self.prepare(resume=True)
        self.prepare()
        self.events.clear()
        original = copy.deepcopy(self.recipe_data)
        self.recipe_data["pin"] = pin(b"different recipe")
        with self.assertRaisesRegex(ValueError, "resume.*changed"):
            self.prepare(resume=True)
        self.recipe_data = original
        self.checkout.return_value = identity(commit="d" * 40)
        with self.assertRaisesRegex(ValueError, "resume.*changed"):
            self.prepare(resume=True)
        self.checkout.return_value = self.producer
        original_code = self.code.return_value
        self.code.return_value = {"prepare.py": pin(b"changed implementation")}
        with self.assertRaisesRegex(ValueError, "resume.*changed"):
            self.prepare(resume=True)
        self.code.return_value = original_code
        for options in (
            {"mode": "online", "network_budget_bytes": 512},
            {"range_cache": self.cache / "different-ranges"},
            {"rehearsal": True},
        ):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, "resume.*changed"):
                self.prepare(resume=True, **options)
        self.assertEqual(self.events, [])

    def test_resume_rejects_changed_decoder_identity_without_reusing_completed_outputs(self):
        self.prepare()
        before = snapshot(self.out)
        source = self.recipe_data["source_names"][-1]
        self.decoder_receipts[source]["identity_sha256"] = pin(b"changed installed decoder")["sha256"]
        self.events.clear()
        with self.assertRaisesRegex(ValueError, "resume-inputs-changed|decoder-identity-changed"):
            self.prepare(resume=True)
        self.assertEqual(self.events, [])
        self.assertEqual(snapshot(self.out), before)

    def test_decoder_identity_change_during_acquisition_stops_before_native_export(self):
        changed_source = self.recipe_data["source_names"][-1]

        def change_decoder(*arguments, **options):
            receipt = self.acquire(*arguments, **options)
            self.decoder_receipts[changed_source]["identity_sha256"] = pin(b"changed decoder during acquisition")[
                "sha256"
            ]
            return receipt

        self.acquisition.side_effect = change_decoder
        with self.assertRaisesRegex(ValueError, "decoder-identity-changed"):
            self.prepare()
        self.assertEqual(self.acquisition.call_count, 1)
        state = decode((self.out / "progress.json").read_bytes())
        attempts = next(attempts for attempts in state["steps"].values() if attempts[-1]["status"] == "failed")
        self.assertEqual(attempts[-1]["status"], "failed")
        self.assertIn("decoder-identity-changed", attempts[-1]["error"])
        self.assertTrue((self.out / attempts[-1]["directory"] / "raw" / sources.RECEIPT).is_file())
        self.assertFalse((self.out / ".running").exists())
        self.assertFalse((self.out / "report.json").exists())
        self.lock_export.assert_called_once()
        self.facts_export.assert_not_called()
        self.staging.assert_not_called()

    def test_acquisition_receipt_must_match_the_pinned_decoder_identity(self):
        def mismatched_decoder(*arguments, **options):
            receipt = self.acquire(*arguments, **options)
            receipt["decoder"]["identity_sha256"] = pin(b"unexpected acquisition decoder")["sha256"]
            (arguments[3] / sources.RECEIPT).write_bytes(encoded(receipt))
            return receipt

        self.acquisition.side_effect = mismatched_decoder
        with self.assertRaisesRegex(ValueError, "acquisition-decoder-mismatch"):
            self.prepare()
        self.assertEqual(self.acquisition.call_count, 1)
        state = decode((self.out / "progress.json").read_bytes())
        attempts = next(attempts for attempts in state["steps"].values() if attempts[-1]["status"] == "failed")
        self.assertEqual(attempts[-1]["status"], "failed")
        self.assertIn("acquisition-decoder-mismatch", attempts[-1]["error"])
        self.assertFalse((self.out / ".running").exists())
        self.assertFalse((self.out / "report.json").exists())
        self.lock_export.assert_called_once()
        self.facts_export.assert_not_called()
        self.staging.assert_not_called()

    def test_pinned_files_are_rechecked_before_acquisition(self):
        for index, path in enumerate(
            (self.recipe_path, self.source_lock, self.decoder_lock, *(Path(record["path"]) for record in self.retained))
        ):
            with self.subTest(path=path):
                original = path.read_bytes()
                path.write_bytes(original + b" ")
                with self.assertRaisesRegex(ValueError, "changed"):
                    self.prepare(out=self.cache / f"changed-{index}")
                path.write_bytes(original)
        self.acquisition.assert_not_called()

    def test_input_mutation_during_acquisition_is_detected_before_native_export_and_keeps_failed_evidence(self):
        retained = Path(self.retained[0]["path"])

        def change_input(*arguments, **options):
            receipt = self.acquire(*arguments, **options)
            retained.write_bytes(b"changed during acquisition")
            return receipt

        self.acquisition.side_effect = change_input
        with self.assertRaisesRegex(ValueError, "input-changed"):
            self.prepare()
        state = decode((self.out / "progress.json").read_bytes())
        attempts = next(attempts for attempts in state["steps"].values() if attempts[-1]["status"] == "failed")
        self.assertEqual(attempts[-1]["status"], "failed")
        self.assertTrue((self.out / attempts[-1]["directory"] / "raw" / sources.RECEIPT).is_file())
        self.assertFalse((self.out / ".running").exists())
        self.lock_export.assert_called_once()
        self.facts_export.assert_not_called()
        self.staging.assert_not_called()

    def test_invalid_export_receipts_never_reach_validation_or_staging(self):
        for mutation in ("producer", "rehearsal", "target", "missing", "manifest"):
            with self.subTest(mutation=mutation):
                self.out = self.cache / f"receipt-{mutation}"

                def export_invalid(**arguments):
                    manifest = self.export_facts(**arguments)
                    directory = arguments["out"]
                    manifest_path = directory / "manifest.json"
                    receipt_path = sibling(directory)
                    producer = self.producer
                    rehearsal = False
                    if mutation == "missing":
                        receipt_path.unlink()
                        return manifest
                    if mutation == "manifest":
                        manifest_path.write_bytes(manifest_path.read_bytes() + b" ")
                        return manifest
                    if mutation == "producer":
                        producer = identity(commit="e" * 40)
                    elif mutation == "rehearsal":
                        rehearsal = True
                    else:
                        manifest["source_identity"]["game_patch"] = "0.5.5.9"
                        manifest_path.write_bytes(encoded(manifest))
                    receipt_path.write_bytes(
                        export_receipt.receipt_bytes(
                            manifest_path.read_bytes(), "RePoE.native.facts", producer, rehearsal
                        )
                    )
                    return manifest

                self.facts_export.side_effect = export_invalid
                with self.assertRaises((ValueError, OSError)):
                    self.prepare()
                self.assertFalse((self.out / "report.json").exists())
                self.assertFalse((self.out / ".running").exists())
        self.validation.assert_not_called()
        self.crafting_export.assert_not_called()
        self.staging.assert_not_called()

    def test_real_recipe_cached_acquisition_native_exports_validation_and_staging_remain_offline(self):
        fixture = test_items_actors.NativeItemsActorsTests()
        fixture.setUpClass()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        self.raw_resources["facts-source"] = {
            name: (fixture.raw / name).read_bytes() for name in fixture.source["resources"]
        }
        self.raw_resources["tables-source"] = {
            "Data/Balance/ModEffectStats.datc64": test_facts.dat_bytes(
                fixture.spec, "ModEffectStats", [{"Stat": 0, "Tags": [], "Multiplier": -3}]
            )
        }
        self.write_recipe()
        source_root = build.ROOT
        for directory in ("RePoE/native", "schema"):
            for path in (source_root / directory).rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts:
                    write_tree(self.repo, {path.relative_to(source_root).as_posix(): path.read_bytes()})
        for name in ("pyproject.toml", "uv.lock"):
            write_tree(self.repo, {name: (source_root / name).read_bytes()})
        self.context.enter_context(mock.patch.object(tables, "ROOT", self.repo))
        self.context.enter_context(mock.patch.object(item_inheritance, "ROOT", self.repo))
        decoder_calls = self.context.enter_context(mock.patch.object(source_fixtures.FakeDecoder, "calls", []))
        self.loader.side_effect = self.original_loader
        self.acquisition.side_effect = self.original_acquire
        self.facts_export.side_effect = self.original_facts
        self.validation.side_effect = self.original_validate
        self.tables_export.side_effect = self.original_tables
        self.descriptions_export.side_effect = self.original_descriptions
        self.inheritance_export.side_effect = self.original_inheritance
        self.problems.side_effect = self.original_problems
        self.patch(publish, "off_branch", return_value=0)
        range_cache = self.cache / "offline-ranges"
        for name in self.recipe_data["source_names"]:
            selected = self.source_documents[name]
            bundle = source_fixtures.bundle_bytes(b"".join(self.raw_resources[name].values()), chunk_size=256)
            url = next(iter(selected["resources"].values()))["bundle_url"]
            sources.RangeCache(range_cache, selected).add(
                url, 0, bundle, len(bundle), '"synthetic-offline"', {"kind": "synthetic-offline-fixture"}
            )
        report = self.prepare(range_cache=range_cache)
        self.assertEqual(report["status"], "awaiting-input-publication")
        self.assertFalse(report["production_ready"])
        self.assertFalse(report["published"])
        self.assertEqual(report["network_reserved_bytes"], 0)
        self.assertTrue(decoder_calls)
        for call in self.acquisition.call_args_list:
            self.assertEqual(call.args[4], self.decoder_python)
            self.assertEqual(call.args[6:], ("offline", 0))
        candidate = self.validation.call_args.kwargs["candidate"]
        self.assertEqual(
            self.validation.call_args.kwargs["manifest_sha256"], build.file_pin(candidate / "manifest.json")["sha256"]
        )
        self.assertEqual(len(decode((candidate / "manifest.json").read_bytes())["files"]), 87)
        validation_step = next(step for step in report["steps"] if "validate" in step["name"])
        self.assertEqual(
            decode((self.out / validation_step["directory"] / "result.json").read_bytes())["result"], "passed"
        )
        ordinary = Path(report["package_directories"]["ordinary"])
        exported_table = decode((ordinary / "passive-tree/supplement/tables.json").read_bytes())
        self.assertEqual(exported_table["ModEffectStats"]["rows"][0]["values"]["Multiplier"], -3)
        inheritance = decode((ordinary / "base-items/supplement/inheritance.json").read_bytes())
        self.assertEqual(inheritance["roots"]["Metadata/Items/Test.it"]["tag_interpretation"]["tags"], ["test"])
        for receipt in self.staged[-1]["receipts"].values():
            self.assertFalse(receipt["rehearsal"])
            self.assertEqual(receipt["target"], TARGET)


class PreparePatchCommandTests(unittest.TestCase):
    def test_main_forwards_every_option_and_prints_the_report(self):
        report = {"schema": "repoe-prepare-patch-report/v1", "published": False}
        arguments = [
            "--recipe",
            "/tmp/recipe.json",
            "--expected-recipe-sha256",
            "a" * 64,
            "--out",
            "/tmp/cache/run",
            "--mode",
            "online",
            "--network-budget-bytes",
            "512",
            "--range-cache",
            "/tmp/ranges",
            "--rehearsal",
            "--resume",
        ]
        output = io.StringIO()
        with mock.patch.object(prepare_patch, "prepare", autospec=True, return_value=report) as prepare:
            with contextlib.redirect_stdout(output):
                prepare_patch.main(arguments)
        prepare.assert_called_once_with(
            recipe=Path("/tmp/recipe.json"),
            expected_recipe_sha256="a" * 64,
            out=Path("/tmp/cache/run"),
            mode="online",
            network_budget_bytes=512,
            range_cache=Path("/tmp/ranges"),
            rehearsal=True,
            resume=True,
        )
        self.assertEqual(decode(output.getvalue().encode()), report)

    def test_main_defaults_offline_requires_all_pins_and_never_accepts_publish_flags(self):
        arguments = ["--recipe", "/tmp/recipe.json", "--expected-recipe-sha256", "a" * 64, "--out", "/tmp/run"]
        with mock.patch.object(prepare_patch, "prepare", autospec=True, return_value={}) as prepare:
            with contextlib.redirect_stdout(io.StringIO()):
                prepare_patch.main(arguments)
            self.assertEqual(prepare.call_args.kwargs["mode"], "offline")
            self.assertEqual(prepare.call_args.kwargs["network_budget_bytes"], 0)
            self.assertIsNone(prepare.call_args.kwargs["range_cache"])
            self.assertFalse(prepare.call_args.kwargs["rehearsal"])
            self.assertFalse(prepare.call_args.kwargs["resume"])
            prepare.reset_mock()
            for invalid in (arguments[2:], arguments[:2] + arguments[4:], arguments[:4], [*arguments, "--yes"]):
                with self.subTest(arguments=invalid), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as error:
                        prepare_patch.main(invalid)
                    self.assertEqual(error.exception.code, 2)
            prepare.assert_not_called()

    def test_main_reports_refusals_without_tracebacks_and_online_needs_an_explicit_budget(self):
        arguments = ["--recipe", "/tmp/recipe.json", "--expected-recipe-sha256", "a" * 64, "--out", "/tmp/run"]
        for online in (False, True):
            error_output = io.StringIO()
            context = (
                contextlib.nullcontext()
                if online
                else mock.patch.object(prepare_patch, "prepare", side_effect=ValueError("synthetic refusal"))
            )
            with context, contextlib.redirect_stderr(error_output), self.assertRaises(SystemExit) as error:
                prepare_patch.main([*arguments, "--mode", "online"] if online else arguments)
            self.assertEqual(error.exception.code, 1)
            self.assertIn("release:prepare-patch:", error_output.getvalue())
            self.assertNotIn("Traceback", error_output.getvalue())
            self.assertIn("explicit" if online else "synthetic refusal", error_output.getvalue())


if __name__ == "__main__":
    unittest.main()
