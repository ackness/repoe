"""Synthetic neutral facts exercise PoBR's catalog policy, not game semantics.

Assembly tests read archives from a local bare repository; no network."""

import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

from RePoE import data_publication as publication
from RePoE import pobr_crafting_catalog as crafting
from RePoE import publication_index as pub

ROOT = Path(__file__).resolve().parents[1]
TARGET = {"game": "poe2", "game_patch": "9.1", "realm": "international"}


def fixture():
    def ref(table, row, identity=None):
        return {"table": table, "row": row, **({"id": identity} if identity is not None else {})}

    classes = [ref("ItemClasses", i, value) for i, value in enumerate(("Wand", "Focus", "Amulet"))]
    mods = []
    for index, identity in enumerate(("AlloyHybrid", "DisplayOnly", "Strength", "Dexterity")):
        slots = [
            {"slot": slot, "stat": None, "min_raw": 0, "max_raw": 0, "min_hardmode_raw": 0, "max_hardmode_raw": 0}
            for slot in range(1, 9)
        ]
        slots[0].update(stat=ref("Stats", index, f"stat{index}"), min_raw=0, max_raw=0)
        mods.append(
            {"mod": ref("Mods", index, identity), "level_raw": 25, "has_hardmode_values_raw": False, "slots": slots}
        )
    mods[0]["slots"][4].update(
        stat=ref("Stats", 1, "stat1"), min_raw=-5, max_raw=5, min_hardmode_raw=77, max_hardmode_raw=88
    )
    mods[0]["slots"][7].update(stat=ref("Stats", 0, "stat0"), min_raw=2, max_raw=3)
    essences, categories, recipes = [], [], []
    currencies = ("CurrencyVerisiumAlloy11", "CurrencyPerfectEssenceAttribute", "CurrencyNormalEssence")
    for index, currency in enumerate(currencies):
        essences.append(
            {"essence": ref("Essences", index), "currency": ref("BaseItemTypes", index, f"Metadata/{currency}")}
        )
        category = ref("EssenceTargetItemCategories", index, f"category{index}")
        selected = [0, 1, 0] if index == 0 else [2]
        item_classes = [{"source_slot": i, "target": classes[c]} for i, c in enumerate(selected)]
        categories.append({"category": category, "item_classes": item_classes})
        outcomes = [] if index == 0 else [2, 3, 2]
        recipes.append(
            {
                "source": ref("EssenceMods", index),
                "essence": essences[-1]["essence"],
                "currency": essences[-1]["currency"],
                "target_category": category,
                "item_classes": item_classes,
                "mod": mods[0 if index == 0 else 1]["mod"],
                "display_mod": mods[1]["mod"],
                "outcome_mods": [{"source_slot": i, "target": mods[m]["mod"]} for i, m in enumerate(outcomes)],
                "outcome_mod_weights_raw": [0, 5, 0] if index == 1 else [],
            }
        )
    return {
        "format": crafting.FORMAT,
        "mods": mods,
        "essences": essences,
        "categories": categories,
        "essence_mods": recipes,
        "summary": {"tables": dict(zip(crafting.TABLES, (3, 3, 4, 4, 3, 3, 3)))},
        "diagnostics": [{"code": "outcome_weight_alignment_unresolved", "source": ref("EssenceMods", 2)}],
    }


def zip_bytes(members):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in sorted(members.items()):
            archive.writestr(name, raw)
    return buffer.getvalue()


def crafting_package(facts, target=TARGET):
    members = {f"{name}.json": b'{"synthetic":true}' for name in crafting.TABLES}
    members.update({"crafting.json": publication.encoded(facts), "input-manifest.json": b'{"synthetic_source":true}'})
    producer = {name: "c" * 64 for name in crafting.PRODUCERS}
    input_pin = pub.pin(members["input-manifest.json"])
    manifest = {
        "format": crafting.FORMAT,
        "status": "partial-candidate",
        "production_ready": False,
        "source_identity": {**target, "acquisition": {"status": "unreviewed-acquisition-draft"}},
        "producer": producer,
        "input_package": {"manifest": input_pin},
        "files": {n: pub.pin(r) for n, r in members.items()},
    }
    members["manifest.json"] = publication.encoded(manifest)
    spec = {
        "publication": "published",
        "repository": pub.OWNER,
        "path": "handoff/synthetic/crafting-facts.zip",
        "manifest": pub.pin(members["manifest.json"]),
        "input_manifest": input_pin,
        "producer": producer,
        "expanded_bytes": sum(map(len, members.values())),
    }
    return spec, zip_bytes(members)


