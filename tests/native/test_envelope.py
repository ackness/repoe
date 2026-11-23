"""Unit tests for shared source-envelope, hashing and strict-JSON helpers."""

from pathlib import Path
import tempfile
import unittest

from RePoE.native import envelope


class EnvelopeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="native-envelope-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.raw = self.root / "raw"
        self.raw.mkdir()
        self.lock = self.root / "lock.json"

    def write_lock(self, payload):
        encoded = envelope.canonical_json(payload)
        self.lock.write_bytes(encoded)
        return encoded, envelope.sha256(encoded)

    def test_json_digest_and_pin_helpers(self):
        raw = envelope.canonical_json({"b": 1, "a": "火"})
        self.assertEqual(raw, '{"a":"火","b":1}\n'.encode())
        self.assertEqual(envelope.decode_json(raw), {"a": "火", "b": 1})
        self.assertTrue(envelope.is_digest(envelope.sha256(raw)))
        self.assertFalse(envelope.is_digest("A" * 64))
        self.assertEqual(envelope.pin(raw), {"bytes": len(raw), "sha256": envelope.sha256(raw)})
        with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
            envelope.decode_json(b'{"a":1,"a":2}')
        with self.assertRaisesRegex(ValueError, "Nonfinite JSON number"):
            envelope.decode_json(b'{"a":NaN}')

    def test_load_source_lock_and_validate_identity(self):
        source = {
            "kind": "official-client-resource-candidate",
            "game": "poe2",
            "game_patch": "0.5.5.8",
            "realm": "international",
            "acquisition": {
                "status": "reviewed-source-input",
                "evidence": [{"kind": "index", "sha256": "a" * 64}],
            },
            "decoder": {"revision": "rev", "schema_sha256": "b" * 64},
        }
        raw_lock, digest = self.write_lock({"schema_version": 1, "sources": {"selected": source}})
        lock_bytes, selected = envelope.load_source_lock(self.lock, "selected", digest)
        self.assertEqual(lock_bytes, raw_lock)
        self.assertEqual(selected, source)
        envelope.validate_source_identity(selected, numeric_patch=True)
        envelope.validate_decoder(selected, {"revision": "rev", "schema_sha256": "b" * 64})
        with self.assertRaisesRegex(ValueError, "external expected byte pin"):
            envelope.load_source_lock(self.lock, "selected", "0" * 64)
        _, bad_schema_digest = self.write_lock({"schema_version": True, "sources": {"selected": source}})
        with self.assertRaisesRegex(ValueError, "Unsupported source lock schema"):
            envelope.load_source_lock(self.lock, "selected", bad_schema_digest)
        with self.assertRaisesRegex(ValueError, "Explicit patch"):
            envelope.validate_source_identity({**source, "game_patch": "1"}, numeric_patch=True)
        with self.assertRaisesRegex(ValueError, "Invalid acquisition evidence"):
            envelope.validate_source_identity(
                {**source, "acquisition": {"status": "reviewed-source-input", "evidence": [{"kind": "x"}]}}
            )
        with self.assertRaisesRegex(ValueError, "pin mismatch: revision"):
            envelope.validate_decoder(selected, {"revision": "other"}, include_key=True)

    def test_verify_raw_resources_checks_bounds_case_collision_and_symlinks(self):
        target = self.raw / "Data/sample.bin"
        target.parent.mkdir(parents=True)
        data = b"hello"
        target.write_bytes(data)
        resources = {"Data/sample.bin": envelope.pin(data)}
        envelope.validate_roots(resources, ["Data/sample.bin"], max_files=4)
        verified, raw_root = envelope.verify_raw_resources(
            self.raw, resources, max_files=4, max_resource_bytes=16, max_total_bytes=16, check_case_collision=True
        )
        self.assertEqual(verified, {"Data/sample.bin": data})
        self.assertEqual(raw_root, self.raw.resolve())

        with self.assertRaisesRegex(ValueError, "Case-colliding"):
            envelope.verify_raw_resources(
                self.raw,
                {"Data/sample.bin": envelope.pin(data), "data/sample.bin": envelope.pin(data)},
                max_files=4,
                max_resource_bytes=16,
                max_total_bytes=32,
                check_case_collision=True,
            )

        backup = self.root / "backup.bin"
        target.rename(backup)
        target.symlink_to(backup)
        with self.assertRaisesRegex(ValueError, "symlink"):
            envelope.verify_raw_resources(self.raw, resources, max_files=4, max_resource_bytes=16, max_total_bytes=16)


if __name__ == "__main__":
    unittest.main()
