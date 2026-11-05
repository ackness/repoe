//! Stable schema IDs for the package members the adapter reads and writes.
//!
//! An ID is `pobr-<name>/v<n>`: `<name>` is the member's file stem with `_`
//! replaced by `-` (`overlay/runes.json` is `pobr-runes/v1`), or the domain
//! name for a domain that writes several members (`pobr-passive-tree/v1`).
//! Data and receipts name these IDs rather than Rust type paths of
//! `pobr_data`, which change when PoBR moves a type.
//!
//! Policies pinned before the IDs existed spell a member's schema as its
//! `pobr_data::catalog::…` type path. Their bytes are pinned inputs, so each
//! ID still accepts that spelling as a legacy alias.

/// One member schema and the type-path spelling pinned policies may use.
#[derive(Clone, Copy, Debug)]
pub(crate) struct SchemaId {
    pub(crate) id: &'static str,
    legacy: &'static str,
}

impl SchemaId {
    pub(crate) fn accepts(self, value: &str) -> bool {
        value == self.id || value == self.legacy
    }
}

pub(crate) const GAME_CONSTANTS: SchemaId = SchemaId {
    id: "pobr-game-constants/v1",
    legacy: "pobr_data::catalog::GameConstantsDef",
};
pub(crate) const CHARACTER_CONSTANTS: SchemaId = SchemaId {
    id: "pobr-character-constants/v1",
    legacy: "pobr_data::catalog::CharacterConstantsDef",
};
pub(crate) const JEWEL_RADII: SchemaId = SchemaId {
    id: "pobr-jewel-radii/v1",
    legacy: "pobr_data::catalog::JewelRadiiDef",
};
pub(crate) const NON_DAMAGING_AILMENTS: SchemaId = SchemaId {
    id: "pobr-non-damaging-ailments/v1",
    legacy: "pobr_data::catalog::non_damaging_ailments::NonDamagingAilmentsDef",
};
pub(crate) const PASSIVE_TREE: SchemaId = SchemaId {
    id: "pobr-passive-tree/v1",
    legacy: "pobr_data::catalog::PassiveNodeDef[]",
};
pub(crate) const PASSIVE_TREE_META: SchemaId = SchemaId {
    id: "pobr-passive-tree-meta/v1",
    legacy: "pobr_data::catalog::PassiveTreeMeta",
};

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ids_accept_their_legacy_type_path_only() {
        assert!(GAME_CONSTANTS.accepts("pobr-game-constants/v1"));
        assert!(GAME_CONSTANTS.accepts("pobr_data::catalog::GameConstantsDef"));
        assert!(!GAME_CONSTANTS.accepts("pobr_data::catalog::JewelRadiiDef"));
        assert!(!GAME_CONSTANTS.accepts("pobr-jewel-radii/v1"));
        assert!(!PASSIVE_TREE.accepts("pobr_data::catalog::PassiveNodeDef"));
    }
}
