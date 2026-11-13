"""Synthetic capture-sc.ps1 output through client:capture: verification, extraction, receipts and refusals."""

from contextlib import contextmanager, redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from unittest.mock import patch

from RePoE.client import capture
from RePoE.client import index

SPEC = importlib.util.spec_from_file_location("draft_fixtures", Path(__file__).with_name("test_source_draft.py"))
fixtures = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixtures)
client = capture.client
bundle_bytes = fixtures.fixtures.bundle_bytes
SEED = 322417471
SCRIPT_SHA256 = "e89de53630ca5a17fb01425c128fa04c7ba1de35f6bed56ae479394dff5a078d"
CSD = "Data/StatDescriptions/gem_stat_descriptions.csd"
DEFAULT = "Data/Balance/GemEffects.datc64"
LOCALE = "Data/Balance/Simplified Chinese/GemEffects.datc64"
CLIENT_ROOT = "C:\\WeGameApps\\rail_apps\\client(2002052)"
# Bundle name → (resources in order). Contents are distinct, so offsets matter.
LAYOUT = {
    "Folders/data/a": [(CSD, b"\xff\xfe" + "description x\r\n".encode("utf-16-le")), (DEFAULT, b"default-gem" * 9)],
    "Folders/data/10/b": [(LOCALE, "简体宝石".encode() * 7)],
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def index_raw(layout, extra_records=()):
    names = list(layout)
    raws = {name: b"".join(raw for _, raw in layout[name]) for name in names}
    table = struct.pack("<I", len(names))
    for name in names:
        table += struct.pack("<I", len(name)) + name.encode() + struct.pack("<I", len(raws[name]))
    records = []
    for number, name in enumerate(names):
        offset = 0
        for path, raw in layout[name]:
            records.append((index.hash64(path.lower().encode(), SEED), number, offset, len(raw)))
            offset += len(raw)
    records += list(extra_records)
    files = struct.pack("<I", len(records)) + b"".join(struct.pack("<QIII", *r) for r in records)
    directories = struct.pack("<I", 1) + struct.pack("<QIII", index.hash64(b"", SEED), 0, 0, 0)
    return table + files + directories + b"unparsed-directory-names", raws


def ident(path, raw):
    return {"path": path, "bytes": len(raw), "sha256": sha(raw), "mtime_utc": "2026-10-28T02:19:59.2937595Z"}


class LocatedDecoder(fixtures.DraftDecoder):
    def __init__(self, python, lock_path, source):
        super().__init__(python, lock_path, source)
        self.identity.update(executable=str(python), module_path=str(python.parent / "ooz.so"))
        self.receipt = {
            **self.receipt,
            **self.identity,
            "identity_sha256": sha(client.encoded(self.identity)),
            "uv_lock_path": str(python.parent / "uv.lock"),
        }


class CaptureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="repoe-capture-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        patcher = patch.object(capture, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.capture = self.root / "sc-capture-20261105T133039Z"
        self.request = self.root / "request.json"
        self.lock = self.root / "uv.lock"
        self.out = self.root / ".cache" / "capture"
        self.lock.write_bytes(b"synthetic decoder lock\n")
        self.paths = [CSD, DEFAULT, LOCALE]
        self.write_request()
        self.files = {}
        raw, bundles = index_raw(LAYOUT)
        self.files["_.index.bin"] = bundle_bytes(raw, chunk_size=32)
        for name, content in bundles.items():
            self.files[name + ".bundle.bin"] = bundle_bytes(content, chunk_size=16)
        self.files["Tiny.V0.1.bundle.bin"] = bundle_bytes(b"unrelated", chunk_size=16)
        self.document = None
        self.write_capture()

    def write_request(self):
        self.request.write_text(json.dumps({"schema": capture.REQUEST_SCHEMA, "resources": self.paths}, indent=2))

    def write_capture(self, document=None, sums=None):
        """Write the capture the way capture-sc.ps1 does; return the capture.json SHA-256."""
        if self.capture.exists():
            shutil.rmtree(self.capture)
        for name, raw in self.files.items():
            path = self.capture / "Bundles2" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        entries = [ident(name, raw) for name, raw in sorted(self.files.items())]
        self.document = document or {
            "schema": capture.CAPTURE_SCHEMA,
            "realm_declared": "china",
            "captured_utc": "20261105T133039Z",
            "client_root": CLIENT_ROOT,
            "index": ident("_.index.bin", self.files["_.index.bin"]),
            "executables": [
                {
                    "name": "PathOfExile_x64.exe",
                    "bytes": 77922344,
                    "sha256": "2b" * 32,
                    "file_version": "0.5.5.172",
                    "product_version": "0.5.5.172",
                    "mtime_utc": "2026-10-28T02:19:59.5757615Z",
                }
            ],
            "files": entries,
            "total_bytes": sum(e["bytes"] for e in entries),
            "script_sha256": SCRIPT_SHA256,
        }
        raw = (json.dumps(self.document, indent=4, ensure_ascii=False) + "\n").encode()
        (self.capture / "capture.json").write_bytes(raw)
        if sums is None:
            sums = "".join(f"{e['sha256']}  Bundles2/{e['path']}\n" for e in self.document["files"])
        (self.capture / "SHA256SUMS").write_text(sums)
        self.capture_sha = sha(raw)
        return self.capture_sha

    def run_capture(
        self,
        out=None,
        expected=None,
        game_patch="0.5.5.5",
        decoder=fixtures.DraftDecoder,
        python=Path("/explicit/python"),
        api=capture.capture,
    ):
        args = (self.capture, expected or self.capture_sha, self.request)
        if api is capture.capture:
            args += (game_patch,)
        with patch.object(client, "ExternalDecoder", decoder):
            return api(*args, out or self.out, python, self.lock)

    def cli_args(self, *options, out=None):
        return [
            "--capture", str(self.capture), "--expect-capture-sha256", self.capture_sha,
            "--request", str(self.request), "--out", str(out or self.out),
            "--decoder-python", "/explicit/python", "--decoder-lock", str(self.lock), *options,
        ]  # fmt: skip

    def refused(self, pattern, error=ValueError):
        with self.assertRaisesRegex(error, pattern):
            self.run_capture()
        self.assertFalse(self.out.exists())

    def test_committed_script_is_byte_exact_and_not_normalized(self):
        self.assertEqual(sha(capture.SCRIPT.read_bytes()), SCRIPT_SHA256)
        attributes = (Path(__file__).resolve().parents[2] / ".gitattributes").read_text().splitlines()
        self.assertIn("RePoE/client/capture-sc.ps1 -text", attributes)

    def test_decoder_declaration_equals_the_native_table_pins(self):
        from RePoE.native import facts

        self.assertEqual(capture.DECODER["revision"], facts.PYPOE)
        self.assertEqual(capture.DECODER["dat_schema_revision"], facts.SCHEMA)
        self.assertEqual(capture.DECODER["schema_sha256"], facts.SCHEMA_SHA)

    def test_collection_requests_include_text_and_name_pairs_in_both_languages(self):
        inventories = {
            "china-text-request-2.json": ("ActiveSkills", "GemEffects", "ItemClasses", "MonsterVarieties"),
            "china-names-request-1.json": (
                "AlternateQualityTypes",
                "Ascendancy",
                "BaseItemTypes",
                "Characters",
                "Mods",
                "PassiveSkills",
                "Words",
            ),
        }
        seen = set()
        for filename, tables in inventories.items():
            request = Path(capture.__file__).with_name(filename)
            paths, groups, _ = capture.load_request(request)
            for group, prefix in (("default", ""), ("Simplified Chinese", "Simplified Chinese/")):
                with self.subTest(request=filename, group=group):
                    self.assertEqual(groups[group], [f"Data/Balance/{prefix}{table}.datc64" for table in tables])
            self.assertTrue(seen.isdisjoint(paths))
            seen.update(paths)
            if filename == "china-text-request-2.json":
                published = Path(capture.__file__).with_name("china-text-request.json")
                _, old_groups, _ = capture.load_request(published)
                self.assertEqual(groups["stat-descriptions"], old_groups["stat-descriptions"])
                self.assertEqual(len(paths), 35)
            else:
                self.assertEqual(set(groups), {"default", "Simplified Chinese"})
                self.assertEqual(len(paths), 14)

    def test_extracts_raw_resources_receipt_and_a_lock_the_candidates_accept(self):
        receipt, receipt_raw, lock_raw = self.run_capture()
        for _, resources in LAYOUT.items():
            for path, raw in resources:
                self.assertEqual((self.out / "raw" / path).read_bytes(), raw)
        self.assertEqual(
            sorted(p.name for p in self.out.iterdir()),
            sorted(["raw", "capture-receipt.json", "source-lock.json", "request.json", "SHA256SUMS"]),
        )
        self.assertEqual((self.out / "capture-receipt.json").read_bytes(), receipt_raw)
        self.assertEqual((self.out / "SHA256SUMS").read_bytes(), (self.capture / "SHA256SUMS").read_bytes())
        self.assertEqual((self.out / "request.json").read_bytes(), self.request.read_bytes())
        self.assertEqual(receipt["game_patch"], "0.5.5.5")
        self.assertEqual(receipt["realm"], "china")
        self.assertEqual(receipt["capture"]["capture_json"]["sha256"], self.capture_sha)
        self.assertEqual(receipt["observed_client"]["executables"][0]["file_version"], "0.5.5.172")
        self.assertEqual(receipt["resources"][LOCALE]["bundle"], "Folders/data/10/b")
        self.assertEqual(receipt["resources"][DEFAULT]["uncompressed_offset"], len(LAYOUT["Folders/data/a"][0][1]))
        self.assertEqual(set(receipt["bundles"]), {"Folders/data/a", "Folders/data/10/b"})
        # No install path, timestamp of a client file or host path is carried forward.
        for raw in (receipt_raw, lock_raw):
            text = raw.decode()
            for forbidden in ('client_root":', "WeGameApps", ":\\\\", 'mtime_utc":', str(self.root)):
                self.assertNotIn(forbidden, text)
        lock = json.loads(lock_raw)
        self.assertEqual(set(lock["sources"]), {"china-stat-descriptions", "china-default", "china-simplified-chinese"})
        evidence = lock["sources"]["china-default"]["acquisition"]["evidence"]
        self.assertEqual(
            evidence,
            [
                {"kind": "client-capture-json", "sha256": self.capture_sha},
                {"kind": "client-capture-receipt", "sha256": sha(receipt_raw)},
                {"kind": "local-index", "sha256": sha(self.files["_.index.bin"])},
            ],
        )
        self.assertEqual(lock["sources"]["china-stat-descriptions"]["roots"], [CSD])
        self.assertEqual(lock["sources"]["china-simplified-chinese"]["language"], "Simplified Chinese")

        from RePoE.native import descriptions, tables

        lock_path, lock_sha = self.out / "source-lock.json", sha(lock_raw)
        _, _, verified, _ = descriptions._inputs(lock_path, "china-stat-descriptions", self.out / "raw", lock_sha)
        self.assertEqual(set(verified), {CSD})
        _, _, verified, _ = tables._inputs(lock_path, "china-default", self.out / "raw", lock_sha)
        self.assertEqual(set(verified), {DEFAULT})
        _, _, verified, _ = tables._inputs(
            lock_path, "china-simplified-chinese", self.out / "raw", lock_sha, "Simplified Chinese"
        )
        self.assertEqual(set(verified), {LOCALE})

    def test_replay_is_byte_identical(self):
        _, receipt, lock = self.run_capture()
        _, again, lock_again = self.run_capture(out=self.root / ".cache" / "again")
        self.assertEqual((receipt, lock), (again, lock_again))

    def test_separate_requests_share_capture_identity_and_failure_keeps_the_main_output(self):
        self.paths = [CSD, DEFAULT]
        self.write_request()
        main, main_raw, main_lock = self.run_capture()
        self.paths = [LOCALE]
        self.write_request()
        names, _, _ = self.run_capture(out=self.root / ".cache" / "names")
        for key in ("capture", "observed_client"):
            self.assertEqual(main[key], names[key])
        self.assertNotEqual(main["request"], names["request"])
        self.assertEqual(set(main["resources"]), {CSD, DEFAULT})
        self.assertEqual(set(names["resources"]), {LOCALE})
        self.paths.append("Data/Balance/Simplified Chinese/Words.datc64")
        self.write_request()
        failed = self.root / ".cache" / "failed-names"
        with self.assertRaisesRegex(ValueError, "Paths not found in the captured index"):
            self.run_capture(out=failed)
        self.assertFalse(failed.exists())
        self.assertEqual((self.out / "capture-receipt.json").read_bytes(), main_raw)
        self.assertEqual((self.out / "source-lock.json").read_bytes(), main_lock)

    def test_decoder_relocation_is_byte_identical(self):
        first, receipt, lock = self.run_capture(decoder=LocatedDecoder, python=Path("/home/alice/venv/python"))
        _, again, lock_again = self.run_capture(
            out=self.root / ".cache" / "relocated", decoder=LocatedDecoder, python=Path("/opt/decoder/python")
        )
        self.assertEqual((receipt, lock), (again, lock_again))
        self.assertEqual(
            first["decoder"]["identity_sha256"], sha(client.encoded({"version": "0.0.8", "synthetic": True}))
        )
        self.assertNotIn(b"alice", receipt)

    def test_nonportable_executable_versions_are_omitted_but_capture_hash_is_preserved(self):
        for number, version in enumerate(
            (
                r"C:\Users\alice\build\0.5.5.172",
                "/home/alice/build/0.5.5.172",
                "/Users/alice/0.5.5.172",
                "alice",
                "0.5.5.172-alice",
                "0.5.5.172 (alice)",
                None,
            )
        ):
            with self.subTest(version=version):
                self.document["executables"][0].update(file_version=version, product_version=version)
                self.write_capture(self.document)
                receipt, receipt_raw, lock_raw = self.run_capture(out=self.root / ".cache" / f"version-{number}")
                exe = receipt["observed_client"]["executables"][0]
                self.assertNotIn("file_version", exe)
                self.assertNotIn("product_version", exe)
                self.assertEqual(receipt["capture"]["capture_json"]["sha256"], self.capture_sha)
                for raw in (receipt_raw, lock_raw):
                    self.assertNotIn(b"alice", raw)
                    self.assertNotIn(b"/home/", raw)
                    self.assertNotIn(b"Users", raw)

    def test_portable_executable_versions_are_preserved(self):
        self.document["executables"][0].update(file_version="0.5.5.172-rc1", product_version="0.5.5.172")
        self.write_capture(self.document)
        receipt, _, _ = self.run_capture()
        exe = receipt["observed_client"]["executables"][0]
        self.assertEqual(exe["file_version"], "0.5.5.172-rc1")
        self.assertEqual(exe["product_version"], "0.5.5.172")

    def test_bundle_cache_is_released_after_each_bundle(self):
        # Interleave the request to ensure a bundle's resources are processed together.
        self.paths = [CSD, LOCALE, DEFAULT]
        self.write_request()
        add = capture.LocalRanges.add
        caches = []

        def checked_add(cache, url, raw):
            self.assertEqual(cache.files, {})
            caches.append(cache)
            add(cache, url, raw)

        with patch.object(capture.LocalRanges, "add", checked_add):
            self.run_capture()
        self.assertEqual(len(caches), 3)  # index and two selected bundles
        self.assertTrue(all(not cache.files for cache in caches))

    def test_capture_mutations_during_extraction_prevent_completion(self):
        read = client.Bundle.read
        unused = self.capture / "Bundles2/Tiny.V0.1.bundle.bin"
        selected = self.capture / "Bundles2/Folders/data/a.bundle.bin"
        extra = self.capture / "Bundles2/extra.bin"
        external = self.root / "external.bin"
        external.write_bytes(unused.read_bytes())

        def corrupt(path):
            raw = path.read_bytes()
            path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))

        def symlink():
            unused.unlink()
            unused.symlink_to(external)

        mutations = (
            (lambda: corrupt(unused), "SHA-256 mismatch"),
            (lambda: corrupt(selected), "SHA-256 mismatch"),
            (unused.unlink, "missing"),
            (selected.unlink, "missing"),
            (lambda: extra.write_bytes(b"unexpected"), "extra"),
            (lambda: extra.mkdir(), "directories differ"),
            (symlink, "Symlink"),
        )
        for number, (mutate, error) in enumerate(mutations):
            with self.subTest(number=number):
                self.write_capture()
                changed = False

                def changing_read(bundle, start, length):
                    nonlocal changed
                    raw = read(bundle, start, length)
                    if not changed and bundle.url.endswith(".bundle.bin"):
                        mutate()
                        changed = True
                    return raw

                out = self.root / ".cache" / f"mutated-{number}"
                with patch.object(client.Bundle, "read", changing_read):
                    with self.assertRaisesRegex(ValueError, error):
                        self.run_capture(out=out)
                self.assertTrue(changed)
                self.assertFalse((out / "source-lock.json").exists())

    def test_refuses_to_reuse_output_or_write_outside_cache(self):
        self.run_capture()
        before = (self.out / "source-lock.json").read_bytes()
        with self.assertRaisesRegex(FileExistsError, "reuse"):
            self.run_capture()
        self.assertEqual((self.out / "source-lock.json").read_bytes(), before)
        with self.assertRaisesRegex(ValueError, r"\.cache"):
            self.run_capture(out=self.root / "elsewhere")
        self.assertFalse((self.root / "elsewhere").exists())
        self.capture = self.root / ".cache" / "sc-capture"
        self.write_capture()
        with self.assertRaisesRegex(ValueError, "separate"):
            self.run_capture(out=self.capture / "out")

    def test_capture_sha_and_script_sha_must_match(self):
        with self.assertRaisesRegex(ValueError, "expected"):
            self.run_capture(expected="0" * 64)
        self.assertFalse(self.out.exists())
        document = {**self.document, "script_sha256": "1" * 64}
        self.write_capture(document)
        self.refused("script_sha256")

    def test_hash_or_size_mismatch_is_refused(self):
        name = "Folders/data/a.bundle.bin"
        raw = (self.capture / "Bundles2" / name).read_bytes()
        (self.capture / "Bundles2" / name).write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        self.refused("SHA-256 mismatch")
        self.write_capture()
        (self.capture / "Bundles2" / name).write_bytes(raw + b"x")
        self.refused("mismatch")
        self.write_capture()
        sums = (self.capture / "SHA256SUMS").read_text().replace(sha(raw), "f" * 64)
        self.write_capture(sums=sums)
        self.refused("SHA256SUMS and capture.json")

    def test_extra_or_missing_files_are_refused(self):
        (self.capture / "Bundles2" / "Folders" / "stray.bundle.bin").write_bytes(b"x")
        self.refused("extra")
        self.write_capture()
        (self.capture / "notes.txt").write_text("x")
        self.refused("Unexpected capture contents")
        self.write_capture()
        (self.capture / "Bundles2" / "Tiny.V0.1.bundle.bin").unlink()
        self.refused("missing")

    def test_symlinks_are_refused(self):
        name = self.capture / "Bundles2" / "Tiny.V0.1.bundle.bin"
        copy = self.root / "copy.bin"
        shutil.copyfile(name, copy)
        name.unlink()
        os.symlink(copy, name)
        self.refused("Symlink")
        self.write_capture()
        linked = self.root / "linked-capture"
        os.symlink(self.capture, linked)
        self.capture = linked
        self.refused("Symlink")

    def test_traversal_and_unexpected_paths_are_refused(self):
        document = {**self.document}
        document["files"] = [*self.document["files"], ident("../outside.bin", b"x")]
        self.write_capture(document)
        self.refused("Unsafe relative path")
        self.write_capture()
        self.paths = [CSD, "Data/Balance/French/GemEffects.datc64"]
        self.write_request()
        self.refused("Unsupported capture resource")

    def test_missing_path_or_bundle_is_refused(self):
        self.paths = [CSD, "Data/Balance/ActiveSkills.datc64"]
        self.write_request()
        self.refused("Paths not found in the captured index: Data/Balance/ActiveSkills.datc64")
        self.paths = [CSD, LOCALE]
        self.write_request()
        del self.files["Folders/data/10/b.bundle.bin"]
        self.write_capture()
        self.refused(r"-Extra 'Folders/data/10/b.bundle.bin'")

    def test_bundle_raw_size_must_equal_the_index(self):
        content = b"".join(raw for _, raw in LAYOUT["Folders/data/10/b"])
        self.files["Folders/data/10/b.bundle.bin"] = bundle_bytes(content + b"tail", chunk_size=16)
        self.write_capture()
        for api in (capture.capture, capture.observe):
            with self.subTest(api=api.__name__), self.assertRaisesRegex(ValueError, "differs from the index"):
                self.run_capture(api=api)
            self.assertFalse(self.out.exists())

    def test_preflight_reports_all_missing_paths_and_bundles_without_resource_reads(self):
        missing = ["Data/Balance/Words.datc64", "Data/Balance/Characters.datc64"]
        self.paths += missing
        self.write_request()
        for name in LAYOUT:
            del self.files[name + ".bundle.bin"]
        self.write_capture()
        read = client.Bundle.read

        def index_only(bundle, start, length):
            self.assertTrue(bundle.url.endswith("/_.index.bin"))
            return read(bundle, start, length)

        with patch.object(client.Bundle, "read", index_only):
            report, raw = self.run_capture(api=capture.preflight)
        coverage = report["coverage"]
        self.assertTrue(report["complete"])
        self.assertFalse(coverage["extraction_ready"])
        self.assertEqual(coverage["missing_paths"], sorted(missing))
        self.assertEqual(
            coverage["missing_bundles"],
            [
                {"file": name + ".bundle.bin", "resources": sorted(path for path, _ in LAYOUT[name])}
                for name in sorted(LAYOUT)
            ],
        )
        self.assertEqual((coverage["matched_count"], coverage["required_bundle_count"]), (3, 2))
        self.assertEqual(coverage["available_bundle_count"], 0)
        self.assertEqual(report["extra_bundles"], sorted(name + ".bundle.bin" for name in LAYOUT))
        self.assertEqual([path.name for path in self.out.iterdir()], ["manifest.json"])
        self.assertEqual((self.out / "manifest.json").read_bytes(), raw)
        failed = self.root / ".cache" / "missing"
        with self.assertRaises(capture.CoverageError) as raised:
            self.run_capture(api=capture.observe, out=failed)
        self.assertEqual(raised.exception.coverage, coverage)
        self.assertFalse(failed.exists())

    def test_observation_preserves_raw_provenance_and_unknown_identity_on_relocated_replay(self):
        report, raw = self.run_capture(api=capture.observe, decoder=LocatedDecoder, python=Path("/alice/python"))
        _, replay = self.run_capture(
            api=capture.observe,
            out=self.root / ".cache" / "replay",
            decoder=LocatedDecoder,
            python=Path("/other/python"),
        )
        self.assertEqual(raw, replay)
        self.assertEqual(report["schema"], "repoe-client-capture-observation/v1")
        self.assertEqual(report["mode"], "raw")
        self.assertTrue(report["coverage"]["extraction_ready"])
        for identity in (report["source_identity"], report["observed_client"]):
            self.assertIsNone(identity["game_patch"])
            self.assertIsNone(identity["realm"])
        self.assertFalse(report["patch_certified"])
        self.assertFalse(report["realm_certified"])
        self.assertFalse(report["production_ready"])
        self.assertEqual(report["capture"]["realm_declared"], "china")
        self.assertEqual(report["observed_client"]["executables"][0]["file_version"], "0.5.5.172")
        self.assertEqual(report["request"]["resources"], self.paths)
        self.assertEqual(report["capture"]["capture_json"]["sha256"], self.capture_sha)
        self.assertEqual(report["index"]["sha256"], sha(self.files["_.index.bin"]))
        self.assertEqual(
            set(path.name for path in self.out.iterdir()), {".raw", "manifest.json", "request.json", "SHA256SUMS"}
        )
        for bundle, resources in LAYOUT.items():
            offset = 0
            for name, content in resources:
                pin = report["resources"][name]
                self.assertEqual((self.out / pin["file"]).read_bytes(), content)
                self.assertEqual((pin["bytes"], pin["sha256"]), (len(content), sha(content)))
                self.assertEqual((pin["bundle"], pin["uncompressed_offset"]), (bundle, offset))
                self.assertEqual(pin["uncompressed_length"], len(content))
                self.assertEqual(report["bundles"][bundle]["sha256"], sha(self.files[bundle + ".bundle.bin"]))
                offset += len(content)
        for name, pin in report["files"].items():
            copied = (self.out / name).read_bytes()
            self.assertEqual(pin, {"bytes": len(copied), "sha256": sha(copied)})
        self.assertNotIn(b"/alice", raw)
        self.assertEqual(self.out.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.out / ".raw").stat().st_mode & 0o777, 0o700)

    def test_diagnostic_modes_reject_integrity_framing_collisions_and_limits(self):
        original = dict(self.files)
        for api in (capture.preflight, capture.observe):
            for failure in ("pin", "hash", "framing", "collision", "limit", "request"):
                with self.subTest(api=api.__name__, failure=failure):
                    self.files = dict(original)
                    self.paths = [CSD, DEFAULT, LOCALE]
                    expected, limit = None, client.MAX_SELECTED_RAW
                    if failure == "framing":
                        self.files["_.index.bin"] = b"x" * 100
                    elif failure == "collision":
                        index_bytes, _ = index_raw(LAYOUT, [(index.hash64(DEFAULT.lower().encode(), SEED), 0, 0, 1)])
                        self.files["_.index.bin"] = bundle_bytes(index_bytes, chunk_size=32)
                    elif failure == "limit":
                        limit = 1
                    elif failure == "request":
                        self.paths = ["Data/Balance/French/GemEffects.datc64"]
                    self.write_request()
                    self.write_capture()
                    if failure == "pin":
                        expected = "0" * 64
                    elif failure == "hash":
                        (self.capture / "Bundles2/Tiny.V0.1.bundle.bin").write_bytes(b"corrupt")
                    with patch.object(client, "MAX_SELECTED_RAW", limit), self.assertRaises(ValueError):
                        self.run_capture(api=api, expected=expected)
                    self.assertFalse(self.out.exists())

    def test_preflight_availability_does_not_hide_malformed_resource_bundles(self):
        self.files["Folders/data/a.bundle.bin"] = b"x" * 100
        self.write_capture()
        report, _ = self.run_capture(api=capture.preflight)
        self.assertTrue(report["coverage"]["extraction_ready"])
        failed = self.root / ".cache" / "bad-resource"
        with self.assertRaisesRegex(ValueError, "Invalid|Malformed"):
            self.run_capture(api=capture.observe, out=failed)
        self.assertFalse(failed.exists())

    def test_observation_checks_copied_outputs_and_live_inputs_before_completion(self):
        write = client.write_new
        for number, target in enumerate(
            ("request.json", "SHA256SUMS", ".raw/" + DEFAULT, "request", "unused", "lock", "tools")
        ):
            with self.subTest(target=target):
                self.write_capture()
                self.write_request()
                self.lock.write_bytes(b"synthetic decoder lock\n")
                out = self.root / ".cache" / f"changed-{number}"
                identities = [capture.tools(), {"changed": "f" * 64}] if target == "tools" else None

                def changing_write(path, raw):
                    write(path, raw)
                    if path == out / "SHA256SUMS" and target != "tools":
                        changed = {
                            "request": self.request,
                            "unused": self.capture / "Bundles2/Tiny.V0.1.bundle.bin",
                            "lock": self.lock,
                        }.get(target, out / target)
                        data = changed.read_bytes()
                        changed.write_bytes(bytes([data[0] ^ 1]) + data[1:])

                with (
                    patch.object(client, "write_new", changing_write),
                    patch.object(capture, "tools", side_effect=identities, wraps=capture.tools),
                    self.assertRaisesRegex(ValueError, "changed|mismatch"),
                ):
                    self.run_capture(api=capture.observe, out=out)
                self.assertFalse((out / "manifest.json").exists())
                with self.assertRaises(FileExistsError):
                    self.run_capture(api=capture.observe, out=out)

    def test_interrupted_manifest_write_is_removed_and_packaging_refuses_partial_root(self):
        from RePoE.release import inputs

        write, fdopen = client.write_new, os.fdopen
        finishing = False

        def writing(path, raw):
            nonlocal finishing
            finishing = path.name == "manifest.json"
            write(path, raw)

        @contextmanager
        def interrupted(fd, mode):
            with fdopen(fd, mode) as stream:
                if mode == "wb" and finishing:
                    stream.write(b'{"schema":')
                    raise OSError("injected manifest interruption")
                yield stream

        with patch.object(client, "write_new", writing), patch.object(os, "fdopen", interrupted):
            with self.assertRaisesRegex(OSError, "injected"):
                self.run_capture(api=capture.observe)
        self.assertFalse((self.out / "manifest.json").exists())
        with self.assertRaisesRegex(ValueError, "Dot directory"):
            inputs.package("diagnostic", self.out, {"game_patch": "0.5.5.5"}, self.root / "stage")

    def test_existing_release_and_native_ingress_reject_diagnostic_artifacts(self):
        from RePoE.client import export_lock
        from RePoE.native import decoded_tables, descriptions, tables
        from RePoE.release import inputs

        report, raw = self.run_capture(api=capture.observe)
        target = {"game": "poe2", "game_patch": "0.5.5.5", "realm": "china"}
        for name in ("diagnostic", "china_text", "crafting"):
            with self.subTest(package=name), self.assertRaisesRegex(ValueError, "Dot directory"):
                inputs.package(name, self.out, target, self.root / "stage")
        nested = self.root / ".cache" / "nested" / "preflight"
        self.run_capture(api=capture.preflight, out=nested)
        with self.assertRaisesRegex(ValueError, "reserved"):
            inputs.package("diagnostic", nested, target, self.root / "stage")
        stage = self.root / "stage"
        stage.mkdir()
        with self.assertRaisesRegex(ValueError, "source_identity.game_patch"):
            inputs.package("diagnostic", nested.parent, target, stage)
        manifest = self.out / "manifest.json"
        for ingress in (tables._inputs, descriptions._inputs):
            with self.subTest(ingress=ingress.__module__), self.assertRaisesRegex(ValueError, "source lock schema"):
                ingress(manifest, "china-default", self.out / ".raw", sha(raw))
        with self.assertRaisesRegex(ValueError, "source lock schema"):
            client.load_source(manifest, "china-default")
        with self.assertRaisesRegex(ValueError, "acquisition source lock"):
            export_lock.create(
                source_lock=manifest, expected_source_lock_sha256=sha(raw), out=self.root / "export.json"
            )
        # Large index hashes can fail the transfer's safe-number guard before its schema guard.
        with self.assertRaises(ValueError):
            decoded_tables._transfer(manifest, sha(raw), self.request)
        self.assertIsNone(report["source_identity"]["game_patch"])

    def test_cli_modes_require_explicit_choice_and_report_coverage_exit_codes(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            for options in ((), ("--preflight", "--observe"), ("--observe", "--game-patch", "0.5.5.5")):
                with self.subTest(options=options), self.assertRaises(SystemExit) as raised:
                    capture.main(self.cli_args(*options))
                self.assertEqual(raised.exception.code, 2)
            for patch_value in (None, "", "unknown"):
                with self.subTest(patch=patch_value), self.assertRaises(ValueError):
                    self.run_capture(game_patch=patch_value)
        self.paths.append("Data/Balance/Words.datc64")
        self.write_request()
        del self.files["Folders/data/10/b.bundle.bin"]
        self.write_capture()
        for flag, code in (("--preflight", 2), ("--observe", 1)):
            out = self.root / ".cache" / flag.removeprefix("--")
            stdout = io.StringIO()
            with (
                patch.object(client, "ExternalDecoder", fixtures.DraftDecoder),
                redirect_stdout(stdout),
                redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as raised,
            ):
                capture.main(self.cli_args(flag, out=out))
            self.assertEqual(raised.exception.code, code)
            report = json.loads(stdout.getvalue())
            self.assertFalse(report["coverage"]["extraction_ready"])
            self.assertEqual(report["coverage"]["missing_paths"], ["Data/Balance/Words.datc64"])
            self.assertEqual(report["extra_bundles"], ["Folders/data/10/b.bundle.bin"])
            self.assertEqual((out / "manifest.json").exists(), flag == "--preflight")

    def test_cli_reports_failure_without_output(self):
        with self.assertRaises(SystemExit) as raised:
            capture.main(
                [
                    "--capture", str(self.capture), "--expect-capture-sha256", "0" * 64,
                    "--request", str(self.request), "--game-patch", "0.5.5.5", "--out", str(self.out),
                    "--decoder-python", "/explicit/python", "--decoder-lock", str(self.lock),
                ]
            )  # fmt: skip
        self.assertEqual(raised.exception.code, 1)
        self.assertFalse(self.out.exists())


if __name__ == "__main__":
    unittest.main()
