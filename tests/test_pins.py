"""Exercise the shared byte-pin, strict-JSON and archive-manifest helpers."""

import io
import stat
import unittest
import zipfile

from RePoE import pins


class PinsTests(unittest.TestCase):
    def setUp(self):
        self.data = {"facts.json": b'{"value":0,"unknown":null}\r\n', "policy.json": b'{"rule":"owned-by-consumer"}'}
        self.manifest = pins.encoded({"files": {name: pins.pin(raw) for name, raw in self.data.items()}})
        self.spec = {
            "manifest": pins.pin(self.manifest),
            "expanded_bytes": sum(map(len, self.data.values())) + len(self.manifest),
        }

    def archive(self, extra=None):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("manifest.json", self.manifest)
            for name, raw in self.data.items():
                archive.writestr(name, raw)
            if extra:
                archive.writestr(*extra)
        return zipfile.ZipFile(io.BytesIO(buffer.getvalue()))

    def test_archive_manifest_checks_inventory_and_member_sizes(self):
        with self.archive() as archive:
            raw, manifest = pins.archive_manifest(archive, self.spec)
        self.assertEqual(raw, self.manifest)
        self.assertEqual(set(manifest["files"]), set(self.data))

    def test_unsafe_duplicate_and_nonregular_zip_members_rejected(self):
        for name in [".", "../escape", "/absolute", "foo\\bar", "foo:stream", "a/./b", "a//b", "a\nb"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                pins.relative(name)
        info = zipfile.ZipInfo("link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.archive((info, b"facts.json")) as archive, self.assertRaisesRegex(ValueError, "Non-regular"):
            pins.archive_manifest(archive, self.spec)
        with self.assertWarns(UserWarning):
            archive = self.archive(("facts.json", b"duplicate"))
        with archive, self.assertRaisesRegex(ValueError, "Duplicate"):
            pins.archive_manifest(archive, self.spec)

    def test_duplicate_json_and_invalid_expanded_size_rejected(self):
        with self.assertRaises(ValueError):
            pins.decode(b'{"files":{},"files":{}}')
        with self.assertRaises(ValueError):
            pins.decode(b'{"value":NaN}')
        self.spec["expanded_bytes"] += 1
        with self.archive() as archive, self.assertRaisesRegex(ValueError, "Expanded size"):
            pins.archive_manifest(archive, self.spec)

    def test_pins(self):
        good = pins.pin(b"abc")
        self.assertEqual(pins.pinned(b"abc", good), b"abc")
        with self.assertRaisesRegex(ValueError, "mismatch"):
            pins.pinned(b"abd", good)
        pins.byte_pin(good)
        for bad in ({**good, "extra": 1}, {"bytes": -1, "sha256": good["sha256"]}, {"bytes": 3, "sha256": "X" * 64}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                pins.byte_pin(bad)
        pins.validate_pin({**good, "extra": 1})


if __name__ == "__main__":
    unittest.main()
