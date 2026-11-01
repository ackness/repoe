"""Synthetic counterexamples; actual source proof uses the fixed external Git objects."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from RePoE import buff_source_reconciliation as rec
from RePoE.data_publication import ROOT, pin

PERFORM = "Modules/CalcPerform.lua"
DEFENCE = "Modules/CalcDefence.lua"
MISC = b"""local function doActorMisc(env, actor)
	local modDB = actor.modDB
	local enemyDB = actor.enemy.modDB
	local output = actor.output
	if env.mode_combat then
		if modDB:Flag(nil, "Example") then
			modDB:NewMod("Damage", "INC", 10)
		end
	end
end
"""
PIPELINE = b"""function calcs.perform(env, skipEHP)
	doActorMisc(env, env.player)
end
"""
ARCANE = b"""function calcs.defence(env, actor)
	if actor.modDB:Flag(nil, "Condition:ExampleArcane") then
		actor.output.Example = 15
	end
end
"""


def function_spec(raw, declaration):
    lines = raw.splitlines(keepends=True)
    start = lines.index(declaration.encode() + b"\n")
    end = lines.index(b"end\n", start + 1)
    spec = {"line_start": start + 1, "line_end": end + 1}
    return {**spec, **pin(rec.segment(raw, spec))}


class BuffSourceReconciliationTests(unittest.TestCase):
    def setUp(self):
        (ROOT / ".cache").mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=ROOT / ".cache")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sources = {
            ("old", PERFORM): MISC + PIPELINE,
            ("new", PERFORM): MISC.replace(b"\tlocal output", b"\t---@class Output\n\tlocal output")
            + PIPELINE.replace(b"\tdoActorMisc", b'\tmodDB:NewMod("Example", "FLAG", true)\n\tdoActorMisc'),
            ("old", DEFENCE): ARCANE,
            ("new", DEFENCE): b"-- relocated\n" + ARCANE,
        }
        self.git_root = self.root / "source.git"
        subprocess.run(["git", "init", "--bare", "-q", str(self.git_root)], check=True)
        revisions = {side: self.commit(side) for side in rec.REVISIONS}
        self.metadata = {
            "schema": rec.SCHEMA,
            "source": {side + "_commit": revision for side, revision in revisions.items()},
            "files": {name: {"git_path": "src/" + name} for name in (PERFORM, DEFENCE)},
            "contexts": {},
            "entries": {},
            "full_context_unchanged": False,
            "guard_eligible": False,
            "semantics_verified": False,
        }
        for key, name, declaration in [
            ("misc", PERFORM, "local function doActorMisc(env, actor)"),
            ("pipeline", PERFORM, "function calcs.perform(env, skipEHP)"),
            ("arcane", DEFENCE, "function calcs.defence(env, actor)"),
        ]:
            self.metadata["contexts"][key] = {"file": name, "kind": "function", "declaration": declaration}
        self.refresh_pins()
        buffs = []
        for key, name, old_range, local in [
            ("Example", PERFORM, (6, 8), "misc"),
            ("ExampleArcane", DEFENCE, (2, 4), "arcane"),
        ]:
            spec = {"line_start": old_range[0], "line_end": old_range[1]}
            chunk = rec.segment(self.sources["old", name], spec)
            ref = {"file": name, **spec, "segment_hash": rec.reference_hash(chunk)}
            buffs.append({"id": key, "vendor_ref": ref, "verified": False})
            self.metadata["entries"][key] = {
                "file": name,
                "old": {k: v for k, v in ref.items() if k != "file"} | pin(chunk),
                "new": rec.windows(self.sources["new", name], chunk)[0]
                | pin(chunk)
                | {"segment_hash": rec.reference_hash(chunk)},
                "local_context": local,
                "context_dependencies": [local, "pipeline"],
            }
        self.definitions_raw = (
            json.dumps({"_meta": {"vendor_commit": revisions["old"]}, "buffs": buffs}) + "\n"
        ).encode()
        self.metadata["definitions"] = pin(self.definitions_raw)

    def git(self, *args, data=None):
        env = dict(
            os.environ,
            GIT_AUTHOR_NAME="Synthetic",
            GIT_AUTHOR_EMAIL="synthetic@example.invalid",
            GIT_COMMITTER_NAME="Synthetic",
            GIT_COMMITTER_EMAIL="synthetic@example.invalid",
            GIT_AUTHOR_DATE="2026-01-01T00:00:00Z",
            GIT_COMMITTER_DATE="2026-01-01T00:00:00Z",
        )
        return subprocess.check_output(["git", "-C", str(self.git_root), *args], input=data, env=env).strip().decode()

    def commit(self, side):
        # Bare object database only: no test checkout or source worktree needed.
        rows = []
        for name in (PERFORM, DEFENCE):
            oid = self.git("hash-object", "-w", "--stdin", data=self.sources[side, name])
            rows.append(f"100644 blob {oid}\t{Path(name).name}\n")
        modules = self.git("mktree", data="".join(rows).encode())
        src = self.git("mktree", data=f"040000 tree {modules}\tModules\n".encode())
        tree = self.git("mktree", data=f"040000 tree {src}\tsrc\n".encode())
        return self.git("commit-tree", tree, data=f"{side}\n".encode())

    def refresh_pins(self):
        for (side, name), raw in self.sources.items():
            self.metadata["files"][name][side] = pin(raw)
        for context in self.metadata["contexts"].values():
            for side in rec.REVISIONS:
                context[side] = function_spec(self.sources[side, context["file"]], context["declaration"])
            context["comparison"] = rec.comparison(
                *(rec.segment(self.sources[side, context["file"]], context[side]) for side in rec.REVISIONS)
            )

    def verify(self):
        return rec.verify(self.metadata, self.definitions_raw, self.sources)

    def files(self):
        metadata_path, definitions_path = self.root / "metadata.json", self.root / "definitions.json"
        raw = (json.dumps(self.metadata) + "\n").encode()
        metadata_path.write_bytes(raw)
        definitions_path.write_bytes(self.definitions_raw)
        return metadata_path, pin(raw)["sha256"], definitions_path, self.git_root

    def test_real_git_objects_preserve_local_and_global_results_separately(self):
        args = self.files()
        result = rec.check(*args)
        self.assertTrue(result["evidence_verified"])
        self.assertFalse(result["guard_eligible"])
        self.assertFalse(result["semantics_verified"])
        self.assertEqual([entry["window"] for entry in result["entries"]], ["unique-byte-identical"] * 2)
        self.assertEqual(result["contexts"]["misc"], "output-annotation-only")
        self.assertEqual(result["contexts"]["arcane"], "identical")
        self.assertEqual([entry["changed_contexts"] for entry in result["entries"]], [["pipeline"], ["pipeline"]])

    def test_cli_default_keeps_guard_closed_and_evidence_only_is_explicit(self):
        metadata_path, digest, definitions_path, git_root = self.files()
        args = [
            "--metadata",
            str(metadata_path),
            "--metadata-sha256",
            digest,
            "--defs",
            str(definitions_path),
            "--source-git",
            str(git_root),
        ]
        before = definitions_path.read_bytes()
        for extra, expected in [([], 2), (["--evidence-only"], 0)]:
            with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()):
                self.assertEqual(rec.main(args + extra), expected)
            self.assertFalse(json.loads(out.getvalue())["guard_eligible"])
        self.assertEqual(definitions_path.read_bytes(), before)

    def test_metadata_and_full_definition_bytes_are_authenticated(self):
        args = list(self.files())
        args[1] = "0" * 64
        with self.assertRaisesRegex(ValueError, "Metadata SHA"):
            rec.check(*args)
        self.definitions_raw += b" "
        with self.assertRaisesRegex(ValueError, "Byte pin"):
            self.verify()

    def test_changed_or_missing_source_does_not_fall_back_to_checkout(self):
        self.metadata["files"][PERFORM]["new"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "Byte pin"):
            rec.read_sources(self.git_root, self.metadata)
        self.metadata["source"]["old_commit"] = "HEAD"
        with self.assertRaisesRegex(ValueError, "Full Git commit"):
            rec.read_sources(self.git_root, self.metadata)
        self.metadata["source"]["old_commit"] = "0" * 40
        with redirect_stderr(io.StringIO()), self.assertRaises(subprocess.CalledProcessError):
            rec.read_sources(self.git_root, self.metadata)

    def test_changed_reference_rejected_even_with_updated_new_pins(self):
        self.sources["new", PERFORM] = self.sources["new", PERFORM].replace(b'"INC", 10', b'"INC", 11')
        self.refresh_pins()
        entry = self.metadata["entries"]["Example"]
        chunk = rec.segment(self.sources["new", PERFORM], entry["new"])
        entry["new"].update(pin(chunk), segment_hash=rec.reference_hash(chunk))
        with self.assertRaisesRegex(ValueError, "Changed reference window"):
            self.verify()

    def test_duplicate_target_window_rejected_even_outside_pinned_context(self):
        entry = self.metadata["entries"]["Example"]
        self.sources["new", PERFORM] += rec.segment(self.sources["old", PERFORM], entry["old"])
        self.refresh_pins()
        with self.assertRaisesRegex(ValueError, "ambiguous new window"):
            self.verify()

    def test_same_window_with_changed_outer_gate_cannot_claim_annotation_only(self):
        self.sources["new", PERFORM] = self.sources["new", PERFORM].replace(b"env.mode_combat", b"env.mode_effective")
        self.refresh_pins()
        self.metadata["contexts"]["misc"]["comparison"] = "output-annotation-only"
        with self.assertRaisesRegex(ValueError, "Context comparison mismatch: misc"):
            self.verify()
        self.metadata["contexts"]["misc"]["comparison"] = "changed"
        result = self.verify()
        self.assertFalse(result["guard_eligible"])
        self.assertIn("misc", result["entries"][0]["changed_contexts"])

    def test_wrong_ref_file_range_hash_context_and_id_inventory_rejected(self):
        original = deepcopy(self.metadata)
        mutations = [
            lambda m: m["entries"]["Example"].update(file=DEFENCE),
            lambda m: m["entries"]["Example"]["old"].update(line_start=5),
            lambda m: m["entries"]["Example"]["new"].update(segment_hash="fnv1a64:0000000000000000"),
            lambda m: m["entries"]["Example"].update(local_context="arcane"),
            lambda m: m["entries"].pop("ExampleArcane"),
            lambda m: m.update(guard_eligible=True),
            lambda m: m.update(full_context_unchanged=True),
            lambda m: m.update(semantics_verified=True),
        ]
        for mutation in mutations:
            self.metadata = deepcopy(original)
            mutation(self.metadata)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.verify()

    def test_truncated_function_context_is_rejected(self):
        context = self.metadata["contexts"]["misc"]
        context["new"]["line_end"] -= 1
        context["new"].update(pin(rec.segment(self.sources["new", PERFORM], context["new"])))
        with self.assertRaisesRegex(ValueError, "Incomplete context function"):
            self.verify()

    def test_legacy_hash_normalizes_newlines_but_crypto_pins_do_not(self):
        self.assertEqual(rec.fnv1a64(b"foobar"), "fnv1a64:85944171f73967e8")
        self.assertEqual(rec.reference_hash(b"one\r\ntwo\r\n"), rec.fnv1a64(b"one\ntwo"))
        self.assertNotEqual(pin(b"one\r\n"), pin(b"one\n"))
        for start, end in [(0, 1), (2, 1), (True, 1), (1, 9)]:
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                rec.segment(b"one\n", {"line_start": start, "line_end": end})

    def test_committed_metadata_keeps_exact_retained_boundary(self):
        metadata = json.loads((ROOT / "publication/retained-buff-source-reconciliation.v1.json").read_bytes())
        self.assertEqual(len(metadata["entries"]), 15)
        self.assertEqual(
            metadata["definitions"],
            {
                "bytes": 14694,
                "sha256": "0fd267716e0e4d1bee9dadf76c2a794b28f0941c1dd301b5c6b2ec3bf9009026",
            },
        )
        self.assertEqual(metadata["entries"]["ArcaneSurge"]["file"], DEFENCE)
        self.assertFalse(metadata["guard_eligible"])


if __name__ == "__main__":
    unittest.main()
