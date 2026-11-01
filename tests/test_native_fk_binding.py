"""Closed-cycle correspondence and strict-v2 isolation with fixed schema shapes."""

import copy
import unittest

from RePoE import native_decoded_tables as strict
from RePoE import native_facts as facts
from RePoE import native_locale_probe as probe
from RePoE.native_fk_binding import Correspondence, ROLES


def table(name, entries):
    fields = [f for f, _ in probe.LAYOUTS[name]]
    defaults = {
        f: []
        if k.startswith("ref|list|")
        else ""
        if k == "ref|string"
        else False
        if k == "bool"
        else None
        if k.startswith("ref|")
        else 0
        for f, k in probe.LAYOUTS[name]
    }
    return {
        "table": name,
        "physical_fields": fields,
        "columns": facts._columns(strict.schema_tables()[name], fields),
        "rows": [{"_row": i, "values": {**copy.deepcopy(defaults), **v}} for i, v in enumerate(entries)],
    }


def setup(default, target, localized=None):
    sides = {
        "source_default": {"BaseItemTypes": table("BaseItemTypes", default)},
        "source_localized": {"BaseItemTypes": table("BaseItemTypes", localized or default)},
        "target": {"BaseItemTypes": table("BaseItemTypes", target)},
    }
    ns = {
        role: {
            "BaseItemTypes": {
                "role": role,
                "table": "BaseItemTypes",
                "manifest_sha256": str(i + 1) * 64,
                "payload_sha256": "a" * 64,
            }
        }
        for i, role in enumerate(ROLES)
    }
    return sides, ns


class ClosedCycleTests(unittest.TestCase):
    def test_equivalent_reorder_and_v2_reject(self):
        a = [{"Id": "A", "FragmentBaseItemType": 1}, {"Id": "B", "FragmentBaseItemType": 0}]
        b = [{"Id": "B", "FragmentBaseItemType": 1}, {"Id": "A", "FragmentBaseItemType": 0}]
        sides, ns = setup(a, b)
        engine = Correspondence(sides, ns)
        self.assertEqual(engine.edge("BaseItemTypes", "FragmentBaseItemType", 0, 1, "target")["reason_codes"], [])
        default = {**sides["source_default"]["BaseItemTypes"], "raw_identity": {"sha256": "a" * 64}}
        old = strict.bind_table(
            "BaseItemTypes",
            default,
            sides["source_localized"]["BaseItemTypes"],
            sides["target"]["BaseItemTypes"],
            {"raw_identity": {"sha256": "b" * 64}},
        )
        self.assertTrue(all(r["decision"] == "rejected" for r in old["records"]))

    def test_self_cycle_and_late_failure_all_roots(self):
        a = [{"Id": "A", "FragmentBaseItemType": 0}]
        sides, ns = setup(a, a)
        self.assertEqual(
            Correspondence(sides, ns).edge("BaseItemTypes", "FragmentBaseItemType", 0, 0, "target")["reason_codes"], []
        )
        a = [{"Id": "A", "FragmentBaseItemType": 1}, {"Id": "B", "FragmentBaseItemType": 0}]
        for field, value in [("Width", 9), ("Name", "Changed English")]:
            b = copy.deepcopy(a)
            b[1][field] = value
            for order in [[0, 1], [1, 0]]:
                sides, ns = setup(a, b)
                engine = Correspondence(sides, ns)
                for start in order:
                    witness = engine.edge("BaseItemTypes", "FragmentBaseItemType", start, start, "target")
                    self.assertIn("fk-required-structure-mismatch", witness["reason_codes"])
                    self.assertEqual(witness["closure_nodes"], 2)
        localized = copy.deepcopy(a)
        localized[1]["Name"] = "本地文本"
        sides, ns = setup(a, a, localized)
        self.assertFalse(
            Correspondence(sides, ns).edge("BaseItemTypes", "FragmentBaseItemType", 0, 0, "source_localized")[
                "reason_codes"
            ]
        )

    def test_ordered_missing_duplicate_and_bounds(self):
        sides, ns = setup([{"Id": "A"}], [{"Id": "A"}])
        for role in ROLES:
            sides[role]["Mods"] = table("Mods", [{"Id": "X"}, {"Id": "Y"}])
            ns[role]["Mods"] = {**ns[role]["BaseItemTypes"], "table": "Mods"}
        engine = Correspondence(sides, ns)
        self.assertIn(
            "fk-key-mismatch", engine.edge("BaseItemTypes", "Implicit_Mods", [0, 1], [1, 0], "target")["reason_codes"]
        )
        self.assertIn(
            "fk-array-shape-mismatch",
            engine.edge("BaseItemTypes", "Implicit_Mods", [0, 1], [0], "target")["reason_codes"],
        )
        self.assertIn(
            "fk-row-out-of-range", engine.edge("BaseItemTypes", "Implicit_Mods", [0], [8], "target")["reason_codes"]
        )
        sides["target"]["Mods"]["rows"][1]["values"]["Id"] = "X"
        self.assertIn(
            "fk-invalid-or-duplicate-key",
            Correspondence(sides, ns).edge("BaseItemTypes", "Implicit_Mods", [0], [0], "target")["reason_codes"],
        )

    def test_package_role_and_physical_column_bound(self):
        sides, ns = setup([{"Id": "A"}], [{"Id": "A"}])
        first = Correspondence(sides, ns).edge("BaseItemTypes", "FragmentBaseItemType", 0, 0, "target")[
            "closure_sha256"
        ]
        ns["target"]["BaseItemTypes"]["payload_sha256"] = "b" * 64
        self.assertNotEqual(
            first,
            Correspondence(sides, ns).edge("BaseItemTypes", "FragmentBaseItemType", 0, 0, "target")["closure_sha256"],
        )
        ns["target"]["BaseItemTypes"]["role"] = "source_default"
        with self.assertRaisesRegex(ValueError, "namespace"):
            Correspondence(sides, ns)
        for role in ROLES:
            sides[role] = {"Characters": table("Characters", [{"Id": "A"}])}
            ns[role] = {
                "Characters": {
                    "role": role,
                    "table": "Characters",
                    "manifest_sha256": "a" * 64,
                    "payload_sha256": "b" * 64,
                }
            }
            fields = sides[role]["Characters"]["physical_fields"]
            fields[64], fields[65] = fields[65], fields[64]
        with self.assertRaisesRegex(ValueError, "pinned schema"):
            Correspondence(sides, ns)


if __name__ == "__main__":
    unittest.main()
