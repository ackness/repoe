"""Source gem identity and ordered constraint facts, without eligibility policy."""

from collections import defaultdict


TABLES = (
    "SkillGems",
    "GemEffects",
    "GemTags",
    "SupportGems",
    "SupportGemFamily",
    "ItemExperienceTypes",
    "ItemExperiencePerLevel",
    "SkillCraftingData",
    "SkillGemSearchTerms",
    "SkillGemSupports",
    "BaseItemTypes",
    "ItemClasses",
    "Tags",
    "ActionTypes",
    "ActiveSkillWeaponRequirement",
    "WieldableClasses",
    "ClientStrings",
    "AlternateSkillTargetingBehaviours",
    "VirtualStatContextFlags",
    "ShapeShiftForms",
    "MinionType",
    "PassiveSkillStatCategories",
    "ItemClassCategories",
    "ItemStances",
)
LIMITS = [
    "Partial candidate only; forbidden as a production snapshot or runtime-ready PoBR pack.",
    "Thirty-nine physical DAT tables and the Default PSG; metadata, text and full foreign-key closure remain incomplete.",
    "Acquisition status/evidence is caller-declared, not source authentication by this exporter.",
    "All source gem rows remain; catalogue playability, unknown flags and hidden/legacy exclusion policy are unresolved.",
    "Type arrays retain ordered operator identities; no expression grammar or support eligibility is evaluated.",
    "Support families and positive associations are facts, not certified conflict rules or an exhaustive whitelist.",
    "Requirements, levels, costs, interpolation and quality channels remain raw; no formulas, units or scope are inferred.",
    "No CSD/locale closure, physical radii, global coordinates, actor formulas or complete gameplay support is inferred.",
]


