"""Historical selector regressions; fixtures do not require Lua or a client."""

import copy
import json
import unittest

from RePoE.release import pins as package
from RePoE.release import historical_trees as trees


def fixture():
    return [
        {
            "skill": 1200,
            "id": "1200",
            "name": "Attribute",
            "kind": "normal",
            "stats": ["+5 to Strength"],
            "unknown": {"preserve": [None, False, "é"]},
        },
        {"skill": 11741, "id": "11741", "name": "Attribute", "kind": "normal", "stats": ["+5 to Strength"]},
        # Identical text is not evidence of a selectable node.
        {"skill": 10, "id": "fixed", "name": "Strength", "kind": "normal", "stats": ["+5 to Strength"]},
        {"skill": 11, "id": "mixed", "stats": ["+5 to Strength", "+5 to Intelligence"]},
        {"skill": 12, "id": "layout", "unknown": None},
        {"skill": 13, "id": "notable", "name": "Brutal", "kind": "notable", "stats": ["+10 to Strength"]},
    ]


def binding(raw, selectors=(1200, 11741)):
    return {
        "input": package.pin(raw),
        "nodes": len(package.decode(raw)),
        "selectors": len(selectors),
        "selector_ids": package.pin(package.encoded(sorted(selectors))),
    }


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.nodes = fixture()
        self.raw = trees.runtime_encoded(self.nodes)
        self.binding = binding(self.raw)

    def test_selectors_preserve_identity_and_every_other_field_fixed_nodes_stay_fixed(self):
        raw, receipt = trees.project(self.raw, self.binding)
        actual = json.loads(raw)
        self.assertEqual(actual[0]["stats"], ["+5 to any Attribute"])
        self.assertEqual(actual[1]["stats"], ["+5 to any Attribute"])
        for original, node in zip(self.nodes, actual):
            expected = copy.deepcopy(original)
            if original["skill"] in (1200, 11741):
                expected["stats"] = ["+5 to any Attribute"]
            self.assertEqual(node, expected)
        self.assertEqual(actual[2]["stats"], ["+5 to Strength"])
        self.assertEqual(receipt["selector_ids"], [1200, 11741])
        self.assertEqual(receipt["unchanged_nodes"], 4)
        self.assertEqual(receipt["input"], package.pin(self.raw))
        self.assertEqual(receipt["output"], package.pin(raw))
        self.assertEqual((raw, receipt), trees.project(self.raw, self.binding))
        self.assertEqual(self.nodes, json.loads(self.raw), "projection must not mutate its input")

    def test_no_text_only_name_only_or_count_only_reclassification(self):
        for change in ("new_name", "new_id", "swapped_identity", "different_amount", "already_fixed"):
            nodes = copy.deepcopy(self.nodes)
            if change == "new_name":
                nodes[2].update(name="Attribute", id="10")
            elif change == "new_id":
                nodes[0].update(skill=200, id="200")
            elif change == "swapped_identity":
                nodes[0]["name"] = "Strength"
                nodes[2].update(name="Attribute", id="10")
            elif change == "different_amount":
                nodes[0]["stats"] = ["+10 to Strength"]
            else:
                nodes[0]["stats"] = ["+5 to any Attribute"]
            raw = trees.runtime_encoded(nodes)
            # Even rebinding a changed file cannot silently change reviewed IDs.
            review = {**self.binding, "input": package.pin(raw)}
            with self.subTest(change=change), self.assertRaises(ValueError):
                trees.project(raw, review)

    def test_shape_identity_inventory_and_raw_pin_guards(self):
        for key, value in (
            ("kind", "notable"),
            ("id", "not-the-reviewed-slug"),
            ("native_stats", {"flat": 5}),
            ("variants", [{"class": "Warrior", "stats": []}]),
            ("ascendancy_id", "Warrior1"),
            ("apply_to_armour", True),
            ("stats", ["+5 to Strength", "an extra effect"]),
            ("skill", True),
            ("skill", 11741),
        ):
            nodes = copy.deepcopy(self.nodes)
            nodes[0][key] = value
            raw = trees.runtime_encoded(nodes)
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                trees.project(raw, {**self.binding, "input": package.pin(raw)})
        with self.assertRaisesRegex(ValueError, "Byte pin"):
            trees.project(self.raw + b"\n", self.binding)
        with self.assertRaisesRegex(ValueError, "inventory"):
            trees.project(self.raw, {**self.binding, "nodes": 99})

    def test_duplicate_json_keys_fail_closed(self):
        raw = self.raw.replace(b'"skill": 1200', b'"skill": 99, "skill": 1200')
        with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
            trees.project(raw, {**self.binding, "input": package.pin(raw)})


if __name__ == "__main__":
    unittest.main()
