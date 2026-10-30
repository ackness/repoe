"""Physical core-skill fixtures exercise raw channels, joins and profile isolation."""

import copy
import os
import subprocess
import sys
from unittest.mock import patch

from RePoE import native_facts as facts, native_validate, schema_candidate
import test_native_facts as fixture


class NativeSkillsTests(fixture.NativeFactsFixture):
    def setUp(self):
        super().setUp()
        self.rows.update(
            {
                "GrantedEffectLabels": [{"Id": "Hidden", "Text": ""}, {"Id": "Other", "Text": "Other mode"}],
                "ActiveSkills": [
                    {"Id": "active", "GrantedEffect": "string_identity_not_row", "Unknown1": "uninterpreted"}
                ],
                "ActiveSkillType": [{"Id": "Attack", "FlagStat": 0}],
                "CostTypes": [
                    {"Id": "Mana", "Stat": 0, "Divisor": 1, "FormatText": "{0} Mana"},
                    {"Id": "Life", "Stat": 1, "Divisor": 1000, "PerMinute": True},
                ],
                "EffectivenessCostConstants": [{"Id": "DamageValue", "Multiplier": 1.25}],
                "GrantedEffectsPerLevel": [
                    {"GrantedEffect": 0, "Level": 1, "CostAmounts": [0, -8], "ActorLevel": 1.5, "Unknown5": -11},
                    {"GrantedEffect": 0, "Level": 1, "CostAmounts": [3, 5], "ActorLevel": 2.5},
                ],
                "GrantedEffectStatSetsPerLevel": [
                    {
                        "StatSet": 0,
                        "GemLevel": 1,
                        "ActorLevel": 1.5,
                        "SpellCritChance": 750,
                        "AttackCritChance": 125,
                        "BaseMultiplier": -123,
                        "BaseResolvedValues": [0, -100],
                        "AdditionalStats": [1, 0],
                        "AdditionalStatsValues": [0, -7],
                        "FloatStats": [6],
                        "FloatStatsValues": [1.25],
                        "InterpolationBases": [0],
                        "StatInterpolations": [4, 0],
                        "GrantedEffects": [0],
                        "Flag0": True,
                        "Unknown0": -23,
                    },
                    {"StatSet": 0, "GemLevel": 1, "ActorLevel": 2.5},
                ],
            }
        )
        self.rows["GrantedEffects"][0].update({"ActiveSkill": 0, "CostTypes": [0, 1]})
        self.rows["GrantedEffectStatSets"][1]["Label"] = None
        self.rows["GrantedEffectStatSets"][2]["Label"] = 1
        self.source.update(
            {
                "profile": facts.SKILLS_PROFILE,
                "acquisition": {
                    "status": "unreviewed-acquisition-draft",
                    "evidence": [{"kind": "fixture-acquisition-receipt", "sha256": "a" * 64}],
                },
            }
        )
        self.write_inputs()

    def create(self):
        return facts.create_candidate(
            source_lock=self.lock, source="fixture", raw=self.raw, out=self.out, profile=facts.SKILLS_PROFILE
        )

    def validate(self):
        return native_validate.validate_candidate(
            source_lock=self.lock, source="fixture", raw=self.raw, candidate=self.out, profile=facts.SKILLS_PROFILE
        )

    def reseal(self, name, document):
        data = facts._json(document)
        (self.out / name).write_bytes(data)
        manifest = self.load("manifest.json")
        manifest["files"][name] = {"bytes": len(data), "sha256": schema_candidate._sha(data)}
        (self.out / "manifest.json").write_bytes(facts._json(manifest))

    def test_complete_physical_channels_and_context_rows_retained_offline(self):
        with patch("socket.socket", side_effect=AssertionError("network")):
            manifest = self.create()
            accepted = self.validate()
        self.assertEqual(manifest["format"], "repoe-native-facts/v2")
        self.assertEqual(manifest["profile"], facts.SKILLS_PROFILE)
        self.assertFalse(manifest["production_ready"])
        self.assertEqual(manifest["source_identity"]["acquisition"], self.source["acquisition"])
        self.assertEqual(len(manifest["files"]), 21)
        self.assertEqual((self.out / "source-lock.json").read_bytes(), self.lock.read_bytes())
        self.assertEqual(accepted["result"], "passed")
        self.assertEqual(manifest["summary"]["effect_level_rows"], 2)
        self.assertEqual(manifest["summary"]["stat_set_level_rows"], 2)
        core = self.load("skill_core.json")
        self.assertEqual(core["active_skills"][0]["granted_effect_string_raw"], "string_identity_not_row")
        self.assertEqual(core["effect_metadata"][0]["active_skill"], {"row": 0, "id": "active"})
        self.assertEqual([r["actor_level_raw"] for r in core["effect_levels"]], [1.5, 2.5])
        self.assertEqual([r["actor_level_raw"] for r in core["stat_set_levels"]], [1.5, 2.5])
        self.assertEqual([c["amount_raw"] for c in core["effect_levels"][0]["costs"]], [0, -8])
        self.assertEqual([c["cost_type"]["id"] for c in core["effect_levels"][0]["costs"]], ["Mana", "Life"])
        self.assertEqual(core["cost_types"][1]["divisor_raw"], 1000)
        self.assertTrue(core["cost_types"][1]["per_minute_raw"])
        level = core["stat_set_levels"][0]
        self.assertEqual(level["base_resolved_values_raw"], [0, -100])
        self.assertEqual(level["additional_stats_values_raw"], [0, -7])
        self.assertEqual([s["id"] for s in level["additional_stats"]], ["stat1", "stat0"])
        self.assertEqual(level["float_stats_values_raw"], [1.25])
        self.assertEqual(level["spell_crit_chance_raw"], 750)
        self.assertEqual(level["attack_crit_chance_raw"], 125)
        self.assertEqual(level["base_multiplier_raw"], -123)
        self.assertEqual(level["interpolation_bases"], [{"row": 0, "id": "DamageValue"}])
        self.assertEqual(level["stat_interpolations_raw"], [4, 0])
        self.assertEqual(self.load("tables/ActiveSkills.json")["rows"][0]["values"]["Unknown1"], "uninterpreted")
        self.assertEqual(self.load("tables/GrantedEffectsPerLevel.json")["rows"][0]["values"]["Unknown5"], -11)
        raw_level = self.load("tables/GrantedEffectStatSetsPerLevel.json")["rows"][0]["values"]
        self.assertEqual(raw_level["Unknown0"], -23)
        self.assertEqual(raw_level["GrantedEffects"], [0])
        self.assertTrue(raw_level["Flag0"])

    def test_label_zero_empty_text_and_null_remain_distinct(self):
        self.create()
        core = self.load("skill_core.json")
        self.assertEqual(
            [s["label"] for s in core["stat_set_labels"]], [{"row": 0, "id": "Hidden"}, None, {"row": 1, "id": "Other"}]
        )
        self.assertEqual(core["labels"][0]["text"], "")

    def test_array_misalignment_preserves_both_sides_with_diagnostics(self):
        self.rows["GrantedEffectsPerLevel"][0]["CostAmounts"] = [8]
        self.rows["GrantedEffectStatSetsPerLevel"][0]["AdditionalStatsValues"] = [0]
        self.rows["GrantedEffectStatSetsPerLevel"][0]["FloatStatsValues"] = []
        self.write_inputs()
        self.create()
        self.assertEqual(self.validate()["result"], "passed")
        core = self.load("skill_core.json")
        self.assertIsNone(core["effect_levels"][0]["costs"])
        self.assertEqual(core["effect_levels"][0]["cost_amounts_raw"], [8])
        diagnostics = self.load("diagnostics.json")["diagnostics"]
        cost = next(d for d in diagnostics if d["code"] == "unresolved_cost_array_alignment")
        self.assertEqual(cost["cost_types_raw"], [0, 1])
        self.assertEqual(cost["cost_amounts_raw"], [8])
        stat = [d for d in diagnostics if d["code"] == "unresolved_level_stat_array_alignment"]
        self.assertEqual(
            [(d["stat_field"], d["values_raw"]) for d in stat], [("AdditionalStats", [0]), ("FloatStats", [])]
        )
        self.assertEqual(len(core["stat_set_levels"][0]["additional_stats"]), 2)

    def test_missing_acquired_foreign_key_fails_before_output(self):
        self.rows["GrantedEffectStatSetsPerLevel"][0]["InterpolationBases"] = [99]
        self.write_inputs()
        with self.assertRaisesRegex(ValueError, "EffectivenessCostConstants"):
            self.create()
        self.assertFalse(self.out.exists())

    def test_duplicate_stable_identity_fails_before_output(self):
        self.rows["ActiveSkills"].append(dict(self.rows["ActiveSkills"][0]))
        self.write_inputs()
        with self.assertRaisesRegex(ValueError, "duplicate stable identity"):
            self.create()
        self.assertFalse(self.out.exists())

    def test_acquisition_evidence_and_exact_resource_profile_are_required(self):
        original = copy.deepcopy(self.source)
        mutations = [
            lambda s: s.pop("profile"),
            lambda s: s["acquisition"].update(status="production-ready"),
            lambda s: s["acquisition"].update(evidence=[]),
            lambda s: s["acquisition"]["evidence"][0].update(sha256="bad"),
            lambda s: s["resources"].pop("Data/Balance/ActiveSkills.datc64"),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                self.source = copy.deepcopy(original)
                mutate(self.source)
                self.write_lock()
                with self.assertRaises(ValueError):
                    self.create()
                self.assertFalse(self.out.exists())

    def test_base_profile_does_not_accept_or_silently_narrow_core_resources(self):
        with self.assertRaisesRegex(ValueError, "exactly the selected profile"):
            facts.create_candidate(source_lock=self.lock, source="fixture", raw=self.raw, out=self.out)
        self.assertFalse(self.out.exists())

    def test_exact_source_lock_bytes_are_checked_despite_resealed_payload_hash(self):
        self.create()
        name = "source-lock.json"
        data = (self.out / name).read_bytes() + b" "
        (self.out / name).write_bytes(data)
        manifest = self.load("manifest.json")
        manifest["files"][name] = {"bytes": len(data), "sha256": schema_candidate._sha(data)}
        (self.out / "manifest.json").write_bytes(facts._json(manifest))
        with self.assertRaisesRegex(ValueError, "exact input bytes"):
            self.validate()

    def test_resealed_projection_and_producer_tampering_fail_validation(self):
        self.create()
        core = self.load("skill_core.json")
        core["stat_set_levels"][0]["float_stats_values_raw"] = [1.5]
        self.reseal("skill_core.json", core)
        with self.assertRaisesRegex(ValueError, "skill_core.json"):
            self.validate()
        self.create_at_new_output()
        manifest = self.load("manifest.json")
        manifest["producer"]["RePoE/native_skills.py"] = "b" * 64
        (self.out / "manifest.json").write_bytes(facts._json(manifest))
        with self.assertRaisesRegex(ValueError, "manifest.producer"):
            self.validate()

    def create_at_new_output(self):
        self.out = self.root / "second-output"
        self.create()

    def test_fresh_processes_are_byte_identical_and_preserve_existing_outputs(self):
        for seed, out in (("1", self.out), ("12345", self.root / "second")):
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
                    str(out),
                    "--profile",
                    facts.SKILLS_PROFILE,
                ],
                cwd=schema_candidate.ROOT,
                env={**os.environ, "PYTHONHASHSEED": seed},
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        snapshot = {p.relative_to(self.out): p.read_bytes() for p in self.out.rglob("*") if p.is_file()}
        second = {
            p.relative_to(self.root / "second"): p.read_bytes()
            for p in (self.root / "second").rglob("*")
            if p.is_file()
        }
        self.assertEqual(snapshot, second)
        with self.assertRaises(FileExistsError):
            self.create()
        self.assertEqual(
            snapshot, {p.relative_to(self.out): p.read_bytes() for p in self.out.rglob("*") if p.is_file()}
        )