def project(tables, resolve):
    def rows(table):
        return tables[table]["rows"]

    def values(table, row):
        resolve(tables, table, row, f"{table} physical row")
        return rows(table)[row]["values"]

    def identity(table, row):
        return resolve(tables, table, row, f"{table} identity")

    def optional(table, row):
        return None if row is None else identity(table, row)

    def refs(table, source):
        return [optional(table, row) for row in source]

    def raw(table, row):
        return {"payload": f"tables/{table}.json", "pointer": f"/rows/{row}/values"}

    def gem(row):
        value = values("SkillGems", row)
        return {"row": row, "item": identity("BaseItemTypes", value["BaseItemType"])}

    def optional_gem(row):
        return None if row is None else gem(row)

    # These collections expose stable string IDs. Source tables without Id keep
    # physical rows and related identities; never invent SkillGems/Wieldable IDs.
    for table in (
        "BaseItemTypes",
        "ItemClasses",
        "Tags",
        "GemEffects",
        "GemTags",
        "SupportGemFamily",
        "ItemExperienceTypes",
        "ActiveSkillWeaponRequirement",
    ):
        ids = [row["values"]["Id"] for row in rows(table)]
        if any(not isinstance(value, str) or not value for value in ids) or len(ids) != len(set(ids)):
            raise ValueError(f"{table}: missing or duplicate stable identity")

    diagnostics = []
    supports_by_gem = defaultdict(list)
    for row in rows("SupportGems"):
        supports_by_gem[row["values"]["SkillGem"]].append(row["_row"])
    for owner, owners in supports_by_gem.items():
        if len(owners) > 1:
            diagnostics.append({"code": "duplicate_support_metadata_owner", "gem": gem(owner), "support_rows": owners})
    item_owners, effect_owners = defaultdict(list), defaultdict(list)
    gems = {
        "catalogue_policy": "source-inventory; playability unresolved",
        "items": [],
        "effects": [],
        "tags": [],
        "supports": [],
        "families": [],
        "support_associations": [],
        "experience_types": [],
        "experience_levels": [],
    }
    for row in rows("SkillGems"):
        index, value = row["_row"], row["values"]
        base = values("BaseItemTypes", value["BaseItemType"])
        item = gem(index)
        item_owners[item["item"]["id"]].append(index)
        bindings = []
        for slot, effect_row in enumerate(value["GemEffects"]):
            bindings.append({"source_slot": slot, "gem_effect": optional("GemEffects", effect_row)})
            if effect_row is None:
                diagnostics.append({"code": "null_gem_effect_binding", "gem": item, "source_slot": slot})
                continue
            effect_owners[effect_row].append({"gem_row": index, "source_slot": slot})
            granted = values("GemEffects", effect_row)["GrantedEffect"]
            if granted is not None:
                support_flag = values("GrantedEffects", granted)["IsSupport"]
                if support_flag != bool(supports_by_gem[index]):
                    diagnostics.append(
                        {
                            "code": "support_flag_metadata_disagreement",
                            "gem": item,
                            "gem_effect_slot": slot,
                            "effect": identity("GrantedEffects", granted),
                            "is_support_raw": support_flag,
                            "support_rows": supports_by_gem[index],
                        }
                    )
        if base["ItemClass"] is not None:
            item_class = values("ItemClasses", base["ItemClass"])["Id"]
            if item_class == "Support Skill Gem" and not supports_by_gem[index]:
                diagnostics.append({"code": "support_class_without_metadata", "gem": item})
        gems["items"].append(
            {
                "gem": item,
                "raw": raw("SkillGems", index),
                "raw_base": raw("BaseItemTypes", value["BaseItemType"]),
                "name": base["Name"],
                "item_class": optional("ItemClasses", base["ItemClass"]),
                "item_tags": refs("Tags", base["Tags"]),
                "gem_effects": bindings,
                "gem_type_raw": value["GemType"],
                "gem_colour_raw": value["GemColour"],
                "min_level_requirement_raw": value["MinLevelReq"],
                "strength_requirement_percent_raw": value["StrengthRequirementPercent"],
                "dexterity_requirement_percent_raw": value["DexterityRequirementPercent"],
                "intelligence_requirement_percent_raw": value["IntelligenceRequirementPercent"],
                "experience_type": optional("ItemExperienceTypes", value["ItemExperienceType"]),
                "global_skill_level_stat": optional("Stats", value["GlobalSkillLevelStat"]),
                "base_skill_gem": optional_gem(value["BaseSkillGem"]),
                "regular_variant": optional_gem(value["RegularVariant"]),
                "awakened_variant": optional_gem(value["AwakenedVariant"]),
                "vaal_variant_item": optional("BaseItemTypes", value["VaalVariant_BaseItemType"]),
                "is_vaal_variant_raw": value["IsVaalVariant"],
                "support_metadata_rows": list(supports_by_gem[index]),
            }
        )
    for item, owners in item_owners.items():
        if len(owners) > 1:
            diagnostics.append({"code": "duplicate_gem_item_identity", "item_id": item, "gem_rows": owners})
    for row in rows("GemEffects"):
        index, value = row["_row"], row["values"]
        gems["effects"].append(
            {
                "gem_effect": identity("GemEffects", index),
                "raw": raw("GemEffects", index),
                "granted_effect": optional("GrantedEffects", value["GrantedEffect"]),
                "additional_granted_effects": refs("GrantedEffects", value["AdditionalGrantedEffects"]),
                "gem_tags": refs("GemTags", value["GemTags"]),
                "name_raw": value["Name"],
                "support_name": value["SupportName"],
                "support_text": value["SupportText"],
                "item_color_raw": value["ItemColor"],
            }
        )
        if not effect_owners[index]:
            diagnostics.append(
                {"code": "gem_effect_without_skill_gem_reference", "gem_effect": identity("GemEffects", index)}
            )
    for row in rows("GemTags"):
        index, value = row["_row"], row["values"]
        gems["tags"].append(
            {
                "tag": identity("GemTags", index),
                "name": value["Name"],
                "raw": raw("GemTags", index),
                "local_level_stat": optional("Stats", value["LocalLevelStat"]),
                "local_quality_stat": optional("Stats", value["LocalQualityStat"]),
                "global_spell_level_stat": optional("Stats", value["GlobalSpellLevelStat"]),
            }
        )
    for row in rows("SupportGems"):
        index, value = row["_row"], row["values"]
        gems["supports"].append(
            {
                "row": index,
                "gem": gem(value["SkillGem"]),
                "families": refs("SupportGemFamily", value["Family"]),
                "is_lineage_raw": value["IsLineage"],
                "raw": raw("SupportGems", index),
            }
        )
        if not value["Family"]:
            diagnostics.append(
                {"code": "support_metadata_empty_families", "support_row": index, "gem": gem(value["SkillGem"])}
            )
    for row in rows("SupportGemFamily"):
        index, value = row["_row"], row["values"]
        gems["families"].append(
            {
                "family": identity("SupportGemFamily", index),
                "text": value["Text"],
                "raw": raw("SupportGemFamily", index),
            }
        )
    for row in rows("SkillGemSupports"):
        index, value = row["_row"], row["values"]
        gems["support_associations"].append(
            {
                "row": index,
                "gem": gem(value["SkillGem"]),
                "supports": [optional_gem(ref) for ref in value["Supports"]],
                "raw": raw("SkillGemSupports", index),
            }
        )
    for row in rows("ItemExperienceTypes"):
        index = row["_row"]
        gems["experience_types"].append(
            {"experience_type": identity("ItemExperienceTypes", index), "raw": raw("ItemExperienceTypes", index)}
        )
    for row in rows("ItemExperiencePerLevel"):
        index, value = row["_row"], row["values"]
        gems["experience_levels"].append(
            {
                "row": index,
                "experience_type": identity("ItemExperienceTypes", value["ItemExperienceType"]),
                "item_current_level_raw": value["ItemCurrentLevel"],
                "experience_raw": value["Experience"],
                "level_raw": value["Level"],
                "raw": raw("ItemExperiencePerLevel", index),
            }
        )

    constraints = {"effects": [], "active_skills": [], "weapon_requirements": [], "wieldable_classes": []}
    for row in rows("GrantedEffects"):
        index, value = row["_row"], row["values"]
        constraints["effects"].append(
            {
                "effect": identity("GrantedEffects", index),
                "raw": raw("GrantedEffects", index),
                "active_skill": optional("ActiveSkills", value["ActiveSkill"]),
                "is_support_raw": value["IsSupport"],
                "cannot_be_supported_raw": value["CannotBeSupported"],
                "supports_gems_only_raw": value["SupportsGemsOnly"],
                "ignore_minion_types_raw": value["IgnoreMinionTypes"],
                "allowed_active_skill_types": refs("ActiveSkillType", value["AllowedActiveSkillTypes"]),
                "excluded_active_skill_types": refs("ActiveSkillType", value["ExcludedActiveSkillTypes"]),
                "added_active_skill_types": refs("ActiveSkillType", value["AddedActiveSkillTypes"]),
                "added_minion_active_skill_types": refs("ActiveSkillType", value["AddedMinionActiveSkillTypes"]),
                "minion_type": optional("MinionType", value["MinionType"]),
                "support_weapon_restrictions": refs("WieldableClasses", value["SupportWeaponRestrictions"]),
            }
        )
    for row in rows("ActiveSkills"):
        index, value = row["_row"], row["values"]
        constraints["active_skills"].append(
            {
                "active_skill": identity("ActiveSkills", index),
                "raw": raw("ActiveSkills", index),
                "active_skill_types": refs("ActiveSkillType", value["ActiveSkillTypes"]),
                "minion_active_skill_types": refs("ActiveSkillType", value["MinionActiveSkillTypes"]),
                "action_type": optional("ActionTypes", value["ActionType"]),
                "weapon_requirement": optional("ActiveSkillWeaponRequirement", value["WeaponRequirements"]),
                "shape_shift_form": optional("ShapeShiftForms", value["ShapeShiftForm"]),
                "is_gem_raw": value["IsGem"],
                "is_manually_casted_raw": value["IsManuallyCasted"],
                "hide_on_website_raw": value["HideOnWebsite"],
            }
        )
    for row in rows("ActiveSkillWeaponRequirement"):
        index, value = row["_row"], row["values"]
        constraints["weapon_requirements"].append(
            {
                "requirement": identity("ActiveSkillWeaponRequirement", index),
                "raw": raw("ActiveSkillWeaponRequirement", index),
                "wieldable_classes": refs("WieldableClasses", value["WieldableClasses"]),
                "stat": optional("Stats", value["Stat"]),
                "client_string": optional("ClientStrings", value["String"]),
            }
        )
    for row in rows("WieldableClasses"):
        index, value = row["_row"], row["values"]
        constraints["wieldable_classes"].append(
            {
                "row": index,
                "item_class": optional("ItemClasses", value["ItemClass"]),
                "tag": optional("Tags", value["Tag"]),
                "two_weapon_slots_raw": value["TwoWeaponSlots"],
                "raw": raw("WieldableClasses", index),
            }
        )
    summary = {
        "gem_items": len(gems["items"]),
        "gem_effect_definitions": len(gems["effects"]),
        "gem_tags": len(gems["tags"]),
        "support_metadata_rows": len(gems["supports"]),
        "support_families": len(gems["families"]),
        "support_association_rows": len(gems["support_associations"]),
        "item_experience_types": len(gems["experience_types"]),
        "item_experience_level_rows": len(gems["experience_levels"]),
        "effect_constraint_rows": len(constraints["effects"]),
        "active_constraint_rows": len(constraints["active_skills"]),
        "weapon_requirement_rows": len(constraints["weapon_requirements"]),
        "wieldable_class_rows": len(constraints["wieldable_classes"]),
    }
    return gems, constraints, summary, diagnostics
