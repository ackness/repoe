"""Source-preservation and offline publication contracts for selected CSD facts."""

import hashlib
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from RePoE import native_csd as csd
from RePoE import native_descriptions as producer


BASE = "Data/StatDescriptions/base.csd"
LOCAL = "Data/StatDescriptions/local.csd"


def raw(text):
    return b"\xff\xfe" + text.encode("utf-16-le")


def description(template="{0:+d}% to [Resistances|Fire Resistance]", language="Simplified Chinese"):
    return (
        "description local_name\r\n\t1 base_fire_damage_resistance_%\r\n\t2\r\n"
        f'\t\t1|# gem_quality "{template}" negate 1\r\n'
        '\t\t#|-1 table_only "Literal\\n{0:-d}%" divide_by_ten_1dp_if_required 1\r\n'
        f'\tlang "{language}"\r\n\t1\r\n\t\t# "火焰😀 {{0}}%"\r\n'
    )


class LexicalTests(unittest.TestCase):
    def test_unicode_spans_restrictions_languages_and_raw_formats(self):
        data = raw('\r\n"caption"\r\nno_identifiers\r\n' + description() + "\r\nno_description later earlier later\r\n")
        parsed = csd.parse_csd(LOCAL, data)
        offset = 2
        for record in parsed["records"]:
            self.assertEqual(record["span"]["byte_start"], offset)
            offset = record["span"]["byte_end"]
        self.assertEqual(offset, len(data))
        entry = next(r for r in parsed["records"] if r["kind"] == "description")
        span = entry["span"]
        self.assertEqual(
            entry["raw_slice_sha256"], hashlib.sha256(data[span["byte_start"] : span["byte_end"]]).hexdigest()
        )
        english, chinese = entry["groups"]
        self.assertIsNone(english["declared_language"])
        self.assertIsNone(english["language_declaration_span"])
        self.assertEqual(chinese["declared_language"], "Simplified Chinese")
        self.assertEqual(chinese["branches"][0]["template_raw"], "火焰😀 {0}%")
        branch = chinese["branches"][0]
        s = branch["span"]
        self.assertEqual(data[s["byte_start"] : s["byte_end"]].decode("utf-16-le"), '\t\t# "火焰😀 {0}%"\r\n')
        self.assertEqual(english["branches"][0]["restrictions_raw"], ["gem_quality"])
        self.assertEqual(english["branches"][1]["restrictions_raw"], ["table_only"])
        self.assertEqual(english["branches"][1]["template_raw"], "Literal\\n{0:-d}%")
        self.assertEqual(english["branches"][1]["placeholders"][0]["format_raw"], "-d")
        self.assertEqual(
            english["branches"][0]["quantifiers_lexical"], [{"name_raw": "negate", "argument_tokens_raw": ["1"]}]
        )
        self.assertEqual(parsed["records"][-1]["ids"], ["later", "earlier", "later"])

    def test_ordered_multi_stat_branches_duplicate_languages_and_empty_groups(self):
        text = 'description\n2 first second\n1\n# !0 table_only "{1:%} {0:+}"\nlang "Future language"\n0\nlang "Future language"\n1\n1|# # "same"\n'
        d = csd.parse_csd(BASE, raw(text))["records"][0]
        self.assertEqual(d["ids"], ["first", "second"])
        self.assertEqual([g["declared_branch_count"] for g in d["groups"]], [1, 0, 1])
        self.assertEqual([p["format_raw"] for p in d["groups"][0]["branches"][0]["placeholders"]], ["%", "+"])
        self.assertEqual(d["groups"][0]["branches"][0]["condition_tokens_raw"], ["#", "!0"])

    def test_parse_gaps_bad_counts_encoding_and_unsafe_includes_reject(self):
        for data in [
            b"plain ascii",
            b"\xff\xfe\x00",
            b"\xff\xfe\x00\xd8",
            raw("unknown_directive\n"),
            raw("description\n2 only_one\n0\n"),
            raw('description\n1 x\n2\n# "one"\n'),
            raw('description\n2 x y\n1\n# "wrong condition count"\n'),
            raw('include "../outside.csd"\n'),
            raw('description\n1 x\n1\n# "x" 1\n'),
        ]:
            with self.subTest(data=data), self.assertRaises((ValueError, UnicodeError)):
                csd.parse_csd(BASE, data)

    def test_unresolved_placeholder_tokens_are_retained_without_repairs(self):
        template = "native {0+d} {0%} -{0}}"
        entry = csd.parse_csd(BASE, raw(description(template)))["records"][0]
        branch = entry["groups"][0]["branches"][0]
        self.assertEqual(branch["template_raw"], template)
        self.assertEqual([p["token_raw"] for p in branch["placeholders"]], ["{0+d}", "{0%}", "{0}"])
        self.assertEqual(
            [p["syntax_status"] for p in branch["placeholders"]],
            ["unresolved-placeholder-syntax"] * 2 + ["recognized-lexical"],
        )
        self.assertEqual(
            [d["code"] for d in branch["template_syntax_diagnostics"]],
            ["unresolved_placeholder_syntax"] * 2 + ["unmatched_template_delimiter"],
        )

    def test_includes_preserve_occurrences_and_suppressions_without_applying_them(self):
        files = {
            BASE: csd.parse_csd(BASE, raw(description())),
            LOCAL: csd.parse_csd(
                LOCAL,
                raw(
                    f'include "{BASE}"\nno_description base_fire_damage_resistance_%\ninclude "{BASE}"\n'
                    + description()
                ),
            ),
        }
        occurrences = list(csd.iter_records(files, LOCAL))
        entries = [r for r in occurrences if r["fact"]["kind"] == "description"]
        self.assertEqual([r["path"] for r in entries], [BASE, BASE, LOCAL])
        self.assertEqual([len(r["include_chain"]) for r in entries], [1, 1, 0])
        self.assertNotEqual(entries[0]["include_chain"], entries[1]["include_chain"])
        for broken in [
            {LOCAL: files[LOCAL]},
            {BASE: csd.parse_csd(BASE, raw(f'include "{LOCAL}"\n')), LOCAL: files[LOCAL]},
        ]:
            with self.assertRaises(ValueError):
                list(csd.iter_records(broken, LOCAL))
        with self.assertRaises(ValueError):
            list(csd.iter_records(files, LOCAL, max_depth=0))


