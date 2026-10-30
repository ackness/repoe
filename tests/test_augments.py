from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call

from PyPoE.poe.file.translations import TranslationFileCache

from RePoE.parser.poe2.augments import augments


class Record:
    """Identity-hashed relational row; foreign keys refer to the same row object."""

    def __init__(self, columns):
        self.columns = columns

    def __getitem__(self, key):
        return self.columns[key]


class Table(list):
    def __init__(self, rows):
        super().__init__(rows)
        self.index = {}

    def build_index(self, column):
        index = self.index[column] = {}
        for row in self:
            index.setdefault(row[column], []).append(row)


class AugmentTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((Path(__file__).parent / "fixtures/augments.json").read_bytes())

    def export(self, directory, *, wrapped_translation=True, translation=None):
        cores = [Record(row) for row in self.fixture["soul_cores"]]
        rows = Table(Record({**row, "SoulCore": cores[row["SoulCore"]]}) for row in self.fixture["soul_core_stats"])
        if translation is None:
            lines = ["synthetic translation"]
            translation = Mock()
            translation.get_translation.return_value = SimpleNamespace(lines=lines) if wrapped_translation else lines
        exporter = augments(
            file_system=None,
            data_path=directory,
            relational_reader={"SoulCores.dat64": cores, "SoulCoreStats.dat64": rows},
            language="English",
            caches={TranslationFileCache: {"stat_descriptions.txt": translation}},
            sequel=2,
        )
        with redirect_stdout(io.StringIO()):
            exporter.write()
        return translation

    def test_actual_export_keeps_raw_values_targets_and_separate_bonded_stats(self):
        for wrapped in (True, False):
            with self.subTest(wrapped_translation=wrapped), tempfile.TemporaryDirectory() as directory:
                translation = self.export(directory, wrapped_translation=wrapped)
                for filename in ("augments.json", "augments.min.json"):
                    self.assertEqual(json.loads((Path(directory) / filename).read_bytes()), self.fixture["expected"])
                translation.get_translation.assert_has_calls(
                    [
                        call(
                            ["synthetic_shared_stat", "synthetic_zero_stat", "synthetic_negative_stat"],
                            [12500, 0, -375],
                            lang="English",
                        ),
                        call(["synthetic_shared_stat", "synthetic_bonded_stat"], [-20, 0], lang="English"),
                        call(["synthetic_bonded_only_stat"], [45], lang="English"),
                    ]
                )
                self.assertEqual(translation.get_translation.call_count, 3)

    def test_untranslated_stats_still_have_raw_values(self):
        translation = Mock()
        translation.get_translation.return_value = SimpleNamespace(lines=[])
        with tempfile.TemporaryDirectory() as directory:
            self.export(directory, translation=translation)
            categories = json.loads((Path(directory) / "augments.json").read_bytes())[
                "Metadata/Items/SyntheticAugment"
            ]["categories"]
        expected = deepcopy(self.fixture["expected"]["Metadata/Items/SyntheticAugment"]["categories"])
        del expected["weapons"]["stat_text"]
        del expected["weapons"]["bonded_stat_text"]
        del expected["armour"]["bonded_stat_text"]
        self.assertEqual(categories, expected)

    def test_repeated_stat_ids_are_preserved_without_combining_values(self):
        row = self.fixture["soul_core_stats"][0]
        row["Stats"][1] = deepcopy(row["Stats"][0])
        with tempfile.TemporaryDirectory() as directory:
            self.export(directory)
            stats = json.loads((Path(directory) / "augments.json").read_bytes())["Metadata/Items/SyntheticAugment"][
                "categories"
            ]["weapons"]["stats"]
        self.assertEqual([stat["id"] for stat in stats[:2]], ["synthetic_shared_stat"] * 2)
        self.assertEqual([stat["value"] for stat in stats], [12500, 0, -375])

    def test_unequal_stat_value_lengths_fail_before_writing(self):
        row = self.fixture["soul_core_stats"][0]
        for stat_col, value_col in (("Stats", "StatsValues"), ("BondedStats", "BondedStatsValues")):
            stats, values = row[stat_col], row[value_col]
            for bad_stats, bad_values in (
                (stats, values[:-1]),
                (stats, [*values, 99]),
                (stats, []),
                ([], values),
            ):
                with self.subTest(column=stat_col, stats=bad_stats, values=bad_values):
                    row[stat_col], row[value_col] = bad_stats, bad_values
                    with tempfile.TemporaryDirectory() as directory:
                        with self.assertRaisesRegex(
                            ValueError,
                            f"Mismatched augment stat/value lengths: Metadata/Items/SyntheticAugment/weapons/{stat_col}",
                        ):
                            self.export(directory)
                        self.assertEqual(list(Path(directory).iterdir()), [])
            row[stat_col], row[value_col] = stats, values

    def test_missing_value_columns_are_not_defaulted_even_for_empty_stats(self):
        row = self.fixture["soul_core_stats"][0]
        for stat_col, value_col in (("Stats", "StatsValues"), ("BondedStats", "BondedStatsValues")):
            stats, values = row[stat_col], row.pop(value_col)
            for source_stats in (stats, []):
                with self.subTest(column=stat_col, stats=source_stats), tempfile.TemporaryDirectory() as directory:
                    row[stat_col] = source_stats
                    with self.assertRaisesRegex(KeyError, value_col):
                        self.export(directory)
                    self.assertEqual(list(Path(directory).iterdir()), [])
            row[stat_col], row[value_col] = stats, values

    def test_duplicate_category_identity_is_rejected(self):
        duplicate = deepcopy(self.fixture["soul_core_stats"][0])
        duplicate["StatCategory"]["Display"] = "Different display, same identity"
        duplicate["StatsValues"][0] = 999
        self.fixture["soul_core_stats"].append(duplicate)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                ValueError, "Duplicate augment category: Metadata/Items/SyntheticAugment/weapons"
            ):
                self.export(directory)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_duplicate_base_identity_is_rejected_without_changing_previous_outputs(self):
        duplicate = deepcopy(self.fixture["soul_cores"][0])
        duplicate["RequiredLevel"] = 99
        self.fixture["soul_cores"].append(duplicate)
        with tempfile.TemporaryDirectory() as directory:
            previous = {name: f"previous {name}" for name in ("augments.json", "augments.min.json")}
            for name, contents in previous.items():
                (Path(directory) / name).write_text(contents)
            with self.assertRaisesRegex(ValueError, "Duplicate augment base item: Metadata/Items/SyntheticAugment"):
                self.export(directory)
            self.assertEqual({path.name: path.read_text() for path in Path(directory).iterdir()}, previous)

    def test_duplicate_display_labels_do_not_merge_categories(self):
        rows = self.fixture["soul_core_stats"]
        rows[1]["StatCategory"]["Display"] = rows[0]["StatCategory"]["Display"]
        with tempfile.TemporaryDirectory() as directory:
            self.export(directory)
            categories = json.loads((Path(directory) / "augments.json").read_bytes())[
                "Metadata/Items/SyntheticAugment"
            ]["categories"]
        self.assertEqual(set(categories), {"weapons", "armour", "empty"})
        self.assertEqual(categories["weapons"]["target_item_classes"], ["OneHandSwords", "TwoHandSwords"])
        self.assertEqual(categories["armour"]["target_item_classes"], ["Boots", "Gloves"])


if __name__ == "__main__":
    unittest.main()
