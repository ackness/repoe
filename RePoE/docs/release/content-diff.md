# Release content comparison

`release:build` compares the package against its declaration's reference and
prints an informational content summary. The bounded details live in
`receipt.json.content_diff` (`repoe-release-content-diff/v1`), outside the
runtime zip. The report changes no member bytes, manifests, contract, `--check`
result, coverage evidence or publication rules.

## Paths and byte classes

The build reads the authenticated reference root manifest's `target.game_patch`.
For comparison only, `data/<reference patch>/X` maps to `data/<target patch>/X`.
The receipt records `reference.reference_patch` and `reference.prefix_mapped`;
member details retain the original reference path. `data/overlay-common/`
keeps its path. Missing/unsafe reference identity, conflicting snapshot
`poe_version`, other patch prefixes and mapping collisions refuse clearly.

The existing generated/passthrough/frozen classes still describe raw bytes.
For example, `generated-different` can accompany an identity-only comparison,
and `generated-identical` can accompany a resolved retarget. Root manifest
retention, `members_identical`, zip identity and `--check` keep their original
byte comparisons.

## Three statuses

- `identity-only`: the comparison found only the exact identity leaves below
  or proved that changed row coordinates resolve to the same stable target.
- `content-changed`: at least one payload, preserved metadata, entity, ordering
  or stable reference target changed. Metadata changes alone do not establish
  a gameplay change: inspect separate `metadata_fields`, `payload_fields` and
  reference counts/samples.
- `unresolved`: interpretation or a changed reference/dependency cannot be
  resolved from the packages, and no content change has been proved.

A content-changed entry can also contain unresolved references. Unknown
interpretation never becomes an identity-only success. Strict JSON decoding
rejects duplicate object keys and invalid constants; a JSON interpretation
failure is reported as unresolved. Authentication of package bytes remains
the build's existing integrity check and still fails the build.

The snapshot manifest's explanation explicitly concerns patch/dependency
stamps only. It does not assert that the underlying members are unchanged:
consult those members' entries and their retained raw classes. A changed file
inventory, domains, contract or other snapshot field remains content.

## Identity rules

The single executable inventory is `IDENTITY_RULES` in
[`content_diff.py`](../../release/content_diff.py). Exclusions require that the
exact path exists on both sides with compatible types: nonempty identity
strings, lowercase SHA-256 strings, or nonnegative integer byte sizes.
Every container along that path must also match its producer's object/array
shape on both sides. Insertions, removals and type or shape changes remain
visible.

In this table, paths start at root `_meta` unless stated otherwise.
`source identity` means only the wrapper's `game_patch`, `source`,
`source_lock_sha256`, `selected_source_sha256`,
`acquisition.evidence[*].sha256`, and `raw_resources[*].{bytes,sha256}`.
It preserves game/realm/kind, acquisition status, evidence kinds, ordered
entries, unknown fields and resource inventory. `input pins` preserves table
keys and masks only their digest values or `{bytes,sha256}` leaves.

| Members (`.json`) | Excluded identity leaves |
| --- | --- |
| `base/monster_resistances`, `base/monster_scaling`, `overlay/totem_varieties` | `facts_manifest_sha256`, `poe_version`, `source_identity` identity leaves, input pins |
| `overlay/boss_poise_thresholds` | `facts_manifest_sha256` |
| `overlay/gem_descriptions` | `facts_manifest_sha256`, `game_patch` |
| `overlay/gem_effects` | `facts_manifest_sha256`, `game_patch`, `source_identity` identity leaves |
| `overlay/gem_quality_stats` | `source_manifest_sha256`, `poe_version`, `target_source` identity leaves, input pins |
| `overlay/granted_effect_minions`, `overlay/minions`, `overlay/spectres` | `target_fields.facts_manifest_sha256`, `target_fields.source_identity` identity leaves |
| `overlay/skill_overrides` | `target_numeric.facts_manifest_sha256`, `target_numeric.source_identity` identity leaves |
| `overlay/runes` | `facts_manifest_sha256`, `source_identity` identity leaves |
| `overlay/stat_descriptions` | `facts_manifest_sha256`, `lookup_manifest_sha256`, `descriptions_manifest_sha256`, `descriptions_sha256`, `source_identity` identity leaves |
| `overlay/trade_crafting_sources` | `source_manifest_sha256`, `input_manifest_sha256`, `declared_target.game_patch` |
| `base/passive_tree` (root node array) | `native_stats.data_version`; each native stat's `provenance.game_patch`, `source_manifest_sha256`, `references[*].sha256` |
| Snapshot `manifest.json` (root paths) | `poe_version`, existing `files[*]` digest values |

