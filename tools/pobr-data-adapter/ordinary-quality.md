# Ordinary quality from target facts

`--ordinary-domain gem-quality` publishes ordered ordinary and additional quality
vectors and native stat-set scopes from authenticated physical facts. The producer
preserves signed permille/1000 rates, channel, order and multiplicity. Calculation,
Gemling gating and `trunc(rate * quality)` belong to PoBR.

```sh
mise run adapter -- \
  --ordinary-facts /absolute/path/to/F \
  --ordinary-domain gem-quality \
  --facts-manifest-sha256 56e71e00a72c8079d100b64861fc030206b12aaeb5ad655ccb4ab4e6726332d0 \
  --quality-policy tools/pobr-data-adapter/policies/gem-quality/0.5.5.5-publication-policy.json \
  --quality-policy-sha256 d800070b942d671c9b3deb7cf3b455b35b1712659b61a86cf7784ae528d4214f \
  --version 0.5.5.5 \
  --out /absolute/path/to/existing-parent/fresh-quality-candidate
```

Both policy arguments are required for this domain and rejected for others.
The policy hash is checked before strict JSON parsing. Duplicate keys, unknown
policy fields, malformed fingerprints, target patch/manifest mismatches and
incomplete or overlapping owner decisions fail before output reservation.

## Publication membership

The v2 policy publishes **every raw quality owner except verified DNT-only gem
owners**. It reads `GrantedEffects`, `Stats`, `GrantedEffectQualityStats`,
`BaseItemTypes`, `SkillGems` and `GemEffects` through the existing authenticated
reader. Every selected payload has an exact byte/hash pin; physical `_row` keys
supply references, never imported `_index`, display names or sorted IDs.

Both primary and additional gem-effect relationships are checked. An excluded
owner must have at least one relationship, and every related gem must have a
base name containing `[DNT`. A real/mixed relationship, missing base, OLD/UNUSED
name or no gem relationship cannot justify exclusion. Supports and unlinked
quality owners remain publishable. All consumed references, including unused
variants and excluded owners' stats, are validated before filtering.

The explicit enabled/excluded lists must partition all source owners, and each
decision must satisfy this fact-based rule. The current 429 rows partition into
424 published owners and five explicit DNT-only exclusions. This restores the
14 real gem-linked owners absent from the historical PoB templates. Historical
vendor membership is archival evidence, never the v2 membership criterion.

The receipt records the complete owner partition, physical gem relationships,
excluded raw fields, selected input hashes and policy bytes. Runtime metadata
keeps `compatibility.excluded_effects`, native scope arrays and a compact
publication summary. Existing serialized metadata is compatible with PoBR's typed
reader; no producer dependency upgrade is required.

## Preserved facts and limits

| Source | Handling |
| --- | --- |
| `GrantedEffect`, `Stats`, `AltStats` | Resolve stable IDs through verified physical references; duplicate owners and unresolved IDs fail |
| `StatsValuesPermille`, `AltStatValuesPermille` | Signed i32 / 1000.0; ordinary then additional, preserving zero, negative rates, order and duplicates |
| `ApplyToStatSets`, `AltApplyToStatSets` | Preserve arrays under the historical `_meta.unapplied_stat_set_scopes` spelling, including excluded rows; zero is valid, null/negative positions fail |
| `AddTypes`, `AddMinionTypes`, remaining columns | Retain source-column inventory and original pinned payloads; do not invent runtime semantics |

The producer does not interpret or repair native scope positions. Snipe's ordinary
`[1,2,3]` and additional `[0]` remain exact; native position 3 has no corresponding
set and must remain diagnosable by the consumer. Publication does not certify
calculation support, independent game rules, source acquisition or complete
runtime adoption. The domain output never writes a full runtime manifest or
`CURRENT` and never reads vendor Lua, language files or old numeric output.

## Historical replay

`0.5.5.5-facts-policy.json` remains byte-for-byte unchanged with schema v1 and
SHA-256 `334907c02b15e2303f9a6f550dfedaf80d889046048fe97d309ceba2182848da`.
It retains the historical 410/19 partition and reads only the original three
quality tables. Its quality overlay replays byte-identically. Historical policy
references and applicability evidence are validated with their original contract;
v2 uses `complete-quality-owners-except-dnt-only-gems` applicability.

The retained ordinary input archive contains the original F manifest and source
lock in `provenance/original-manifest.json` and
`provenance/original-source-lock.json`. Its `facts/tables/` members for the six
selected tables match those original pins. Reconstructing these selected inputs
permits exact historical-envelope replay; it does not equate the prepared archive's
`050fcf93…` manifest with the original `56e71e00…` manifest or certify unselected
payloads.

## Verification

```sh
CARGO_TARGET_DIR=/absolute/exclusive/target cargo test --locked \
  --manifest-path tools/pobr-data-adapter/Cargo.toml quality -- --test-threads=1
```

Tests cover primary/additional/mixed/unlinked relationships, strict DNT exclusions,
malformed references before filtering, missing/extra policy owners, legacy behavior,
and the 429 real source vectors, channel ordering and scopes. Fixture provenance
is documented in `tests/fixtures/ordinary-facts/README.md`. Real publication replay
also compares the complete generated overlay against the source and old immutable
package, preserving all unrelated game and language bytes.
