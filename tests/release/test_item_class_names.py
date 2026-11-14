"""ItemClasses projection rules with synthetic client strings."""

import unittest

from RePoE.release import item_class_names

TARGET = {"game": "poe2", "game_patch": "9.9", "realm": "international"}


def table(values):
    return {"table": "ItemClasses", "rows": [{"_row": index, "values": row} for index, row in enumerate(values)]}


class ItemClassNamesTest(unittest.TestCase):
    def test_preserves_raw_ids_and_names_and_counts_skipped_names(self):
        values = [
            {"Id": "Z", "Name": "Shared"},
            {"Id": " A ", "Name": "[Name|Names] \r\n"},
            {"Id": "B", "Name": "Shared"},
            {"Id": "Empty", "Name": ""},
            {"Id": "Blank", "Name": " \t\r\n"},
        ]
        document, summary = item_class_names.project(table(values), TARGET)
        self.assertEqual(document["_meta"], {"schema": item_class_names.SCHEMA, **TARGET})
        self.assertEqual(
            document["scopes"], {"ItemClasses.Name": {" A ": "[Name|Names] \r\n", "B": "Shared", "Z": "Shared"}}
        )
        self.assertEqual(list(document["scopes"]["ItemClasses.Name"]), [" A ", "B", "Z"])
        self.assertEqual(summary, {"rows": 5, "emitted": 3, "empty": 1, "whitespace": 1})
        self.assertEqual(item_class_names.project(table(list(reversed(values))), TARGET), (document, summary))

    def test_every_id_is_checked_even_when_its_name_would_be_skipped(self):
        for value in ({}, *({"Id": key} for key in (None, 1, False, [], {}, "", " \t\n"))):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "Id must be a nonblank string"):
                item_class_names.project(table([{**value, "Name": ""}]), TARGET)

    def test_duplicate_ids_refuse_including_identical_or_empty_names(self):
        for names in (("Same", "Same"), ("One", "Two"), ("", ""), (" \t", " \t")):
            with self.subTest(names=names), self.assertRaisesRegex(ValueError, "duplicate Id"):
                item_class_names.project(table([{"Id": "X", "Name": name} for name in names]), TARGET)

    def test_names_must_be_present_strings(self):
        for value in ({}, *({"Name": name} for name in (None, 1, False, [], {}))):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "Name must be a string"):
                item_class_names.project(table([{"Id": "X", **value}]), TARGET)

    def test_table_and_row_shape_are_required(self):
        for value in (None, {}, {"table": "Other", "rows": []}, {"table": "ItemClasses"}, table([]) | {"rows": {}}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                item_class_names.project(value, TARGET)
        for row in (None, {}, {"values": None}, {"values": []}):
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, "row needs values"):
                item_class_names.project({"table": "ItemClasses", "rows": [row]}, TARGET)


if __name__ == "__main__":
    unittest.main()
