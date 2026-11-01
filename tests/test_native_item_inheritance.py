"""Metadata order/presence, interpretation rejection, closure and source pins."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from RePoE import native_item_inheritance as producer


BASE = "Metadata/Items/Item.it"
CHILD = "Metadata/Items/Rings/Ring.it"


def raw(text):
    return b"\xff\xfe" + text.encode("utf-16le")


def item(parent="nothing", fields='tag = "default"', extra=""):
    return raw(f'version 3\r\nextends "{parent}"\r\nBase\r\n{{\r\n{fields}\r\n}}\r\n{extra}')


class ItemInheritanceTests(unittest.TestCase):
    def setUp(self):
        cache = producer.ROOT / ".cache"
        cache.mkdir(exist_ok=True)
        temp = tempfile.TemporaryDirectory(prefix="item-inheritance-test-", dir=cache)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.raw = self.root / "raw"
        self.lock = self.root / "lock.json"
        self.source = {
            "kind": "official-client-resource-candidate",
            "game": "poe2",
            "game_patch": "0.5.5.5",
            "realm": "international",
            "acquisition": {
                "status": "unreviewed-acquisition-draft",
                "evidence": [{"kind": "test", "sha256": "a" * 64}],
            },
            "roots": [CHILD],
            "resources": {},
        }
        self.put(BASE, item())
        self.put(CHILD, item("Metadata/Items/Item", 'tag = "ring"\r\ntag = "ring"\r\ntag = "default"'))

    def put(self, name, data):
        path = self.raw / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self.source["resources"][name] = {"bytes": len(data), "sha256": producer.envelope._sha(data)}
        self.pin()

    def pin(self):
        self.lock.write_bytes(producer.envelope._json({"schema_version": 1, "sources": {"test": self.source}}))
        self.digest = producer.envelope._sha(self.lock.read_bytes())

    def create(self, name="a"):
        return producer.create_candidate(
            source_lock=self.lock,
            source="test",
            raw=self.raw,
            out=self.root / name,
            expected_source_lock_sha256=self.digest,
        )

    def test_replay_no_network_duplicate_occurrences_and_exact_spans(self):
        with patch("socket.socket", side_effect=AssertionError("network forbidden")):
            first = self.create()
            self.assertEqual(first, self.create("b"))
        doc = json.loads((self.root / "a/inheritance.json").read_bytes())
        root = doc["roots"][CHILD]
        self.assertEqual(root["chain_child_to_parent"], [CHILD, BASE])
        self.assertEqual(len(root["base_tag_occurrences"]), 4)
        self.assertEqual(root["tag_interpretation"]["tags"], ["ring", "default"])
        for name, file in doc["files"].items():
            data = (self.raw / name).read_bytes()
            for field in file["fields"]:
                start, end = field["byte_span"]
                self.assertEqual(data[start:end].decode("utf-16le"), field["raw_text"])
        self.assertFalse(first["production_ready"])
        self.assertFalse(doc["interpretation_policy"]["official_merge_semantics_certified"])
        with self.assertRaises(FileExistsError):
            self.create()

    def test_unknown_nested_blocks_and_repeated_scalars_remain_literal(self):
        self.put(
            CHILD,
            item(
                "Metadata/Items/Item",
                'tag = "ring"\r\nx = 0\r\nx = -7',
                "Future\n{\nNested\n{\nx = 12\n}\n}\nEmpty {}\n",
            ),
        )
        self.create()
        doc = json.loads((self.root / "a/inheritance.json").read_bytes())
        file = doc["files"][CHILD]
        self.assertEqual([f["rhs_literal"] for f in file["fields"] if f["key"] == "x"], ["0", "-7", "12"])
        self.assertEqual([b["scope"] for b in file["blocks"]], [["Base"], ["Future"], ["Future", "Nested"], ["Empty"]])
        self.assertEqual(doc["roots"][CHILD]["tag_interpretation"]["tags"], ["ring", "default"])

    def test_ambiguous_base_blocks_or_nonliteral_tag_reject_interpretation(self):
        for number, data in enumerate(
            [
                item("Metadata/Items/Item", "tag = future_expression"),
                item("Metadata/Items/Item", 'tag = "ring"', 'Base\n{\ntag = "other"\n}\n'),
            ]
        ):
            self.put(CHILD, data)
            self.create(str(number))
            doc = json.loads((self.root / str(number) / "inheritance.json").read_bytes())
            meaning = doc["roots"][CHILD]["tag_interpretation"]
            self.assertEqual(meaning["status"], "rejected")
            self.assertIsNone(meaning["tags"])
            self.assertTrue(meaning["diagnostics"])

    def test_unrecognized_syntax_and_incomplete_files_reject(self):
        for data in [
            b"no BOM",
            raw('extends "nothing"\nFuture()\n'),
            item() + raw("{")[2:],
            raw("version 3\nBase {}\n"),
        ]:
            with self.subTest(data=data), self.assertRaises((ValueError, UnicodeError)):
                producer.parse_item(BASE, data)

    def test_all_raw_pins_checked_before_any_parse(self):
        (self.raw / BASE).write_bytes(item(fields='tag = "changed"'))
        with patch.object(producer, "parse_item", side_effect=AssertionError("must not parse")):
            with self.assertRaisesRegex(ValueError, "fingerprint"):
                self.create()
        self.assertFalse((self.root / "a").exists())

    def test_lock_pin_and_unsafe_paths_reject_before_output(self):
        self.digest = "b" * 64
        with self.assertRaisesRegex(ValueError, "external expected"):
            self.create()
        for name in [
            "Metadata/Items/../escape.it",
            "Metadata/Items/Actor.ot",
            "Metadata/Items/Item.it.it",
            "Metadata/Items/Ring.IT",
        ]:
            with self.assertRaises(ValueError):
                producer.resource_path(name)

    def test_missing_cycle_and_unreachable_resource_reject(self):
        self.put(CHILD, item("Metadata/Items/Absent"))
        with self.assertRaisesRegex(ValueError, "Missing/cyclic/deep"):
            self.create()
        self.put(CHILD, item("Metadata/Items/Rings/Ring"))
        with self.assertRaisesRegex(ValueError, "Missing/cyclic/deep"):
            self.create()
        self.put(CHILD, item("Metadata/Items/Item"))
        self.put("Metadata/Items/Unused.it", item())
        with self.assertRaisesRegex(ValueError, "outside root closure"):
            self.create()

    def test_input_symlink_and_output_outside_cache_reject(self):
        path = self.raw / BASE
        saved = path.with_suffix(".saved")
        path.rename(saved)
        path.symlink_to(saved)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.create()
        with self.assertRaisesRegex(ValueError, "beneath"):
            producer.create_candidate(
                source_lock=self.lock,
                source="test",
                raw=self.raw,
                out=producer.ROOT / "forbidden",
                expected_source_lock_sha256=self.digest,
            )


if __name__ == "__main__":
    unittest.main()
