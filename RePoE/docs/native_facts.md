# Native facts candidate v1

`repoe-native-facts/v1` is an **opt-in, partial facts candidate**, never a
production snapshot or runtime-ready PoBR pack. The existing `repoe` exporters
and CLI defaults are unchanged. This source-checkout tool uses the locked native
schema converter and pinned PyPoE; it does not use legacy specifications,
adaptation, virtual stat views, relational readers, downloads or APIs.

## Offline invocation

All four arguments are mandatory. Paths below are caller-supplied examples, not
runtime defaults or dependencies on another checkout:

```sh
mise run facts:candidate -- \
  --source-lock /path/to/sources.lock.json \
  --source official-client-0.5.5.5 \
  --raw /path/to/candidate-0.5.5.5/raw \
  --out .cache/native-facts/replay-a
# Equivalent entry point:
mise exec -- uv run --locked --offline python -B -m RePoE.native_facts \
  --source-lock /path/to/sources.lock.json \
  --source official-client-0.5.5.5 \
  --raw /path/to/candidate-0.5.5.5/raw \
  --out .cache/native-facts/replay-b
```

The selected schema-1 source-lock entry must have kind
`official-client-resource-candidate`, game `poe2`, realm `international`, and
patch `0.5.5.5`. It must contain **exactly** these nine `resources` keys:

- `Data/Balance/Characters.datc64`
- `Data/Balance/ClassPassiveSkillOverrides.datc64`
- `Data/Balance/GrantedEffectQualityStats.datc64`
- `Data/Balance/GrantedEffectStatSets.datc64`
- `Data/Balance/GrantedEffects.datc64`
- `Data/Balance/PassiveSkillTrees.datc64`
- `Data/Balance/PassiveSkills.datc64`
- `Data/Balance/Stats.datc64`
- `Metadata/PassiveSkillGraph.psg`

Each resource requires `bytes` (positive integer) and `sha256` (64 lowercase hex
digits). Other lock acquisition metadata is not interpreted. `decoder.revision`
must be PyPoE `66d1d7442c5718260e1a8efd24989d22987e91af`;
`decoder.dat_schema_revision` must be `6034b071846ef61b39046ebdb59e6d5717179509`;
`decoder.schema_sha256` must be
`50e098543345cf8323aeb294e2cfef1b6b44842faccf560ada935cebe22727df`.
The installed noneditable dependency and prepared local schema must match these
pins. No supplied Python specification is accepted or executed.

The tool reads each game-relative path directly under `--raw`, rejects paths
resolving outside that root, and verifies size and SHA-256 **before decoding or
output**. It keeps those verified bytes in memory; it never creates another raw
copy. Missing inputs, bad checksums/pins, row width mismatches, decoder warnings,
unresolved acquired relationships, invalid graph joins, unsupported/truncated PSG
framing, unequal stat/value arrays and JSON nonfinite numbers reject generation.
The independent PSG framing check accounts for every byte and compares every
field exposed by `PSGFile`. Warnings are rejection reasons, never claimed as a
successful decode. Native execution disables dependency bytecode writes.

An existing output (including an empty directory or dangling symlink) is refused.
Input/validation errors leave no output. After validation, a new directory is
reserved with `mkdir`, payload files are linked from adjacent staging and the
manifest is linked **last**. An I/O interruption can leave an incomplete directory;
without the manifest it is not a valid candidate. Retry with a new output path.

## Receipt and identities

The output has 12 payload files plus `manifest.json`:

| File | Content |
| --- | --- |
| `tables/<Table>.json` (eight files) | Every physical row and generated physical field, including unknown fields |
| `graph.json` | Default tree identity, complete PSG framing and original geometry/topology fields |
| `passives.json` | Every passive definition, separate default graph instances, all class override facts |
| `skills.json` | Every effect's ordered stat-set identities and every main/alternate quality channel |
| `diagnostics.json` | Scope limits, unavailable/unknown relationship occurrences and source discrepancies |

Every JSON file is UTF-8 with Unicode preserved, object keys sorted, compact
separators, one terminal newline and no nonfinite numbers. Source order is
preserved in arrays. No invocation time or absolute machine path is inserted.
The manifest records:

- `format`, `status: "partial-candidate"`, `production_ready: false`, scope and summary;
- `source_identity`: exact source-lock byte hash, selected-source hash, selected
  key/game/realm/patch, and all nine raw game-relative paths/hashes/sizes;
- `decoder`: Git revision, Python version and installed PyPoE Python module hashes;
- `schema`: frozen input hash/revision, generated native specification hash and
  zero compatibility views;
- `producer`: hashes of the producer, trusted schema tool, project/lock and schema receipts;
- `files`: every payload's exact byte count and SHA-256; the manifest does not hash itself.

`selected_source_sha256` hashes the selected entry using the JSON encoding above,
including its terminal newline. A caller should pin the **manifest bytes' SHA-256**
externally, verify it before parsing, then require the format/status/source
identities and exact expected file inventory. Verify every listed path's size/hash
before consuming it. Reject traversal, extra/unexpected manifest paths or missing
files; do not discover inputs by glob. Internal hashes establish consistency, not
source authenticity: the caller must trust/pin the source lock and receipt. These
are candidate source bytes, not a publication approval or raw redistribution grant.

## Physical tables

A table document contains `table`, `raw_resource`, `row_key`, `physical_fields`,
`columns`, `validation` and `rows`. Each row is:

```json
{"_row":1367,"values":{"Id":"energy_shield_and_armour44","PassiveSkillGraphId":31955,"Stat5Value":10,"Stats":[134,15701,2525,14187,2966]}}
```

