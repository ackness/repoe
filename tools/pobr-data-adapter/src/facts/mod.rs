//! Authenticated RePoE facts input: envelope and source-lock verification, selected
//! physical tables, the player context archive and guarded output directories.

pub(crate) mod inputs;
pub(crate) mod model;
pub(crate) mod output;
pub(crate) mod physical;
pub(crate) mod player;
pub(crate) mod reader;
pub(crate) mod trust;

pub(crate) use output::Output;

use std::path::PathBuf;

pub(crate) struct Args {
    pub(crate) input: PathBuf,
    pub(crate) expected_manifest_sha256: String,
    pub(crate) source_lock: PathBuf,
    pub(crate) out: PathBuf,
    pub(crate) profile: Profile,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum Profile {
    BaseV1,
    CoreSkillsA0,
    GemsConstraintsA1,
    ItemsActorsBc,
}

impl Profile {
    pub(crate) fn format(self) -> &'static str {
        match self {
            Self::BaseV1 => "repoe-native-facts/v1",
            Self::CoreSkillsA0 => "repoe-native-facts/v2",
            Self::GemsConstraintsA1 => "repoe-native-facts/v3",
            Self::ItemsActorsBc => "repoe-native-facts/v4",
        }
    }

    pub(crate) fn producer_revision(self) -> &'static str {
        match self {
            Self::BaseV1 => trust::PRODUCER_REVISION,
            Self::CoreSkillsA0 => "aa2fb163aa422317db5c32031607eb199214e7b7",
            Self::GemsConstraintsA1 => "c450fb8e3ad4e5792386c7c5bb81c90d85407e62",
            Self::ItemsActorsBc => "e41401224a085a676c84b8f14b144f20fe37c79a",
        }
    }

    pub(crate) fn name(self) -> Option<&'static str> {
        match self {
            Self::BaseV1 => None,
            Self::CoreSkillsA0 => Some("core-skills-a0"),
            Self::GemsConstraintsA1 => Some("gems-constraints-a1"),
            Self::ItemsActorsBc => Some("items-actors-bc"),
        }
    }
}

pub(crate) fn json_bytes(value: &impl serde::Serialize) -> Result<Vec<u8>, String> {
    let mut bytes = serde_json::to_vec(value).map_err(|e| e.to_string())?;
    bytes.push(b'\n');
    Ok(bytes)
}
