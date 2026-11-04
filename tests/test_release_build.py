"""Synthetic end-to-end tests for RePoE.release.build (no real packages or Rust adapter)."""

import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock
import zipfile

from RePoE.data_publication import encoded, pin
from RePoE.release import build

TARGET = {"game": "poe2", "game_patch": "9.9", "realm": "international"}
ORIGINAL = "a" * 64
REBOUND = "b" * 64
FAKE_ADAPTER = textwrap.dedent(
    """\
    import hashlib, json, sys
    from pathlib import Path
    args = sys.argv[1:]
    values = dict(zip(args[::2], args[1::2]))
    if values.get("--ordinary-domain") == "fail":
        sys.exit("synthetic failure")
    out = Path(values["--out"])
    out.mkdir()
    files = {}
    for flag, paired in (("--codec-source", "--codec-source-sha256"), ("--codec-policy", "--codec-policy-sha256")):
        if flag in values:
            raw = Path(values[flag]).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == values[paired], flag
    source = Path(values["--codec-source"]).read_bytes()
    extra = values.get("--ordinary-domain") == "extra"
    for name in ["overlay/a.json"] + (["overlay/unexpected.json"] if extra else []):
        (out / name).parent.mkdir(parents=True, exist_ok=True)
        (out / name).write_bytes(source)
        files[name] = {"bytes": len(source), "sha256": hashlib.sha256(source).hexdigest()}
    receipt = {"files": files, "adapter": {"implementation_revision": "sha256:test"}}
    (out / "producer-receipt.json").write_text(json.dumps(receipt))
    """
)


def runtime(value):
    return build.runtime_encoded(value)


def zip_bytes(members):
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "part.zip"
        build.write_zip(path, members)
        return path.read_bytes()


class ReleaseBuildTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "test")
        self.codec = runtime({"_meta": {"generator": "legacy"}, "value": 1})
        self.frozen = runtime({"_meta": {"generator": "manual"}, "rule": True})
        self.policy = runtime({"target": {"facts_manifest_sha256": ORIGINAL, "game_patch": "9.9"}})
        self.policies = self.root / "policies"
        self.policies.mkdir()
        (self.policies / "p.json").write_bytes(self.policy)
        self.adapter = self.root / "adapter"
        self.adapter.write_text(f"#!{sys.executable}\n{FAKE_ADAPTER}")
        self.adapter.chmod(0o755)
        self.facts = self.root / "facts"
        self.facts.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True).stdout

    def commit(self, files):
        for name, raw in files.items():
            (self.repo / name).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / name).write_bytes(raw)
        self.git("add", ".")
        self.git("commit", "-q", "-m", "handoff")
        return self.git("rev-parse", "HEAD").decode().strip()

    def package_spec(self, path, raw, revision):
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            manifest = archive.read("manifest.json")
            expanded = sum(info.file_size for info in archive.infolist())
        return {"revision": revision, "path": path, **pin(raw), "manifest": pin(manifest), "expanded_bytes": expanded}

    def fixture(self, published_a=None, frozen_pin=None, domain="copy", generated_frozen=False):
        """Commit an input and a reference package; write a release declaration."""
        inputs = {"codec/a.json": self.codec}
        inputs_raw = zip_bytes({**inputs, "manifest.json": encoded({"files": {k: pin(v) for k, v in inputs.items()}})})
        published_a = self.codec if published_a is None else published_a
        members = {"data/9.9/overlay/a.json": published_a, "data/9.9/overlay/frozen.json": self.frozen}
        snapshot = {
            "schema_version": 3,
            "poe_version": "9.9",
            "files": {
                "overlay/a.json": hashlib.sha256(published_a).hexdigest(),
                "overlay/frozen.json": hashlib.sha256(self.frozen).hexdigest(),
                "i18n/zh-CN/x.json": "c" * 64,
            },
        }
        members["data/9.9/manifest.json"] = runtime(snapshot)
        manifest = {
            "schema": build.PART_SCHEMA,
            "kind": "game",
            "target": TARGET,
            "history": "retained",
            "files": {k: pin(v) for k, v in sorted(members.items())},
        }
        previous_raw = zip_bytes({**members, "manifest.json": encoded(manifest)})
        revision = self.commit({"handoff/in/inputs.zip": inputs_raw, "handoff/prev/game.zip": previous_raw})
        self.previous_raw = previous_raw
        config = self.root / "config"
        config.mkdir(exist_ok=True)
        lock = {
            "schema": "repoe-release-inputs/v1",
            "target": TARGET,
            "packages": {
                "inputs": self.package_spec("handoff/in/inputs.zip", inputs_raw, revision),
                "previous": self.package_spec("handoff/prev/game.zip", previous_raw, revision),
            },
            "reference": "previous",
            "facts": {"package": "inputs", "identities": {"rebound": REBOUND, "original": ORIGINAL}},
        }
        jobs = [
            {
                "id": "a",
                "kind": "adapter",
                "domain": domain,
                "facts": "rebound",
                "options": {
                    "--codec-source": "inputs:codec/a.json",
                    "--codec-policy": {"policy": "policy:p.json", "rebind": ["target", "facts_manifest_sha256"]},
                },
                "outputs": {"overlay/a.json": "data/9.9/overlay/a.json"},
            },
            {
                "id": "snapshot",
                "kind": "snapshot-manifest",
                "template": "previous:data/9.9/manifest.json",
                "external": ["i18n/"],
                "member": "data/9.9/manifest.json",
            },
        ]
        domains = {
            "schema": "repoe-release-domains/v1",
            "target": TARGET,
            "manifest": {"mode": "retain-if-identical"},
            "jobs": jobs,
        }
        frozen_members = {
            "data/9.9/overlay/frozen.json": {
                **(frozen_pin or pin(self.frozen)),
                "category": "shared-overlay",
                "origin": "manual",
                "reason": "test",
                "exit": "test",
            }
        }
        if generated_frozen:
            declaration = frozen_members["data/9.9/overlay/frozen.json"]
            frozen_members["data/9.9/overlay/a.json"] = {**declaration, **pin(published_a)}
        frozen = {
            "schema": "repoe-release-frozen-inputs/v1",
            "target": TARGET,
            "source": "previous",
            "members": frozen_members,
        }
        for name, value in (("inputs.lock.json", lock), ("domains.json", domains), ("frozen-inputs.json", frozen)):
            (config / name).write_text(json.dumps(value, indent=2))
        return config

    def fake_facts(self, package, spec, cache):
        return {
            "handoff": pin(b"{}"),
            "archive": pin(b""),
            "roots": {
                "rebound": (self.facts, {"bytes": 1, "sha256": REBOUND}),
                "original": (self.facts, {"bytes": 1, "sha256": ORIGINAL}),
            },
        }

    def run_build(self, config, **kwargs):
        with mock.patch.object(build, "prepare_facts", self.fake_facts):
            return build.build(
                config,
                out=self.root / "out",
                adapter=self.adapter,
                cache=self.root / "cache",
                repo=self.repo,
                policies=self.policies,
                **kwargs,
            )

    def test_reproduces_reference_package(self):
        out, receipt = self.run_build(self.fixture())
        self.assertEqual(receipt["summary"], {"generated-identical": 2, "frozen": 1})
        self.assertEqual(receipt["manifest"]["class"], "retained-reference-manifest")
        self.assertTrue(receipt["package"]["identical_to_reference"])
        self.assertEqual((out / "game-build-part.zip").read_bytes(), self.previous_raw)
        self.assertEqual(json.loads((out / "receipt.json").read_bytes()), receipt)
        self.assertIn("inputs:codec/a.json", receipt["inputs"]["files"])
        self.assertEqual(receipt["jobs"]["snapshot"]["retained_external_pins"], {"i18n/zh-CN/x.json": "c" * 64})
        policy = out / "work" / "policies" / "a" / "p.json"
        self.assertEqual(json.loads(policy.read_bytes())["target"]["facts_manifest_sha256"], REBOUND)

    def test_differing_output_is_classified_and_gets_a_fresh_manifest(self):
        published = runtime({"_meta": {"generator": "old"}, "value": 0})
        out, receipt = self.run_build(self.fixture(published_a=published))
        member = receipt["members"]["data/9.9/overlay/a.json"]
        self.assertEqual(member["class"], "generated-different")
        self.assertEqual(member["reference"], pin(published))
        # The snapshot is re-pinned over the generated bytes, so it differs too.
        self.assertEqual(receipt["members"]["data/9.9/manifest.json"]["class"], "generated-different")
        self.assertEqual(receipt["manifest"]["class"], "fresh-manifest")
        self.assertFalse(receipt["package"]["identical_to_reference"])
        with zipfile.ZipFile(out / "game-build-part.zip") as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(archive.read("data/9.9/overlay/a.json"), self.codec)
        self.assertEqual(manifest["schema"], build.PART_SCHEMA)
        self.assertEqual(manifest["files"]["data/9.9/overlay/a.json"], pin(self.codec))

    def test_fresh_manifest_mode_overrides_retention(self):
        _, receipt = self.run_build(self.fixture(), manifest_mode="fresh")
        self.assertEqual(receipt["manifest"]["class"], "fresh-manifest")
        self.assertTrue(receipt["reference"]["members_identical"])
        self.assertFalse(receipt["package"]["identical_to_reference"])

    def test_frozen_pin_drift_rejects(self):
        config = self.fixture(frozen_pin={"bytes": 1, "sha256": "0" * 64})
        with self.assertRaisesRegex(ValueError, "Frozen bytes changed"):
            self.run_build(config)

    def test_member_cannot_be_generated_and_frozen(self):
        with self.assertRaisesRegex(ValueError, "both generated and frozen"):
            self.run_build(self.fixture(generated_frozen=True))

    def test_undeclared_adapter_output_rejects(self):
        with self.assertRaisesRegex(ValueError, "adapter outputs"):
            self.run_build(self.fixture(domain="extra"))

    def test_producer_failure_keeps_logs(self):
        with self.assertRaisesRegex(ValueError, "Producer failed"):
            self.run_build(self.fixture(domain="fail"))
        self.assertIn("synthetic failure", (self.root / "out/work/logs/a/stderr.txt").read_text())

    def test_policy_rebind_requires_original_identity(self):
        (self.policies / "p.json").write_bytes(runtime({"target": {"facts_manifest_sha256": "d" * 64}}))
        with self.assertRaisesRegex(ValueError, "not the original facts identity"):
            self.run_build(self.fixture())

    def test_missing_commit_requires_fetch(self):
        config = self.fixture()
        lock = json.loads((config / "inputs.lock.json").read_text())
        lock["packages"]["inputs"]["revision"] = "f" * 40
        (config / "inputs.lock.json").write_text(json.dumps(lock))
        with self.assertRaisesRegex(ValueError, "--fetch"):
            self.run_build(config)

    def test_refuses_to_replace_foreign_output(self):
        (self.root / "out").mkdir()
        (self.root / "out" / "keep.txt").write_text("x")
        with self.assertRaisesRegex(ValueError, "non-release directory"):
            self.run_build(self.fixture())
        self.assertTrue((self.root / "out" / "keep.txt").exists())

    def test_template_expansion(self):
        bindings = {"a.b": [1], "nested": {"c": 2}}
        value = {"x": {"$retained": "a.b"}, "y": [{"$retained": "nested.c"}], "z": 3}
        self.assertEqual(build.expand_template(value, bindings), {"x": [1], "y": [2], "z": 3})


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    unittest.main()