This actual row excerpt omits other physical fields for readability.
`_row` and every projection's `row` are **zero-based ephemeral source row indices**,
valid only for these exact raw bytes. They are never stable game IDs. `values`
contains exactly all `physical_fields`; foreign row indices, zero, signed values,
empty strings/arrays and PyPoE-decoded nulls are preserved. PyPoE maps its binary
null sentinels to JSON `null`; the original physical bytes remain identified by
the raw receipt. No foreign index is replaced by its display text.

`columns` is ordered by original schema column. Each entry has `source_column`
(zero-based ordinal), the complete original `schema` column metadata and its
`physical_fields` mapping. Unnamed columns retain `schema.name: null` and the
converter's generated name. Native intervals retain both generated endpoints:
`Stat8Value` with `interval: true` maps to `Stat8Min` and `Stat8Max`, preserving
both values rather than manufacturing a virtual `Stats` view. The eight actual
source tables contain no interval columns; this capacity is tested synthetically.
`validation` records row count, schema/actual physical row bytes and empty warnings.

## Passive and graph projections

`passives.json.definitions` preserves **all 9,731** definitions in source order.
Each has `definition: {row,id}`, raw `graph_id`, `in_default_graph`, and ordered
`stats` entries such as this actual fifth slot:

```json
{"slot":5,"value_field":"Stat5Value","stat":{"row":2966,"id":"recover_X_life_on_block"},"value":10}
```

This is source row **1367**, graph ID **31955**; the stat row is ephemeral
and must not be used as an external stable key. All seven physical value fields,
even unused slots, remain in the table file. Attribute, unlock, visibility, frame,
variant and unknown metadata remain in the same source row; unresolved targets
are diagnosed, not synthesized. Source placeholder definitions outside this graph
remain present and are not defaulted or filtered.

`default_graph_instances` contains **5,152** entries with `definition: {row,id}`,
`graph_id`, zero-based `group`, raw `radius`, `position`, directed `connections`
and parallel signed `splines`. Every root/edge resolves, and every instance joins
exactly one definition. There are **5,957** stat entries on these definitions,
including 14 after slot four. `graph.json` records `tree: {row,id}`, `raw_resource`,
header `[3,0]`, raw `skills_per_orbit`, roots `{graph_id,unknown}`, groups and exact
`parsed_bytes`. Groups retain `x`, `y`, `flag`, `unknown1`, signed `unknown2` and
ordered nodes; 29 groups have nonzero `unknown1` in this source. The parser's
`radius` is a raw orbit index; no physical radii or global coordinates are supplied.

`class_overrides` retains all **61** rows, character/base/replacement `{row,id}`,
both raw graph IDs and both membership flags. All 61 replacements have no default
graph instance. The generic `override_base_absent_from_default_graph` diagnostic
identifies actual rows **51** (`55194 -> 57601`) and **53** (`19680 -> 40837`),
both Druid. Definitions remain present. This neither deletes nodes, instantiates
replacements nor establishes historical deletion or an old-patch equivalence.

## Effects, qualities and closure

`skills.json.effects` contains `{effect: {row,id}, ordered_stat_sets: [...]}`.
Entries preserve primary `StatSet` followed by `AdditionalStatSets` source order,
with `source_field`, zero-based `source_slot` (null for primary),
`local_index_hypothesis` and `stat_set: {row,id}`. Null primary references have no
set identity. Null additional references remain in the physical table and generate
a diagnostic rather than an invented set. No labels are resolved from numbers.

Each `qualities` entry retains `row`, `effect`, ordered stat sets, and separate
`main` / `alternate` objects containing `scope_raw` plus ordered `stats` entries
`{slot,stat:{row,id},value_permille}`. Quality stat slots are zero-based array
positions; passive slots are one-based named value slots. No `/1000` conversion,
English generation, scope application or empty-scope policy is performed.
`AddTypes` and `AddMinionTypes` remain unchanged in the physical row.

Actual quality row **69**, effect `SnipePlayer`, preserves main scope `[1,2,3]`,
alternate `[0]`, primary value `200`, alternate values `[1000,1000]`, and exactly
three ordered sets: rows `[127,128,129]`, IDs `SnipePlayer`,
`SnipeExplosionPlayer`, `SnipeFrozenExplosionPlayer`. Diagnostic
`quality_scope_out_of_range_under_local_index_hypothesis` retains value `3`, the
whole raw scope and the ordered identities. It does not clamp, apply globally,
create a fourth set or certify the local-index hypothesis as game policy.
Tempest Bell row 3 retains scopes `[2]` / `[0]`, values `150` / `500` and ordered
set rows `[395,396,397]`. Essence Drain row 42 retains `[1]` / `[0,1]`.

All nonnull references into the acquired eight tables are checked. References to
unavailable targets are preserved in the raw table and enumerated by table/field,
source row, array slot (null for scalar) and raw value in diagnostics. Unknown
foreign targets are also enumerated. Enum metadata remains unresolved. This
includes 927 nonnull stat-set label references, including row-zero references.
Four other tree definitions are retained with `unavailable_tree_graph`; their PSG
resources are outside this bounded input. ActiveSkills, per-level data, labels,
ascendancies/variants/frame metadata, other graphs, CSD/text, renderer radius
semantics and full relationship closure remain unproven. Consumers must retain
these diagnostics and must not label this partial candidate production-ready.

## Validation boundary

`mise run check` includes synthetic binary DAT/PSG fixtures, interval endpoints,
all slots/metadata, absent-base membership, raw scopes, unavailable row-zero
labels, forged/corrupt/missing inputs, exact framing/warnings, new-output
protection and byte-identical independent-process replay. Synthetic fixtures are
not real-client certification. A real-source replay must additionally compare
all emitted physical rows/columns and selected projections against the acquired
source evidence, and pin the resulting manifest bytes for downstream consumption.
No large game bytes are committed by this feature.
