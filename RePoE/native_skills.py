"""Source-ordered skill-core facts, without interpolation or gameplay policy."""

TABLES = (
    "GrantedEffectLabels",
    "ActiveSkills",
    "ActiveSkillType",
    "CostTypes",
    "GrantedEffectsPerLevel",
    "GrantedEffectStatSetsPerLevel",
    "EffectivenessCostConstants",
)
LIMITS = [
    "Partial candidate only; forbidden as a production snapshot or runtime-ready PoBR pack.",
    "Fifteen physical DAT tables and the Default PSG; foreign-key/metadata closure remains incomplete.",
    "Acquisition evidence/status is caller-declared, not source authentication by this exporter.",
    "Community schema field names are interpretations, not certified gameplay semantics.",
    "Raw level/cost/interpolation channels are retained; no interpolation, quality application or unit policy is inferred.",
    "No gem catalogue, complete text/locale coverage, physical radii or global coordinates are inferred.",
    "Definition existence and default graph membership are distinct; no historical deletion is inferred.",
]


def project(tables, resolve):
    def rows(table):
        return tables[table]["rows"]

    def identity(table, row):
        return resolve(tables, table, row, f"{table} identity")

    def optional(table, row):
        return None if row is None else identity(table, row)

    def raw(table, row):
        return {"payload": f"tables/{table}.json", "pointer": f"/rows/{row}/values"}

    # These definition tables expose stable string IDs; levels expose owner
    # relations instead. Never manufacture a stable ID from a physical row.
    for table in ("GrantedEffectLabels", "ActiveSkills", "ActiveSkillType", "CostTypes", "EffectivenessCostConstants"):
        ids = [row["values"]["Id"] for row in rows(table)]
        if any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
            raise ValueError(f"{table}: missing or duplicate stable identity")

    core = {
        "labels": [
            {
                "label": identity("GrantedEffectLabels", row["_row"]),
                "text": row["values"]["Text"],
                "raw": raw("GrantedEffectLabels", row["_row"]),
            }
            for row in rows("GrantedEffectLabels")
        ],
        "stat_set_labels": [
            {
                "stat_set": identity("GrantedEffectStatSets", row["_row"]),
                "label": optional("GrantedEffectLabels", row["values"]["Label"]),
                "raw": raw("GrantedEffectStatSets", row["_row"]),
            }
            for row in rows("GrantedEffectStatSets")
        ],
        "active_skill_types": [
            {
                "skill_type": identity("ActiveSkillType", row["_row"]),
                "flag_stat": optional("Stats", row["values"]["FlagStat"]),
                "raw": raw("ActiveSkillType", row["_row"]),
            }
            for row in rows("ActiveSkillType")
        ],
        "active_skills": [
            {
                "active_skill": identity("ActiveSkills", row["_row"]),
                "granted_effect_string_raw": row["values"]["GrantedEffect"],
                "raw": raw("ActiveSkills", row["_row"]),
            }
            for row in rows("ActiveSkills")
        ],
        "effect_metadata": [
            {
                "effect": identity("GrantedEffects", row["_row"]),
                "active_skill": optional("ActiveSkills", row["values"]["ActiveSkill"]),
                "cost_types": [optional("CostTypes", value) for value in row["values"]["CostTypes"]],
                "raw": raw("GrantedEffects", row["_row"]),
            }
            for row in rows("GrantedEffects")
        ],
        "cost_types": [
            {
                "cost_type": identity("CostTypes", row["_row"]),
                "stat": optional("Stats", row["values"]["Stat"]),
                "divisor_raw": row["values"]["Divisor"],
                "per_minute_raw": row["values"]["PerMinute"],
                "format_text": row["values"]["FormatText"],
                "raw": raw("CostTypes", row["_row"]),
            }
            for row in rows("CostTypes")
        ],
        "interpolation_constants": [
            {
                "constant": identity("EffectivenessCostConstants", row["_row"]),
                "multiplier_raw": row["values"]["Multiplier"],
                "raw": raw("EffectivenessCostConstants", row["_row"]),
            }
            for row in rows("EffectivenessCostConstants")
        ],
        "effect_levels": [],
        "stat_set_levels": [],
    }
    diagnostics = []
    for row in rows("GrantedEffectsPerLevel"):
        values = row["values"]
        effect = identity("GrantedEffects", values["GrantedEffect"])
        types = rows("GrantedEffects")[effect["row"]]["values"]["CostTypes"]
        amounts = values["CostAmounts"]
        entry = {
            "row": row["_row"],
            "effect": effect,
            "level_raw": values["Level"],
            "actor_level_raw": values["ActorLevel"],
            "cost_amounts_raw": amounts,
            "raw": raw("GrantedEffectsPerLevel", row["_row"]),
        }
        # Retain both arrays if their alignment is unresolved; never zip to the
        # shorter input or invent a default cost type/amount.
        if len(types) == len(amounts):
            entry["costs"] = [
                {"slot": slot, "cost_type": optional("CostTypes", cost_type), "amount_raw": amount}
                for slot, (cost_type, amount) in enumerate(zip(types, amounts, strict=True))
            ]
        else:
            entry["costs"] = None
            diagnostics.append(
                {
                    "code": "unresolved_cost_array_alignment",
                    "row": row["_row"],
                    "effect": effect,
                    "cost_types_raw": types,
                    "cost_amounts_raw": amounts,
                }
            )
        core["effect_levels"].append(entry)
    for row in rows("GrantedEffectStatSetsPerLevel"):
        values = row["values"]
        entry = {
            "row": row["_row"],
            "stat_set": identity("GrantedEffectStatSets", values["StatSet"]),
            "gem_level_raw": values["GemLevel"],
            "actor_level_raw": values["ActorLevel"],
            "spell_crit_chance_raw": values["SpellCritChance"],
            "attack_crit_chance_raw": values["AttackCritChance"],
            "base_multiplier_raw": values["BaseMultiplier"],
            "base_resolved_values_raw": values["BaseResolvedValues"],
            "additional_stats_values_raw": values["AdditionalStatsValues"],
            "float_stats_values_raw": values["FloatStatsValues"],
            "additional_stats": [optional("Stats", value) for value in values["AdditionalStats"]],
            "float_stats": [optional("Stats", value) for value in values["FloatStats"]],
            "interpolation_bases": [
                optional("EffectivenessCostConstants", value) for value in values["InterpolationBases"]
            ],
            "stat_interpolations_raw": values["StatInterpolations"],
            "raw": raw("GrantedEffectStatSetsPerLevel", row["_row"]),
        }
        for stats, amounts in [("AdditionalStats", "AdditionalStatsValues"), ("FloatStats", "FloatStatsValues")]:
            if len(values[stats]) != len(values[amounts]):
                diagnostics.append(
                    {
                        "code": "unresolved_level_stat_array_alignment",
                        "row": row["_row"],
                        "stat_set": entry["stat_set"],
                        "stat_field": stats,
                        "value_field": amounts,
                        "stats_raw": values[stats],
                        "values_raw": values[amounts],
                    }
                )
        core["stat_set_levels"].append(entry)
    summary = {
        "labels": len(core["labels"]),
        "active_skills": len(core["active_skills"]),
        "active_skill_types": len(core["active_skill_types"]),
        "cost_types": len(core["cost_types"]),
        "effect_level_rows": len(core["effect_levels"]),
        "stat_set_level_rows": len(core["stat_set_levels"]),
        "interpolation_constants": len(core["interpolation_constants"]),
    }
    return core, summary, diagnostics
