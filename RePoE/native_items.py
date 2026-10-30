"""Source item/mod/socketable facts; no catalogue, units or applicability policy."""

from collections import defaultdict


TABLES = (
    "ArmourTypes",
    "AttributeRequirements",
    "BuffDefinitions",
    "BuffTemplates",
    "ClientStrings2",
    "ComponentCharges",
    "EssenceMods",
    "EssenceReplacementType",
    "EssenceTargetItemCategories",
    "Essences",
    "Flasks",
    "ItemInherentSkills",
    "ItemSpirit",
    "ModFamily",
    "ModType",
    "Mods",
    "ShieldTypes",
    "SoulCoreLimits",
    "SoulCoreStatCategories",
    "SoulCoreStats",
    "SoulCoreTypes",
    "SoulCores",
    "UtilityFlaskBuffs",
    "WeaponClasses",
    "WeaponTypes",
)
COMPONENTS = (
    "ArmourTypes",
    "AttributeRequirements",
    "ShieldTypes",
    "WeaponTypes",
    "ItemSpirit",
    "ItemInherentSkills",
    "Flasks",
)


class Facts:
    """Small physical-row helpers shared by the two bounded domain projections."""

    def __init__(self, tables, resolve):
        self.tables, self.resolve = tables, resolve

    def rows(self, table):
        return self.tables[table]["rows"]

    def values(self, table, row):
        self.resolve(self.tables, table, row, f"{table} physical owner")
        return self.rows(table)[row]["values"]

    def identity(self, table, row):
        if row is None:
            return None
        result = self.resolve(self.tables, table, row, f"{table} reference")
        # Some physical Id columns are numeric and have no established stable-ID
        # semantics. Keep them in the canonical row, not in the stable ID channel.
        if not isinstance(result.get("id"), str):
            result.pop("id", None)
        return result

    @staticmethod
    def raw(table, row):
        return {"payload": f"tables/{table}.json", "pointer": f"/rows/{row}/values"}

    def ordered(self, table, values):
        return [{"source_slot": slot, "target": self.identity(table, row)} for slot, row in enumerate(values)]

    def pairs(self, table, ids, values, context):
        if len(ids) != len(values):
            raise ValueError(f"{context}: unequal reference/value arrays")
        return [
            {"source_slot": slot, "target": self.identity(table, row), "value_raw": value}
            for slot, (row, value) in enumerate(zip(ids, values, strict=True))
        ]

    def stable_ids(self, table):
        ids = [row["values"]["Id"] for row in self.rows(table)]
        if any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
            raise ValueError(f"{table}: missing or duplicate stable string identity")

    def owners(self, table, field, target="BaseItemTypes"):
        result = {}
        for row in self.rows(table):
            owner = row["values"][field]
            self.values(target, owner)
            if owner in result:
                raise ValueError(f"{table}[{row['_row']}].{field}: ambiguous component owner {owner}")
            result[owner] = row["_row"]
        return result

    def record(self, table, row):
        return {"row": row, "raw": self.raw(table, row), "values_raw": self.values(table, row)}


