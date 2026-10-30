import json
from pathlib import Path
import unittest

from RePoE.parser.poe2.passives import PASSIVE_COLS, passive


class DatRecordLike(list):
    """Membership searches values; named access can resolve virtual columns."""

    def __init__(self, columns):
        super().__init__(columns.values())
        self.columns = columns

    def __getitem__(self, key):
        return self.columns[key] if isinstance(key, str) else super().__getitem__(key)


def row(values):
    result = {name: None for name in PASSIVE_COLS}
    result.update(
        Id="proof",
        Stats=[{"Id": f"stat_{i}"} for i in range(len(values))],
        PassiveSkillBuffs=[],
        Ascendancy=None,
        Icon_DDSFile=None,
        AtlasSubTree=None,
        GrantedSkill=None,
    )
    result.update({f"Stat{i}Value": value for i, value in enumerate(values, 1)})
    return result


class PassiveTests(unittest.TestCase):
    def test_fixed_source_node_keeps_its_fifth_stat(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/passive-31955.json").read_bytes())
        result = passive(DatRecordLike(fixture["row"]), None, "English")
        self.assertEqual(result["stats"], fixture["expected_stats"])
        self.assertEqual(result["stats"]["recover_X_life_on_block"], 10)

    def test_all_actual_stat_slots_preserve_zero_and_negative_values(self):
        source = row([10, 0, -3, 4, 15, 16, 17])
        result = passive(DatRecordLike(source), None, "English")
        self.assertEqual(result["stats"], {f"stat_{i}": value for i, value in enumerate([10, 0, -3, 4, 15, 16, 17])})

    def test_empty_stats_and_missing_values_are_distinct(self):
        self.assertEqual(passive(row([]), None, "English")["stats"], {})
        source = row([1, 2])
        del source["Stat2Value"]
        with self.assertRaises(KeyError):
            passive(source, None, "English")

    def test_duplicate_stats_cannot_be_flattened_by_overwriting(self):
        source = row([1, 2])
        source["Stats"][1]["Id"] = source["Stats"][0]["Id"]
        with self.assertRaisesRegex(ValueError, "Duplicate passive stat"):
            passive(source, None, "English")

    def test_native_reminders_groups_and_buff_relationships(self):
        source = row([])
        source.update(
            ReminderStrings=["reminder"], AtlasNodeGroup="group", PassiveSkillBuffs=[{"BuffDefinition": {"Id": "buff"}}]
        )
        result = passive(DatRecordLike(source), None, "English")
        self.assertEqual(result["reminder_text"], ["reminder"])
        self.assertEqual(result["atlas_group"], "group")
        self.assertEqual(result["buff_definitions"], ["buff"])

    def test_known_legacy_aliases_remain_supported(self):
        source = row([])
        source["ReminderTextKeys"] = source.pop("ReminderStrings")
        source["AtlasnodeGroup"] = source.pop("AtlasNodeGroup")
        source["PassiveSkillBuffsKeys"] = [{"BuffDefinitionsKey": {"Id": "buff"}}]
        del source["PassiveSkillBuffs"]
        self.assertEqual(passive(DatRecordLike(source), None, "English")["buff_definitions"], ["buff"])


if __name__ == "__main__":
    unittest.main()
