"""Policy identities follow verified package members, never a supplied hash map."""

import contextlib
import copy
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from RePoE.client import export_receipt
from RePoE.release import build, inputs, policy_rebinding as rebinding
from RePoE.release.pins import decode, encoded, pin
from tests.client.test_export_receipt import candidate
from tests.release.test_inputs import receipted


class PolicyRebindingTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = self.root / "old"
        self.policies = self.root / "policies"
        self.cache = self.root / "cache"
        self.config.mkdir()
        self.old_target = {"game": "poe2", "game_patch": "0.5", "realm": "international"}
        self.new_target = {**self.old_target, "game_patch": "0.6"}
        self.old_files = self.files(self.old_target, b'"old descriptions"\n')
        self.new_files = self.files(self.new_target, b'"new descriptions and changed bytes"\n')
        self.old_stage = self.stage("old", self.old_files, self.old_target)
        self.new_stage = self.stage("new", self.new_files, self.new_target)
        entries = decode((self.old_stage / "lock.json").read_bytes())
        spec = entries["ordinary"]
        build.write_new(
            self.cache / "downloads" / spec["sha256"], (self.old_stage / "assets" / spec["asset"]).read_bytes()
        )
        self.lock = {
            "target": self.old_target,
            "packages": entries,
            "facts": {
                "package": "ordinary",
                "root": "facts",
                "identities": dict.fromkeys(
                    build.FACTS_IDENTITIES, pin(self.old_files["facts/manifest.json"])["sha256"]
                ),
            },
        }
        self.policy = {
            "version": "0.5",
            "target": {"game_patch": "0.5", "facts_manifest_sha256": self.lock["facts"]["identities"]["original"]},
            "descriptions_manifest_sha256": pin(self.old_files["text/manifest.json"])["sha256"],
            "payload": pin(self.old_files["text/descriptions.json"]),
            "player_manifest_sha256": pin(self.old_files["player/manifest.json"])["sha256"],
            "player": {"source_lock_sha256": pin(self.old_files["player/source-lock.json"])["sha256"]},
            "history": {"version": "0.5", "game_patch": "0.5", "evidence_sha256": "c" * 64},
            "statement": "Do not replace 0.5 or " + pin(self.old_files["text/descriptions.json"])["sha256"],
        }
        self.policy_path = self.policies / "text/0.5-policy.json"
        build.write_new(self.policy_path, encoded(self.policy))
        self.domains = {
            "target": self.old_target,
            "jobs": [
                {
                    "id": "text",
                    "kind": "adapter",
                    "facts": "original",
                    "options": {
                        "--codec-policy": "policy:text/0.5-policy.json",
                        "--item-descriptions": "ordinary:text/descriptions.json",
                        "--player-context": "ordinary:player",
                    },
                    "outputs": {"overlay/text.json": "data/0.5/overlay/text.json"},
                },
                {
                    "id": "template",
                    "kind": "adapter",
                    "facts": "rebound",
                    "options": {
                        "--codec-policy": {
                            "policy": "policy:text/0.5-policy.json",
                            "bindings": "ordinary:bindings.json",
                            "rebind": ["target", "facts_manifest_sha256"],
                            "expect": {"bytes": 1, "sha256": "d" * 64},
                        },
                        "--item-descriptions": "ordinary:text/descriptions.json",
                    },
                },
                {
                    "id": "snapshot",
                    "kind": "snapshot-manifest",
                    "member": "data/0.5/manifest.json",
                    "template": "previous:data/0.5/manifest.json",
                },
            ],
        }
        self.write_config()

    def files(self, target, payload):
        files = {"facts/value.json": encoded({"patch": target["game_patch"]}), "bindings.json": b"{}\n"}
        files["facts/manifest.json"] = candidate(
            "repoe-native-facts/v4",
            target,
            status="partial-candidate",
            production_ready=False,
            files={"value.json": pin(files["facts/value.json"])},
        )
        files["text/descriptions.json"] = payload
        files["player/source-lock.json"] = encoded({"target": target})
        for directory, format_ in (
            ("text", "repoe-native-descriptions/v1"),
            ("player", "repoe-native-player-context/v1"),
        ):
            files[directory + "/manifest.json"] = candidate(format_, target)
        return receipted(files)

    def stage(self, name, files, target):
        source = self.root / (name + "-source")
        for member, raw in files.items():
            build.write_new(source / member, raw)
        out = self.root / (name + "-stage")
        inputs.stage({"ordinary": source}, target, out, tag="inputs/" + target["game_patch"] + "-1")
        return out

    def write_config(self):
        (self.config / "inputs.lock.json").write_bytes(encoded(self.lock))
        (self.config / "domains.json").write_bytes(encoded(self.domains))

    def run_rebind(self, **kwargs):
        return rebinding.rebind(
            config=self.config,
            staged=self.new_stage,
            patch="0.6",
            domains_out=self.root / "new/domains.json",
            policies=self.policies,
            cache=self.cache,
            **kwargs,
        )

    def test_derives_manifests_payloads_byte_counts_and_template_expect_without_text_replacement(self):
        before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        reports = self.run_rebind()
        policy = decode((self.policies / "text/0.6-policy.json").read_bytes())
        self.assertEqual(policy["payload"], pin(self.new_files["text/descriptions.json"]))
        self.assertEqual(
            policy["target"]["facts_manifest_sha256"], pin(self.new_files["facts/manifest.json"])["sha256"]
        )
        for key, member in (
            ("descriptions_manifest_sha256", "text/manifest.json"),
            ("player_manifest_sha256", "player/manifest.json"),
        ):
            self.assertEqual(policy[key], pin(self.new_files[member])["sha256"])
        self.assertEqual(
            policy["player"]["source_lock_sha256"], pin(self.new_files["player/source-lock.json"])["sha256"]
        )
        self.assertEqual(policy["history"], self.policy["history"])
        self.assertEqual(policy["statement"], self.policy["statement"])
        changes = {tuple(item["path"]): item for item in reports["text/0.6-policy.json"]}
        self.assertEqual(changes[("payload", "sha256")]["members"], ["ordinary:text/descriptions.json"])
        self.assertEqual(changes[("payload", "sha256")]["old"], self.policy["payload"]["sha256"])
        self.assertEqual(changes[("payload", "sha256")]["new"], policy["payload"]["sha256"])
        self.assertIn(("payload", "bytes"), changes)
        domains = decode((self.root / "new/domains.json").read_bytes())
        self.assertEqual(domains["target"], self.new_target)
        self.assertEqual(domains["jobs"][0]["outputs"]["overlay/text.json"], "data/0.6/overlay/text.json")
        spec = domains["jobs"][1]["options"]["--codec-policy"]
        self.assertEqual(spec["expect"], pin(build.runtime_encoded(policy)))
        self.assertEqual(domains["jobs"][2]["template"], "previous:data/0.5/manifest.json")
        self.assertEqual(domains["jobs"][2]["member"], "data/0.6/manifest.json")
        for path, raw in before.items():
            self.assertEqual(path.read_bytes(), raw, path)
        # Old published inputs have no export receipts; new members need no old counterpart.
        old = {
            "ordinary": SimpleNamespace(
                members={n: pin(r) for n, r in self.old_files.items() if not n.endswith(export_receipt.SUFFIX)}
            )
        }
        new = rebinding.staged_packages(self.new_stage, {"ordinary"}, self.cache, build.ROOT)
        self.assertEqual(
            build.export_commits(new),
            {f"ordinary:{directory}.export-receipt.json": "c" * 40 for directory in ("facts", "player", "text")},
        )
        identities = rebinding.Identities(old, new, {"roots": {}}, {"roots": {}})
        rebound, _ = rebinding.rebind_document(self.policy, identities, "0.5", "0.6", "policy:text/0.5-policy.json")
        self.assertEqual(rebound, policy)

    def test_cli_lists_field_paths_and_changed_payload_members(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            rebinding.main(
                [
                    "--config",
                    str(self.config),
                    "--staged",
                    str(self.new_stage),
                    "--patch",
                    "0.6",
                    "--domains-out",
                    str(self.root / "new/domains.json"),
                    "--policies",
                    str(self.policies),
                    "--cache",
                    str(self.cache),
                ]
            )
        text = output.getvalue()
        self.assertIn("policy:text/0.6-policy.json", text)
        self.assertIn(
            "/payload/sha256: "
            + self.policy["payload"]["sha256"]
            + " -> "
            + pin(self.new_files["text/descriptions.json"])["sha256"],
            text,
        )
        self.assertIn("[ordinary:text/descriptions.json]", text)

    def test_tree_context_evidence_and_review_markers_survive_real_rebinding(self):
        old_payload = pin(self.old_files["text/descriptions.json"])["sha256"]
        old_manifest = self.lock["facts"]["identities"]["original"]
        self.policy.update(
            schema="pobr-ordinary-target-tree-policy/v4",
            base_policy={"target": copy.deepcopy(self.policy["target"])},
            context_baseline={
                "sha256": old_payload,
                "review": "reviewed",
                "reason": "Keep this explicitly selected old table identity",
            },
            context_columns={
                "bound_fields_sha256": old_manifest,
                "target_fields_sha256": pin(self.old_files["text/manifest.json"])["sha256"],
                "review": "reviewed",
                "reason": "Historical field change decision",
                "added": [
                    {
                        "field": "Opaque",
                        "neutral_value": old_payload,
                        "review": "unreviewed",
                        "reason": "",
                    }
                ],
                "removed": [],
            },
        )
        self.policy_path.write_bytes(encoded(self.policy))
        before = copy.deepcopy(self.policy)
        reports = self.run_rebind()
        policy = decode((self.policies / "text/0.6-policy.json").read_bytes())
        for key in ("context_baseline", "context_columns"):
            self.assertEqual(policy[key], before[key])
        self.assertNotEqual(old_payload, pin(self.new_files["text/descriptions.json"])["sha256"])
        self.assertNotEqual(old_manifest, pin(self.new_files["facts/manifest.json"])["sha256"])
        self.assertEqual(policy["payload"], pin(self.new_files["text/descriptions.json"]))
        self.assertEqual(policy["descriptions_manifest_sha256"], pin(self.new_files["text/manifest.json"])["sha256"])
        for target in (policy["target"], policy["base_policy"]["target"]):
            self.assertEqual(target["game_patch"], "0.6")
            self.assertEqual(target["facts_manifest_sha256"], pin(self.new_files["facts/manifest.json"])["sha256"])
        self.assertFalse(
            any(item["path"][0] in {"context_baseline", "context_columns"} for item in reports["text/0.6-policy.json"])
        )
        self.assertEqual(decode(self.policy_path.read_bytes()), before)

    def test_context_preservation_is_scoped_to_root_tree_policy_metadata(self):
        old_pin, new_pin = pin(b"old"), pin(b"new target")
        identities = rebinding.Identities(
            {"ordinary": SimpleNamespace(members={"table.json": old_pin})},
            {"ordinary": SimpleNamespace(members={"table.json": new_pin})},
            {"roots": {}},
            {"roots": {}},
        )
        for schema in (
            None,
            "pobr-ordinary-text-policy/v1",
            *(f"pobr-ordinary-target-tree-policy/v{version}" for version in range(1, 5)),
        ):
            with self.subTest(schema=schema):
                document = {
                    "schema": schema,
                    "context_baseline": {**old_pin, "review": "unreviewed", "reason": ""},
                    "context_columns": {"bound_fields_sha256": old_pin["sha256"], "review": "unreviewed"},
                    "elsewhere": {"context_baseline": old_pin, "context_columns": old_pin},
                    "source_sha256": old_pin["sha256"],
                }
                rebound, _ = rebinding.rebind_document(document, identities, "0.5", "0.6", "policy:fixture")
                is_tree = schema and schema.startswith("pobr-ordinary-target-tree-policy/")
                self.assertEqual(
                    rebound["context_baseline"]["sha256"], old_pin["sha256"] if is_tree else new_pin["sha256"]
                )
                self.assertEqual(
                    rebound["context_baseline"]["bytes"], old_pin["bytes"] if is_tree else new_pin["bytes"]
                )
                self.assertEqual(
                    rebound["context_columns"]["bound_fields_sha256"],
                    old_pin["sha256"] if is_tree else new_pin["sha256"],
                )
                self.assertEqual(rebound["context_baseline"]["review"], "unreviewed")
                self.assertEqual(rebound["elsewhere"], {"context_baseline": new_pin, "context_columns": new_pin})
                self.assertEqual(rebound["source_sha256"], new_pin["sha256"])
                document["source_sha256"] = "malformed"
                with self.assertRaisesRegex(ValueError, "unknown-identity"):
                    rebinding.rebind_document(document, identities, "0.5", "0.6", "policy:fixture")

    def test_missing_payload_unknown_manifest_and_wrong_target_refuse_before_writing(self):
        for case in ("missing", "unknown", "target"):
            with self.subTest(case=case):
                files = dict(self.new_files)
                if case == "missing":
                    del files["text/descriptions.json"]
                self.new_stage = self.stage(case, files, self.new_target)
                policy = copy.deepcopy(self.policy)
                if case == "unknown":
                    policy["player_manifest_sha256"] = "f" * 64
                self.policy_path.write_bytes(encoded(policy))
                if case == "target":
                    self.new_target["realm"] = "china"
                    self.new_stage = self.stage("china", self.files(self.new_target, b"[]"), self.new_target)
                with self.assertRaisesRegex(
                    ValueError,
                    {"missing": "missing-counterpart", "unknown": "unknown-identity", "target": "target-mismatch"}[
                        case
                    ],
                ):
                    self.run_rebind()
                self.assertFalse((self.policies / "text/0.6-policy.json").exists())
                self.assertFalse((self.root / "new/domains.json").exists())

    def test_existing_output_refuses_without_overwriting_or_creating_other_outputs(self):
        for output in (self.policies / "text/0.6-policy.json", self.root / "new/domains.json"):
            with self.subTest(output=output):
                build.write_new(output, b"keep these bytes")
                with self.assertRaisesRegex(ValueError, "existing-output"):
                    self.run_rebind()
                self.assertEqual(output.read_bytes(), b"keep these bytes")
                other = (
                    self.root / "new/domains.json"
                    if output.parent == self.policies / "text"
                    else self.policies / "text/0.6-policy.json"
                )
                self.assertFalse(other.exists())
                output.unlink()

    def test_duplicate_old_payload_refuses_divergence_or_removal_across_members_and_packages(self):
        for packages in (False, True):
            for missing in (False, True):
                with self.subTest(packages=packages, missing=missing):
                    old = {"ordinary": SimpleNamespace(members={"a.json": pin(b"same")})}
                    other = "other" if packages else "ordinary"
                    member = "a.json" if packages else "b.json"
                    old.setdefault(other, SimpleNamespace(members={})).members[member] = pin(b"same")
                    new = {"ordinary": SimpleNamespace(members={"a.json": pin(b"one")})}
                    new.setdefault(other, SimpleNamespace(members={}))
                    if not missing:
                        new[other].members[member] = pin(b"two")
                    identities = rebinding.Identities(old, new, {"roots": {}}, {"roots": {}})
                    with self.assertRaisesRegex(
                        ValueError, "missing-counterpart" if missing else "ambiguous-counterpart"
                    ):
                        rebinding.rebind_document(
                            {"source_sha256": pin(b"same")["sha256"], "descriptions_sha256": pin(b"same")["sha256"]},
                            identities,
                            "0.5",
                            "0.6",
                            "policy:pin",
                        )

    def test_job_reference_cannot_hide_a_renamed_member_with_the_same_old_payload(self):
        self.old_files["other/descriptions.json"] = self.old_files["text/descriptions.json"]
        stage = self.stage("duplicate-old", self.old_files, self.old_target)
        entries = decode((stage / "lock.json").read_bytes())
        spec = entries["ordinary"]
        build.write_new(self.cache / "downloads" / spec["sha256"], (stage / "assets" / spec["asset"]).read_bytes())
        self.lock["packages"] = entries
        self.write_config()
        self.new_files["renamed/descriptions.json"] = self.new_files["text/descriptions.json"]
        self.new_stage = self.stage("renamed", self.new_files, self.new_target)
        with self.assertRaisesRegex(ValueError, "missing-counterpart.*ordinary:other/descriptions.json"):
            self.run_rebind()
        self.assertFalse((self.policies / "text/0.6-policy.json").exists())
        self.assertFalse((self.root / "new/domains.json").exists())

    def test_identical_counterparts_are_safe_and_report_all_package_members(self):
        old = {name: SimpleNamespace(members={"a.json": pin(b"same")}) for name in ("ordinary", "other")}
        new = {name: SimpleNamespace(members={"a.json": pin(b"one")}) for name in old}
        identities = rebinding.Identities(old, new, {"roots": {}}, {"roots": {}})
        after, members = identities.counterpart(pin(b"same")["sha256"], "policy:pin")
        self.assertEqual(after, pin(b"one"))
        self.assertEqual(members, ["ordinary:a.json", "other:a.json"])

    def test_facts_manifest_cannot_override_a_different_payload_counterpart(self):
        before = pin(self.old_files["facts/manifest.json"])
        old = {"ordinary": SimpleNamespace(members={"payload.json": before})}
        new = {"ordinary": SimpleNamespace(members={"payload.json": pin(b"different")})}
        old_root = self.root / "old-source/facts"
        new_root = self.root / "new-source/facts"
        identities = rebinding.Identities(
            old,
            new,
            {"roots": {"original": (old_root, before)}},
            {"roots": {"original": (new_root, pin(self.new_files["facts/manifest.json"]))}},
        )
        with self.assertRaisesRegex(ValueError, "ambiguous-counterpart"):
            identities.counterpart(before["sha256"], "policy:payload")

    def test_malformed_identity_refuses_instead_of_retaining_a_stale_pin(self):
        for key in ("player_manifest_sha256", "source_lock_sha256"):
            for value in ("invalid", "f" * 64):
                with self.subTest(key=key, value=value):
                    policy = copy.deepcopy(self.policy)
                    parent = policy if key == "player_manifest_sha256" else policy["player"]
                    parent[key] = value
                    self.policy_path.write_bytes(encoded(policy))
                    with self.assertRaisesRegex(ValueError, "unknown-identity.*" + key):
                        self.run_rebind()
                    self.assertFalse((self.root / "new/domains.json").exists())

    def test_unknown_direct_payload_pin_and_corrupt_staged_asset_refuse(self):
        self.policy["descriptions_sha256"] = "f" * 64
        self.policy_path.write_bytes(encoded(self.policy))
        with self.assertRaisesRegex(ValueError, "unknown-identity.*descriptions_sha256"):
            self.run_rebind()
        asset = next((self.new_stage / "assets").glob("*.zip"))
        asset.write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "Byte pin mismatch"):
            self.run_rebind()
        self.assertFalse((self.root / "new/domains.json").exists())

    def test_cli_missing_counterpart_is_named_nonzero_and_leaves_no_outputs(self):
        files = dict(self.new_files)
        del files["text/descriptions.json"]
        stage = self.stage("missing-cli", files, self.new_target)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as error:
            rebinding.main(
                [
                    "--config",
                    str(self.config),
                    "--staged",
                    str(stage),
                    "--patch",
                    "0.6",
                    "--domains-out",
                    str(self.root / "new/domains.json"),
                    "--policies",
                    str(self.policies),
                    "--cache",
                    str(self.cache),
                ]
            )
        self.assertEqual(error.exception.code, 1)
        self.assertIn("policy-rebind: missing-counterpart:", stderr.getvalue())
        self.assertIn("ordinary:text/descriptions.json", stderr.getvalue())
        self.assertFalse((self.root / "new/domains.json").exists())

    def test_write_failure_rolls_back_only_new_outputs(self):
        original = rebinding.source_io.write_new
        output = self.root / "new/domains.json"

        def fail(path, raw):
            if path == output:
                raise OSError("synthetic disk failure")
            return original(path, raw)

        with (
            mock.patch.object(rebinding.source_io, "write_new", fail),
            self.assertRaisesRegex(OSError, "synthetic disk failure"),
        ):
            self.run_rebind()
        self.assertFalse((self.policies / "text/0.6-policy.json").exists())
        self.assertFalse(output.exists())
        self.assertEqual(decode(self.policy_path.read_bytes()), self.policy)

    def test_symlinks_and_exclusive_create_race_preserve_existing_files(self):
        output = self.root / "new/domains.json"
        output.parent.mkdir()
        existing = self.root / "existing.json"
        existing.write_bytes(b"keep existing")
        output.symlink_to(existing)
        with self.assertRaisesRegex(ValueError, "Symlink"):
            self.run_rebind()
        output.unlink()
        output.parent.rmdir()
        output.parent.symlink_to(self.root / "old", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "Symlink"):
            self.run_rebind()
        output.parent.unlink()
        original = rebinding.source_io.write_new

        def race(path, raw):
            if path == output:
                path.parent.mkdir()
                path.write_bytes(b"concurrent file")
            return original(path, raw)

        with mock.patch.object(rebinding.source_io, "write_new", race), self.assertRaises(FileExistsError):
            self.run_rebind()
        self.assertEqual(output.read_bytes(), b"concurrent file")
        self.assertEqual(existing.read_bytes(), b"keep existing")
        self.assertFalse((self.policies / "text/0.6-policy.json").exists())

    def test_parent_symlink_created_after_preflight_cannot_redirect_outputs_into_an_input(self):
        output = self.root / "new/domains.json"
        original = Path.mkdir

        def redirect(path, *args, **kwargs):
            original(path, *args, **kwargs)
            if path == output.parent:
                path.rmdir()
                path.symlink_to(self.config, target_is_directory=True)

        before = (self.config / "domains.json").read_bytes()
        with mock.patch.object(Path, "mkdir", redirect), self.assertRaisesRegex(ValueError, "Symlink"):
            self.run_rebind()
        self.assertEqual((self.config / "domains.json").read_bytes(), before)
        self.assertFalse((self.policies / "text/0.6-policy.json").exists())


if __name__ == "__main__":
    unittest.main()