def project(tables, resolve):
    facts = Facts(tables, resolve)
    for table in (
        "BaseItemTypes",
        "Mods",
        "ModFamily",
        "Tags",
        "ItemClasses",
        "SoulCoreTypes",
        "SoulCoreStatCategories",
        "SoulCoreLimits",
        "EssenceReplacementType",
        "EssenceTargetItemCategories",
    ):
        facts.stable_ids(table)
    mods = []
    for row in facts.rows("Mods"):
        index, value = row["_row"], row["values"]
        slots = []
        for slot in range(1, 9):
            stat = facts.identity("Stats", value[f"Stat{slot}"])
            minimum, maximum = value[f"Stat{slot}Min"], value[f"Stat{slot}Max"]
            if stat is not None and minimum > maximum:
                raise ValueError(f"Mods[{index}].Stat{slot}: inverted regular interval")
            slots.append(
                {
                    "slot": slot,
                    "stat": stat,
                    "min_raw": minimum,
                    "max_raw": maximum,
                    "min_hardmode_raw": value[f"Stat{slot}MinHardmode"],
                    "max_hardmode_raw": value[f"Stat{slot}MaxHardmode"],
                }
            )
        mods.append(
            {
                "mod": facts.identity("Mods", index),
                "raw": facts.raw("Mods", index),
                "slots": slots,
                "name_raw": value["Name"],
                "mod_type": facts.identity("ModType", value["ModType"]),
                "domain_raw": value["Domain"],
                "generation_type_raw": value["GenerationType"],
                "level_raw": value["Level"],
                "max_level_raw": value["MaxLevel"],
                "spawn_level_override_raw": value["SpawnLevel_Override"],
                "crafting_class_restrictions": facts.ordered("ItemClasses", value["CraftingItemClassRestrictions"]),
                "families": facts.ordered("ModFamily", value["Families"]),
                "tags": facts.ordered("Tags", value["Tags"]),
                "implicit_tags": facts.ordered("Tags", value["ImplicitTags"]),
                "spawn_weights": facts.pairs(
                    "Tags", value["SpawnWeight_Tags"], value["SpawnWeight_Values"], f"Mods[{index}].SpawnWeight"
                ),
                "generation_weights": facts.pairs(
                    "Tags",
                    value["GenerationWeight_Tags"],
                    value["GenerationWeight_Values"],
                    f"Mods[{index}].GenerationWeight",
                ),
                "has_hardmode_values_raw": value["HasHardmodeStatValues"],
                "essence_only_raw": value["IsEssenceOnlyModifier"],
                "granted_effect_levels": facts.ordered("GrantedEffectsPerLevel", value["GrantedEffectsPerLevel"]),
                "buff_template": facts.identity("BuffTemplates", value["BuffTemplate"]),
                "buff_templates2": facts.ordered("BuffTemplates", value["BuffTemplate2"]),
            }
        )
    components = {table: facts.owners(table, "BaseItemType") for table in COMPONENTS}
    charges = {}
    bases_by_id = {row["values"]["Id"]: row["_row"] for row in facts.rows("BaseItemTypes")}
    for row in facts.rows("ComponentCharges"):
        key = row["values"]["BaseItemTypesKey"]
        if key not in bases_by_id or key in charges:
            raise ValueError(f"ComponentCharges[{row['_row']}].BaseItemTypesKey: unresolved or ambiguous {key!r}")
        charges[key] = row["_row"]
    bases = []
    for row in facts.rows("BaseItemTypes"):
        index, value = row["_row"], row["values"]
        bases.append(
            {
                "item": facts.identity("BaseItemTypes", index),
                "raw": facts.raw("BaseItemTypes", index),
                "name": value["Name"],
                "item_class": facts.identity("ItemClasses", value["ItemClass"]),
                "width_raw": value["Width"],
                "height_raw": value["Height"],
                "drop_level_raw": value["DropLevel"],
                "mod_domain_raw": value["ModDomain"],
                "inherits_from_raw": value["InheritsFrom"],
                "direct_tags": facts.ordered("Tags", value["Tags"]),
                "implicit_mods": facts.ordered("Mods", value["Implicit_Mods"]),
                "components": {
                    table: facts.record(table, owners[index]) if index in owners else None
                    for table, owners in components.items()
                },
                "charges": facts.record("ComponentCharges", charges[value["Id"]]) if value["Id"] in charges else None,
            }
        )
    core_owner = facts.owners("SoulCores", "BaseItemType")
    groups = defaultdict(list)
    pairs_seen = defaultdict(list)
    for row in facts.rows("SoulCoreStats"):
        index, value = row["_row"], row["values"]
        facts.values("SoulCores", value["SoulCore"])
        pairs_seen[(value["SoulCore"], value["StatCategory"])].append(index)
        groups[value["SoulCore"]].append(
            {
                "row": index,
                "raw": facts.raw("SoulCoreStats", index),
                "category": facts.identity("SoulCoreStatCategories", value["StatCategory"]),
                "regular": facts.pairs("Stats", value["Stats"], value["StatsValues"], f"SoulCoreStats[{index}].Stats"),
                "bonded": facts.pairs(
                    "Stats", value["BondedStats"], value["BondedStatsValues"], f"SoulCoreStats[{index}].BondedStats"
                ),
            }
        )
    cores = [
        {
            "row": row["_row"],
            "raw": facts.raw("SoulCores", row["_row"]),
            "item": facts.identity("BaseItemTypes", row["values"]["BaseItemType"]),
            "type": facts.identity("SoulCoreTypes", row["values"]["Type"]),
            "limit": facts.identity("SoulCoreLimits", row["values"]["Limit"]),
            "tier_higher": facts.identity("SoulCores", row["values"]["TierHigher"]),
            "constraints_raw": row["values"],
            "stat_groups": groups[row["_row"]],
        }
        for row in facts.rows("SoulCores")
    ]
    categories = [
        {
            "category": facts.identity("SoulCoreStatCategories", row["_row"]),
            "raw": facts.raw("SoulCoreStatCategories", row["_row"]),
            "display_raw": row["values"]["Display"],
            "unknown0_raw": row["values"]["Unknown0"],
            "target_item_classes": facts.ordered("ItemClasses", row["values"]["TargetItemClasses"]),
        }
        for row in facts.rows("SoulCoreStatCategories")
    ]
    buffs = []
    for row in facts.rows("UtilityFlaskBuffs"):
        value = row["values"]
        definition = facts.values("BuffDefinitions", value["BuffDefinition"])
        buffs.append(
            {
                "row": row["_row"],
                "raw": facts.raw("UtilityFlaskBuffs", row["_row"]),
                "definition": facts.identity("BuffDefinitions", value["BuffDefinition"]),
                "primary": facts.pairs(
                    "Stats", definition["Stats"], value["StatValues"], f"UtilityFlaskBuffs[{row['_row']}].primary"
                ),
                "secondary_values_raw": value["StatValues2"],
                "definition_raw": facts.raw("BuffDefinitions", value["BuffDefinition"]),
                "granted_flags": facts.ordered("Stats", definition["GrantedFlags"]),
                "granted_stats": facts.ordered("Stats", definition["GrantedStats"]),
                "condition_stats": facts.ordered("Stats", definition["ConditionStats"]),
            }
        )
    essences = []
    for row in facts.rows("EssenceMods"):
        value = row["values"]
        essences.append(
            {
                "row": row["_row"],
                "raw": facts.raw("EssenceMods", row["_row"]),
                "essence": facts.identity("Essences", value["Essence"]),
                "target_category": facts.identity("EssenceTargetItemCategories", value["TargetItemCategory"]),
                "mod": facts.identity("Mods", value["Mod"]),
                "display_mod": facts.identity("Mods", value["DisplayMod"]),
                "outcome_mods": facts.ordered("Mods", value["OutcomeMods"]),
                "outcome_weights_raw": value["OutcomeModWeights"],
                "outcomes": facts.pairs(
                    "Mods", value["OutcomeMods"], value["OutcomeModWeights"], f"EssenceMods[{row['_row']}].outcomes"
                )
                if len(value["OutcomeMods"]) == len(value["OutcomeModWeights"])
                else None,
                "text_raw": value["Text"],
            }
        )
    diagnostics = [
        {"code": "duplicate_soulcore_category", "core_row": key[0], "category_row": key[1], "rows": rows}
        for key, rows in pairs_seen.items()
        if len(rows) > 1
    ]
    diagnostics.extend(
        {"code": "soulcore_without_stat_groups", "core_row": core["row"], "item": core["item"]}
        for core in cores
        if not core["stat_groups"]
    )
    diagnostics.extend(
        {
            "code": "essence_outcome_weight_alignment_unresolved",
            "row": entry["row"],
            "outcome_mods": entry["outcome_mods"],
            "outcome_weights_raw": entry["outcome_weights_raw"],
        }
        for entry in essences
        if entry["outcomes"] is None
    )
    document = {
        "catalogue_policy": "source-inventory; playability unresolved",
        "mods": mods,
        "base_items": bases,
        "soul_cores": cores,
        "soul_core_categories": categories,
        "utility_buffs": buffs,
        "essence_mods": essences,
        "auxiliary_rows": {
            name: [facts.record(name, row["_row"]) for row in facts.rows(name)]
            for name in (
                "ModType",
                "ModFamily",
                "WeaponClasses",
                "SoulCoreTypes",
                "SoulCoreLimits",
                "Essences",
                "EssenceTargetItemCategories",
                "EssenceReplacementType",
            )
        },
    }
    summary = {
        "mod_rows": len(mods),
        "base_item_rows": len(bases),
        "soul_core_rows": len(core_owner),
        "soul_core_stat_rows": len(facts.rows("SoulCoreStats")),
        "soul_core_category_rows": len(categories),
        "utility_buff_rows": len(buffs),
        "essence_mod_rows": len(essences),
    }
    return document, summary, diagnostics
