"""Synthetic end-to-end tests for RePoE.release.build (no real packages or Rust adapter)."""

import ast
import functools
import hashlib
import http.server
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
from unittest import mock
import zipfile

from RePoE.client import export_receipt
from RePoE.release.pins import encoded, pin
from RePoE.release import build
from tests.client.test_export_receipt import DIRTY, candidate, receipt_for

TARGET = {"game": "poe2", "game_patch": "9.9", "realm": "international"}
ORIGINAL = "a" * 64
REBOUND = "b" * 64
FAKE_ADAPTER = textwrap.dedent(
    """\
    import hashlib, json, sys
    from pathlib import Path
    args = sys.argv[1:]
    if args == ["--contract-version"]:
        sys.exit(print(1))
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


def serve(case, directory, redirect=False):
    """A local Release host for ``case``: ``/<repository>/releases/download/<tag>/<asset>`` under ``directory``.

    With ``redirect`` every request is redirected once, as GitHub redirects to its asset storage.
    """

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            if redirect and not self.path.startswith("/storage/"):
                self.send_response(302)
                self.send_header("Location", "/storage" + self.path)
                self.end_headers()
                return
            self.path = self.path.removeprefix("/storage")
            super().do_GET()

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(directory)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    case.addCleanup(server.server_close)
    case.addCleanup(server.shutdown)
    return f"http://127.0.0.1:{server.server_port}"


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
        snapshot_fields=None,
        extra_inputs=None,
    ):
        """Commit an input and a reference package; write a release declaration."""
        inputs = {"codec/a.json": self.codec, **(extra_inputs or {})}
        inputs_raw = zip_bytes({**inputs, "manifest.json": encoded({"files": {k: pin(v) for k, v in inputs.items()}})})
        published_a = self.derived if published_a is None else published_a
        members = {"data/9.9/overlay/a.json": published_a, "data/9.9/overlay/frozen.json": self.frozen}
        snapshot = {
            "schema_version": 3,
            "poe_version": "9.9",
            "domains": {"overlay": ["a", "frozen"]},
            "files": {
                "overlay/a.json": hashlib.sha256(published_a).hexdigest(),
                "overlay/frozen.json": hashlib.sha256(self.frozen).hexdigest(),
                "i18n/zh-CN/x.json": "c" * 64,
            },
            **(snapshot_fields or {}),
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
        self.assertEqual(receipt["schema"], "repoe-release-receipt/v2")
        self.assertEqual(receipt["package"]["sha256"], build.file_pin(out / "game-build-part.zip")["sha256"])
        self.assertEqual(receipt["summary"], {"generated-identical": 1, "passthrough-identical": 1, "frozen": 1})
        self.assertEqual(receipt["provenance"], {"generated": 1, "passthrough": 1, "frozen": 1})
        self.assertEqual(
            receipt["jobs"]["snapshot"]["passthrough"]["data/9.9/manifest.json"],
            {
                "input": "previous:data/9.9/manifest.json",
                "carried": "template",
                "fields": ["domains", "schema_version"],
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
        # The fresh manifest names no producer commit or receipt; the receipt pins the zip instead.
        self.assertNotIn("release_build", manifest)
        zip_pin = build.file_pin(out / "game-build-part.zip")
        self.assertEqual(
            {k: receipt["package"][k] for k in ("path", "bytes", "sha256")}, {"path": "game-build-part.zip", **zip_pin}
        )
        with zipfile.ZipFile(out / "game-build-part.zip") as archive:
            manifest_pin = {"class": "fresh-manifest", **pin(archive.read("manifest.json"))}
        self.assertEqual(receipt["package"]["manifest"], manifest_pin)
        self.assertEqual(json.loads(receipt_raw(out)), receipt)
        sums = (out / "SHA256SUMS").read_text().split()
        self.assertEqual(sums[2:4], [pin(receipt_raw(out))["sha256"], "receipt.json"])
        self.assertEqual(build.check_failure(outcome), "package differs from the reference package")

    def test_fresh_package_does_not_depend_on_the_producer_commit(self):
        published = runtime({"_meta": {"generator": "old"}, "value": 0})
        config = self.fixture(published_a=published)
        out, first, _ = self.run_build(config)
        zip_raw = (out / "game-build-part.zip").read_bytes()
        self.commit({"later.txt": b"another producer commit"})
        out, second, _ = self.run_build(config)
        self.assertNotEqual(first["producer"]["commit"], second["producer"]["commit"])
        self.assertEqual((out / "game-build-part.zip").read_bytes(), zip_raw)

    def test_expect_pin_decides_the_check(self):
        published = runtime({"_meta": {"generator": "old"}, "value": 0})
        config = self.fixture(published_a=published)
        _, _, outcome = self.run_build(config)
        built = {k: outcome["package"][k] for k in ("bytes", "sha256")}
        lock = json.loads((config / "inputs.lock.json").read_text())
        for expect, failure in ((built, None), ({"bytes": 1, "sha256": "0" * 64}, "differs from the expect pin")):
            with self.subTest(expect=expect):
                lock["expect"] = {"package": expect}
                (config / "inputs.lock.json").write_text(json.dumps(lock))
                _, _, outcome = self.run_build(config)
                self.assertFalse(outcome["package"]["identical_to_reference"])
                self.assertEqual(outcome["package"]["matches_expect"], failure is None)
                self.assertEqual(outcome["package"]["expect"], expect)
                if failure is None:
                    self.assertIsNone(build.check_failure(outcome))
                else:
                    self.assertIn(failure, build.check_failure(outcome))
        lock["expect"] = {"package": built, "receipt": built}
        (config / "inputs.lock.json").write_text(json.dumps(lock))
        with self.assertRaisesRegex(ValueError, "only a package pin"):
            build.load_config(config)

    def test_fresh_manifest_mode_overrides_retention(self):
        _, receipt, outcome = self.run_build(self.fixture(), manifest_mode="fresh")
        self.assertEqual(outcome["manifest"]["class"], "fresh-manifest")
        self.assertTrue(receipt["reference"]["members_identical"])
        self.assertFalse(outcome["package"]["identical_to_reference"])

    def test_build_requires_receipts_for_every_export_format_and_checks_nested_receipts(self):
        for format_ in sorted(export_receipt.FORMATS):
            with self.subTest(format=format_):
                stripped = encoded({"format": format_, "source_identity": TARGET})
                config = self.fixture(extra_inputs={"candidate/manifest.json": stripped})
                with self.assertRaisesRegex(ValueError, "inputs: candidate/manifest.json: no export receipt"):
                    self.run_build(config)
        manifest = candidate()
        nested = zip_bytes(
            {
                "candidate/manifest.json": manifest,
                "candidate.export-receipt.json": receipt_for(manifest, rehearsal=True),
            }
        )
        config = self.fixture(extra_inputs={"envelope.zip": nested})
        with self.assertRaisesRegex(ValueError, "inputs:envelope.zip!candidate.export-receipt.json is a rehearsal"):
            self.run_build(config)
        bare = zip_bytes({"manifest.json": manifest})
        config = self.fixture(extra_inputs={"envelope.zip": bare})
        with self.assertRaisesRegex(ValueError, "envelope.zip!manifest.json: candidate manifest must be inside"):
            self.run_build(config)
        # The historical extraction branch cannot unwrap an arbitrary unreceipted envelope under another name.
        files = {"handoff.json": encoded({"archive": pin(bare)}), "envelope.bin": bare}
        for name, raw in files.items():
            build.write_new(self.root / "unreceipted" / name, raw)
        package = build.Package("inputs", {}, b"", self.root / "unreceipted", {n: pin(r) for n, r in files.items()})
        with (
            mock.patch.object(build.source_rebinding, "verify", side_effect=AssertionError("unreviewed extraction")),
            self.assertRaisesRegex(ValueError, "Only the frozen historical facts envelope"),
        ):
            build.prepare_facts(package, {"handoff": "handoff.json", "archive": "envelope.bin"}, self.root / "cache")

    def test_fresh_facts_root_builds_with_one_pinned_identity(self):
        from RePoE.release import inputs

        payloads = {"source-lock.json": encoded({"schema_version": 1}), "tables/Stats.json": b"[]\n"}
        manifest_raw = encoded(
            {
                "format": "repoe-native-facts/v4",
                "status": "partial-candidate",
                "production_ready": False,
                "source_identity": TARGET,
                export_receipt.FIELD: export_receipt.SCHEMA,
                "files": {name: pin(raw) for name, raw in payloads.items()},
            }
        )
        config = self.fixture()
        source = self.root / "ordinary"
        for name, raw in {**payloads, "manifest.json": manifest_raw}.items():
            build.write_new(source / "facts" / name, raw)
        build.write_new(source / "codec/a.json", self.codec)
        cache = self.root / "cache"
        lock = json.loads((config / "inputs.lock.json").read_text())
        identities = dict.fromkeys(build.FACTS_IDENTITIES, pin(manifest_raw)["sha256"])
        lock["facts"] = {"package": "inputs", "root": "facts", "identities": identities}

        def declare(stage, **identity):
            """Package the root with an export receipt from ``identity`` and pin it in the declaration."""
            (source / "facts.export-receipt.json").write_bytes(receipt_for(manifest_raw, **identity))
            staged = inputs.stage({"ordinary": source}, TARGET, self.root / stage)
            entry = inputs.lock_entries(staged, "inputs/9.9-1")["ordinary"]
            asset = (staged["directory"] / "assets" / entry["asset"]).read_bytes()
            build.write_new(cache / "inputs/downloads" / entry["sha256"], asset)
            lock["packages"]["inputs"] = entry
            (config / "inputs.lock.json").write_text(json.dumps(lock))
            return entry

        entry = declare("stage")
        (self.policies / "p.json").write_bytes(runtime({"target": {"facts_manifest_sha256": identities["original"]}}))
        domains = json.loads((config / "domains.json").read_text())
        for identity in build.FACTS_IDENTITIES:
            with self.subTest(identity=identity):
                domains["jobs"][0]["facts"] = identity
                (config / "domains.json").write_text(json.dumps(domains))
                out, receipt, outcome = build.build(
                    config,
                    out=self.root / "out",
                    adapter=self.adapter,
                    cache=cache,
                    repo=self.repo,
                    policies=self.policies,
                )
                self.assertTrue(outcome["package"]["identical_to_reference"])
                self.assertEqual(receipt["inputs"]["facts"]["identities"], dict.fromkeys(identities, pin(manifest_raw)))
                self.assertIsNone(receipt["inputs"]["facts"]["handoff"])
                self.assertIsNone(receipt["inputs"]["facts"]["archive"])
                self.assertEqual(receipt["inputs"]["exports"], {"inputs:facts.export-receipt.json": "c" * 40})
        package = build.open_package(self.repo, "inputs", entry, cache / "inputs", False)
        for change, message in (
            ({"identities": {**identities, "original": ORIGINAL}}, "Facts identities differ from lock"),
            ({"handoff": "handoff.json"}, "cannot also declare a handoff/archive"),
            ({"root": "../facts"}, "Unsafe member path"),
        ):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, message):
                build.prepare_facts(package, {**lock["facts"], **change}, cache)
        (package.root / "facts/tables/Stats.json").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "facts member changed: tables/Stats.json"):
            build.prepare_facts(package, lock["facts"], cache)
        # A fresh root without the field would reach the adapter as a historical package.
        stripped = encoded({k: v for k, v in json.loads(manifest_raw).items() if k != export_receipt.FIELD})
        build.write_new(self.root / "bare/facts/manifest.json", stripped)
        bare = build.Package("inputs", {}, b"", self.root / "bare", {"facts/manifest.json": pin(stripped)})
        with self.assertRaisesRegex(ValueError, "Facts root facts carries no producer_receipt"):
            build.prepare_facts(bare, lock["facts"], cache)
        # release:inputs stages a rehearsal export; it is never built into a game package.
        declare("rehearsal-stage", rehearsal=True, dirty_paths=DIRTY)
        with self.assertRaisesRegex(
            ValueError, r"inputs:facts\.export-receipt\.json is a rehearsal; it cannot be built"
        ):
            build.build(
                config, out=self.root / "out", adapter=self.adapter, cache=cache, repo=self.repo, policies=self.policies
            )

    def test_new_patch_maps_frozen_members_and_accepts_only_the_source_snapshot_version(self):
        config = self.fixture()
        target = {**TARGET, "game_patch": "10.2.3"}
        for name in build.SCHEMAS:
            path = config / name
            document = json.loads(path.read_text().replace("data/9.9/", "data/10.2.3/"))
            document["target"] = target
            if name == "domains.json":
                document["jobs"][1]["template"] = "previous:data/9.9/manifest.json"
            path.write_text(json.dumps(document))
        out, _, _ = self.run_build(config)
        with zipfile.ZipFile(out / "game-build-part.zip") as archive:
            self.assertEqual(archive.read("data/10.2.3/overlay/frozen.json"), self.frozen)
            self.assertEqual(json.loads(archive.read("data/10.2.3/manifest.json"))["poe_version"], "10.2.3")
        frozen_path = config / "frozen-inputs.json"
        frozen = json.loads(frozen_path.read_text())
        frozen["members"]["data/10.2.3/overlay/frozen.json"]["sha256"] = "0" * 64
        frozen_path.write_text(json.dumps(frozen))
        with self.assertRaisesRegex(ValueError, "Frozen bytes changed: data/10.2.3/overlay/frozen.json"):
            self.run_build(config)
        # A template's own version must match its source package, even if its path looks right.
        with self.assertRaisesRegex(ValueError, "snapshot: template version mismatch"):
            self.run_build(self.fixture(snapshot_fields={"poe_version": "8.8"}))

    def test_unversioned_frozen_members_do_not_require_a_source_patch(self):
        config = self.fixture()
        domains_path = config / "domains.json"
        domains = json.loads(domains_path.read_text())
        domains["jobs"] = domains["jobs"][:1]
        domains_path.write_text(json.dumps(domains))
        frozen_path = config / "frozen-inputs.json"
        frozen = json.loads(frozen_path.read_text())
        entry = next(iter(frozen["members"].values()))
        frozen["source"] = "inputs"
        for members in ({}, {"codec/a.json": {**entry, **pin(self.codec)}}):
            with self.subTest(members=list(members)):
                frozen["members"] = members
                frozen_path.write_text(json.dumps(frozen))
                out, _, _ = self.run_build(config)
                with zipfile.ZipFile(out / "game-build-part.zip") as archive:
                    self.assertEqual("codec/a.json" in archive.namelist(), bool(members))
                    if members:
                        self.assertEqual(archive.read("codec/a.json"), self.codec)

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

    def test_snapshot_adds_new_members_and_records_the_adapter_contract(self):
        config = self.fixture()
        domains = json.loads((config / "domains.json").read_text())
        domains["jobs"][0]["outputs"]["overlay/b.json"] = "data/9.9/overlay/b.json"
        snapshot = domains["jobs"][1]
        snapshot["add"] = {"overlay/b.json": "overlay"}
        snapshot["contract_version"] = "adapter"
        (config / "domains.json").write_text(json.dumps(domains))
        adapter = self.adapter.read_text().replace('["overlay/a.json"]', '["overlay/a.json", "overlay/b.json"]')
        self.adapter.write_text(adapter)
        out, receipt, _ = self.run_build(config)
        with zipfile.ZipFile(out / "game-build-part.zip") as archive:
            snapshot = json.loads(archive.read("data/9.9/manifest.json"))
            added = archive.read("data/9.9/overlay/b.json")
        self.assertEqual(snapshot["contract_version"], 1)
        self.assertEqual(snapshot["domains"], {"overlay": ["a", "b", "frozen"]})
        self.assertEqual(list(snapshot["files"]), sorted(snapshot["files"]))
        self.assertEqual(snapshot["files"]["overlay/b.json"], hashlib.sha256(added).hexdigest())
        self.assertEqual(receipt["members"]["data/9.9/overlay/b.json"]["class"], "generated-new")
        carried = receipt["jobs"]["snapshot"]["passthrough"]["data/9.9/manifest.json"]
        self.assertNotIn("contract_version", json.dumps(carried))

    def test_gem_descriptions_job_reads_the_facts_and_adds_its_member(self):
        gem_effects = {"gems": [{"gem_id": "G", "granted_effect_id": "SupportX", "variant_id": "XSupport"}]}
        granted = [{"id": "SupportX", "is_support": True, "active_skill": "x_skill"}]
        config = self.fixture(
            extra_inputs={"gem/gem_effects.json": runtime(gem_effects), "gem/granted_effects.json": runtime(granted)}
        )
        gems = {"effects": [{"gem_effect": {"id": "XSupport", "row": 0}, "support_text": "Supports [Hit|Hits]. "}]}
        table = {"table": "ActiveSkills", "rows": [{"_row": 0, "values": {"Id": "x_skill", "Description": "Does X."}}]}
        (self.facts / "tables").mkdir()
        (self.facts / "gems.json").write_bytes(runtime(gems))
        (self.facts / "tables/ActiveSkills.json").write_bytes(runtime(table))
        domains = json.loads((config / "domains.json").read_text())
        job = {
            "id": "gem-descriptions",
            "kind": "gem-descriptions",
            "facts": "rebound",
            "gem_effects": "inputs:gem/gem_effects.json",
            "granted_effects": "inputs:gem/granted_effects.json",
            "outputs": {"overlay/gem_descriptions.json": "data/9.9/overlay/gem_descriptions.json"},
        }
        domains["jobs"].insert(1, job)
        domains["jobs"][2]["add"] = {"overlay/gem_descriptions.json": "overlay"}
        (config / "domains.json").write_text(json.dumps(domains))
        out, receipt, _ = self.run_build(config)
        with zipfile.ZipFile(out / "game-build-part.zip") as archive:
            member = json.loads(archive.read("data/9.9/overlay/gem_descriptions.json"))
            snapshot = json.loads(archive.read("data/9.9/manifest.json"))
        self.assertEqual(
            member["scopes"],
            {
                "ActiveSkills.Description": {"x_skill": "Does X."},
                "GemEffects.SupportText": {"XSupport": "Supports [Hit|Hits]. "},
            },
        )
        self.assertEqual(member["_meta"]["facts_manifest_sha256"], REBOUND)
        self.assertEqual(snapshot["domains"]["overlay"], ["a", "frozen", "gem_descriptions"])
        self.assertEqual(receipt["members"]["data/9.9/overlay/gem_descriptions.json"]["class"], "generated-new")
        self.assertIn("facts:rebound:gems.json", receipt["inputs"]["files"])
        self.assertEqual(
            receipt["jobs"]["gem-descriptions"]["summary"],
            {"gem_effects": 1, "ActiveSkills.Description": 1, "GemEffects.SupportText": 1},
        )
        lock = json.loads((config / "inputs.lock.json").read_text())
        del lock["facts"]
        (config / "inputs.lock.json").write_text(json.dumps(lock))
        del domains["jobs"][0]
        (config / "domains.json").write_text(json.dumps(domains))
        with self.assertRaisesRegex(ValueError, "so do gem-descriptions jobs"):
            build.load_config(config)

    def test_snapshot_omits_the_language_owners_entries_and_fields(self):
        config = self.fixture(snapshot_fields={"languages": ["zh-CN"]})
        domains = json.loads((config / "domains.json").read_text())
        snapshot = domains["jobs"][1]
        del snapshot["external"]
        snapshot["omit"] = {"entries": ["i18n/"], "fields": ["languages"]}
        (config / "domains.json").write_text(json.dumps(domains))
        out, receipt, _ = self.run_build(config)
        with zipfile.ZipFile(out / "game-build-part.zip") as archive:
            manifest = json.loads(archive.read("data/9.9/manifest.json"))
        self.assertEqual(list(manifest["files"]), ["overlay/a.json", "overlay/frozen.json"])
        self.assertNotIn("languages", manifest)
        carried = receipt["jobs"]["snapshot"]["passthrough"]["data/9.9/manifest.json"]
        self.assertEqual((carried["omitted_pins"], carried["omitted_fields"]), (1, ["languages"]))
        self.assertEqual(carried["retained_pins"], 0)
        for omit, message in (
            ({"entries": ["overlay/"]}, "a member of this package is omitted: overlay/a.json"),
            ({"fields": ["files"]}, "cannot omit files"),
            ({"fields": ["domains"]}, "cannot omit domains"),
            ({"fields": ["schema_version"]}, "cannot omit schema_version"),
            ({"prefixes": []}, "unknown omit keys"),
        ):
            with self.subTest(omit=omit):
                snapshot["omit"] = omit
                (config / "domains.json").write_text(json.dumps(domains))
                with self.assertRaisesRegex(ValueError, message):
                    self.run_build(config)

    def test_snapshot_omit_skips_what_the_template_lacks(self):
        # A template that already leaves the language owner's part out.
        config = self.fixture()
        domains = json.loads((config / "domains.json").read_text())
        snapshot = domains["jobs"][1]
        snapshot["omit"] = {"entries": ["i18n/", "absent/"], "fields": ["languages"]}
        (config / "domains.json").write_text(json.dumps(domains))
        out, receipt, _ = self.run_build(config)
        with zipfile.ZipFile(out / "game-build-part.zip") as archive:
            manifest = json.loads(archive.read("data/9.9/manifest.json"))
        self.assertEqual(list(manifest["files"]), ["overlay/a.json", "overlay/frozen.json"])
        carried = receipt["jobs"]["snapshot"]["passthrough"]["data/9.9/manifest.json"]
        self.assertEqual((carried["omitted_pins"], carried["omitted_fields"]), (1, []))

    def test_snapshot_add_of_a_declared_entry_is_a_no_op(self):
        config = self.fixture()
        plain, _, _ = self.run_build(config)
        domains = json.loads((config / "domains.json").read_text())
        domains["jobs"][1]["add"] = {"overlay/a.json": "overlay"}
        (config / "domains.json").write_text(json.dumps(domains))
        out, _, _ = self.run_build(config)
        with (
            zipfile.ZipFile(plain / "game-build-part.zip") as before,
            zipfile.ZipFile(out / "game-build-part.zip") as after,
        ):
            self.assertEqual(before.read("data/9.9/manifest.json"), after.read("data/9.9/manifest.json"))

    def test_snapshot_add_rejects_a_non_member_or_an_undeclared_domain(self):
        config = self.fixture()
        domains = json.loads((config / "domains.json").read_text())
        domains["jobs"][1]["add"] = {"overlay/b.json": "overlay"}
        (config / "domains.json").write_text(json.dumps(domains))
        with self.assertRaisesRegex(ValueError, "added entry is not a member: overlay/b.json"):
            self.run_build(config)
        config = self.fixture(snapshot_fields={"domains": {"overlay": ["frozen"]}})
        domains = json.loads((config / "domains.json").read_text())
        domains["jobs"][1]["add"] = {"overlay/a.json": "overlay"}
        (config / "domains.json").write_text(json.dumps(domains))
        with self.assertRaisesRegex(ValueError, "overlay/a.json is in the template but overlay lacks a"):
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
        with self.assertRaisesRegex(ValueError, "named <patch> or <patch>-<n>"):
            build.default_config(releases)
        (releases / "next").rename(releases / "0.10.0-2")
        # <patch>-<n> sorts after <patch>, then by n.
        (releases / "0.10.0-10").mkdir()
        (releases / "0.10.0-10" / "inputs.lock.json").write_text("{}")
        self.assertEqual(build.default_config(releases), releases / "0.10.0-10")

    def test_config_names_give_the_sequence_and_output_directory(self):
        for name, sequence, output in (
            ("9.9", None, "poe2-international-9.9"),
            ("9.9-2", 2, "poe2-international-9.9-2"),
            ("9.8-2", None, "poe2-international-9.9"),
            ("scratch", None, "poe2-international-9.9"),
        ):
            with self.subTest(name=name):
                self.assertEqual(build.config_sequence(Path(name), TARGET), sequence)
                self.assertEqual(build.output_name(Path(name), TARGET), output)
        self.assertIsNone(build.config_key("9.9-0"))

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
            renamed = renamed.rename(config.parent / "9.9-3")
            self.assertEqual(build.load_config(renamed)[0], renamed)
            renamed = renamed.rename(config.parent / "9.8-3")
            with self.assertRaisesRegex(ValueError, "declares game patch 9.9"):
                build.load_config(renamed)

    def test_release_workflow_paths_cover_the_build_code(self):
        root = Path(build.__file__).resolve().parents[2]
        imported, pending = set(), ["RePoE/release/build.py"]
        while pending:
            module = pending.pop()
            for node in ast.walk(ast.parse((root / module).read_text())):
                if not isinstance(node, ast.ImportFrom):
                    continue
                if node.level:
                    # ``from . import x`` / ``from .x import y`` inside the module's own package.
                    package = PurePosixPath(module).parents[node.level - 1].as_posix().replace("/", ".")
                    base = f"{package}.{node.module}" if node.module else package
                elif (node.module or "").split(".")[0] == "RePoE":
                    base = node.module
                else:
                    continue
                # ``from RePoE.a import b`` imports module ``RePoE/a/b.py`` or a name of ``RePoE/a.py``.
                for name in [f"{base}.{a.name}".replace(".", "/") + ".py" for a in node.names] + [
                    base.replace(".", "/") + ".py"
                ]:
                    if name not in imported and (root / name).is_file():
                        imported.add(name)
                        pending.append(name)
        # Equality, not a subset: a stale CODE path or a walker that misses an import fails here.
        self.assertEqual(imported | {"RePoE/release/build.py"}, {name for name in build.CODE if name.endswith(".py")})
        # Every package the build imports from runs its __init__.py, so the paths filter must cover those too.
        packages = {str(PurePosixPath(name).parent / "__init__.py") for name in imported}
        workflow = (root / ".github/workflows/release-build.yml").read_text()
        patterns = re.findall(r"^ +- ([^\s:]+)$", workflow.split("pull_request:")[0], re.MULTILINE)
        for name in sorted(set(build.CODE) | packages):
            covered = any(name == p or (p.endswith("/**") and name.startswith(p[:-2])) for p in patterns)
            self.assertTrue(covered, f"{name} is not in the release workflow's paths filter")

    def test_receipt_records_the_pobr_contract(self):
        _, receipt, _ = self.run_build(self.fixture())
        contract = receipt["producer"]["contract"]
        self.assertEqual(contract["version"], 1)
        if contract["tag"] is None:
            # A [patch] to a local PoBR checkout: the receipt names the local
            # crates instead of a tag, and release:publish refuses it.
            self.assertEqual(contract["local"], sorted(build.POBR_CRATES))
        else:
            self.assertRegex(contract["tag"], r"^contract/1\.\d+$")
            self.assertRegex(contract["commit"], r"^[0-9a-f]{40}$")
        lock = self.root / "Cargo.lock"
        lock.write_text('[[package]]\nname = "pobr-data"\nversion = "0.0.1"\n')
        self.assertEqual(
            build.pobr_contract(self.adapter, lock),
            {"repository": "ackness/pobr", "version": 1, "tag": None, "commit": None, "local": ["pobr-data"]},
        )
        source = "git+https://github.com/ackness/pobr?tag=contract%2F2.0#" + "1" * 40
        lock.write_text(f'[[package]]\nname = "pobr-data"\nsource = "{source}"\n')
        with self.assertRaisesRegex(ValueError, "contract version 1, but Cargo.lock pins contract/2.0"):
            build.pobr_contract(self.adapter, lock)
        lock.write_text(lock.read_text() + f'[[package]]\nname = "pobr-core"\nsource = "{source[:-40]}{"2" * 40}"\n')
        with self.assertRaisesRegex(ValueError, "exactly one"):
            build.pobr_contract(self.adapter, lock)
        dotgit = "git+https://github.com/ackness/pobr.git?tag=contract%2F1.3#" + "e" * 40
        lock.write_text(f'[[package]]\nname = "pobr-data"\nsource = "{dotgit}"\n')
        self.assertEqual(build.pobr_contract(self.adapter, lock)["tag"], "contract/1.3")
        # A tag must describe every PoBR crate: one patched to a local checkout refuses it.
        lock.write_text(lock.read_text() + '[[package]]\nname = "pobr-core"\nversion = "0.0.1"\n')
        with self.assertRaisesRegex(ValueError, r"mixes a local PoBR \[patch\] \(pobr-core\)"):
            build.pobr_contract(self.adapter, lock)
        lock.write_text(f'[[package]]\nname = "pobr-data"\nsource = "{dotgit[:-1]}X"\n')
        with self.assertRaisesRegex(ValueError, "pinned by tag and commit"):
            build.pobr_contract(self.adapter, lock)

    def release_reference(self, config, raw=None):
        """Move the reference package from its Git blob to a Release asset on a local host."""
        lock = json.loads((config / "inputs.lock.json").read_text())
        spec = lock["packages"]["previous"]
        for key in ("revision", "path"):
            del spec[key]
        spec.update(repository="ackness/repoe", tag="game/9.9-1", asset="pobr-game-9.9.zip")
        (config / "inputs.lock.json").write_text(json.dumps(lock))
        host = self.root / "host"
        asset = host / "ackness/repoe/releases/download/game/9.9-1/pobr-game-9.9.zip"
        asset.parent.mkdir(parents=True)
        asset.write_bytes(self.previous_raw if raw is None else raw)
        return host

    def test_reference_can_be_a_release_asset(self):
        config = self.fixture()
        base = serve(self, self.release_reference(config), redirect=True)
        with mock.patch.dict(os.environ, {"REPOE_RELEASE_BASE_URL": base}):
            with self.assertRaisesRegex(ValueError, "game/9.9-1 pobr-game-9.9.zip is not cached; rerun with --fetch"):
                self.run_build(config)
            out, receipt, outcome = self.run_build(config, fetch=True)
        self.assertTrue(outcome["package"]["identical_to_reference"])
        self.assertEqual((out / "game-build-part.zip").read_bytes(), self.previous_raw)
        self.assertEqual(receipt["inputs"]["packages"]["previous"]["tag"], "game/9.9-1")
        self.assertNotIn("previous", receipt["inputs"]["tags"])
        cached = self.root / "cache/inputs/downloads" / hashlib.sha256(self.previous_raw).hexdigest()
        self.assertEqual(cached.read_bytes(), self.previous_raw)
        # Offline from the cache; a corrupt cache entry is refused, never trusted.
        self.assertTrue(self.run_build(config)[2]["package"]["identical_to_reference"])
        cached.write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "Corrupt cache entry"):
            self.run_build(config)

    def test_a_release_asset_must_match_its_pin(self):
        config = self.fixture()
        base = serve(self, self.release_reference(config, raw=b"not the package"))
        with mock.patch.dict(os.environ, {"REPOE_RELEASE_BASE_URL": base}):
            with self.assertRaisesRegex(ValueError, "does not match its pin"):
                self.run_build(config, fetch=True)
        downloads = self.root / "cache/inputs/downloads"
        self.assertEqual(list(downloads.iterdir()) if downloads.exists() else [], [])
        with mock.patch.dict(os.environ, {"REPOE_RELEASE_BASE_URL": base + "/missing"}):
            with self.assertRaisesRegex(ValueError, "Cannot download .*404.*REPOE_RELEASE_TRANSPORT=gh"):
                self.run_build(config, fetch=True)
        lock = json.loads((config / "inputs.lock.json").read_text())
        lock["packages"]["previous"]["path"] = "handoff/prev/game.zip"
        (config / "inputs.lock.json").write_text(json.dumps(lock))
        with self.assertRaisesRegex(ValueError, "no Git path"):
            build.load_config(config)

    def test_gh_transport_downloads_with_gh(self):
        spec = {"repository": "ackness/repoe", "tag": "game/9.9-1", "asset": "a.zip", **pin(b"zip")}
        result = subprocess.CompletedProcess([], 0, b"zip", b"")
        with mock.patch.object(subprocess, "run", return_value=result) as run:
            self.assertEqual(build.assets.download(spec, transport="gh"), b"zip")
        self.assertEqual(run.call_args[0][0][:4], ["gh", "release", "download", "game/9.9-1"])
        with self.assertRaisesRegex(ValueError, "must be https or gh"):
            build.assets.download(spec, transport="ftp")
        with mock.patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired(["gh"], 5)):
            with self.assertRaisesRegex(ValueError, "did not finish within 5 s"):
                build.assets.download(spec, transport="gh", timeout=5)
        with mock.patch.object(subprocess, "run", side_effect=FileNotFoundError("gh")):
            with self.assertRaisesRegex(ValueError, "gh is not available"):
                build.assets.download(spec, transport="gh")

    def test_a_replay_without_facts_runs_only_package_derived_jobs(self):
        config = self.fixture()
        lock = json.loads((config / "inputs.lock.json").read_text())
        del lock["facts"]
        (config / "inputs.lock.json").write_text(json.dumps(lock))
        with self.assertRaisesRegex(ValueError, "Adapter jobs need a facts envelope"):
            build.load_config(config)
        domains = json.loads((config / "domains.json").read_text())
        del domains["jobs"][0]
        (config / "domains.json").write_text(json.dumps(domains))
        frozen = json.loads((config / "frozen-inputs.json").read_text())
        frozen["members"]["data/9.9/overlay/a.json"] = {
            **frozen["members"]["data/9.9/overlay/frozen.json"],
            **pin(self.derived),
        }
        (config / "frozen-inputs.json").write_text(json.dumps(frozen))
        out, receipt, outcome = build.build(
            config, out=self.root / "out", adapter=self.adapter, cache=self.root / "cache", repo=self.repo
        )
        self.assertIsNone(receipt["inputs"]["facts"])
        self.assertEqual(receipt["summary"], {"passthrough-identical": 1, "frozen": 2})
        self.assertTrue(outcome["package"]["identical_to_reference"])

    def test_template_expansion(self):
        bindings = {"a.b": [1], "nested": {"c": 2}}
        value = {"x": {"$retained": "a.b"}, "y": [{"$retained": "nested.c"}], "z": 3}
        self.assertEqual(build.expand_template(value, bindings), {"x": [1], "y": [2], "z": 3})


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    unittest.main()
