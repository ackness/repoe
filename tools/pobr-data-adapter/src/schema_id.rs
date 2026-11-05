//! The one registry of schema IDs the adapter reads and writes.
//!
//! IDs follow the contract crate's convention, `<name>/v<n>` (as in
//! `pobr_data::catalog::BUFF_DEFINITIONS_SCHEMA = "buff_definitions/v1"`).
//!
//! * Every domain candidate receipt names its output by one of the
//!   `pub(crate) const …: &str` IDs below (`adapter.output_schema`), never by
//!   a Rust type path. The translation repository selects receipts by them.
//! * A member that declares its own schema in `_meta.schema` is that member's
//!   declaration; its domain ID must agree with it. Converters therefore write
//!   `_meta.schema` from these same constants, and the spellings are kept
//!   exactly as published (including the hyphenated `monster-resistances/v1`,
//!   `monster-scaling/v1` and `totem-varieties/v1`).
//! * For a member without `_meta.schema`, the ID is the member's file stem
//!   (`overlay/runes.json` is `runes/v1`); a domain that writes several
//!   members is named after the domain (`stats_mods/v1`, `skills/v1`).
//!
//! Policies name the schema of each selected input file by the same IDs
//! ([`SchemaId`]); the `pobr_data::catalog::…` type-path spellings that
//! policies pinned before the registry used were retired with game
//! 0.5.5.5-2, when every pinned policy was rewritten.

// Domain outputs. Members that declare `_meta.schema` themselves:
pub(crate) const ITEM_GRANTED_SKILLS: &str = "item_granted_skills/v1";
pub(crate) const UNIQUE_RELATIONS: &str = "unique_relations/v1";
pub(crate) const GEM_QUALITY_STATS: &str = "gem_quality_stats/v1";
pub(crate) const STAT_SET_LABELS: &str = "stat_set_labels/v1";
pub(crate) const GEM_EFFECTS: &str = "gem_effects/v1";
pub(crate) const MONSTER_RESISTANCES: &str = "monster-resistances/v1";
pub(crate) const TOTEM_VARIETIES: &str = "totem-varieties/v1";
pub(crate) const MONSTER_SCALING: &str = "monster-scaling/v1";
pub(crate) const SKILL_STAT_MAP: &str = "skill_stat_map/v1";
pub(crate) const SKILL_OVERRIDES: &str = "skill_overrides/v1";
pub(crate) const MINIONS: &str = "minions/v1";
pub(crate) const SPECTRES: &str = "spectres/v1";
pub(crate) const GRANTED_EFFECT_MINIONS: &str = "granted_effect_minions/v1";
// Members without `_meta.schema` (named by file stem):
pub(crate) const UNARMED_DATA: &str = "unarmed_data/v1";
/// `overlay-common/passive_jewel_slots.json` declares this spelling.
pub(crate) const PASSIVE_JEWEL_SLOTS: &str = "passive_jewel_slots/v1";
/// `overlay-common/boss_poise_thresholds.json` declares this spelling.
pub(crate) const BOSS_POISE_THRESHOLDS: &str = "boss_poise_thresholds/v1";
pub(crate) const CATALYSTS: &str = "catalysts/v1";
pub(crate) const STAT_DESCRIPTIONS: &str = "stat_descriptions/v1";
pub(crate) const RUNES: &str = "runes/v1";
// Domains that write several members (named by domain):
/// `base/stats.json` and `base/mods.json`.
pub(crate) const STATS_MODS: &str = "stats_mods/v1";
/// `base/base_items.json`, plus `overlay/base_item_overrides.json`, which
/// declares its own `base_item_overrides/v1`.
pub(crate) const BASE_ITEMS: &str = "base_items/v1";
/// `base/{skill_gems,granted_effects,granted_effect_levels,granted_effect_stat_sets,cost_types}.json`.
pub(crate) const SKILLS: &str = "skills/v1";
/// The passive-tree domain: `base/passive_tree.json` ([`PASSIVE_TREE`], the
/// same ID as its main member) and `base/passive_tree_meta.json`
/// ([`PASSIVE_TREE_META`]).
pub(crate) const PASSIVE_TREE_DOMAIN: &str = PASSIVE_TREE.id;
/// `base/{game_constants,character_constants,jewel_radii,non_damaging_ailments}.json`.
pub(crate) const RUNTIME_CONSTANTS: &str = "runtime_constants/v1";

/// The schema of one selected input file, as policies name it.
#[derive(Clone, Copy, Debug)]
pub(crate) struct SchemaId {
    pub(crate) id: &'static str,
}

impl SchemaId {
    pub(crate) fn accepts(self, value: &str) -> bool {
        value == self.id
    }
}

pub(crate) const GAME_CONSTANTS: SchemaId = SchemaId {
    id: "game_constants/v1",
};
pub(crate) const CHARACTER_CONSTANTS: SchemaId = SchemaId {
    id: "character_constants/v1",
};
pub(crate) const JEWEL_RADII: SchemaId = SchemaId {
    id: "jewel_radii/v1",
};
pub(crate) const NON_DAMAGING_AILMENTS: SchemaId = SchemaId {
    id: "non_damaging_ailments/v1",
};
/// The member `base/passive_tree.json` (a `PassiveNodeDef` array). The
/// passive-tree domain reuses its ID ([`PASSIVE_TREE_DOMAIN`]).
pub(crate) const PASSIVE_TREE: SchemaId = SchemaId {
    id: "passive_tree/v1",
};
/// The member `base/passive_tree_meta.json`.
pub(crate) const PASSIVE_TREE_META: SchemaId = SchemaId {
    id: "passive_tree_meta/v1",
};

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ids_accept_only_themselves() {
        assert!(GAME_CONSTANTS.accepts("game_constants/v1"));
        assert!(!GAME_CONSTANTS.accepts("pobr_data::catalog::GameConstantsDef"));
        assert!(!GAME_CONSTANTS.accepts("jewel_radii/v1"));
        assert!(!PASSIVE_TREE.accepts("pobr_data::catalog::PassiveNodeDef[]"));
    }

    /// The `_meta.schema` spellings of the published 0.5.5.5 game package
    /// (`3edc9b1e…`): converters write these constants, so a domain ID can only
    /// change together with the member's own declaration.
    #[test]
    fn ids_match_the_published_member_declarations() {
        for (id, published) in [
            (ITEM_GRANTED_SKILLS, "item_granted_skills/v1"),
            (GEM_QUALITY_STATS, "gem_quality_stats/v1"),
            (STAT_SET_LABELS, "stat_set_labels/v1"),
            (GEM_EFFECTS, "gem_effects/v1"),
            (MONSTER_RESISTANCES, "monster-resistances/v1"),
            (TOTEM_VARIETIES, "totem-varieties/v1"),
            (MONSTER_SCALING, "monster-scaling/v1"),
            (SKILL_STAT_MAP, "skill_stat_map/v1"),
            (SKILL_OVERRIDES, "skill_overrides/v1"),
            (MINIONS, "minions/v1"),
            (SPECTRES, "spectres/v1"),
            (GRANTED_EFFECT_MINIONS, "granted_effect_minions/v1"),
            (PASSIVE_JEWEL_SLOTS, "passive_jewel_slots/v1"),
            (BOSS_POISE_THRESHOLDS, "boss_poise_thresholds/v1"),
        ] {
            assert_eq!(id, published);
        }
        assert_eq!(PASSIVE_TREE_DOMAIN, "passive_tree/v1");
    }
}
