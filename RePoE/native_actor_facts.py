"""Native constants, monster and minion facts without server formula assumptions."""

from RePoE.native_items import Facts


TABLES = (
    "DefaultMonsterStats",
    "DisplayMinionMonsterType",
    "GameConstants",
    "MinionGemLevelScaling",
    "MinionStats",
    "MonsterResistances",
    "MonsterTypes",
    "MonsterVarieties",
    "PlayerMinionIntrinsicStats",
    "SkillTotemVariations",
    "SpectreOverrides",
    "SummonedSpecificMonsters",
    "SummonedSpecificMonstersOnDeath",
)
LIMITS = [
    "Partial candidate only; forbidden as a production snapshot or runtime-ready PoBR pack.",
    "Seventy-seven physical DAT tables and the Default PSG; complete metadata/text and foreign-key closure remain incomplete.",
    "Acquisition status/evidence is caller-declared, not source authentication by this exporter.",
    "Source rows, eight modifier slots, ordered relations, unknowns and nulls are retained without playable catalogue filtering.",
    "Item inheritance stems/direct tags do not establish inherited tags, mod applicability, enum meanings or unit conversions.",
    "SoulCore categories, normal/bonded stats, limits and flags retain raw meanings; no target-category or stacking policy is inferred.",
    "Constants, level tables and monster/minion relations do not certify server formulas, selected actor defaults or gem-to-variety identity.",
    "Ordered skill types and support families remain facts, not an expression grammar, conflict policy or exhaustive support whitelist.",
    "No CSD/locale closure, physical radii, global coordinates, quality scopes, timeline or complete gameplay support is inferred.",
]


def project(tables, resolve):
    facts = Facts(tables, resolve)
    for table in ("GameConstants", "MonsterVarieties", "MonsterTypes", "MonsterResistances", "MinionType"):
        facts.stable_ids(table)
    constants = []
    for row in facts.rows("GameConstants"):
        value = row["values"]
        if value["Divisor"] == 0:
            raise ValueError(f"GameConstants[{row['_row']}].Divisor: zero divisor")
        constants.append(
            {
                "constant": facts.identity("GameConstants", row["_row"]),
                "raw": facts.raw("GameConstants", row["_row"]),
                "value_raw": value["Value"],
                "divisor_raw": value["Divisor"],
            }
        )
    levels = facts.rows("DefaultMonsterStats")
    if [row["values"]["DisplayLevel"] for row in levels] != [str(level) for level in range(1, 101)]:
        raise ValueError("DefaultMonsterStats.DisplayLevel: expected source order 1..100")
    monsters = []
    for row in facts.rows("MonsterVarieties"):
        index, value = row["_row"], row["values"]
        monsters.append(
            {
                "monster": facts.identity("MonsterVarieties", index),
                "raw": facts.raw("MonsterVarieties", index),
                "monster_type": facts.identity("MonsterTypes", value["MonsterType"]),
                "facts_raw": {
                    field: value[field]
                    for field in (
                        "Name",
                        "BaseMonsterTypeIndex",
                        "InheritsFrom",
                        "LifeMultiplier",
                        "DamageMultiplier",
                        "AttackSpeed",
                        "AttackCrit",
                        "PoiseThreshold",
                        "BossHealthBar",
                        "MonsterCategory",
                        "MonsterArmour",
                        "MonsterSegment",
                    )
                },
                "main_hand_item_class": facts.identity("ItemClasses", value["MainHand_ItemClass"]),
                "off_hand_item_class": facts.identity("ItemClasses", value["OffHand_ItemClass"]),
                "tags": facts.ordered("Tags", value["Tags"]),
                "granted_effects": facts.ordered("GrantedEffects", value["GrantedEffects"]),
                "taunt_granted_effect": facts.identity("GrantedEffects", value["TauntGrantedEffect"]),
                "mod_groups": {
                    field: facts.ordered("Mods", value[field])
                    for field in ("Mods", "Mods2", "Special_Mods", "Part1_Mods", "Part2_Mods", "Endgame_Mods")
                },
            }
        )
    types = [
        {
            "monster_type": facts.identity("MonsterTypes", row["_row"]),
            "raw": facts.raw("MonsterTypes", row["_row"]),
            "values_raw": row["values"],
            "resistances": facts.ordered("MonsterResistances", row["values"]["MonsterResistances"]),
        }
        for row in facts.rows("MonsterTypes")
    ]
    summoned = [
        {
            "row": row["_row"],
            "raw": facts.raw("SummonedSpecificMonsters", row["_row"]),
            "id_raw": row["values"]["Id"],
            "monster": facts.identity("MonsterVarieties", row["values"]["MonsterVarietiesKey"]),
            "buff_definition": facts.identity("BuffDefinitions", row["values"]["BuffDefinition"]),
        }
        for row in facts.rows("SummonedSpecificMonsters")
    ]
    intrinsic = [
        {
            "row": row["_row"],
            "raw": facts.raw("PlayerMinionIntrinsicStats", row["_row"]),
            "stat": facts.identity("Stats", row["values"]["Stat"]),
            "value_raw": row["values"]["Value"],
        }
        for row in facts.rows("PlayerMinionIntrinsicStats")
    ]
    spectres = [
        {
            "row": row["_row"],
            "raw": facts.raw("SpectreOverrides", row["_row"]),
            "monster": facts.identity("MonsterVarieties", row["values"]["Monster"]),
            "spectre": facts.identity("MonsterVarieties", row["values"]["Spectre"]),
        }
        for row in facts.rows("SpectreOverrides")
    ]
    auxiliary = (
        "MinionType",
        "MinionStats",
        "MinionGemLevelScaling",
        "SpectreOverrides",
        "SkillTotemVariations",
        "SummonedSpecificMonstersOnDeath",
        "DisplayMinionMonsterType",
        "MonsterResistances",
    )
    document = {
        "actor_policy": "source-inventory; playable identity and server formulas unresolved",
        "constants": constants,
        "default_monster_stats": [facts.record("DefaultMonsterStats", row["_row"]) for row in levels],
        "monsters": monsters,
        "monster_types": types,
        "summoned_specific_monsters": summoned,
        "intrinsic_minion_stats": intrinsic,
        "spectre_overrides": spectres,
        "auxiliary_rows": {name: [facts.record(name, row["_row"]) for row in facts.rows(name)] for name in auxiliary},
    }
    summary = {
        "constant_rows": len(constants),
        "default_monster_level_rows": len(levels),
        "monster_variety_rows": len(monsters),
        "monster_type_rows": len(types),
        "monster_resistance_rows": len(facts.rows("MonsterResistances")),
        "summoned_monster_rows": len(summoned),
        "intrinsic_minion_stat_rows": len(intrinsic),
        "minion_gem_scaling_rows": len(facts.rows("MinionGemLevelScaling")),
        "spectre_override_rows": len(spectres),
    }
    return document, summary, []
