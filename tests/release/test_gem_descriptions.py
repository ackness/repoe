"""RePoE.release.gem_descriptions: row selection, raw text and determinism (synthetic inputs)."""

import json
import unittest

from RePoE.release import gem_descriptions as gd


def effect(gem_id, support_text=""):
    return {"gem_effect": {"id": gem_id, "row": 0}, "support_text": support_text}


def active_skills(rows):
    return {"table": "ActiveSkills", "rows": [{"_row": i, "values": row} for i, row in enumerate(rows)]}


class GemDescriptionsTest(unittest.TestCase):
    def setUp(self):
        # Raw client strings: markup, a trailing space and a CRLF stay as they are.
        self.support_text = "Supports [Attack|Attacks] that [Hit|Hits] enemies. "
        self.active_text = "Slams the ground with a [Mace].\r\nDeals [Physical] damage."
        self.gems = {
            "effects": [
                effect("FasterAttackSupport", self.support_text),
                effect("GroundSlam"),
                effect("EmptySupport", ""),
                effect("BlankSupport", "  "),
                effect("MonsterOnly", "Never reached by a player gem."),
            ]
        }
        self.skills = active_skills(
            [
                {"Id": "ground_slam", "Description": self.active_text},
                {"Id": "no_text", "Description": ""},
                {"Id": "monster_skill", "Description": "Not a player gem's skill."},
            ]
        )
        self.gem_effects = {
            "gems": [
                {
                    "gem_id": "G/Support",
                    "granted_effect_id": "SupportFasterAttack",
                    "variant_id": "FasterAttackSupport",
                },
                {"gem_id": "G/Slam", "granted_effect_id": "GroundSlamPlayer", "variant_id": "GroundSlam"},
                # Two gems may share one variant; it is listed once.
                {"gem_id": "G/Slam2", "granted_effect_id": "GroundSlamPlayer", "variant_id": "GroundSlam"},
                {"gem_id": "G/Empty", "granted_effect_id": "SupportEmpty", "variant_id": "EmptySupport"},
                {"gem_id": "G/Blank", "granted_effect_id": "SupportEmpty", "variant_id": "BlankSupport"},
                {"gem_id": "G/Quiet", "granted_effect_id": "NoTextPlayer", "variant_id": "GroundSlam"},
            ]
        }
        self.granted = [
            {"id": "SupportFasterAttack", "is_support": True},
            {"id": "SupportEmpty", "is_support": True, "active_skill": None},
            {"id": "GroundSlamPlayer", "is_support": False, "active_skill": "ground_slam"},
            {"id": "NoTextPlayer", "is_support": False, "active_skill": "no_text"},
            {"id": "MonsterSlam", "is_support": False, "active_skill": "monster_skill"},
        ]

    def project(self, **changes):
        arguments = {
            "gems": self.gems,
            "active_skills": self.skills,
            "gem_effects": self.gem_effects,
            "granted_effects": self.granted,
            "facts_manifest_sha256": "f" * 64,
            "game_patch": "9.9",
            **changes,
        }
        return gd.project(**arguments)

    def test_selects_only_rows_player_gems_reach_with_text(self):
        document, summary = self.project()
        self.assertEqual(
            document["scopes"],
            {
                "ActiveSkills.Description": {"ground_slam": self.active_text},
                "GemEffects.SupportText": {"FasterAttackSupport": self.support_text},
            },
        )
        self.assertEqual(summary, {"gem_effects": 6, "ActiveSkills.Description": 1, "GemEffects.SupportText": 1})
        self.assertEqual(
            document["_meta"],
            {
                "schema": "repoe-gem-descriptions/v1",
                "generator": "RePoE.release.gem_descriptions",
                "facts_manifest_sha256": "f" * 64,
                "game_patch": "9.9",
            },
        )

    def test_text_is_the_raw_client_string(self):
        raw = gd.runtime_encoded(self.project()[0])
        decoded = json.loads(raw)
        self.assertEqual(decoded["scopes"]["GemEffects.SupportText"]["FasterAttackSupport"], self.support_text)
        self.assertTrue(decoded["scopes"]["GemEffects.SupportText"]["FasterAttackSupport"].endswith(". "))
        self.assertIn("\r\n", decoded["scopes"]["ActiveSkills.Description"]["ground_slam"])
        self.assertIn("[Attack|Attacks]", raw.decode())

    def test_output_is_deterministic_and_sorted(self):
        first = gd.runtime_encoded(self.project()[0])
        shuffled = self.project(
            gems={"effects": list(reversed(self.gems["effects"]))},
            gem_effects={"gems": list(reversed(self.gem_effects["gems"]))},
            granted_effects=list(reversed(self.granted)),
            active_skills=active_skills(list(reversed([row["values"] for row in self.skills["rows"]]))),
        )
        self.assertEqual(gd.runtime_encoded(shuffled[0]), first)
        self.assertTrue(first.endswith(b"}\n"))
        self.assertEqual(list(json.loads(first)["scopes"]), ["ActiveSkills.Description", "GemEffects.SupportText"])

    def test_ids_are_emitted_in_sorted_order(self):
        # Two entries per scope, fed in reverse lexical order.
        gems = {"effects": [effect("ZetaSupport", "Supports z."), effect("AlphaSupport", "Supports a.")]}
        skills = active_skills([{"Id": "zeta_skill", "Description": "Z."}, {"Id": "alpha_skill", "Description": "A."}])
        gem_effects = {
            "gems": [
                {"gem_id": "G/Z", "granted_effect_id": "SupportZeta", "variant_id": "ZetaSupport"},
                {"gem_id": "G/A", "granted_effect_id": "SupportAlpha", "variant_id": "AlphaSupport"},
                {"gem_id": "G/ZS", "granted_effect_id": "ZetaPlayer", "variant_id": "ZetaSupport"},
                {"gem_id": "G/AS", "granted_effect_id": "AlphaPlayer", "variant_id": "AlphaSupport"},
            ]
        }
        granted = [
            {"id": "SupportZeta", "is_support": True},
            {"id": "SupportAlpha", "is_support": True},
            {"id": "ZetaPlayer", "is_support": False, "active_skill": "zeta_skill"},
            {"id": "AlphaPlayer", "is_support": False, "active_skill": "alpha_skill"},
        ]
        document = json.loads(
            gd.runtime_encoded(
                self.project(gems=gems, active_skills=skills, gem_effects=gem_effects, granted_effects=granted)[0]
            )
        )
        self.assertEqual(list(document["scopes"]["GemEffects.SupportText"]), ["AlphaSupport", "ZetaSupport"])
        self.assertEqual(list(document["scopes"]["ActiveSkills.Description"]), ["alpha_skill", "zeta_skill"])

    def test_unknown_markup_refuses(self):
        for text in (
            "An [unmatched tag",
            "A stray ] bracket",
            "[A|B|C]",
            "[[nested]]",
            "[]",
            "a | b",
            "<b>x</b>",
            "{0}",
        ):
            gems = {"effects": [effect("FasterAttackSupport", text), effect("GroundSlam")]}
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "unsupported markup"):
                self.project(gems=gems)
        skills = active_skills(
            [{"Id": "ground_slam", "Description": "Bad [markup"}, {"Id": "no_text", "Description": ""}]
        )
        with self.assertRaisesRegex(ValueError, "ActiveSkills.Description ground_slam: unsupported markup"):
            self.project(active_skills=skills)

    def test_dangling_references_refuse(self):
        gem_effects = {"gems": [{"gem_id": "G", "granted_effect_id": "SupportFasterAttack", "variant_id": "Missing"}]}
        with self.assertRaisesRegex(ValueError, "not a GemEffects row"):
            self.project(gem_effects=gem_effects)
        gem_effects = {"gems": [{"gem_id": "G", "granted_effect_id": "Missing", "variant_id": "GroundSlam"}]}
        with self.assertRaisesRegex(ValueError, "not in granted_effects"):
            self.project(gem_effects=gem_effects)
        granted = [{"id": "GroundSlamPlayer", "active_skill": "missing"}, *self.granted[:2], *self.granted[3:]]
        with self.assertRaisesRegex(ValueError, "not an ActiveSkills row"):
            self.project(granted_effects=granted)

    def test_duplicate_ids_refuse(self):
        with self.assertRaisesRegex(ValueError, "duplicate Id GroundSlam"):
            self.project(gems={"effects": [*self.gems["effects"], effect("GroundSlam")]})
        rows = [row["values"] for row in self.skills["rows"]]
        with self.assertRaisesRegex(ValueError, "ActiveSkills: duplicate Id ground_slam"):
            self.project(active_skills=active_skills([*rows, rows[0]]))
        with self.assertRaisesRegex(ValueError, "Not the ActiveSkills table"):
            self.project(active_skills={"table": "GemEffects", "rows": []})


if __name__ == "__main__":
    unittest.main()
