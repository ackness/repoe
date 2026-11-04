"""Synthetic end-to-end tests for RePoE.release.build (no real packages or Rust adapter)."""

import ast
import hashlib
import io
import json
import os
from pathlib import Path
import re
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
    domain = values.get("--ordinary-domain")
    source = Path(values["--codec-source"]).read_bytes()
    if domain not in ("copy", "restamp"):
        # A derived output: the value is computed from the input.
        document = json.loads(source)
        document = {"_meta": {"generator": "adapter"}, "value": document["value"] + 1}
        source = (json.dumps(document, indent=2) + "\\n").encode()
    elif domain == "restamp":
        document = json.loads(source)
        document["_meta"] = {"generator": "restamped"}
        source = (json.dumps(document, indent=2) + "\\n").encode()
    extra = domain == "extra"
    for name in ["overlay/a.json"] + (["overlay/unexpected.json"] if extra else []):
        (out / name).parent.mkdir(parents=True, exist_ok=True)
        (out / name).write_bytes(source)
        files[name] = {"bytes": len(source), "sha256": hashlib.sha256(source).hexdigest()}
    receipt = {
        "files": files,
        "adapter": {"implementation_revision": "sha256:test"},
        "input": {"root": str(Path(values["--ordinary-facts"]).resolve()), "manifest_sha256": "m"},
    }
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