def game_package(catalog_sha256, target=TARGET, extra=None):
    version = target["game_patch"]
    members = {f"data/{version}/base/stats.json": b'{"stats":[]}\n', "data/overlay-common/x.json": b"{}\n"}
    snapshot = {"schema_version": 3, "poe_version": version, "files": {"base/stats.json": "e" * 64}}
    if catalog_sha256 is not None:
        snapshot["files"]["overlay/trade_crafting_sources.json"] = catalog_sha256
    members[f"data/{version}/manifest.json"] = json.dumps(snapshot).encode()
    members.update(extra or {})
    manifest = {
        "schema": crafting.PART_SCHEMA,
        "kind": "game",
        "target": target,
        "files": {n: pub.pin(r) for n, r in members.items()},
    }
    members["manifest.json"] = publication.encoded(manifest)
    spec = {
        "publication": "published",
        "repository": pub.OWNER,
        "path": "handoff/synthetic/game-build-part.zip",
        "manifest": pub.pin(members["manifest.json"]),
        "expanded_bytes": sum(map(len, members.values())),
    }
    return spec, zip_bytes(members)


class CraftingProjectionTests(unittest.TestCase):
    def setUp(self):
        self.facts = fixture()

    def project(self):
        return crafting.project(
            self.facts, source_manifest_sha256="a" * 64, facts_manifest_sha256="b" * 64, target=TARGET
        )

    def test_categories_outcome_policy_deduplication_and_all_eight_stat_slots(self):
        document, receipt = self.project()
        alloy, dexterity, strength = document["mods"]
        self.assertEqual(
            alloy,
            {
                "source": "alloy",
                "id": "AlloyHybrid",
                "item_types": ["Focus", "Wand"],
                "level": 25,
                "stats": [
                    {"id": "stat0", "min": 0, "max": 0},
                    {"id": "stat1", "min": -5, "max": 5},
                    {"id": "stat0", "min": 2, "max": 3},
                ],
            },
        )
        self.assertEqual([dexterity["id"], strength["id"]], ["Dexterity", "Strength"])
        self.assertEqual(dexterity["item_types"], ["Amulet"])
        self.assertEqual(receipt["summary"], {"selected_rows": 2, "catalog_mods": 3})
        self.assertEqual(len(receipt["selected"][1]["mods"]), 3)  # raw duplicate retained in provenance
        self.assertEqual(receipt["source_diagnostics"], self.facts["diagnostics"])
        self.assertNotIn("DisplayOnly", [m["id"] for m in document["mods"]])
        self.assertFalse(document["_meta"]["client_identity_independently_observed"])

    def test_null_stat_nonzero_intervals_and_hardmode_remain_diagnosed(self):
        mod = self.facts["mods"][0]
        mod["slots"][1].update(min_raw=-20, max_raw=-20)
        mod["has_hardmode_values_raw"] = True
        before = copy.deepcopy(self.facts)
        document, receipt = self.project()
        self.assertEqual(self.facts, before)
        unknown = receipt["diagnostics"][0]
        self.assertEqual(
            (unknown["code"], unknown["stat"], unknown["min_raw"], unknown["max_raw"]),
            ("unidentified_stat_interval", None, -20, -20),
        )
        self.assertEqual(receipt["diagnostics"][1]["code"], "hardmode_channel_not_projected")
        self.assertEqual(document["mods"][0]["stats"][1], {"id": "stat1", "min": -5, "max": 5})

    def test_unknown_identified_interval_and_null_selected_owners_reject(self):
        for case in ("endpoint", "inverted", "category", "class", "outcome", "boolean", "identity", "slots"):
            with self.subTest(case=case):
                self.facts = fixture()
                row, mod = self.facts["essence_mods"][0], self.facts["mods"][0]
                if case == "endpoint":
                    mod["slots"][0]["min_raw"] = None
                elif case == "inverted":
                    mod["slots"][0].update(min_raw=5, max_raw=0)
                elif case == "category":
                    row.update(target_category=None, item_classes=None)
                elif case == "class":
                    row["item_classes"][0]["target"] = None
                elif case == "outcome":
                    row.update(mod=None)
                elif case == "boolean":
                    mod["mod"]["row"] = False
                elif case == "identity":
                    row["mod"] = {"table": "Mods", "row": 0, "id": "foreign"}
                else:
                    mod["slots"].pop()
                with self.assertRaises(ValueError):
                    self.project()

    def test_selected_weights_are_diagnostic_never_probabilities_or_mod_substitution(self):
        self.facts["essence_mods"][1]["outcome_mod_weights_raw"] = []
        document, receipt = self.project()
        self.assertEqual([m["id"] for m in document["mods"]], ["AlloyHybrid", "Dexterity", "Strength"])
        self.assertEqual(receipt["diagnostics"][0]["code"], "selected_outcome_weights_unresolved")
        self.facts["essence_mods"][0].update(mod=None)
        with self.assertRaisesRegex(ValueError, "no identified outcome"):
            self.project()

    def test_empty_category_is_known_empty_not_wildcard(self):
        self.facts["categories"][0]["item_classes"] = []
        self.facts["essence_mods"][0]["item_classes"] = []
        document, _ = self.project()
        self.assertEqual(document["mods"][0]["item_types"], [])


