"""Small synthetic metadata regressions; no real archives, checkout or network.

The `origin` of artifact tests is a local bare repository."""

from copy import deepcopy
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from RePoE import publication_index as pub

ROOT = Path(__file__).resolve().parents[1]


class PublicationIndexTests(unittest.TestCase):
    def setUp(self):
        (ROOT / ".cache").mkdir(exist_ok=True)
        # Keep the tiny fixtures, including failures, for inspection.
        self.root = Path(tempfile.mkdtemp(prefix="publication-index-test-", dir=ROOT / ".cache"))
        self.repo = self.root / "metadata.git"
        self.git("init", "--bare", str(self.repo), outside=True)
        self.index = self.root / "publication/index.json"
        self.accepted = {"target": {"game": "poe2", "game_patch": "synthetic", "realm": "international"}, "inputs": {}}
        for n, role in enumerate(sorted(pub.ROLES), 1):
            self.accepted["inputs"][role] = {
                "repository": pub.OWNER,
                "revision": str(n) * 40,
                "publication": "published",
                "path": f"handoff/{role}.zip",
                **pub.pin(b"archive"),
                "manifest": pub.pin(b"manifest"),
                "expanded_bytes": 100,
                "original_identity": {"game_patch": None, "realm": None, "production_ready": False},
            }
        del self.accepted["inputs"]["display_source"]["publication"]
        self.accepted["inputs"]["source_verifier"] = {
            "schema": "pobr-source-verifier/v1",
            "repository": pub.OWNER,
            "revision": "a" * 40,
            "files": {
                "RePoE/__init__.py": pub.pin(b"init"),
                "RePoE/source_io.py": pub.pin(b"io"),
                "RePoE/source_rebinding.py": pub.pin(b"verifier"),
            },
        }
        self.locks = {
            "build": {
                "schema": "pobr-build-data-lock/v2",
                "target": self.accepted["target"],
                "packages": {"game": self.accepted["inputs"]["game"]},
                "crafting": self.accepted["inputs"]["crafting"],
                "test_fixtures": self.accepted["inputs"]["test_fixtures"],
                "snapshot_manifest": {"must_not_enter_owner_descriptor": True},
            },
            "ordinary": {
                "schema": "pobr-ordinary-input-lock/v2",
                "target": self.accepted["target"],
                "packages": {"repoe": self.accepted["inputs"]["ordinary"]},
                "source_verifier": self.accepted["inputs"]["source_verifier"],
            },
            "imports": {
                "schema": "pobr-data-import-lock/v1",
                "target": self.accepted["target"],
                "packages": {
                    "repoe": self.accepted["inputs"]["display_source"],
                    "translation": {"must_not_enter_owner_descriptor": True},
                },
            },
        }
        self.descriptor = pub.bootstrap(self.accepted, self.root / "bootstrap.json")

    def git(self, *args, data=None, outside=False):
        command = ["git"] + ([] if outside else ["-C", str(self.repo)]) + list(args)
        env = dict(
            os.environ,
            GIT_AUTHOR_NAME="Synthetic",
            GIT_AUTHOR_EMAIL="synthetic@example.invalid",
            GIT_COMMITTER_NAME="Synthetic",
            GIT_COMMITTER_EMAIL="synthetic@example.invalid",
            GIT_AUTHOR_DATE="2000-01-01T00:00:00Z",
            GIT_COMMITTER_DATE="2000-01-01T00:00:00Z",
        )
        return subprocess.check_output(command, input=data, env=env, stderr=subprocess.PIPE).decode().strip()

    def commit(self, value=None, *, raw=None, mode="100644"):
        value = self.descriptor if value is None else value
        raw = pub.encoded(value) if raw is None else raw
        path = f"publication/releases/poe2-international/{value['sequence']}.json"
        oid = self.git("hash-object", "-w", "--stdin", data=raw)
        kind = "blob"
        for name in reversed(path.split("/")):
            oid = self.git("mktree", "-z", data=f"{mode} {kind} {oid}\t{name}\0".encode())
            kind, mode = "tree", "040000"
        rev = self.git("commit-tree", oid, "-m", f"Synthetic sequence {value['sequence']}")
        return {"revision": rev, "path": path, **pub.pin(raw)}

    def register(self, value=None, accepted=None, **kwargs):
        head = self.commit(value)
        return pub.register(self.repo, head, self.index, accepted or self.accepted, **kwargs)

    def next_descriptor(self, head, previous=None, role="source_verifier"):
        value = deepcopy(previous or self.descriptor)
        value["sequence"] += 1
        value["previous"] = head
        value["components"][role]["input"]["revision"] = "b" * 40
        value["components"][role]["sequence"] += 1
        accepted = {"target": value["target"], "inputs": {r: c["input"] for r, c in value["components"].items()}}
        return value, accepted

    def lock_files(self):
        paths, hashes = {}, {}
        for name, value in self.locks.items():
            paths[name] = self.root / f"{name}.json"
            raw = pub.encoded(value)
            paths[name].write_bytes(raw)
            hashes[name] = pub.pin(raw)["sha256"]
        return paths, hashes

    def test_complete_bootstrap_and_registration_offline_preserves_original_forms(self):
        paths, hashes = self.lock_files()
        with patch.object(socket, "socket", side_effect=AssertionError("No network")):
            accepted = pub.load_accepted_inputs(paths["build"], paths["ordinary"], paths["imports"], sha256s=hashes)
            self.assertEqual(accepted, self.accepted)
            index = self.register(accepted=accepted)
            self.assertEqual(pub.validate_index(index, self.repo, accepted), self.descriptor)
        inputs = {r: c["input"] for r, c in self.descriptor["components"].items()}
        self.assertEqual(inputs, self.accepted["inputs"])
        self.assertNotIn("publication", inputs["display_source"])
        self.assertNotIn("publication", inputs["source_verifier"])
        self.assertIsNone(inputs["game"]["original_identity"]["realm"])
        self.assertNotIn("snapshot_manifest", self.descriptor)
        self.assertNotIn("translation", self.descriptor["components"])
        self.assertEqual(json.loads(self.index.read_bytes()), index)

    def test_every_missing_or_extra_role_and_old_v1_rejected_without_descriptor(self):
        for role in sorted(pub.ROLES):
            accepted = deepcopy(self.accepted)
            del accepted["inputs"][role]
            out = self.root / f"missing-{role}.json"
            with self.subTest(role=role), self.assertRaisesRegex(ValueError, "role"):
                pub.bootstrap(accepted, out)
            self.assertFalse(out.exists())
        value = deepcopy(self.descriptor)
        value["components"]["unexpected"] = value["components"]["game"]
        with self.assertRaisesRegex(ValueError, "role"):
            self.register(value)
        for schema in ["repoe-independent-data-handoffs/v1", "owned-data-publication/v1"]:
            value = deepcopy(self.descriptor)
            value["schema"] = schema
            with self.assertRaisesRegex(ValueError, "v2"):
                self.register(value)
        self.assertFalse(self.index.exists())

    def test_unpublished_missing_package_and_verifier_reclassification_rejected(self):
        for role in pub.ROLES - {"source_verifier"}:
            for state in ["local-only", "pending", False, None]:
                value = deepcopy(self.descriptor)
                value["components"][role]["input"]["publication"] = state
                with self.subTest(role=role, state=state), self.assertRaisesRegex(ValueError, "Unpublished"):
                    self.register(value)
        value = deepcopy(self.descriptor)
        del value["components"]["game"]["input"]["publication"]
        with self.assertRaisesRegex(ValueError, "Unpublished"):
            self.register(value)
        value = deepcopy(self.descriptor)
        value["components"]["source_verifier"]["input"]["publication"] = "published"
        with self.assertRaisesRegex(ValueError, "Git-files"):
            self.register(value)
        self.assertFalse(self.index.exists())

    def test_invalid_pins_paths_and_producer_hashes_rejected(self):
        for field, bad in [
            ("revision", "main"),
            ("revision", "a" * 39),
            ("revision", "0" * 40),
            ("bytes", -1),
            ("bytes", True),
            ("bytes", 1.0),
            ("sha256", "ab"),
            ("path", "../escape"),
            ("path", "a//b"),
            ("path", "a/./b"),
            ("path", "/absolute"),
            ("path", "a\\b"),
            ("path", "x:stream"),
            ("path", "."),
            ("path", "x\ny"),
        ]:
            value = deepcopy(self.descriptor)
            value["components"]["game"]["input"][field] = bad
            with self.subTest(field=field, bad=bad), self.assertRaises(ValueError):
                self.register(value)
        for change in [
            {"input_manifest": {"bytes": True, "sha256": "a" * 64}},
            {"producer": {"RePoE/producer.py": "bad"}},
            {"files": ["../bad"]},
        ]:
            value = deepcopy(self.descriptor)
            value["components"]["crafting"]["input"].update(change)
            with self.assertRaises(ValueError):
                self.register(value)
        self.assertFalse(self.index.exists())

    def test_duplicate_json_nonfinite_and_oversized_metadata_rejected(self):
        for raw in [
            b'{"schema":1,"schema":2}',
            b'{"nested":{"x":1,"x":2}}',
            b'{"value":NaN}',
            b'{"value":Infinity}',
            b'{"value":1e400}',
            b" " * (pub.LIMIT + 1),
        ]:
            with self.subTest(raw=raw[:70]), self.assertRaises(ValueError):
                self.register_raw(raw)
        self.assertFalse(self.index.exists())

    def register_raw(self, raw):
        return pub.register(self.repo, self.commit(raw=raw), self.index, self.accepted)

    def test_wrong_owner_target_scope_and_sequences_rejected(self):
        for field, bad in [
            ("owner", "other/repo"),
            ("sequence", 0),
            ("sequence", True),
            ("scope", {"complete": True}),
            ("target", {**self.accepted["target"], "realm": "global"}),
        ]:
            value = deepcopy(self.descriptor)
            value[field] = bad
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.register(value)
        value = deepcopy(self.descriptor)
        value["components"]["game"]["input"]["target"] = {**self.accepted["target"], "game_patch": "wrong"}
        with self.assertRaisesRegex(ValueError, "input target"):
            self.register(value)
        self.assertFalse(self.index.exists())

    def test_git_and_filesystem_symlinks_rejected(self):
        head = self.commit(raw=b"elsewhere", mode="120000")
        with self.assertRaisesRegex(ValueError, "symlink"):
            pub.register(self.repo, head, self.index, self.accepted)
        alias = self.root / "alias.json"
        alias.symlink_to(self.root / "bootstrap.json")
        with self.assertRaisesRegex(ValueError, "Symlink"):
            pub.read_metadata(alias)
        directory = self.root / "alias-dir"
        directory.symlink_to(self.root, target_is_directory=True)
        for destination in [alias, directory / "new.json"]:
            with self.assertRaisesRegex(ValueError, "Symlink"):
                pub.bootstrap(self.accepted, destination)
        head = self.commit()
        with self.assertRaisesRegex(ValueError, "Symlink"):
            pub.register(self.repo, head, alias, self.accepted)
        self.assertFalse(self.index.exists())

    def test_git_pin_missing_commit_and_path_fail_without_index(self):
        head = self.commit()
        for field, bad in [
            ("revision", "f" * 40),
            ("revision", "main"),
            ("bytes", head["bytes"] + 1),
            ("sha256", "0" * 64),
            ("path", "../bad"),
            ("path", "missing.json"),
        ]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                pub.register(self.repo, {**head, field: bad}, self.index, self.accepted)
        self.assertFalse(self.index.exists())

    def test_same_sequence_different_content_is_rejected_and_idempotent_retry_preserves_bytes(self):
        first = self.register()
        before = self.index.read_bytes()
        digest = pub.pin(before)["sha256"]
        pub.register(self.repo, first["head"], self.index, self.accepted, expected_index_sha256=digest)
        self.assertEqual(before, self.index.read_bytes())
        other = deepcopy(self.descriptor)
        other["components"]["game"]["input"]["revision"] = "f" * 40
        accepted = deepcopy(self.accepted)
        accepted["inputs"]["game"] = other["components"]["game"]["input"]
        with self.assertRaisesRegex(ValueError, "Same sequence"):
            self.register(other, accepted, expected_index_sha256=digest)
        self.assertEqual(before, self.index.read_bytes())

    def test_role_change_increments_only_changed_role_and_orphan_commits_are_valid(self):
        first = self.register()
        following, accepted = self.next_descriptor(first["head"])
        second = self.register(following, accepted, expected_index_sha256=pub.pin(self.index.read_bytes())["sha256"])
        self.assertEqual(second["sequence"], 2)
        pub.validate_index(second, self.repo, accepted)
        for role in pub.ROLES:
            self.assertEqual(following["components"][role]["sequence"], 2 if role == "source_verifier" else 1)

    def test_role_rollback_same_sequence_changed_input_and_unchanged_bump_rejected(self):
        first = self.register()
        before = self.index.read_bytes()
        digest = pub.pin(before)["sha256"]
        following, accepted = self.next_descriptor(first["head"])
        for role, sequence in [("source_verifier", 1), ("source_verifier", 3), ("game", 0), ("game", 2)]:
            bad = deepcopy(following)
            bad["components"][role]["sequence"] = sequence
            with self.subTest(role=role, sequence=sequence), self.assertRaises(ValueError):
                self.register(bad, accepted, expected_index_sha256=digest)
            self.assertEqual(before, self.index.read_bytes())
        no_change = deepcopy(self.descriptor)
        no_change.update(sequence=2, previous=first["head"])
        with self.assertRaisesRegex(ValueError, "No new role"):
            self.register(no_change, expected_index_sha256=digest)
        self.assertEqual(before, self.index.read_bytes())

    def test_new_explicit_accepted_patch_keeps_channel_and_requires_matching_target(self):
        first = self.register()
        following, accepted = self.next_descriptor(first["head"])
        following["target"] = {**following["target"], "game_patch": "synthetic-next"}
        before = self.index.read_bytes()
        digest = pub.pin(before)["sha256"]
        with self.assertRaisesRegex(ValueError, "accepted target"):
            self.register(following, accepted, expected_index_sha256=digest)
        self.assertEqual(before, self.index.read_bytes())
        accepted["target"] = following["target"]
        index = self.register(following, accepted, expected_index_sha256=digest)
        self.assertEqual(index["channel"], first["channel"])
        self.assertEqual(pub.validate_index(index, self.repo, accepted)["target"], following["target"])

    def test_missing_wrong_predecessor_gap_and_rollback_rejected(self):
        first = self.register()
        before = self.index.read_bytes()
        digest = pub.pin(before)["sha256"]
        following, accepted = self.next_descriptor(first["head"])
        for previous in [None, {**first["head"], "revision": "f" * 40}, {**first["head"], "sha256": "0" * 64}]:
            bad = deepcopy(following)
            bad["previous"] = previous
            with self.assertRaises(ValueError):
                self.register(bad, accepted, expected_index_sha256=digest)
            self.assertEqual(before, self.index.read_bytes())
        gap = deepcopy(following)
        gap["sequence"] = 3
        with self.assertRaisesRegex(ValueError, "sequence"):
            self.register(gap, accepted, expected_index_sha256=digest)
        self.register(following, accepted, expected_index_sha256=digest)
        second = self.index.read_bytes()
        with self.assertRaisesRegex(ValueError, "rollback"):
            self.register(expected_index_sha256=pub.pin(second)["sha256"])
        self.assertEqual(second, self.index.read_bytes())

    def test_new_sequence_requires_existing_index_and_exact_predecessor(self):
        head = self.commit()
        following, accepted = self.next_descriptor(head)
        with self.assertRaisesRegex(ValueError, "Missing predecessor index"):
            self.register(following, accepted)
        self.assertFalse(self.index.exists())
        self.register()
        before = self.index.read_bytes()
        alternative = self.commit(raw=pub.encoded(self.descriptor) + b"\n")
        following["previous"] = alternative
        with self.assertRaisesRegex(ValueError, "Wrong index predecessor"):
            self.register(following, accepted, expected_index_sha256=pub.pin(before)["sha256"])
        self.assertEqual(before, self.index.read_bytes())

    def test_compare_and_swap_lock_and_atomic_failure_leave_index_unchanged(self):
        first = self.register()
        before = self.index.read_bytes()
        following, accepted = self.next_descriptor(first["head"])
        for digest in [None, "0" * 64]:
            with self.assertRaisesRegex(ValueError, "compare-and-swap"):
                self.register(following, accepted, expected_index_sha256=digest)
        lock = self.index.with_name("index.json.lock")
        lock.write_bytes(b"other writer")
        with self.assertRaisesRegex(ValueError, "locked"):
            self.register(following, accepted, expected_index_sha256=pub.pin(before)["sha256"])
        self.assertEqual(lock.read_bytes(), b"other writer")
        lock.unlink()  # Release this test's own synthetic lock.
        with patch.object(pub.os, "replace", side_effect=OSError("synthetic write failure")):
            with self.assertRaises(OSError):
                self.register(following, accepted, expected_index_sha256=pub.pin(before)["sha256"])
        self.assertEqual(before, self.index.read_bytes())
        self.assertFalse(lock.exists())

    def test_bad_or_untrusted_acceptance_record_rejected_without_output(self):
        paths, hashes = self.lock_files()
        with self.assertRaisesRegex(ValueError, "SHA mismatch"):
            pub.load_accepted_inputs(
                paths["build"], paths["ordinary"], paths["imports"], sha256s={**hashes, "build": "0" * 64}
            )
        self.locks["build"]["schema"] = "pobr-build-data-lock/v1"
        paths, hashes = self.lock_files()
        with self.assertRaisesRegex(ValueError, "schema"):
            pub.load_accepted_inputs(paths["build"], paths["ordinary"], paths["imports"], sha256s=hashes)
        value = deepcopy(self.descriptor)
        value["components"]["display_source"]["input"]["revision"] = "f" * 40
        with self.assertRaisesRegex(ValueError, "completed accepted inputs"):
            self.register(value)
        with self.assertRaisesRegex(ValueError, "accepted record"):
            pub.register(self.repo, self.commit(), self.index, None)
        self.assertFalse(self.index.exists())

    def test_initial_atomic_write_failure_leaves_no_index_or_descriptor(self):
        with patch.object(pub.os, "replace", side_effect=OSError("synthetic first write failure")):
            with self.assertRaises(OSError):
                self.register()
        self.assertFalse(self.index.exists())
        out = self.root / "failed-descriptor.json"
        with patch.object(pub.os, "link", side_effect=OSError("synthetic descriptor failure")):
            with self.assertRaises(OSError):
                pub.bootstrap(self.accepted, out)
        self.assertFalse(out.exists())

    def test_bootstrap_create_race_does_not_overwrite_other_descriptor(self):
        out = self.root / "racing-descriptor.json"

        def racing_link(source, destination):
            destination.write_bytes(b"other writer")
            raise FileExistsError("synthetic create race")

        with patch.object(pub.os, "link", side_effect=racing_link):
            with self.assertRaises(FileExistsError):
                pub.bootstrap(self.accepted, out)
        self.assertEqual(out.read_bytes(), b"other writer")

    def test_index_fields_channel_sequence_and_duplicate_json_rejected(self):
        index = self.register()
        for field, bad in [
            ("schema", "v1"),
            ("channel", {"game": "poe2", "realm": "global"}),
            ("sequence", 2),
            ("sequence", True),
            ("head", None),
        ]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                pub.validate_index({**index, field: bad}, self.repo, self.accepted)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            pub.decode(b'{"head":null,"head":null}')

    def test_bootstrap_never_overwrites_existing_descriptor(self):
        out = self.root / "bootstrap.json"
        before = out.read_bytes()
        with self.assertRaisesRegex(ValueError, "exists"):
            pub.bootstrap(self.accepted, out)
        self.assertEqual(before, out.read_bytes())

    def origin(self):
        """A local bare `origin`, so tag listing runs without network."""
        origin = self.root / "origin.git"
        if not origin.exists():
            self.git("init", "--bare", str(origin), outside=True)
            self.git("remote", "add", "origin", str(origin))
        return origin

    def tree(self, files):
        """Nested Git trees for {path: raw}; returns the root tree oid."""
        nodes = {}
        for path, raw in files.items():
            *parents, name = path.split("/")
            node = nodes
            for part in parents:
                node = node.setdefault(part, {})
            node[name] = self.git("hash-object", "-w", "--stdin", data=raw)

        def write(node):
            entries = []
            for name, child in sorted(node.items()):
                if isinstance(child, dict):
                    entries.append(f"040000 tree {write(child)}\t{name}\0")
                else:
                    entries.append(f"100644 blob {child}\t{name}\0")
            return self.git("mktree", "-z", data="".join(entries).encode())

        return write(nodes)

    def artifact(self, name, *, tag=True, members=None):
        """Commit a handoff ZIP and return its complete role declaration."""
        # Compressible content keeps expanded_bytes above the archive size, as in real packages.
        data = b"0" * 4096
        manifest = pub.encoded({"schema": "synthetic/v1", "files": {"data.json": pub.pin(data)}})
        members = members or {"manifest.json": manifest, "data.json": data}
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            for member, raw in members.items():
                info = zipfile.ZipInfo(member, (2000, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, raw)
        raw = stream.getvalue()
        path = f"handoff/{name}/data.zip"
        rev = self.git("commit-tree", self.tree({path: raw}), "-m", f"Synthetic artifact {name}")
        if tag:
            self.origin()
            self.git("push", "-q", "origin", f"{rev}:refs/tags/handoff/{name}")
        return {
            "repository": pub.OWNER,
            "revision": rev,
            "publication": "published",
            "path": path,
            **pub.pin(raw),
            "manifest": pub.pin(members["manifest.json"]),
            "expanded_bytes": sum(len(body) for body in members.values()),
        }

    def changed(self, first, role, declaration):
        value = deepcopy(self.descriptor)
        value["sequence"], value["previous"] = 2, first["head"]
        value["components"][role] = {"sequence": 2, "input": declaration}
        return value

    def test_later_sequence_registers_from_verified_artifacts_without_accepted_records(self):
        first = self.register()
        digest = pub.pin(self.index.read_bytes())["sha256"]
        declaration = self.artifact("game-next")
        value = self.changed(first, "game", declaration)
        index = pub.register(self.repo, self.commit(value), self.index, expected_index_sha256=digest)
        self.assertEqual(index["sequence"], 2)
        self.assertEqual(pub.validate_index(index, self.repo)["components"]["game"]["input"], declaration)

    def test_artifact_verification_rejects_untagged_wrong_and_unreachable_inputs(self):
        first = self.register()
        before = self.index.read_bytes()
        digest = pub.pin(before)["sha256"]
        good = self.artifact("good")
        twice = self.artifact("twice")
        self.git("push", "-q", "origin", f"{twice['revision']}:refs/tags/handoff/twice-alias")
        bad_size = dict(good, expanded_bytes=good["expanded_bytes"] + 1)
        bad_manifest = dict(good, manifest=pub.pin(b"other manifest"))
        bad_bytes = dict(good, sha256="0" * 64)
        cases = [
            ("game", self.artifact("untagged", tag=False), "exactly one handoff"),
            ("game", twice, "exactly one handoff"),
            ("game", dict(good, revision="f" * 40), "exactly one handoff"),
            ("game", bad_size, "Expanded size"),
            ("game", bad_manifest, "manifest pin"),
            ("game", bad_bytes, "pin mismatch"),
        ]
        verifier = deepcopy(self.accepted["inputs"]["source_verifier"])
        verifier["revision"] = self.git("commit-tree", self.tree({"RePoE/x.py": b"x"}), "-m", "Off branch")
        verifier["files"] = {"RePoE/x.py": pub.pin(b"x")}
        cases.append(("source_verifier", verifier, "default branch"))
        for role, declaration, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                head = self.commit(self.changed(first, role, declaration))
                pub.register(self.repo, head, self.index, expected_index_sha256=digest)
            self.assertEqual(before, self.index.read_bytes())
        self.git("update-ref", pub.DEFAULT_BRANCH, verifier["revision"])
        head = self.commit(self.changed(first, "source_verifier", verifier))
        self.assertEqual(pub.register(self.repo, head, self.index, expected_index_sha256=digest)["sequence"], 2)

    def test_draft_inherits_unchanged_roles_and_its_output_registers(self):
        first = self.register()
        digest = pub.pin(self.index.read_bytes())["sha256"]
        declaration = self.artifact("draft-game")
        unchanged = self.descriptor["components"]["ordinary"]["input"]
        out = self.root / "publication/releases/poe2-international/2.json"
        value = pub.draft(self.repo, self.index, {"game": declaration, "ordinary": unchanged}, out)
        self.assertEqual(json.loads(out.read_bytes()), value)
        self.assertEqual(value["previous"], first["head"])
        self.assertEqual({r: c["sequence"] for r, c in value["components"].items() if c["sequence"] != 1}, {"game": 2})
        index = pub.register(self.repo, self.commit(value), self.index, expected_index_sha256=digest)
        self.assertEqual(index["sequence"], 2)
        for inputs, destination, message in [
            ({"unknown": declaration}, self.root / "publication/releases/poe2-international/3.json", "Unknown role"),
            ({"game": declaration}, self.root / "publication/releases/poe2-international/9.json", "No new role"),
            ({"game": self.artifact("third")}, self.root / "3.json", "releases/<game>-<realm>"),
            ({"game": self.artifact("fourth", tag=False)}, out.with_name("3.json"), "exactly one handoff"),
        ]:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                pub.draft(self.repo, self.index, inputs, destination)
            self.assertFalse(destination.exists())

    def test_sequence_one_still_requires_the_accepted_bootstrap_records(self):
        with self.assertRaisesRegex(ValueError, "accepted record"):
            pub.register(self.repo, self.commit(), self.index)
        self.assertFalse(self.index.exists())

    def test_current_bootstrap_has_exact_current_role_revisions(self):
        path = ROOT / "publication/releases/poe2-international/1.json"
        value = pub.validate_descriptor(pub.decode(pub.read_metadata(path)))
        self.assertEqual(value["target"], {"game": "poe2", "game_patch": "0.5.5.5", "realm": "international"})
        expected = {
            "game": "2c664da43c2cc850e98a4fdba0e875a0acd5c3b1",
            "crafting": "2c664da43c2cc850e98a4fdba0e875a0acd5c3b1",
            "ordinary": "aed5f7348f41dcff6abd526d882c6a95d8acce0b",
            "display_source": "61fe85cccfba2ec044007a152b5753f106bd83a4",
            "source_verifier": "a27c0a795728bb64d988519ccebe7faeacf9edf7",
            "test_fixtures": "dbd35717c0807e42e398093d72554ea91b149809",
        }
        self.assertEqual({r: c["input"]["revision"] for r, c in value["components"].items()}, expected)

    def test_history_migration_changes_locations_without_changing_artifact_pins(self):
        migration = json.loads((ROOT / "publication/history-rewrite-20261103.json").read_bytes())
        before = pub.decode(pub.read_metadata(ROOT / "publication/releases/poe2-international/1.json"))
        after = pub.validate_descriptor(
            pub.decode(pub.read_metadata(ROOT / "publication/releases/poe2-international/2.json"))
        )
        self.assertEqual(after["sequence"], before["sequence"] + 1)
        previous = after["previous"]
        # CI uses a shallow source checkout; historical Git reachability is
        # verified by the publication guard, not by this metadata regression.
        self.assertEqual(
            pub.pin(pub.read_metadata(ROOT / previous["path"])),
            {key: previous[key] for key in ("bytes", "sha256")},
        )
        changed = set()
        for role, old in before["components"].items():
            actual = after["components"][role]
            expected = deepcopy(old)
            revision = old["input"]["revision"]
            expected["input"]["revision"] = migration["commits"].get(revision, revision)
            if expected["input"] != old["input"]:
                expected["sequence"] += 1
                changed.add(role)
            self.assertEqual(actual, expected)
        self.assertEqual(changed, {"game", "crafting", "display_source", "source_verifier"})
        self.assertEqual(after["scope"], before["scope"])
        self.assertEqual(after["target"], before["target"])


if __name__ == "__main__":
    unittest.main()
