"""Native item identity, repeated relations and ordered support-token fixtures."""

import copy
import os
import subprocess
import sys
from unittest.mock import patch

from RePoE import native_facts as facts, native_gems, native_validate, schema_candidate
from test_native_skills import NativeSkillsFixture


class NativeGemTests(NativeSkillsFixture):
    def setUp(self):
        super().setUp()
        self.rows.update({name: [] for name in native_gems.TABLES})
        self.rows.update(
            {
                "BaseItemTypes": [
                    {"Id": f"Metadata/Items/Gem/{i}", "Name": "Shared name", "ItemClass": int(i > 0), "Tags": [0]}
                    for i in range(3)
                ],
                "ItemClasses": [{"Id": "Active Skill Gem"}, {"Id": "Support Skill Gem"}],
                "Tags": [{"Id": "item_tag"}],
                "SkillGems": [
                    {
                        "BaseItemType": 0,
                        "GemEffects": [0, 1, 0],
                        "ItemExperienceType": 0,
                        "BaseSkillGem": 1,
                        "RegularVariant": 1,
                        "AwakenedVariant": 2,
                        "VaalVariant_BaseItemType": 2,
                        "MinLevelReq": 0,
                        "StrengthRequirementPercent": -5,
                        "GlobalSkillLevelStat": 0,
                        "Flag4": True,
                    },
                    {"BaseItemType": 1, "GemEffects": [0]},
                    {"BaseItemType": 2, "GemEffects": [1]},
                ],
                "GemEffects": [
                    {"Id": "effect_a", "GrantedEffect": 0, "AdditionalGrantedEffects": [1, 0, 1], "GemTags": [1, 0, 1]},
                    {"Id": "effect_b", "GrantedEffect": 1, "GemTags": [0]},
                    {"Id": "unreferenced", "GrantedEffect": 0, "GemTags": []},
                ],
                "GemTags": [{"Id": "tag_a", "Name": "[Tag]", "LocalLevelStat": 0}, {"Id": "tag_b", "Name": ""}],
                "SupportGems": [{"SkillGem": 1, "Family": [1, 0], "IsLineage": True}],
                "SupportGemFamily": [
                    {"Id": "family_a", "Text": "Shared text"},
                    {"Id": "family_b", "Text": "Shared text"},
                ],
                "SkillGemSupports": [{"SkillGem": 0, "Supports": [1, 1, 2, None]}],
                "ItemExperienceTypes": [{"Id": "regular"}, {"Id": "playtest"}],
                "ItemExperiencePerLevel": [
                    {"ItemExperienceType": 0, "ItemCurrentLevel": 1, "Experience": 0, "Level": 0},
                    {"ItemExperienceType": 0, "ItemCurrentLevel": 1, "Experience": 10, "Level": 0},
                ],
                "ActionTypes": [{"Id": "action"}],
                "ActiveSkillWeaponRequirement": [
                    {"Id": "requirement", "WieldableClasses": [1, 0, 1], "String": 0, "Stat": 0}
                ],
                "WieldableClasses": [{"ItemClass": 0, "Tag": 0, "TwoWeaponSlots": True}, {"ItemClass": 1}],
                "ClientStrings": [{"Id": "requirement_text", "Text": "Requirements"}],
                "MinionType": [{"Id": "minion"}],
            }
        )
        self.rows["GrantedEffects"].append({"Id": "extra_effect", "StatSet": 2, "ActiveSkill": 0})
        self.rows["ActiveSkillType"].extend([{"Id": "AND"}, {"Id": "NOT"}])
        self.rows["GrantedEffects"][0].update(
            {
                "AllowedActiveSkillTypes": [0, 1, 2, 0],
                "ExcludedActiveSkillTypes": [2, 1],
                "MinionType": 0,
                "SupportWeaponRestrictions": [1, 0],
            }
        )
        self.rows["ActiveSkills"][0].update(
            {
                "ActiveSkillTypes": [0, 1, 2],
                "WeaponRequirements": 0,
                "ActionType": 0,
                "IsGem": True,
                "HideOnWebsite": True,
            }
        )
        self.source["profile"] = facts.GEMS_PROFILE
        self.write_inputs()

    def create(self):
        return facts.create_candidate(
            source_lock=self.lock, source="fixture", raw=self.raw, out=self.out, profile=facts.GEMS_PROFILE
        )

    def validate(self):
        return native_validate.validate_candidate(
            source_lock=self.lock, source="fixture", raw=self.raw, candidate=self.out, profile=facts.GEMS_PROFILE
        )

    def test_source_item_identity_nested_order_and_raw_requirements_are_preserved(self):
        with patch("socket.socket", side_effect=AssertionError("network")):
            manifest = self.create()
            self.assertEqual(self.validate()["result"], "passed")
        self.assertEqual(manifest["format"], "repoe-native-facts/v3")
        self.assertEqual(len(manifest["files"]), 47)
        self.assertFalse(manifest["production_ready"])
        self.assertEqual((self.out / "source-lock.json").read_bytes(), self.lock.read_bytes())
        self.assertEqual(manifest["summary"]["gem_items"], 3)
        self.assertEqual(manifest["source_identity"]["acquisition"]["status"], "unreviewed-acquisition-draft")
        gems = self.load("gems.json")
        self.assertEqual([r["gem"]["item"]["id"] for r in gems["items"]], [f"Metadata/Items/Gem/{i}" for i in range(3)])
        self.assertEqual([r["name"] for r in gems["items"]], ["Shared name"] * 3)
        self.assertEqual(
            [r["gem_effect"]["id"] for r in gems["items"][0]["gem_effects"]], ["effect_a", "effect_b", "effect_a"]
        )
        self.assertEqual([r["source_slot"] for r in gems["items"][0]["gem_effects"]], [0, 1, 2])
        self.assertEqual(
            gems["items"][0]["base_skill_gem"], {"row": 1, "item": {"row": 1, "id": "Metadata/Items/Gem/1"}}
        )
        self.assertEqual(gems["items"][0]["strength_requirement_percent_raw"], -5)
        self.assertEqual(gems["items"][0]["global_skill_level_stat"], {"row": 0, "id": "stat0"})
        self.assertEqual(
            [r["id"] for r in gems["effects"][0]["additional_granted_effects"]],
            ["extra_effect", "ScopedEffect", "extra_effect"],
        )
        self.assertEqual([r["id"] for r in gems["supports"][0]["families"]], ["family_b", "family_a"])
        self.assertEqual(gems["supports"][0]["gem"]["item"]["id"], "Metadata/Items/Gem/1")
        self.assertEqual(gems["tags"][0]["local_level_stat"]["row"], 0)
        self.assertEqual([r["experience_raw"] for r in gems["experience_levels"]], [0, 10])
        self.assertEqual([r["item_current_level_raw"] for r in gems["experience_levels"]], [1, 1])
        self.assertEqual(
            [r["row"] if r else None for r in gems["support_associations"][0]["supports"]], [1, 1, 2, None]
        )
        self.assertTrue(self.load("tables/SkillGems.json")["rows"][0]["values"]["Flag4"])

    def test_operator_tokens_weapon_rows_and_visibility_are_facts_not_eligibility(self):
        self.create()
        constraints = self.load("constraints.json")
        effect = constraints["effects"][0]
        self.assertEqual([r["id"] for r in effect["allowed_active_skill_types"]], ["Attack", "AND", "NOT", "Attack"])
        self.assertEqual(effect["support_weapon_restrictions"], [{"row": 1}, {"row": 0}])
        self.assertEqual([r["row"] for r in constraints["weapon_requirements"][0]["wieldable_classes"]], [1, 0, 1])
        self.assertEqual(constraints["weapon_requirements"][0]["client_string"], {"row": 0, "id": "requirement_text"})
        self.assertTrue(constraints["active_skills"][0]["hide_on_website_raw"])
        self.assertEqual(len(self.load("gems.json")["items"]), 3)
        self.assertNotIn("eligible", effect)

    def test_ambiguous_item_and_support_metadata_and_empty_families_remain_diagnostic(self):
        self.rows["SkillGems"][2]["BaseItemType"] = 0
        self.rows["SupportGems"].append({"SkillGem": 1, "Family": []})
        self.rows["SkillGems"][0]["GemEffects"].append(None)
        self.write_inputs()
        self.create()
        gems = self.load("gems.json")
        self.assertEqual(len(gems["items"]), 3)
        self.assertEqual(len(gems["supports"]), 2)
        self.assertIsNone(gems["items"][0]["gem_effects"][-1]["gem_effect"])
        codes = {r["code"] for r in self.load("diagnostics.json")["diagnostics"]}
        self.assertTrue(
            {
                "duplicate_gem_item_identity",
                "duplicate_support_metadata_owner",
                "support_metadata_empty_families",
                "null_gem_effect_binding",
                "gem_effect_without_skill_gem_reference",
            }
            <= codes
        )

    def test_broken_acquired_relations_and_named_identity_fail_before_output(self):
        original = copy.deepcopy(self.rows)
        for table, field, value in [
            ("GemEffects", "AdditionalGrantedEffects", [99]),
            ("SupportGems", "Family", [99]),
            ("SkillGems", "BaseSkillGem", 99),
            ("ActiveSkillWeaponRequirement", "WieldableClasses", [99]),
        ]:
            self.rows = copy.deepcopy(original)
            self.rows[table][0][field] = value
            self.write_inputs()
            with self.subTest(table=table, field=field), self.assertRaises(ValueError):
                self.create()
            self.assertFalse(self.out.exists())
        self.rows = copy.deepcopy(original)
        self.rows["GemEffects"].append(dict(self.rows["GemEffects"][0]))
        self.write_inputs()
        with self.assertRaisesRegex(ValueError, "duplicate stable identity"):
            self.create()

    def test_resealed_foreign_operator_and_variant_projections_fail_acceptance(self):
        self.create()
        self.assertEqual(self.validate()["result"], "passed")
        good = self.load("gems.json")
        document = copy.deepcopy(good)
        document["items"][0]["base_skill_gem"]["item"]["id"] = "wrong"
        self.reseal("gems.json", document)
        with self.assertRaisesRegex(ValueError, "gems.json"):
            self.validate()
        self.reseal("gems.json", good)
        document = self.load("constraints.json")
        document["effects"][0]["allowed_active_skill_types"].reverse()
        self.reseal("constraints.json", document)
        with self.assertRaisesRegex(ValueError, "constraints.json"):
            self.validate()

    def test_core_profile_cannot_silently_consume_or_narrow_a1_input(self):
        with self.assertRaisesRegex(ValueError, "exactly the selected profile"):
            facts.create_candidate(
                source_lock=self.lock, source="fixture", raw=self.raw, out=self.out, profile=facts.SKILLS_PROFILE
            )
        self.assertFalse(self.out.exists())

    def test_two_processes_preserve_all_candidate_bytes(self):
        for seed, out in (("1", self.out), ("99", self.root / "second")):
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "RePoE.native_facts",
                    "--profile",
                    facts.GEMS_PROFILE,
                    "--source-lock",
                    str(self.lock),
                    "--source",
                    "fixture",
                    "--raw",
                    str(self.raw),
                    "--out",
                    str(out),
                ],
                cwd=schema_candidate.ROOT,
                env={**os.environ, "PYTHONHASHSEED": seed},
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        first = {p.relative_to(self.out): p.read_bytes() for p in self.out.rglob("*") if p.is_file()}
        second = {
            p.relative_to(self.root / "second"): p.read_bytes()
            for p in (self.root / "second").rglob("*")
            if p.is_file()
        }
        self.assertEqual(first, second)
