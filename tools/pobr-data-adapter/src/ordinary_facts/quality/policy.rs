//! A pinned target applicability decision, separate from source acquisition and numeric facts.

use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::native_facts::reader::{self, VerifiedFacts};
use crate::raw_source::sha256_hex;
use crate::skills::quality::{Compatibility, validate_compatibility};

pub(in crate::ordinary_facts) struct Args {
    pub path: PathBuf,
    pub expected_sha256: String,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Policy {
    schema: String,
    target: Target,
    pub compatibility: Compatibility,
    pub reference: Reference,
    pub target_applicability: Applicability,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Target {
    game_patch: String,
    facts_manifest_sha256: String,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Reference {
    schema: String,
    game_patch: String,
    policy_path: String,
    policy_sha256: String,
    quality_path: String,
    quality_sha256: String,
    provenance: Value,
    inputs: BTreeMap<String, String>,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Applicability {
    kind: String,
    source_check_sha256: String,
    baseline_sha256: String,
    statement: String,
}

pub(in crate::ordinary_facts) struct Pinned {
    pub(super) policy: Policy,
    pub(super) bytes: Vec<u8>,
    pub(super) sha256: String,
    pub(super) parent: PathBuf,
}

pub(in crate::ordinary_facts) fn read(args: &Args) -> Result<Pinned, String> {
    hex(&args.expected_sha256, 64, "expected quality policy SHA256")?;
    let path = args
        .path
        .canonicalize()
        .map_err(|e| format!("quality policy: {e}"))?;
    let bytes = fs::read(&path).map_err(|e| format!("quality policy: {e}"))?;
    let sha256 = sha256_hex(&bytes);
    if sha256 != args.expected_sha256 {
        return Err("quality policy SHA256 mismatch (checked before parsing)".into());
    }
    let policy: Policy = serde_json::from_value(reader::strict_json(&bytes)?)
        .map_err(|e| format!("quality policy: {e}"))?;
    if !matches!(
        policy.schema.as_str(),
        "pobr-ordinary-quality-policy/v1" | "pobr-ordinary-quality-policy/v2"
    ) {
        return Err("unsupported quality policy schema".into());
    }
    hex(
        &policy.target.facts_manifest_sha256,
        64,
        "target facts manifest SHA256",
    )?;
    validate_compatibility(&policy.compatibility)?;
    hex(
        &policy.compatibility.reference_vendor_commit,
        40,
        "reference vendor commit",
    )?;
    hex(
        &policy.compatibility.reference_sha256,
        64,
        "reference vendor SHA256",
    )?;
    let reference = &policy.reference;
    for (name, value) in [
        ("reference policy SHA256", &reference.policy_sha256),
        ("reference quality SHA256", &reference.quality_sha256),
        (
            "applicability source check SHA256",
            &policy.target_applicability.source_check_sha256,
        ),
        (
            "applicability baseline SHA256",
            &policy.target_applicability.baseline_sha256,
        ),
    ] {
        hex(value, 64, name)?;
    }
    let expected: Vec<_> = super::TABLES.iter().map(|t| format!("{t}.json")).collect();
    if reference.schema != "gem-quality-source/v1"
        || reference.game_patch.trim().is_empty()
        || reference.policy_path.trim().is_empty()
        || reference.quality_path.trim().is_empty()
        || !reference.provenance.is_object()
        || reference.inputs.len() != expected.len()
        || expected
            .iter()
            .any(|name| !reference.inputs.contains_key(name))
    {
        return Err("invalid prior quality source reference".into());
    }
    for (name, digest) in &reference.inputs {
        hex(digest, 64, name)?;
    }
    if policy.target_applicability.kind
        != if policy.schema == "pobr-ordinary-quality-policy/v2" {
            "complete-quality-owners-except-dnt-only-gems"
        } else {
            "unchanged-owned-values-and-scopes"
        }
        || policy.target_applicability.baseline_sha256 != reference.quality_sha256
        || policy.target_applicability.statement.trim().is_empty()
    {
        return Err("invalid quality target applicability evidence".into());
    }
    Ok(Pinned {
        policy,
        bytes,
        sha256,
        parent: path.parent().ok_or("quality policy has no parent")?.into(),
    })
}

fn hex(value: &str, length: usize, field: &str) -> Result<(), String> {
    if value.len() != length
        || !value
            .bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
    {
        return Err(format!(
            "{field}: expected {length} lowercase hexadecimal characters"
        ));
    }
    Ok(())
}

impl Pinned {
    pub(in crate::ordinary_facts) fn tables(&self) -> &'static [&'static str] {
        if self.policy.schema == "pobr-ordinary-quality-policy/v2" {
            &super::publication::TABLES
        } else {
            &super::TABLES
        }
    }

    pub(super) fn validate_target(&self, input: &VerifiedFacts) -> Result<(), String> {
        if input.manifest["source_identity"]["game_patch"].as_str()
            != Some(self.policy.target.game_patch.as_str())
            || self.policy.target.facts_manifest_sha256 != sha256_hex(&input.manifest_bytes)
        {
            return Err("quality policy target patch / facts manifest mismatch".into());
        }
        Ok(())
    }
}
