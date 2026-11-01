"""Exercise offline publication, ownership boundaries and actual immutable Git blobs."""

import io
from pathlib import Path
import socket
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from RePoE import data_publication as pub


class PublicationTests(unittest.TestCase):
    def setUp(self):
        (pub.ROOT / ".cache").mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=pub.ROOT / ".cache")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = {"facts.json": b'{"value":0,"unknown":null}\r\n', "policy.json": b'{"rule":"owned-by-consumer"}'}
        self.source_manifest = pub.encoded({"files": {name: pub.pin(raw) for name, raw in self.data.items()}})
        self.archive = self.root / "source.zip"
        self.make_zip()
        self.spec = {
            "repository": "example/source",
            "revision": "1" * 40,
            "path": "fixed/data.zip",
            **pub.pin(self.archive.read_bytes()),
            "manifest": pub.pin(self.source_manifest),
            "expanded_bytes": sum(map(len, self.data.values())) + len(self.source_manifest),
        }
        self.plan = {
            "schema": "repoe-data-publication-plan/v1",
            "repository": "ackness/repoe",
            "target": {"game": "poe2", "game_patch": "synthetic", "realm": "international"},
            "path": "handoff/synthetic/data.zip",
            "ref": "refs/heads/handoff/synthetic",
            "sources": {"source": self.spec},
            "members": {"facts.json": self.member("facts.json")},
            "excluded": {"source": {"policy.json": "Consumer policy"}},
            "limits": ["Synthetic only"],
        }

    def member(self, name):
        return {
            "source": "source",
            "member": name,
            "kind": "native-facts",
            **pub.pin(self.data[name]),
            "observed_identity": {"game_patch": None, "realm": None},
            "note": "Synthetic fixture",
        }

    def make_zip(self, extra=None):
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("manifest.json", self.source_manifest)
            for name, raw in self.data.items():
                archive.writestr(name, raw)
            if extra:
                archive.writestr(*extra)

    def build(self, name="output", inputs=None):
        path = self.root / "plan.json"
        path.write_bytes(pub.encoded(self.plan))
        return pub.package(
            path, pub.pin(path.read_bytes())["sha256"], inputs or {"source": self.archive}, self.root / name
        )

    def test_exact_bytes_determinism_and_policy_exclusion_offline(self):
        with patch.object(socket, "socket", side_effect=AssertionError("No network allowed")):
            first = self.build()
            second = self.build("repeat")
        self.assertEqual(first, second)
        self.assertEqual((self.root / "output/data.zip").read_bytes(), (self.root / "repeat/data.zip").read_bytes())
        with zipfile.ZipFile(self.root / "output/data.zip") as archive:
            manifest_raw, manifest = pub.archive_manifest(archive, first)
            self.assertEqual(archive.read("facts.json"), self.data["facts.json"])
            self.assertNotIn("policy.json", archive.namelist())
            self.assertEqual(manifest["excluded"]["source"]["policy.json"], "Consumer policy")
            self.assertIsNone(manifest["members"]["facts.json"]["observed_identity"]["game_patch"])
            self.assertEqual(pub.pin(manifest_raw), first["manifest"])
        with self.assertRaises(ValueError):
            self.build()

    def test_source_pin_tamper_and_plan_digest_fail_without_output(self):
        self.archive.write_bytes(self.archive.read_bytes() + b"altered")
        with self.assertRaisesRegex(ValueError, "Source archive pin"):
            self.build()
        path = self.root / "plan.json"
        with self.assertRaisesRegex(ValueError, "Plan SHA"):
            pub.package(path, "0" * 64, {"source": self.archive}, self.root / "bad-plan")
        self.assertFalse((self.root / "output").exists())

    def test_incomplete_accounting_and_wrong_selected_pin_rejected(self):
        self.plan["excluded"]["source"].clear()
        with self.assertRaisesRegex(ValueError, "Unaccounted"):
            self.build()
        self.plan["excluded"]["source"]["policy.json"] = "Consumer policy"
        self.plan["members"]["facts.json"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "Selection pin"):
            self.build()

    def test_no_input_fallback(self):
        with self.assertRaisesRegex(ValueError, "Explicit source paths"):
            self.build(inputs={"other": self.archive})
        alias = self.root / "alias.zip"
        alias.symlink_to(self.archive)
        with self.assertRaisesRegex(ValueError, "Symlink"):
            self.build(inputs={"source": alias})

    def test_unsafe_duplicate_and_nonregular_zip_members_rejected(self):
        for name in [".", "../escape", "/absolute", "foo\\bar", "foo:stream", "a/./b", "a//b", "a\nb"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                pub.relative(name)
        info = zipfile.ZipInfo("link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.make_zip((info, b"facts.json"))
        with zipfile.ZipFile(self.archive) as archive, self.assertRaisesRegex(ValueError, "Non-regular"):
            pub.archive_manifest(archive, self.spec)
        with self.assertWarns(UserWarning):
            self.make_zip(("facts.json", b"duplicate"))
        with zipfile.ZipFile(self.archive) as archive, self.assertRaisesRegex(ValueError, "Duplicate"):
            pub.archive_manifest(archive, self.spec)

    def test_duplicate_json_and_invalid_expanded_size_rejected(self):
        with self.assertRaises(ValueError):
            pub.decode(b'{"files":{},"files":{}}')
        with self.assertRaises(ValueError):
            pub.decode(b'{"value":NaN}')
        self.spec["expanded_bytes"] += 1
        with self.assertRaisesRegex(ValueError, "Expanded size"):
            self.build()

    def test_selected_mapping_objects_preserve_values_without_policy(self):
        original = {
            "bindings": {"z": {"raw": [0, None, -1], "id": 3}, "a": {"z": 2, "a": 1}},
            "base": {"meta": {"patch": "old"}},
            "interpretation": "consumer-owned",
        }
        import json

        raw = (json.dumps(original, ensure_ascii=False, indent=2) + "\n").encode()
        fields = [["bindings"], ["base", "meta"]]
        result = pub.selected(raw, {"fields": fields})
        self.assertEqual(
            pub.decode(result), {"bindings": original["bindings"], "base": {"meta": original["base"]["meta"]}}
        )
        self.assertNotIn(b"interpretation", result)
        self.assertEqual(list(pub.decode(result)["bindings"]), ["z", "a"])
        self.assertEqual(list(pub.decode(result)["bindings"]["z"]), ["raw", "id"])
        self.data["policy.json"] = raw
        self.source_manifest = pub.encoded({"files": {n: pub.pin(v) for n, v in self.data.items()}})
        self.make_zip()
        self.spec.update(
            pub.pin(self.archive.read_bytes()),
            manifest=pub.pin(self.source_manifest),
            expanded_bytes=sum(map(len, self.data.values())) + len(self.source_manifest),
        )
        self.plan["members"]["mapping.json"] = {
            **self.member("policy.json"),
            "kind": "retained-compatibility",
            "fields": fields,
            "source_pin": pub.pin(raw),
            **pub.pin(result),
        }
        self.build()
        with zipfile.ZipFile(self.root / "output/data.zip") as archive:
            self.assertEqual(archive.read("mapping.json"), result)
            self.assertNotIn("policy.json", archive.namelist())

    def git_source(self):
        bare = self.root / "source.git"
        subprocess.run(["git", "init", "--bare", "--quiet", str(bare)], check=True)

        def git(*args, raw=None):
            return subprocess.check_output(["git", "--git-dir", str(bare), *args], input=raw).decode().strip()

        oid = git("hash-object", "-w", "--stdin", raw=self.data["facts.json"])
        tree = git("mktree", raw=f"100644 blob {oid}\tfacts.json\n".encode())
        root_tree = git("mktree", raw=f"040000 tree {tree}\tdata\n".encode())
        revision = git(
            "-c",
            "user.name=Synthetic",
            "-c",
            "user.email=synthetic@example.invalid",
            "commit-tree",
            root_tree,
            raw=b"Synthetic source\n",
        )
        self.plan["sources"]["source"] = {
            "type": "git-tree",
            "repository": "example/source",
            "revision": revision,
            "path": "data",
            "inventory_paths": ["data"],
            "files": {"facts.json": pub.pin(self.data["facts.json"])},
        }
        self.plan["excluded"]["source"] = {}
        return bare

    def test_immutable_git_source_and_game_part(self):
        bare = self.git_source()
        self.plan.update(output_schema="pobr-build-data-part/v1", kind="game")
        self.plan["members"] = {"data/synthetic/base/facts.json": self.member("facts.json")}
        result = self.build(inputs={"source": bare})
        with zipfile.ZipFile(self.root / "output/data.zip") as archive:
            _, manifest = pub.archive_manifest(archive, result)
            self.assertEqual((manifest["schema"], manifest["kind"]), ("pobr-build-data-part/v1", "game"))
        self.plan["members"] = {"data/synthetic/i18n/en/facts.json": self.member("facts.json")}
        with self.assertRaisesRegex(ValueError, "Invalid game"):
            self.build("invalid-language", inputs={"source": bare})

    def test_git_inventory_mismatch_rejected(self):
        bare = self.git_source()
        self.plan["sources"]["source"]["files"]["missing.json"] = pub.pin(b"missing")
        with self.assertRaisesRegex(ValueError, "Git inventory"):
            self.build(inputs={"source": bare})

    def test_actual_fresh_git_fetch_recovers_pinned_blob_without_sources(self):
        self.build()
        result = pub.git_handoff(self.root / "output")
        # Remove every original input, leaving only the independent artifact Git.
        self.archive.unlink()
        (self.root / "plan.json").unlink()
        fresh = self.root / "fresh.git"
        subprocess.run(["git", "init", "--bare", "--quiet", str(fresh)], check=True)
        subprocess.run(
            ["git", "--git-dir", str(fresh), "fetch", "--quiet", "--depth=1", result["bare"], result["revision"]],
            check=True,
        )
        raw = subprocess.check_output(
            ["git", "--git-dir", str(fresh), "cat-file", "blob", result["revision"] + ":" + result["path"]]
        )
        self.assertEqual(pub.pin(raw), {k: result[k] for k in ("bytes", "sha256")})
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertEqual(archive.read("facts.json"), self.data["facts.json"])
        with self.assertRaises(ValueError):
            pub.git_handoff(self.root / "output")


if __name__ == "__main__":
    unittest.main()