Policy, codec, compatibility and legacy-source pins remain compared, including
their metadata. So do schemas, generator/source formats, ownership,
applicability, projection recipes, statements and every unlisted field.
No recursive filtering by names such as `id`, `version`, `hash`, `_meta`
or `provenance` is performed. An identity-only result approves no policy.

## Entities and references

Arrays align through unique nonempty `id`/`Id` values or explicitly supported
keys: stat-set `effect_id`/`set_id`/`gem_level`, effect-level dictionaries and
`level`, gem-effect `gem_id`, and quality/minion-link `effect_id`.
Dictionary keys align directly. Relative order changes among surviving
entities remain visible; inserting an entity does not cascade through later
rows. The first stat set is the main branch, so a changed first set remains
content even if the same sets are present. Dictionary entity paths escape
`~` as `~0` and `/` as `~1` so distinct keys retain distinct counts.

Duplicate, missing or invalid keys fall back to complete ordered comparison,
with `entity_counts_available: false`. Unkeyed arrays retain order, types and
duplicates. A length change is a collection delta rather than a guessed
entity alignment. Do not interpret unavailable entity counts as a count of zero.

Supported physical references are checked even when the referring bytes are
identical or frozen. Each side uses its own package evidence:

- Main `granted_effects.stat_set` joins effect `id` to
  `granted_effect_stat_sets.effect_id` and the first `sets[0].set_id`.
  Row-to-ID and ID-to-row associations must both be unambiguous. The shortened
  published array is never indexed by the raw physical number.
- Ordered `cost_types` slots resolve through the package's ordered cost-type
  table. Mod-type rows use the producer-resolved `group` identity.
  Active-skill type coordinates retain their stable type IDs.
- Passive `passive_row`/`stat_row` and supported reference pointers use the
  packet's corroborating passive/stat identities. Resource and field suffixes
  remain significant.
- Changed stat semantic/category numbers have no published target table and
  remain unresolved.

A changed number is a proven `row_reference_shifts` event only if both
targets resolve uniquely to the same identity. Different stable targets are
`retargeted_references`, including an unchanged number whose dependency
changed. Missing/conflicting targets are `unresolved_references`; raw numeric
changes also increment `unresolved_raw_changes`. Uniform offsets prove nothing.
Unchanged unresolved numbers are reported when their dependency changed.
No unpublished facts cache fills a gap in package evidence.

## Counts, samples and receipt size

Counts cover the complete comparison. `samples`, entity details and displayed
strings are bounded, ordered deterministically, and record omissions. The
summary separates payload/metadata fields, entities, shifts, retargets,
unresolved references, alignment and interpretation failures.
Escaped lone surrogates in source strings remain visible as literal escapes
in report displays, without changing the source member or receipt encoder.

The existing consumer metadata cap is 4 MiB. The build measures the final
canonical UTF-8 receipt, including package and mapping metadata, then degrades
only the optional report: sample values, samples, then member details.
Full aggregate counts and field/entity/member omission counts survive the
summary fallback. Existing coverage, D40 issues, producer and provenance
evidence are never trimmed.

If even the compact summary does not fit, `content_diff` is omitted and the
build log prints all aggregate counts plus an explicit size diagnostic.
An already oversized original receipt is preserved and identified as such.
Size limits and unresolved content add no new build/publication gate.