class CraftingAssemblyTests(unittest.TestCase):
    def setUp(self):
        (ROOT / ".cache").mkdir(exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix="crafting-catalog-test-", dir=ROOT / ".cache"))
        self.repo = self.root / "artifacts.git"
        subprocess.check_output(["git", "init", "--bare", "--quiet", str(self.repo)])
        self.facts = fixture()
        self.crafting, crafting_zip = crafting_package(self.facts)
        catalog = crafting.runtime_encoded(self.catalog())
        self.game, game_zip = game_package(hashlib.sha256(catalog).hexdigest())
        self.catalog_raw = catalog
        revision = self.commit({self.crafting["path"]: crafting_zip, self.game["path"]: game_zip})
        for spec, raw in ((self.crafting, crafting_zip), (self.game, game_zip)):
            spec.update(revision=revision, **pub.pin(raw))

    def catalog(self, facts=None):
        spec = self.crafting
        document, _ = crafting.project(
            facts or self.facts,
            source_manifest_sha256=spec["manifest"]["sha256"],
            facts_manifest_sha256=spec["input_manifest"]["sha256"],
            target=TARGET,
        )
        return document

    def git(self, *args, data=None):
        env = dict(
            os.environ,
            GIT_AUTHOR_NAME="Synthetic",
            GIT_AUTHOR_EMAIL="synthetic@example.invalid",
            GIT_COMMITTER_NAME="Synthetic",
            GIT_COMMITTER_EMAIL="synthetic@example.invalid",
            GIT_AUTHOR_DATE="2000-01-01T00:00:00Z",
            GIT_COMMITTER_DATE="2000-01-01T00:00:00Z",
        )
        return subprocess.check_output(["git", "-C", str(self.repo), *args], input=data, env=env).decode().strip()

    def commit(self, files):
        """One orphan commit holding every file under a shared `handoff/synthetic/` tree."""
        entries = []
        for path, raw in sorted(files.items()):
            blob = self.git("hash-object", "-w", "--stdin", data=raw)
            entries.append(f"100644 blob {blob}\t{path.rsplit('/', 1)[1]}\n")
        tree = self.git("mktree", data="".join(entries).encode())
        for part in reversed(("handoff", "synthetic")):
            tree = self.git("mktree", data=f"040000 tree {tree}\t{part}\n".encode())
        return self.git("commit-tree", tree, "-m", "Synthetic artifacts")

    def assemble(self, game=None, crafting_spec=None, out="out"):
        return crafting.assemble(
            self.repo, TARGET, game or self.game, crafting_spec or self.crafting, "game-crafting-test", self.root / out
        )

    def test_assembly_adds_only_the_snapshot_pinned_catalog_and_is_reproducible(self):
        result = self.assemble()
        replay = self.assemble(out="replay")
        archive_raw = (self.root / "out/data.zip").read_bytes()
        self.assertEqual(archive_raw, (self.root / "replay/data.zip").read_bytes())
        self.assertEqual(result, replay)
        self.assertEqual(result["path"], "handoff/game-crafting-test/game-build-part.zip")
        self.assertEqual(result["ref"], "refs/tags/handoff/game-crafting-test")
        with zipfile.ZipFile(io.BytesIO(archive_raw)) as archive:
            manifest_raw, manifest = publication.archive_manifest(archive, result)
            self.assertEqual(archive.read("data/9.1/overlay/trade_crafting_sources.json"), self.catalog_raw)
            self.assertEqual(archive.read("data/9.1/base/stats.json"), b'{"stats":[]}\n')
        self.assertEqual(pub.pin(manifest_raw), result["manifest"])
        self.assertEqual(manifest["retained_input_package"], self.game)
        self.assertEqual(manifest["projection"]["crafting_input"], self.crafting)
        self.assertEqual(manifest["projection"]["output"], pub.pin(self.catalog_raw))
        self.assertEqual(set(manifest["files"]), {*self.base_files(), "data/9.1/overlay/trade_crafting_sources.json"})
        self.assertFalse(manifest["production_ready"])

    def base_files(self):
        raw = pub.tree_blob(self.repo, self.game["revision"], self.game["path"], self.game)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            return set(json.loads(archive.read("manifest.json"))["files"])

    def test_staged_handoff_is_a_valid_game_input(self):
        self.assemble()
        handoff = publication.git_handoff(self.root / "out")
        declaration = crafting.game_input(handoff)
        pub.input_declaration("game", declaration)
        subprocess.check_output(
            ["git", "-C", str(self.repo), "fetch", "--quiet", handoff["bare"], f"{handoff['ref']}:{handoff['ref']}"]
        )
        pub.verify_artifact(self.repo, "game", declaration, {"handoff/game-crafting-test": handoff["revision"]})

    def test_snapshot_mismatch_existing_catalog_and_foreign_inputs_reject_without_output(self):
        cases = {}
        changed = fixture()
        changed["mods"][2]["level_raw"] = 26
        other = crafting.runtime_encoded(self.catalog(changed))
        for case, game_args in (
            ("snapshot", (hashlib.sha256(other).hexdigest(),)),
            ("unlisted", (None,)),
        ):
            spec, raw = game_package(*game_args)
            cases[case] = (spec, raw)
        sha = hashlib.sha256(self.catalog_raw).hexdigest()
        cases["existing"] = game_package(sha, extra={"data/9.1/overlay/trade_crafting_sources.json": self.catalog_raw})
        cases["target"] = game_package(sha, target={**TARGET, "realm": "china"})
        for case, (spec, raw) in cases.items():
            with self.subTest(case=case):
                spec.update(revision=self.commit({spec["path"]: raw}), **pub.pin(raw))
                with self.assertRaises(ValueError):
                    self.assemble(game=spec, out=case)
                self.assertFalse((self.root / case).exists())
        for case in ("producer", "input", "owner", "publication"):
            with self.subTest(case=case):
                spec = copy.deepcopy(self.crafting)
                if case == "producer":
                    spec["producer"]["RePoE/native_crafting_facts.py"] = "d" * 64
                elif case == "input":
                    spec["input_manifest"]["sha256"] = "d" * 64
                elif case == "owner":
                    spec["repository"] = "ackness/pobr"
                else:
                    spec["publication"] = "local-only"
                with self.assertRaises(ValueError):
                    self.assemble(crafting_spec=spec, out=case)
                self.assertFalse((self.root / case).exists())

    def test_existing_output_is_never_replaced(self):
        (self.root / "out").mkdir()
        with self.assertRaisesRegex(ValueError, "Fresh repository cache output"):
            self.assemble()


if __name__ == "__main__":
    unittest.main()
