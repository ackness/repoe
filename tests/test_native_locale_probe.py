"""Memory-only locale probing: preserve physical fields and reject bad buffers."""

import hashlib
import json
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

from RePoE import native_locale_probe as probe
from RePoE import schema_candidate
from RePoE.native_tools import pinned_pypoe
from test_native_facts import dat_bytes


class LocaleProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with pinned_pypoe():
            _, cls.spec = schema_candidate._native_specification(
                (schema_candidate.ROOT / "schema/poe2.json").read_bytes()
            )

    def decode(self, name, raw):
        return probe.decode_table(name, raw, expected_bytes=len(raw), expected_sha256=hashlib.sha256(raw).hexdigest())

    def test_all_words_fields_null_order_signed_unicode_and_no_io(self):
        source = {
            "Wordlist": -3,
            "Text": "原名😀",
            "HASH32": 42,
            "Text2": "本地名",
            "Inflection": "",
            "SpawnWeight_Tags": [2, None, 2],
            "SpawnWeight_Values": [-1, 0, 1],
        }
        raw = dat_bytes(self.spec, "Words", [source])
        with (
            patch("builtins.open", side_effect=AssertionError("no files")),
            patch("socket.socket", side_effect=AssertionError("no network")),
        ):
            table = self.decode("Words", raw)
        self.assertEqual(table["rows"][0]["values"], source)
        self.assertEqual(table["validation"]["schema_row_bytes"], 64)
        self.assertFalse(table["patch_certified"])
        self.assertFalse(table["realm_certified"])

    def test_ascendancy_full_row_and_reference_nulls(self):
        raw = dat_bytes(
            self.spec,
            "Ascendancy",
            [
                {
                    "Id": "Witch1",
                    "Name": "血法师",
                    "Character": 4,
                    "BaseAscendancy": None,
                    "Disabled": False,
                    "Unknown0": -17,
                }
            ],
        )
        table = self.decode("Ascendancy", raw)
        row = table["rows"][0]["values"]
        self.assertEqual(len(row), 19)
        self.assertEqual(row["Name"], "血法师")
        self.assertEqual(row["Character"], 4)
        self.assertIsNone(row["BaseAscendancy"])
        self.assertEqual(row["Unknown0"], -17)
        self.assertEqual(table["validation"]["schema_row_bytes"], 165)

    def test_bad_pin_rejects_before_framing(self):
        with self.assertRaisesRegex(ValueError, "byte pin"):
            probe.decode_table("Words", b"bad framing!", expected_bytes=12, expected_sha256="a" * 64)

    def test_bad_width_pointer_encoding_and_array_length_reject(self):
        good = dat_bytes(self.spec, "Words", [{"Text": "sample", "Text2": "样本"}])
        broken_marker = bytearray(good)
        broken_marker[68] = 0
        bad_pointer = bytearray(good)
        struct.pack_into("<Q", bad_pointer, 8, len(good) + 100)
        huge_array = bytearray(good)
        struct.pack_into("<QQ", huge_array, 16, 100001, 8)
        for raw in [bytes(broken_marker), bytes(bad_pointer), bytes(huge_array), good[:-4]]:
            with self.subTest(raw=raw), self.assertRaises((ValueError, UnicodeError)):
                self.decode("Words", raw)

    def test_pair_reports_missing_duplicate_and_nontext_differences(self):
        default = self.decode("Words", dat_bytes(self.spec, "Words", [{"HASH32": 7, "Wordlist": 3, "Text2": "name"}]))
        localized = self.decode(
            "Words",
            dat_bytes(
                self.spec, "Words", [{"HASH32": 7, "Wordlist": 4, "Text2": "名字"}, {"HASH32": 7}, {"HASH32": 9}]
            ),
        )
        result = probe.compare_pair(default, localized)
        self.assertEqual(result["localized_only"], [9])
        self.assertTrue(result["duplicate_or_null_keys"][1])
        self.assertTrue(result["nontext_differences"])
        self.assertFalse(result["patch_certified"])

    def test_embedded_layout_exactly_matches_fixed_native_schema(self):
        schema = (Path(schema_candidate.ROOT) / "schema/poe2.json").read_bytes()
        tables = {table["name"]: table for table in json.loads(schema)["tables"]}
        for name, layout in probe.LAYOUTS.items():
            self.assertEqual(layout, [(field, spec.type) for field, spec in self.spec[name + ".dat"].fields.items()])
            self.assertEqual(
                hashlib.sha256(probe.encoded(tables[name]["columns"])).hexdigest(), probe.COLUMN_PINS[name]
            )
        self.assertEqual(
            hashlib.sha256((Path(schema_candidate.ROOT) / "schema/poe2.json").read_bytes()).hexdigest(),
            probe.SCHEMA_SHA256,
        )

    def test_little_endian_strings_preserve_literal_bom_and_pair_order_is_stable(self):
        source = [{"HASH32": key, "Wordlist": 2, "Text": "\ufeff原文"} for key in [20, 3, 11]]
        default = self.decode("Words", dat_bytes(self.spec, "Words", source))
        self.assertEqual(default["rows"][0]["values"]["Text"], "\ufeff原文")
        localized = self.decode(
            "Words", dat_bytes(self.spec, "Words", [{**row, "Wordlist": 4} for row in reversed(source)])
        )
        result = probe.compare_pair(default, localized)
        self.assertEqual([row["key"] for row in result["nontext_differences"]], [11, 20, 3])

    def test_nine_table_wire_types_and_all_columns_survive(self):
        values = {
            "int": -17,
            "uint": 4294967294,
            "ushort": 65535,
            "byte": -3,
            "float": 1.25,
            "bool": True,
            "ref|string": "原文😀",
            "ref|out": None,
            "ref|generic": None,
            "ref|list|byte": [-128, 0, 127],
            "ref|list|int": [-17, 0, 17],
            "ref|list|ref|out": [3, None, 3],
            "ref|list|ref|generic": [3, None, 3],
        }
        self.assertEqual(len(probe.LAYOUTS), 9)
        for name, layout in probe.LAYOUTS.items():
            source = {field: values[kind] for field, kind in layout}
            decoded = self.decode(name, dat_bytes(self.spec, name, [source]))
            probe.validate_table(decoded)
            self.assertEqual(decoded["rows"][0]["values"], source)


if __name__ == "__main__":
    unittest.main()
