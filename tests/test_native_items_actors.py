"""Native B/C facts preserve slots, source units, nullable identities and gaps."""

import copy
import os
import subprocess
import sys
from unittest.mock import patch

from RePoE import native_actor_facts, native_facts as facts, native_items, native_validate
from test_native_gems import NativeGemFixture


class NativeItemsActorsTests(NativeGemFixture):
    def setUp(self):
        super().setUp()
        self.rows.update({name: [] for name in (*native_items.TABLES, *native_actor_facts.TABLES)})
        mod = {
            "Id": "eight_slots",
            "Name": "Raw name",
            "ModType": 0,
            "Families": [1, 0, 1],
            "Domain": 1,
            "GenerationType": 2,
            "Level": 0,
            "MaxLevel": 65536,
            "SpawnLevel_Override": 0,
            "Tags": [0, 0],
            "ImplicitTags": [0],
            "SpawnWeight_Tags": [0, 0],
            "SpawnWeight_Values": [0, 3],
            "BuffTemplate": 0,
            "BuffTemplate2": [0, 0],
            "HasHardmodeStatValues": True,
            "GrantedEffectsPerLevel": [0, 1, 0],
        }
        for slot in range(1, 9):
            mod.update(
                {
                    f"Stat{slot}": 0 if slot in (1, 5, 6, 7, 8) else None,
                    f"Stat{slot}Min": -slot,
                    f"Stat{slot}Max": slot,
                    f"Stat{slot}MinHardmode": -2 * slot,
                    f"Stat{slot}MaxHardmode": 3 * slot,
                }
            )
        self.rows.update(
            {
                "Mods": [mod],
                "ModType": [{"Name": 0, "Stats": [0, 1]}],
                "ModFamily": [{"Id": "first"}, {"Id": "second"}],
                "ClientStrings2": [{"Id": "name", "Text": "Raw name"}],
                "ArmourTypes": [{"BaseItemType": 0, "Armour": 17, "IncreasedMovementSpeed": -5}],
                "AttributeRequirements": [{"BaseItemType": 0, "ReqStr": 0, "ReqDex": 7}],
                "ShieldTypes": [{"BaseItemType": 0, "Block": 25}],
                "WeaponTypes": [{"BaseItemType": 0, "WeaponClass": 0, "Speed": 1100, "ReloadTime": 1250}],
                "WeaponClasses": [{"ItemClass": 0, "Name": 0}],
                "ItemSpirit": [{"BaseItemType": 0, "SpiritGranted": 30}],
                "ItemInherentSkills": [{"BaseItemType": 0, "SkillsGranted": [1, 0, 1], "IsWeapon": True}],
                "Flasks": [
                    {"BaseItemType": 1, "UtilityBuff": [0], "LifePerUse": 0, "ManaPerUse": 5, "RecoveryTime": 0}
                ],
                "ComponentCharges": [
                    {
                        "BaseItemTypesKey": "Metadata/Items/Gem/1",
                        "MaxCharges": 0,
                        "PerCharge": 3,
                        "MaxCharges2": 7,
                        "PerCharge2": 0,
                    }
                ],
                "BuffDefinitions": [
                    {"Id": "buff", "Stats": [0], "GrantedFlags": [1], "GrantedStats": [2], "ConditionStats": [3]}
                ],
                "BuffTemplates": [{"Id": "template"}],
                "UtilityFlaskBuffs": [{"BuffDefinition": 0, "StatValues": [25], "StatValues2": []}],
                "SoulCores": [{"BaseItemType": 2, "Type": 0, "Limit": 0, "CanSocketInJewellery": True}],
                "SoulCoreTypes": [{"Id": "Rune", "EffectStat": 0, "SocketedStat": 1}],
                "SoulCoreLimits": [{"Id": "limit", "Limit": 1, "Flag0": True}],
                "SoulCoreStatCategories": [{"Id": "all", "Display": "All", "TargetItemClasses": [], "Unknown0": 8}],
                "SoulCoreStats": [
                    {
                        "SoulCore": 0,
                        "StatCategory": 0,
                        "Stats": [],
                        "StatsValues": [],
                        "BondedStats": [1, 0],
                        "BondedStatsValues": [0, -7],
                    }
                ],
                "Essences": [{"BaseItemType": 2, "ReplacementType": 0}],
                "EssenceReplacementType": [{"Id": "replace"}],
                "EssenceTargetItemCategories": [{"Id": "gear", "ItemClasses": [0]}],
                "EssenceMods": [
                    {
                        "Essence": 0,
                        "TargetItemCategory": 0,
                        "Mod": 0,
                        "DisplayMod": 0,
                        "OutcomeMods": [0, 0],
                        "OutcomeModWeights": [],
                    }
                ],
                "GameConstants": [{"Id": "Whitespace ", "Value": 0, "Divisor": 100}],
                "DefaultMonsterStats": [
                    {"DisplayLevel": str(i), "Damage": 1.25, "MinionDamage": -0.0} for i in range(1, 101)
                ],
                "MonsterVarieties": [
                    {
                        "Id": "monster",
                        "MonsterType": 0,
                        "Mods": [0, 0],
                        "Tags": [0, 0],
                        "GrantedEffects": [0, 1, 0],
                        "AttackCrit": 0.0625,
                        "InheritsFrom": ["Addon", "Addon"],
                    }
                ],
                "MonsterTypes": [{"Id": "type", "MonsterResistances": [0, 0], "Armour": 0, "IsSummoned": True}],
                "MonsterResistances": [{"Id": "resists", "Fire1": [0, -5], "Cold1": []}],
                "SummonedSpecificMonsters": [
                    {"Id": 17, "MonsterVarietiesKey": None},
                    {"Id": 0, "MonsterVarietiesKey": 0},
                ],
                "PlayerMinionIntrinsicStats": [{"Stat": 0, "Value": -10}],
                "MinionGemLevelScaling": [{"GemLevel": 1, "MinionLevel": 0}, {"GemLevel": 1, "MinionLevel": 2}],
                "SpectreOverrides": [{"Monster": 0, "Spectre": 0}],
            }
        )
        self.rows["BaseItemTypes"][0].update({"Implicit_Mods": [0, 0], "InheritsFrom": "Metadata/Item", "Width": 2})
        self.source["profile"] = facts.ITEMS_ACTORS_PROFILE
        self.write_inputs()

    def create(self):
        return facts.create_candidate(
            source_lock=self.lock, source="fixture", raw=self.raw, out=self.out, profile=facts.ITEMS_ACTORS_PROFILE
        )

    def validate(self):
        return native_validate.validate_candidate(
            source_lock=self.lock,
            source="fixture",
            raw=self.raw,
            candidate=self.out,
            profile=facts.ITEMS_ACTORS_PROFILE,
        )

    def test_exact_eight_slots_owner_joins_and_separate_stat_channels(self):
        with patch("socket.socket", side_effect=AssertionError("network")):
            manifest = self.create()
            self.assertEqual(self.validate()["result"], "passed")
        self.assertEqual(manifest["format"], "repoe-native-facts/v4")
        self.assertEqual(len(manifest["files"]), 87)
        self.assertFalse(manifest["production_ready"])
        self.assertEqual((self.out / "source-lock.json").read_bytes(), self.lock.read_bytes())
        items = self.load("items.json")
        slots = items["mods"][0]["slots"]
        self.assertEqual([slot["slot"] for slot in slots], list(range(1, 9)))
        self.assertIsNone(slots[1]["stat"])
        self.assertEqual((slots[7]["min_raw"], slots[7]["max_hardmode_raw"]), (-8, 24))
        self.assertEqual([ref["target"]["id"] for ref in items["mods"][0]["families"]], ["second", "first", "second"])
        self.assertEqual([ref["value_raw"] for ref in items["mods"][0]["spawn_weights"]], [0, 3])
        self.assertEqual(items["base_items"][0]["components"]["WeaponTypes"]["values_raw"]["ReloadTime"], 1250)
        self.assertEqual(items["base_items"][1]["charges"]["values_raw"]["PerCharge2"], 0)
        self.assertIsNone(items["base_items"][0]["charges"])
        self.assertEqual(items["soul_cores"][0]["stat_groups"][0]["regular"], [])
        self.assertEqual([ref["value_raw"] for ref in items["soul_cores"][0]["stat_groups"][0]["bonded"]], [0, -7])
        self.assertEqual(items["soul_core_categories"][0]["target_item_classes"], [])
        self.assertEqual(items["soul_core_categories"][0]["unknown0_raw"], 8)
        buff = items["utility_buffs"][0]
        self.assertEqual(buff["primary"][0]["value_raw"], 25)
        self.assertEqual(buff["secondary_values_raw"], [])
        self.assertEqual(buff["granted_flags"][0]["target"]["id"], "stat1")

    def test_actor_facts_keep_float_channels_whitespace_numeric_id_and_missing_monster(self):
        self.create()
        actors = self.load("actors.json")
        self.assertEqual(actors["constants"][0]["constant"]["id"], "Whitespace ")
        self.assertEqual(actors["constants"][0]["divisor_raw"], 100)
        self.assertEqual(actors["default_monster_stats"][0]["values_raw"]["Damage"], 1.25)
        self.assertEqual(facts._json(actors["default_monster_stats"][0]["values_raw"]["MinionDamage"]), b"-0.0\n")
        self.assertEqual(actors["summoned_specific_monsters"][0]["id_raw"], 17)
        self.assertIsNone(actors["summoned_specific_monsters"][0]["monster"])
        self.assertNotIn("id", actors["summoned_specific_monsters"][0])
        self.assertEqual(actors["summoned_specific_monsters"][1]["monster"], {"row": 0, "id": "monster"})
        self.assertEqual(actors["monsters"][0]["facts_raw"]["InheritsFrom"], ["Addon", "Addon"])
        self.assertEqual(actors["auxiliary_rows"]["DisplayMinionMonsterType"], [])
        self.assertEqual(
            [row["values_raw"]["MinionLevel"] for row in actors["auxiliary_rows"]["MinionGemLevelScaling"]], [0, 2]
        )

    def test_missing_essence_weights_and_missing_core_groups_remain_explicit(self):
        self.rows["SoulCoreStats"] = []
        self.write_inputs()
        self.create()
        items = self.load("items.json")
        self.assertEqual(items["soul_cores"][0]["stat_groups"], [])
        essence = items["essence_mods"][0]
        self.assertIsNone(essence["outcomes"])
        self.assertEqual(len(essence["outcome_mods"]), 2)
        self.assertEqual(essence["outcome_weights_raw"], [])
        codes = [entry["code"] for entry in self.load("diagnostics.json")["diagnostics"]]
        self.assertIn("essence_outcome_weight_alignment_unresolved", codes)
        self.assertIn("soulcore_without_stat_groups", codes)

    def test_bad_required_pairs_owners_and_constants_fail_before_output(self):
        original = copy.deepcopy(self.rows)
        mutations = [
            ("Mods", lambda rows: rows[0].update(SpawnWeight_Values=[])),
            ("Mods", lambda rows: rows[0].update(Stat8Min=9)),
            ("UtilityFlaskBuffs", lambda rows: rows[0].update(StatValues=[])),
            ("SoulCoreStats", lambda rows: rows[0].update(BondedStatsValues=[])),
            ("ArmourTypes", lambda rows: rows.append(copy.deepcopy(rows[0]))),
            ("ComponentCharges", lambda rows: rows[0].update(BaseItemTypesKey="missing")),
            ("GameConstants", lambda rows: rows[0].update(Divisor=0)),
            ("DefaultMonsterStats", lambda rows: rows[0].update(DisplayLevel="2")),
            ("Mods", lambda rows: rows[0].update(Stat8=99)),
        ]
        for table, mutate in mutations:
            self.rows = copy.deepcopy(original)
            mutate(self.rows[table])
            self.write_inputs()
            with self.subTest(table=table), self.assertRaises(ValueError):
                self.create()
            self.assertFalse(self.out.exists())

    def test_resealed_projection_tampering_fails_acceptance(self):
        self.create()
        for name, pointer in [
            ("items.json", ("mods", 0, "slots", 7, "max_raw")),
            ("actors.json", ("constants", 0, "divisor_raw")),
        ]:
            original = self.load(name)
            altered = copy.deepcopy(original)
            target = altered
            for key in pointer[:-1]:
                target = target[key]
            target[pointer[-1]] = 999
            self.reseal(name, altered)
            with self.assertRaisesRegex(ValueError, "differ from raw replay"):
                self.validate()
            self.reseal(name, original)

    def test_a1_profile_never_silently_narrows_bounded_bc_input(self):
        with self.assertRaisesRegex(ValueError, "exactly the selected profile"):
            facts.create_candidate(
                source_lock=self.lock, source="fixture", raw=self.raw, out=self.out, profile=facts.GEMS_PROFILE
            )
        self.assertFalse(self.out.exists())

    def test_independent_processes_reproduce_bc_bytes(self):
        for seed, name in [("7", "first"), ("1009", "second")]:
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "RePoE.native_facts",
                    "--source-lock",
                    str(self.lock),
                    "--source",
                    "fixture",
                    "--raw",
                    str(self.raw),
                    "--out",
                    str(self.root / name),
                    "--profile",
                    facts.ITEMS_ACTORS_PROFILE,
                ],
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONHASHSEED": seed},
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        first = {
            str(path.relative_to(self.root / "first")): path.read_bytes()
            for path in (self.root / "first").rglob("*")
            if path.is_file()
        }
        second = {
            str(path.relative_to(self.root / "second")): path.read_bytes()
            for path in (self.root / "second").rglob("*")
            if path.is_file()
        }
        self.assertEqual(first, second)
