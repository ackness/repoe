"""Synthetic capture-sc.ps1 output through client:capture: verification, extraction, receipts and refusals."""

import hashlib
import importlib.util
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
    ):
        with patch.object(client, "ExternalDecoder", decoder):
            return capture.capture(
                self.capture,
                expected or self.capture_sha,
                self.request,
                game_patch,
                out or self.out,
                python,
                self.lock,
            )

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

    def test_decoder_relocation_is_byte_identical(self):
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
        self.refused("differs from the index")

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