def receipt_raw(out):
    return (out / "receipt.json").read_bytes()


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
        self.derived = runtime({"_meta": {"generator": "adapter"}, "value": 2})
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

    def fixture(
        self,
        published_a=None,
        frozen_pin=None,
        domain="derive",
        generated_frozen=False,
        passthrough=None,
        snapshot_passthrough=True,
    ):
        """Commit an input and a reference package; write a release declaration."""
        inputs = {"codec/a.json": self.codec}
        inputs_raw = zip_bytes({**inputs, "manifest.json": encoded({"files": {k: pin(v) for k, v in inputs.items()}})})
        published_a = self.derived if published_a is None else published_a
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
                **({"passthrough": passthrough} if passthrough else {}),
            },
            {
                "id": "snapshot",
                "kind": "snapshot-manifest",
                "template": "previous:data/9.9/manifest.json",
                "external": ["i18n/"],
                "member": "data/9.9/manifest.json",
                **({"passthrough": "template fields"} if snapshot_passthrough else {}),
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
            "categories": {"shared-overlay": "test"},
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
        out, receipt, outcome = self.run_build(self.fixture())
        self.assertEqual(receipt["summary"], {"generated-identical": 1, "passthrough-identical": 1, "frozen": 1})
        self.assertEqual(receipt["provenance"], {"generated": 1, "passthrough": 1, "frozen": 1})
        self.assertEqual(
            receipt["jobs"]["snapshot"]["passthrough"]["data/9.9/manifest.json"],
            {
                "input": "previous:data/9.9/manifest.json",
                "carried": "template",
                "fields": ["schema_version"],
                "retained_pins": 1,
                "regenerated_pins": 2,
            },
        )
        self.assertEqual(outcome["manifest"]["class"], "retained-reference-manifest")
        self.assertTrue(outcome["package"]["identical_to_reference"])
        self.assertEqual((out / "game-build-part.zip").read_bytes(), self.previous_raw)
        self.assertEqual(json.loads((out / "receipt.json").read_bytes()), receipt)
        self.assertEqual(json.loads((out / "package.json").read_bytes()), outcome)
        self.assertEqual(outcome["receipt"], {"path": "receipt.json", **build.file_pin(out / "receipt.json")})
        self.assertEqual(outcome["package"]["sha256"], build.file_pin(out / "game-build-part.zip")["sha256"])
        self.assertIn("inputs:codec/a.json", receipt["inputs"]["files"])
        self.assertEqual(receipt["jobs"]["snapshot"]["retained_external_pins"], {"i18n/zh-CN/x.json": "c" * 64})
        # The adapter's absolute facts root is replaced by the facts identity in the pinned copy.
        self.assertIn(str(self.facts.resolve()), (out / "work/jobs/a/producer-receipt.json").read_text())
        portable = receipt["jobs"]["a"]["receipt"]
        self.assertEqual(portable["path"], "work/receipts/a.json")
        self.assertEqual(build.file_pin(out / portable["path"]), {k: portable[k] for k in ("bytes", "sha256")})
        self.assertEqual(json.loads((out / portable["path"]).read_text())["input"]["root"], "facts:rebound")
        self.assertNotIn(str(self.root), json.dumps(receipt["jobs"]))
        policy = out / "work" / "policies" / "a" / "p.json"
        self.assertEqual(json.loads(policy.read_bytes())["target"]["facts_manifest_sha256"], REBOUND)

    def test_differing_output_is_classified_and_gets_a_fresh_manifest(self):
        published = runtime({"_meta": {"generator": "old"}, "value": 0})
        out, receipt, outcome = self.run_build(self.fixture(published_a=published))
        member = receipt["members"]["data/9.9/overlay/a.json"]
        self.assertEqual(member["class"], "generated-different")
        self.assertEqual(member["reference"], pin(published))
        # The snapshot is re-pinned over the generated bytes, so it differs too.
        self.assertEqual(receipt["members"]["data/9.9/manifest.json"]["class"], "passthrough-different")
        self.assertEqual(outcome["manifest"]["class"], "fresh-manifest")
        self.assertFalse(outcome["package"]["identical_to_reference"])
        with zipfile.ZipFile(out / "game-build-part.zip") as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(archive.read("data/9.9/overlay/a.json"), self.derived)
        self.assertEqual(manifest["schema"], build.PART_SCHEMA)
        self.assertEqual(manifest["files"]["data/9.9/overlay/a.json"], pin(self.derived))
        # The fresh manifest pins a file that exists: the published receipt.json.
        self.assertEqual(manifest["release_build"]["receipt"], {"path": "receipt.json", **pin(receipt_raw(out))})
        sums = (out / "SHA256SUMS").read_text().split()
        self.assertEqual(sums[2:4], [manifest["release_build"]["receipt"]["sha256"], "receipt.json"])

    def test_fresh_manifest_mode_overrides_retention(self):
        _, receipt, outcome = self.run_build(self.fixture(), manifest_mode="fresh")
        self.assertEqual(outcome["manifest"]["class"], "fresh-manifest")
        self.assertTrue(receipt["reference"]["members_identical"])
        self.assertFalse(outcome["package"]["identical_to_reference"])

    def test_passthrough_members_are_counted_separately(self):
        restamped = runtime({"_meta": {"generator": "restamped"}, "value": 1})
        for domain, carried, published in (
            ("copy", "verbatim", self.codec),
            ("restamp", "payload-except-_meta", restamped),
        ):
            with self.subTest(domain=domain):
                config = self.fixture(published_a=published, domain=domain, passthrough="carries the codec source")
                _, receipt, _ = self.run_build(config)
                self.assertEqual(receipt["summary"], {"passthrough-identical": 2, "frozen": 1})
                self.assertEqual(receipt["provenance"], {"passthrough": 2, "frozen": 1})
                self.assertEqual(
                    receipt["jobs"]["a"]["passthrough"],
                    {"data/9.9/overlay/a.json": {"input": "inputs:codec/a.json", "carried": carried}},
                )
                self.assertEqual(receipt["members"]["data/9.9/overlay/a.json"]["class"], "passthrough-identical")

    def test_undeclared_passthrough_rejects(self):
        with self.assertRaisesRegex(ValueError, "without a passthrough declaration"):
            self.run_build(self.fixture(published_a=self.codec, domain="copy"))
        with self.assertRaisesRegex(ValueError, "snapshot: outputs carry input content over"):
            self.run_build(self.fixture(snapshot_passthrough=False))

    def test_stale_passthrough_declaration_rejects(self):
        with self.assertRaisesRegex(ValueError, "declared passthrough, but no output"):
            self.run_build(self.fixture(passthrough="claims a carry-over"))

    def test_snapshot_member_missing_from_template_rejects(self):
        config = self.fixture()
        domains = json.loads((config / "domains.json").read_text())
        domains["jobs"][0]["outputs"]["overlay/b.json"] = "data/9.9/overlay/b.json"
        (config / "domains.json").write_text(json.dumps(domains))
        adapter = self.adapter.read_text().replace('["overlay/a.json"]', '["overlay/a.json", "overlay/b.json"]')
        self.adapter.write_text(adapter)
        with self.assertRaisesRegex(ValueError, r"members missing from the snapshot template: \['overlay/b.json'\]"):
            self.run_build(config)

    def test_frozen_pin_drift_rejects(self):
        config = self.fixture(frozen_pin={"bytes": 1, "sha256": "0" * 64})
        with self.assertRaisesRegex(ValueError, "Frozen bytes changed"):
            self.run_build(config)

    def test_frozen_declarations_need_a_known_category_and_origin(self):
        config = self.fixture()
        declared = (config / "frozen-inputs.json").read_text()
        for field, value, message in (("category", "pob2", "undeclared category"), ("origin", " ", "empty origin")):
            with self.subTest(field=field):
                frozen = json.loads(declared)
                frozen["members"]["data/9.9/overlay/frozen.json"][field] = value
                (config / "frozen-inputs.json").write_text(json.dumps(frozen))
                with self.assertRaisesRegex(ValueError, message):
                    build.load_config(config)

    def test_fresh_manifest_names_the_frozen_declaration(self):
        out, _, _ = self.run_build(self.fixture(), manifest_mode="fresh")
        with zipfile.ZipFile(out / "game-build-part.zip") as archive:
            limits = json.loads(archive.read("manifest.json"))["limits"]
        self.assertIn(f"{self.root / 'config' / 'frozen-inputs.json'} with their recorded origin", limits[0])

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

    def set_tag(self, config, tag):
        lock = json.loads((config / "inputs.lock.json").read_text())
        lock["packages"]["inputs"]["tag"] = tag
        (config / "inputs.lock.json").write_text(json.dumps(lock))

    def test_publication_tag_must_name_the_locked_revision(self):
        config = self.fixture()
        self.set_tag(config, "handoff/inputs")
        _, receipt, _ = self.run_build(config)
        self.assertEqual(receipt["inputs"]["tags"], {"inputs": "not-present-locally"})
        self.git("tag", "handoff/inputs")
        _, receipt, _ = self.run_build(config)
        self.assertEqual(receipt["inputs"]["tags"], {"inputs": "verified"})
        self.git("tag", "-d", "handoff/inputs")
        self.commit({"later.txt": b"later"})
        self.git("tag", "-a", "-m", "moved", "handoff/inputs")
        with self.assertRaisesRegex(ValueError, "Tag handoff/inputs names .* not the locked revision"):
            self.run_build(config)

    def test_untracked_producer_inputs_mark_the_build_dirty(self):
        config = self.fixture()
        (self.repo / "scratch.txt").write_text("unrelated")
        _, receipt, _ = self.run_build(config)
        self.assertFalse(receipt["producer"]["dirty"])
        (self.repo / "tools/pobr-data-adapter/policies").mkdir(parents=True)
        (self.repo / "tools/pobr-data-adapter/policies/new.json").write_text("{}")
        _, receipt, _ = self.run_build(config)
        self.assertTrue(receipt["producer"]["dirty"])
        self.assertEqual(receipt["producer"]["dirty_paths"], ["tools/pobr-data-adapter/policies/new.json"])

    def test_offline_git_disables_lazy_fetch(self):
        printenv = ["-c", "alias.printenv=!env", "printenv"]
        environment = {k: v for k, v in os.environ.items() if k != "GIT_NO_LAZY_FETCH"}
        with mock.patch.dict(os.environ, environment, clear=True):
            self.assertIn(b"GIT_NO_LAZY_FETCH=1", build.git(self.repo, *printenv).stdout)
            self.assertNotIn(b"GIT_NO_LAZY_FETCH=1", build.git(self.repo, *printenv, online=True).stdout)

    def test_refuses_to_replace_foreign_output(self):
        (self.root / "out").mkdir()
        (self.root / "out" / "keep.txt").write_text("x")
        with self.assertRaisesRegex(ValueError, "non-release directory"):
            self.run_build(self.fixture())
        self.assertTrue((self.root / "out" / "keep.txt").exists())

    def test_default_config_is_the_highest_patch(self):
        releases = self.root / "release"
        for name in ("0.5.5.5", "0.10.0", "0.9.1.2"):
            (releases / name).mkdir(parents=True)
            (releases / name / "inputs.lock.json").write_text("{}")
        (releases / "notes").mkdir()  # no declaration: ignored
        self.assertEqual(build.default_config(releases), releases / "0.10.0")
        (releases / "next").mkdir()
        (releases / "next" / "inputs.lock.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "named by game patch"):
            build.default_config(releases)

    def test_config_option_selects_the_declaration(self):
        config = self.fixture()
        calls = []

        def fake_build(*args):
            calls.append(args[0])
            raise ValueError("stop")

        for argv, expected in (([], None), (["--config", str(config)], config)):
            with self.subTest(argv=argv), mock.patch.object(build, "build", fake_build):
                with self.assertRaises(SystemExit), mock.patch("sys.stderr", io.StringIO()):
                    build.main(argv)
                self.assertEqual(calls.pop(), expected)
        # A directory under release/ must be named by the patch it declares.
        with mock.patch.object(build, "RELEASES", config.parent):
            with self.assertRaisesRegex(ValueError, "declares game patch 9.9"):
                build.load_config(config)
            renamed = config.rename(config.parent / "9.9")
            self.assertEqual(build.load_config(renamed)[0], renamed)

    def test_release_workflow_paths_cover_the_build_code(self):
        root = Path(build.__file__).resolve().parents[2]
        imported, pending = set(), ["RePoE/release/build.py"]
        while pending:
            module = pending.pop()
            for node in ast.walk(ast.parse((root / module).read_text())):
                if isinstance(node, ast.ImportFrom) and node.level == 1:
                    names = [f"RePoE/{node.module}.py"] if node.module else [f"RePoE/{a.name}.py" for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module == "RePoE":
                    names = [f"RePoE/{alias.name}.py" for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("RePoE."):
                    names = [node.module.replace(".", "/") + ".py"]
                else:
                    continue
                for name in names:
                    if name not in imported and (root / name).is_file():
                        imported.add(name)
                        pending.append(name)
        self.assertLessEqual(imported, set(build.CODE))
        workflow = (root / ".github/workflows/release-build.yml").read_text()
        patterns = re.findall(r"^ +- ([^\s:]+)$", workflow.split("pull_request:")[0], re.MULTILINE)
        for name in build.CODE:
            covered = any(name == p or (p.endswith("/**") and name.startswith(p[:-2])) for p in patterns)
            self.assertTrue(covered, f"{name} is not in the release workflow's paths filter")

    def test_template_expansion(self):
        bindings = {"a.b": [1], "nested": {"c": 2}}
        value = {"x": {"$retained": "a.b"}, "y": [{"$retained": "nested.c"}], "z": 3}
        self.assertEqual(build.expand_template(value, bindings), {"x": [1], "y": [2], "z": 3})


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    unittest.main()