class CandidateTests(unittest.TestCase):
    def setUp(self):
        cache = producer.ROOT / ".cache"
        cache.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="description-test-", dir=cache)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.raw = self.root / "raw"
        self.resources = {
            BASE: raw(description()),
            LOCAL: raw(f'include "{BASE}"\n' + description("same stat local text")),
        }
        for name, data in self.resources.items():
            path = self.raw / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.lock = {
            "schema_version": 1,
            "sources": {
                "test": {
                    "kind": "official-client-resource-candidate",
                    "game": "poe2",
                    "game_patch": "test-patch",
                    "realm": "international",
                    "roots": [LOCAL],
                    "acquisition": {
                        "status": "unreviewed-acquisition-draft",
                        "evidence": [{"kind": "synthetic", "sha256": "0" * 64}],
                    },
                    "resources": {
                        name: {"bytes": len(data), "sha256": producer._sha(data)}
                        for name, data in self.resources.items()
                    },
                }
            },
        }
        self.lock_path = self.root / "source-lock.json"

    def args(self, out="candidate"):
        encoded = producer._json(self.lock)
        self.lock_path.write_bytes(encoded)
        return {
            "source_lock": self.lock_path,
            "source": "test",
            "raw": self.raw,
            "out": self.root / out,
            "expected_source_lock_sha256": producer._sha(encoded),
        }

    def test_offline_candidate_retains_source_and_all_original_bytes(self):
        args = self.args()
        before = {path: path.read_bytes() for path in self.raw.rglob("*.csd")}
        previous_imports = {name: module for name, module in sys.modules.items() if name.startswith("PyPoE")}
        with patch.object(socket, "socket", side_effect=AssertionError("unexpected network")):
            manifest = producer.create_candidate(**args)
        self.assertEqual(manifest["summary"]["descriptions"], 2)
        self.assertEqual(manifest["summary"]["branches"], 6)
        self.assertEqual(manifest["summary"]["explicit_languages"], ["Simplified Chinese"])
        self.assertFalse(manifest["production_ready"])
        self.assertEqual(manifest["source_identity"]["acquisition"]["status"], "unreviewed-acquisition-draft")
        for path, data in before.items():
            self.assertEqual(path.read_bytes(), data)
        for name, fp in manifest["files"].items():
            data = (args["out"] / name).read_bytes()
            self.assertEqual(fp, {"bytes": len(data), "sha256": producer._sha(data)})
        self.assertEqual((args["out"] / "source-lock.json").read_bytes(), self.lock_path.read_bytes())
        self.assertEqual(
            previous_imports, {name: module for name, module in sys.modules.items() if name.startswith("PyPoE")}
        )

    def test_external_pin_invalid_source_and_parse_failures_write_no_output(self):
        mutations = [
            lambda a: a.update(expected_source_lock_sha256="0" * 64),
            lambda a: self.lock_path.write_bytes(
                self.lock_path.read_bytes().replace(b'"schema_version":1', b'"schema_version":true')
            ),
            lambda a: (self.raw / BASE).write_bytes(raw(description() + "invalid\n")),
            lambda a: (self.raw / BASE).unlink(),
        ]
        for index, mutate in enumerate(mutations):
            for name, data in self.resources.items():
                (self.raw / name).write_bytes(data)
            args = self.args(f"bad-{index}")
            mutate(args)
            with self.assertRaises((ValueError, OSError)):
                producer.create_candidate(**args)
            self.assertFalse(args["out"].exists())
        encoded = producer._json(self.lock)
        self.lock_path.write_bytes(encoded.replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1'))
        args = self.args("duplicate")
        duplicate = encoded.replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1')
        self.lock_path.write_bytes(duplicate)
        args["expected_source_lock_sha256"] = producer._sha(duplicate)
        with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
            producer.create_candidate(**args)

    def test_unreachable_missing_and_cyclic_closure_reject_before_publication(self):
        for roots in [[BASE], [LOCAL, LOCAL]]:
            self.lock["sources"]["test"]["roots"] = roots
            with self.assertRaises(ValueError):
                producer.create_candidate(**self.args())
            self.assertFalse((self.root / "candidate").exists())
        self.lock["sources"]["test"]["roots"] = [LOCAL]
        del self.lock["sources"]["test"]["resources"][BASE]
        with self.assertRaisesRegex(ValueError, "Missing explicit CSD include"):
            producer.create_candidate(**self.args())

    def test_existing_outputs_symlinks_and_raw_aliases_are_preserved(self):
        args = self.args()
        args["out"].mkdir()
        sentinel = args["out"] / "keep"
        sentinel.write_bytes(b"unchanged")
        with self.assertRaises(FileExistsError):
            producer.create_candidate(**args)
        self.assertEqual(sentinel.read_bytes(), b"unchanged")
        alias = self.root / "alias"
        alias.symlink_to(self.raw, target_is_directory=True)
        for destination in [alias / "new", self.raw / "new", self.root / "dangling"]:
            if destination.name == "dangling":
                destination.symlink_to(self.root / "absent")
            args = self.args(str(destination))
            with self.assertRaises((ValueError, OSError)):
                producer.create_candidate(**args)
        self.assertFalse((self.raw / "new").exists())

    def test_new_process_exports_are_deterministic(self):
        args = self.args()
        commands = []
        for seed, name in [("3", "one"), ("99", "two")]:
            command = [
                sys.executable,
                "-B",
                "-m",
                "RePoE.native_descriptions",
                "--source-lock",
                str(self.lock_path),
                "--expected-source-lock-sha256",
                args["expected_source_lock_sha256"],
                "--source",
                "test",
                "--raw",
                str(self.raw),
                "--out",
                str(self.root / name),
            ]
            completed = subprocess.run(
                command, cwd=producer.ROOT, env={**os.environ, "PYTHONHASHSEED": seed}, text=True, capture_output=True
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            commands.append(completed.stdout)
        self.assertEqual(commands[0], commands[1])
        for name in ["descriptions.json", "diagnostics.json", "source-lock.json", "manifest.json"]:
            self.assertEqual((self.root / "one" / name).read_bytes(), (self.root / "two" / name).read_bytes())

    def test_parent_symlink_replacement_cannot_redirect_writes_into_raw(self):
        parent = self.root / "parent"
        parent.mkdir()
        moved = self.root / "parent-moved"
        original_mkdir = os.mkdir
        changed = False

        def replace_at_reservation(path, *args, **kwargs):
            nonlocal changed
            if path == "new" and not changed:
                changed = True
                parent.rename(moved)
                parent.symlink_to(self.raw, target_is_directory=True)
            return original_mkdir(path, *args, **kwargs)

        with patch.object(os, "mkdir", side_effect=replace_at_reservation):
            with self.assertRaisesRegex(ValueError, "namespace changed"):
                producer.create_candidate(**self.args("parent/new"))
        self.assertTrue(changed)
        self.assertFalse((self.raw / "new").exists())
        self.assertEqual(list((moved / "new").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
