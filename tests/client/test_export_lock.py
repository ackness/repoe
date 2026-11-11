"""Acquisition-to-export lock conversion preserves claims and rejects unpinned inputs."""

import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest

from RePoE.client import export_lock, source_io
from RePoE.client.capture import DECODER
from RePoE.native import tables


REHEARSAL_PATH = "docs/data-versioning-20261111/rehearsal-scripts/0558"
REHEARSAL = next(
    (parent / REHEARSAL_PATH for parent in Path(__file__).resolve().parents if (parent / REHEARSAL_PATH).is_dir()),
    Path(__file__).resolve().parents[3] / REHEARSAL_PATH,
)
RESOURCE = "Data/Balance/Test.datc64"


class ExportLockTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="repoe-export-lock-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.acquisition = self.root / "acquisition.json"
        self.out = self.root / "export.json"
        self.raw = b"synthetic table bytes"
        source = {
            "kind": "official-client-resource-candidate",
            "game": "poe2",
            "game_patch": "9.9.9.9",
            "realm": "international",
            "base_url": "https://patch-poe2.poecdn.com/9.9.9.9/",
            "acquisition": {
                "status": "unreviewed-acquisition-draft",
                "evidence": [{"kind": "synthetic", "sha256": "a" * 64}],
            },
            "decoder": DECODER,
            "resources": {
                RESOURCE: {
                    "sha256": source_io.sha256(self.raw),
                    "bytes": len(self.raw),
                    "bundle_url": "https://patch-poe2.poecdn.com/9.9.9.9/Bundles2/test.bundle.bin",
                    "uncompressed_offset": 17,
                    "uncompressed_length": len(self.raw),
                }
            },
            "scope": "Preserve declarations, including 繁中.",
            "future": {"keep": [3, 2, 1]},
        }
        self.lock = {"schema_version": 1, "future": "kept", "sources": {"z": source, "a": copy.deepcopy(source)}}
        self.save()

    def save(self):
        self.original = (json.dumps(self.lock, ensure_ascii=False, indent=2) + "\n").encode()
        self.acquisition.write_bytes(self.original)
        self.sha256 = source_io.sha256(self.original)

    def convert(self, **kwargs):
        return export_lock.create(
            source_lock=self.acquisition, expected_source_lock_sha256=self.sha256, out=self.out, **kwargs
        )

    def test_round_trip_preserves_metadata_order_and_accepts_the_same_raw_bytes(self):
        digest = self.convert()
        exported = source_io.decode(self.out.read_bytes())
        expected = copy.deepcopy(self.lock)
        for source in expected["sources"].values():
            source["resources"][RESOURCE] = {"sha256": source_io.sha256(self.raw), "bytes": len(self.raw)}
        self.assertEqual(self.out.read_bytes(), (json.dumps(expected, ensure_ascii=False, indent=2) + "\n").encode())
        self.assertEqual(list(exported["sources"]), ["z", "a"])
        self.assertEqual(self.acquisition.read_bytes(), self.original)
        raw_root = self.root / "raw"
        (raw_root / RESOURCE).parent.mkdir(parents=True)
        (raw_root / RESOURCE).write_bytes(self.raw)
        _, source, verified, _ = tables._inputs(self.out, "z", raw_root, digest)
        self.assertEqual(source, expected["sources"]["z"])
        self.assertEqual(verified, {RESOURCE: self.raw})
        again = self.root / "again.json"
        export_lock.create(source_lock=self.acquisition, expected_source_lock_sha256=self.sha256, out=again)
        self.assertEqual(self.out.read_bytes(), again.read_bytes())

    def test_source_selection_is_explicit_and_keeps_input_order(self):
        self.convert(sources=["a", "z"])
        self.assertEqual(list(source_io.decode(self.out.read_bytes())["sources"]), ["z", "a"])
        self.out.unlink()
        self.convert(sources=["a"])
        self.assertEqual(list(source_io.decode(self.out.read_bytes())["sources"]), ["a"])
        self.out.unlink()
        for sources in ([], ["absent"], ["z", "z"]):
            with self.subTest(sources=sources), self.assertRaisesRegex(ValueError, "unique, existing"):
                self.convert(sources=sources)
            self.assertFalse(self.out.exists())

    def test_missing_raw_pins_locations_and_invalid_acquisition_records_are_refused(self):
        original = copy.deepcopy(self.lock)
        mutations = [
            *(
                lambda record, key=key: record.pop(key)
                for key in ("sha256", "bytes", "bundle_url", "uncompressed_offset", "uncompressed_length")
            ),
            lambda record: record.update(sha256="invalid"),
            lambda record: record.update(bytes=True),
            lambda record: record.update(uncompressed_offset=-1),
            lambda record: record.update(uncompressed_length=1),
            lambda record: record.update(bundle_url="https://example.com/test.bundle.bin"),
        ]
        for number, mutate in enumerate(mutations):
            with self.subTest(case=number):
                self.lock = copy.deepcopy(original)
                mutate(self.lock["sources"]["a"]["resources"][RESOURCE])
                self.save()
                with self.assertRaises(ValueError):
                    self.convert(sources=["z"])
                self.assertFalse(self.out.exists())

    def test_export_lock_and_wrong_or_missing_external_pin_are_refused(self):
        self.convert()
        self.acquisition.write_bytes(self.out.read_bytes())
        self.sha256 = source_io.sha256(self.acquisition.read_bytes())
        self.out.unlink()
        with self.assertRaisesRegex(ValueError, "pins and locations required"):
            self.convert()
        self.save()
        for digest in ("0" * 64, "", None, "not-a-pin"):
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                export_lock.create(source_lock=self.acquisition, expected_source_lock_sha256=digest, out=self.out)
            self.assertFalse(self.out.exists())
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            export_lock.main(["--source-lock", str(self.acquisition), "--out", str(self.out)])
        self.assertEqual(error.exception.code, 2)

    def test_invalid_json_schema_and_existing_or_symlinked_outputs_are_refused(self):
        for raw in (
            b'{"schema_version": 1, "schema_version": 1}',
            b"[]",
            b'{"schema_version": true}',
            b'{"schema_version": 1, "sources": {}}',
        ):
            with self.subTest(raw=raw):
                self.acquisition.write_bytes(raw)
                self.sha256 = source_io.sha256(raw)
                with self.assertRaises(ValueError):
                    self.convert()
                self.assertFalse(self.out.exists())
        self.save()
        self.out.write_bytes(b"keep")
        with self.assertRaises(FileExistsError):
            self.convert()
        self.assertEqual(self.out.read_bytes(), b"keep")
        self.out.unlink()
        self.out.symlink_to(self.acquisition)
        with self.assertRaisesRegex(ValueError, "Symlinks"):
            self.convert()
        self.assertEqual(self.acquisition.read_bytes(), self.original)

    def test_cached_rehearsal_conversion_matches_the_committed_export_lock_bytes(self):
        acquisition = REHEARSAL / "sources-0.5.5.8.json"
        expected = REHEARSAL / "sources-0.5.5.8-export.json"
        if not acquisition.is_file() or not expected.is_file():
            self.skipTest(f"Optional 0.5.5.8 rehearsal docs are missing: {REHEARSAL}")
        # The recorded export omits facts, which retain their acquisition lock.
        sources = list(source_io.decode(expected.read_bytes())["sources"])
        export_lock.create(
            source_lock=acquisition,
            expected_source_lock_sha256=source_io.sha256(acquisition.read_bytes()),
            out=self.out,
            sources=sources,
        )
        self.assertEqual(self.out.read_bytes(), expected.read_bytes())


if __name__ == "__main__":
    unittest.main()
