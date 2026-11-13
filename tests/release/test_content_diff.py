"""Semantic report regressions: conservative evidence, alignment and encoded budgets."""

import copy
import unittest

from RePoE.release import content_diff
from RePoE.release.pins import encoded

PREFIX = "data/9.9/"


class ContentDiffTest(unittest.TestCase):
    def compare(self, before, after, raw=False, frozen=()):
        previous = {PREFIX + name: value if raw else encoded(value) for name, value in before.items()}
        current = {PREFIX + name: value if raw else encoded(value) for name, value in after.items()}
        classes = {
            name: {
                "class": "frozen"
                if name.removeprefix(PREFIX) in frozen
                else "generated-identical"
                if previous.get(name) == value
                else "generated-different"
            }
            for name, value in current.items()
        }
        return content_diff.compare(current, previous, classes, PREFIX, {name: name for name in previous})

    def member(self, report, name):
        return next(member for member in report["members"] if member["member"] == PREFIX + name)

    def test_exact_typed_identity_leaves_and_real_value_change(self):
        name = "overlay/gem_descriptions.json"
        before = {"_meta": {"facts_manifest_sha256": "a" * 64, "game_patch": "9.8"}, "scopes": {"x": "same"}}
        after = copy.deepcopy(before)
        after["_meta"] = {"facts_manifest_sha256": "b" * 64, "game_patch": "9.9"}
        member = self.member(self.compare({name: before}, {name: after}), name)
        self.assertEqual(member["status"], "identity-only")
        self.assertEqual(member["counts"]["identity_fields"], 2)
        after["scopes"]["x"] = "new fact"
        member = self.member(self.compare({name: before}, {name: after}), name)
        self.assertEqual(member["status"], "content-changed")
        self.assertEqual(member["counts"]["payload_fields"], 1)
        for meta in ({}, {"game_patch": 9.8}, {"game_patch": False}):
            after["_meta"] = meta
            self.assertEqual(
                self.member(self.compare({name: before}, {name: after}), name)["status"], "content-changed"
            )

    def test_policy_evidence_structure_unknown_fields_and_semantic_metadata_survive(self):
        name = "overlay/gem_effects.json"
        before = {
            "_meta": {
                "codec_policy_sha256": "a" * 64,
                "source_identity": {
                    "acquisition": {"status": "draft", "evidence": [{"kind": "receipt", "sha256": "b" * 64}]},
                    "game": "poe2",
                },
            },
            "gems": [],
        }
        mutations = (
            lambda doc: doc["_meta"].update(codec_policy_sha256="c" * 64),
            lambda doc: doc["_meta"]["source_identity"]["acquisition"]["evidence"][0].update(kind="new kind"),
            lambda doc: doc["_meta"]["source_identity"]["acquisition"]["evidence"][0].update(unknown="new field"),
            lambda doc: doc["_meta"]["source_identity"]["acquisition"].update(status="reviewed"),
            lambda doc: doc["_meta"]["source_identity"].update(game="other"),
        )
        for mutate in mutations:
            after = copy.deepcopy(before)
            mutate(after)
            member = self.member(self.compare({name: before}, {name: after}), name)
            self.assertEqual(member["status"], "content-changed")
            self.assertGreater(member["counts"]["metadata_fields"], 0)
            self.assertEqual(member["counts"]["payload_fields"], 0)
        after = copy.deepcopy(before)
        after["_meta"]["source_identity"]["acquisition"]["evidence"][0]["sha256"] = "c" * 64
        self.assertEqual(self.member(self.compare({name: before}, {name: after}), name)["status"], "identity-only")

    def test_identity_wildcards_require_the_producers_container_shapes(self):
        for name, before, after in (
            (
                "overlay/gem_effects.json",
                {"_meta": {"source_identity": {"acquisition": {"evidence": {"entry": {"sha256": "a" * 64}}}}}},
                {"_meta": {"source_identity": {"acquisition": {"evidence": {"entry": {"sha256": "b" * 64}}}}}},
            ),
            (
                "base/monster_scaling.json",
                {"_meta": {"inputs": ["a" * 64]}},
                {"_meta": {"inputs": ["b" * 64]}},
            ),
            (
                "base/passive_tree.json",
                {"node": {"native_stats": {"data_version": "9.8"}}},
                {"node": {"native_stats": {"data_version": "9.9"}}},
            ),
        ):
            with self.subTest(name=name):
                member = self.member(self.compare({name: before}, {name: after}), name)
                self.assertEqual(member["status"], "content-changed")
                self.assertEqual(member["counts"]["identity_fields"], 0)

    def test_escaped_surrogates_cannot_turn_the_optional_report_into_an_encoding_failure(self):
        name = "base/mods.json"
        before = b'[{"id":"\\ud800","value":"old"}]'
        after = b'[{"id":"\\ud800","value":"new"}]'
        report = self.compare({name: before}, {name: after}, raw=True)
        receipt = {"coverage": {"issues": ["D40 evidence"]}}
        content_diff.attach(receipt, report)
        self.assertLessEqual(len(encoded(receipt)), content_diff.RECEIPT_LIMIT)
        self.assertEqual(receipt["coverage"]["issues"], ["D40 evidence"])
        self.assertEqual(report["summary"]["counts"]["changed_entities"], 1)

    def test_oversized_pointer_coordinates_remain_unresolved(self):
        name = "base/passive_tree.json"
        before = [
            {
                "id": "node",
                "native_stats": {
                    "stats": [
                        {
                            "id": "stat",
                            "provenance": {
                                "references": [
                                    {"resource": "tables/Stats.json", "pointer": "/rows/" + "9" * 5000 + "/values/Id"}
                                ]
                            },
                        }
                    ]
                },
            }
        ]
        after = copy.deepcopy(before)
        after[0]["native_stats"]["stats"][0]["provenance"]["references"][0]["pointer"] = "/rows/1/values/Id"
        member = self.member(self.compare({name: before}, {name: after}), name)
        self.assertEqual(member["status"], "unresolved")
        self.assertEqual(member["counts"]["unresolved_references"], 1)

    def test_inserted_entities_do_not_cascade_and_samples_count_every_change(self):
        name = "base/mods.json"
        before = [{"id": str(index), "value": 1} for index in range(20)]
        after = [{"id": "inserted", "value": 7}] + [{**row, "value": 2} for row in before]
        member = self.member(self.compare({name: before}, {name: after}), name)
        self.assertEqual(member["counts"]["added_entities"], 1)
        self.assertEqual(member["counts"]["changed_entities"], 20)
        self.assertEqual(member["counts"]["payload_fields"], 20)
        self.assertEqual(len(member["samples"]["payload_fields"]), content_diff.SAMPLES)
        self.assertEqual(member["omitted_samples"]["payload_fields"], 15)
        self.assertEqual(member["entity_details"]["omitted"], 16)

    def test_dictionary_entities_and_typed_ids_have_truthful_entity_counts(self):
        name = "base/monster_resistances.json"
        before = {"monsters": {"a": {"fire": 1}, "b": {"fire": 2}}}
        after = {"monsters": {"a": {"fire": 3}, "b": {"fire": 4}}}
        self.assertEqual(
            self.member(self.compare({name: before}, {name: after}), name)["counts"]["changed_entities"], 2
        )
        name = "base/mods.json"
        before = [{"id": 1, "value": 0}, {"id": "1", "value": 0}]
        after = [{**row, "value": 1} for row in before]
        self.assertEqual(
            self.member(self.compare({name: before}, {name: after}), name)["counts"]["changed_entities"], 2
        )
        name = "base/granted_effect_levels.json"
        before = {"effect": [{"level": 1, "damage": 2}, {"level": 3, "damage": 4}]}
        after = {"effect": [{"level": 1, "damage": 2}, {"level": 2, "damage": 3}, {"level": 3, "damage": 4}]}
        member = self.member(self.compare({name: before}, {name: after}), name)
        self.assertEqual(member["counts"]["added_entities"], 1)
        self.assertEqual(member["counts"]["payload_fields"], 0)

    def test_dictionary_entity_paths_do_not_merge_distinct_keys_containing_slashes(self):
        name = "overlay/gem_descriptions.json"
        before = {"scopes": {"a/b": {"c": "old"}, "a": {"b/c": "old"}}}
        after = {"scopes": {"a/b": {"c": "new"}, "a": {"b/c": "new"}}}
        member = self.member(self.compare({name: before}, {name: after}), name)
        self.assertEqual(member["counts"]["changed_entities"], 2)
        self.assertEqual(member["entity_details"]["total"], 2)

    def test_duplicate_missing_keys_and_unkeyed_order_are_not_overwritten(self):
        name = "base/mods.json"
        for before, after in (
            ([{"id": "x", "v": 1}, {"id": "x", "v": 2}], [{"id": "x", "v": 3}, {"id": "x", "v": 2}]),
            ([{"id": "x"}, {"v": 1}], [{"id": "x"}, {"v": 2}]),
            ([{"id": True}], [{"id": 1}]),
            ([{"name": "a"}, {"name": "b"}], [{"name": "b"}, {"name": "a"}]),
        ):
            member = self.member(self.compare({name: before}, {name: after}), name)
            self.assertEqual(member["status"], "content-changed")
            self.assertFalse(member["entity_counts_available"])
        member = self.member(self.compare({name: [{"id": "a"}, {"id": "b"}]}, {name: [{"id": "b"}, {"id": "a"}]}), name)
        self.assertEqual(member["counts"]["order_changes"], 1)

    def reference_packages(self, row=7, target="set-a"):
        return {
            "base/granted_effects.json": [{"id": "effect", "stat_set": row, "cost_types": [0]}],
            "base/granted_effect_stat_sets.json": [{"effect_id": "effect", "sets": [{"set_id": target}]}],
            "base/cost_types.json": [{"id": "Mana", "divisor": 1}],
        }

    def test_proven_shift_retarget_and_raw_identical_retarget(self):
        name = "base/granted_effects.json"
        before = self.reference_packages()
        for after, shifts, retargets in (
            (self.reference_packages(row=8), 1, 0),
            (self.reference_packages(row=8, target="set-b"), 0, 1),
            (self.reference_packages(target="set-b"), 0, 1),
        ):
            member = self.member(self.compare(before, after), name)
            self.assertEqual(member["counts"]["row_reference_shifts"], shifts)
            self.assertEqual(member["counts"]["retargeted_references"], retargets)
            self.assertEqual(member["status"], "content-changed" if retargets else "identity-only")
        member = self.member(self.compare(before, self.reference_packages(target="set-b")), name)
        self.assertEqual(member["raw_class"], "generated-identical")

    def test_unresolved_raw_movement_and_unchanged_reference_to_changed_dependency(self):
        name = "base/granted_effects.json"
        before = self.reference_packages()
        before["base/granted_effect_stat_sets.json"] = []
        for changed_row in (False, True):
            after = copy.deepcopy(before)
            after["base/granted_effect_stat_sets.json"] = [{"effect_id": "other", "sets": [{"set_id": "new"}]}]
            if changed_row:
                after[name][0]["stat_set"] += 1
            member = self.member(self.compare(before, after), name)
            self.assertEqual(member["status"], "unresolved")
            self.assertEqual(member["counts"]["unresolved_references"], 1)
            self.assertEqual(member["counts"]["unresolved_raw_changes"], int(changed_row))

    def test_main_set_reorder_and_cost_slot_retarget_stay_content(self):
        before = self.reference_packages()
        before["base/granted_effect_stat_sets.json"][0]["sets"].append({"set_id": "set-b"})
        after = copy.deepcopy(before)
        after["base/granted_effect_stat_sets.json"][0]["sets"].reverse()
        report = self.compare(before, after)
        sets = self.member(report, "base/granted_effect_stat_sets.json")
        self.assertEqual(sets["status"], "content-changed")
        self.assertGreater(sets["counts"]["payload_fields"], 0)
        self.assertEqual(self.member(report, "base/granted_effects.json")["counts"]["retargeted_references"], 1)
        after = copy.deepcopy(before)
        after["base/cost_types.json"][0]["id"] = "Life"
        self.assertEqual(
            self.member(self.compare(before, after), "base/granted_effects.json")["counts"]["retargeted_references"], 1
        )

    def test_frozen_reference_bearing_member_is_still_checked(self):
        before = self.reference_packages()
        after = self.reference_packages(target="new-target")
        member = self.member(
            self.compare(before, after, frozen=("base/granted_effects.json",)), "base/granted_effects.json"
        )
        self.assertEqual(member["raw_class"], "frozen")
        self.assertEqual(member["counts"]["retargeted_references"], 1)

    def test_ambiguous_bidirectional_identity_never_proves_shift(self):
        before = self.reference_packages()
        before["base/granted_effects.json"].append({"id": "alias", "stat_set": 8})
        before["base/granted_effect_stat_sets.json"].append({"effect_id": "alias", "sets": [{"set_id": "set-a"}]})
        after = copy.deepcopy(before)
        after["base/granted_effects.json"][0]["stat_set"] = 9
        member = self.member(self.compare(before, after), "base/granted_effects.json")
        self.assertEqual(member["counts"]["row_reference_shifts"], 0)
        self.assertGreater(member["counts"]["unresolved_references"], 0)

    def test_strict_json_failure_and_unknown_type_distinctions(self):
        name = "base/mods.json"
        for raw in (b'{"id":1,"id":2}', b'{"v":NaN}', b"not json"):
            member = self.member(self.compare({name: raw}, {name: raw}, raw=True), name)
            self.assertEqual(member["status"], "unresolved")
        for before, after in (({"v": 1}, {"v": True}), ({"v": 1}, {"v": 1.0})):
            self.assertEqual(
                self.member(self.compare({name: before}, {name: after}), name)["status"], "content-changed"
            )

    def test_snapshot_reports_stamps_without_claiming_dependencies_equal(self):
        name = "manifest.json"
        before = {"poe_version": "9.8", "files": {"base/a.json": "a" * 64}, "contract_version": 1}
        after = {"poe_version": "9.9", "files": {"base/a.json": "b" * 64}, "contract_version": 1}
        member = self.member(self.compare({name: before}, {name: after}), name)
        self.assertEqual(member["status"], "identity-only")
        self.assertIn("dependency stamps only", member["reason"])
        after["files"]["base/new.json"] = "c" * 64
        member = self.member(self.compare({name: before}, {name: after}), name)
        self.assertEqual(member["status"], "content-changed")
        self.assertNotIn("compares dependency stamps only", member["reason"])

    def test_final_encoded_receipt_budget_is_deterministic_and_preserves_original_evidence(self):
        name = "base/mods.json"
        before = [{"id": f"{index}漢字" + "\n" * 300, "value": "x"} for index in range(12)]
        after = [{**row, "value": '漢字"\\\n' * 300} for row in before]
        report = self.compare({name: before}, {name: after})
        original = {"coverage": {"jobs": {"tree": {"issues": ["D40 evidence"]}}}, "producer": {"commit": "a" * 40}}
        exact_limit = len(encoded({**original, "content_diff": report}))
        receipt = copy.deepcopy(original)
        self.assertIsNone(content_diff.attach(receipt, report, exact_limit))
        self.assertEqual(len(encoded(receipt)), exact_limit)
        receipt = copy.deepcopy(original)
        self.assertIsNotNone(content_diff.attach(receipt, report, exact_limit - 1))
        self.assertLessEqual(len(encoded(receipt)), exact_limit - 1)
        compact = copy.deepcopy(report)
        compact.update(members=[], omitted_members=report["summary"]["reported_members"])
        # Enough for summary, intentionally too little for details.
        limit = len(encoded({**original, "content_diff": compact})) + 400
        receipts = [copy.deepcopy(original) for _ in range(2)]
        for receipt in receipts:
            diagnostic = content_diff.attach(receipt, report, limit)
            self.assertIsNotNone(diagnostic)
            self.assertLessEqual(len(encoded(receipt)), limit)
            self.assertEqual(receipt["coverage"], original["coverage"])
            self.assertEqual(receipt["content_diff"]["summary"], report["summary"])
            self.assertEqual(receipt["content_diff"]["omitted_members"], 1)
            self.assertEqual(receipt["content_diff"]["omitted_entity_details"], 12)
        self.assertEqual(encoded(receipts[0]), encoded(receipts[1]))
        for limit in (len(encoded(original)) + 1, len(encoded(original)) - 1):
            receipt = copy.deepcopy(original)
            diagnostic = content_diff.attach(receipt, report, limit)
            self.assertEqual(receipt, original)
            self.assertIn("content_diff omitted for size", diagnostic)
            self.assertIn("changed_entities=12", diagnostic)
        self.assertIn("already exceeds cap", diagnostic)


if __name__ == "__main__":
    unittest.main()
