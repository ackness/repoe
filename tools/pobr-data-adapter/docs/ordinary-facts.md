# Ordinary domains from pinned facts

`--ordinary-facts` converts a fixed RePoE physical fact package into the existing
`StatDef`, `ModDef`, `ModStat` and `SpawnWeight` JSON shapes by default. Add
`--ordinary-domain stats-mods` to select that same domain explicitly.

Each call produces one domain for later assembly into an ordinary runtime
package. It does not produce a complete GameData/BuildData package or a restricted
runtime profile.

| Domain selection | Conversion and scope | Details |
| --- | --- | --- |
| `--ordinary-domain stats-mods` | Existing `StatDef`, `ModDef`, `ModStat` and `SpawnWeight` JSON shapes; the default domain | Sections below |
| `--ordinary-domain base-items` | Existing item DTOs | [Base items](ordinary-base-items.md) |
| `--ordinary-domain skills` | Six ordinary skill files | [Skills](ordinary-skills.md) |
| `--ordinary-domain gem-quality` | Gem quality with an explicitly pinned target policy | [Gem quality](ordinary-quality.md) |
| `--ordinary-domain stat-set-codec` | Verbatim legacy export-index sidecar | [Stat-set codec](ordinary-stat-set-codec.md) |
| `--ordinary-domain gem-effects` | Target gem links with explicit legacy display and owner compatibility | [Gem effects](ordinary-gem-effects.md) |
| `--ordinary-domain monster-resistances` | Normal-rarity base resistances through the original monster join | [Monster resistances](ordinary-monster-resistances.md) |
| `--ordinary-domain totem-varieties` | Target skin-zero totem object overlay; unresolved selectors remain disclosed | [Totem varieties](ordinary-totem-varieties.md) |
| `--ordinary-domain monster-scaling` | Original nine per-level monster arrays | [Monster scaling](ordinary-monster-scaling.md) |
| `--ordinary-domain skill-stat-map` | Pinned interpretation map with separately verified branch-codec identity | [Skill-stat map](ordinary-skill-stat-map.md) |
| `--ordinary-domain skill-overrides` | Target primary multipliers with explicit fixed prepared compatibility | [Skill overrides](ordinary-skill-overrides.md) |
| `--ordinary-domain minions` and `--ordinary-domain spectres` | Shared actor-field producer with fixed curated membership | [Actors](ordinary-actors.md) |
| `--ordinary-domain granted-effect-minions` | Curated actor links with the target support-gating boolean | [Minion links](ordinary-minion-links.md) |
| `--ordinary-domain passive-tree` | Target graph, names and complete supported stat text from explicit tree reference/CSD inputs, with field-scoped compatibility | [Passive tree](ordinary-passive-tree.md) |
| `--ordinary-domain runtime-constants` | Foundation constant files and optional existing ailment DTO, with explicit selected legacy inputs | [Runtime constants](ordinary-runtime-constants.md) |
| `--ordinary-domain socketables` | Target rune/augment membership, restrictions and complete supported effect text, with exact whole-entry compatibility and selected translation-library consumption | [Socketables](ordinary-socketables.md) |
| `--ordinary-domain stat-descriptions` | Unscaled global singleton templates from pinned RePoE descriptions, with explicit field-scoped compatibility | [Stat descriptions](ordinary-stat-descriptions.md) |
| `--ordinary-domain catalysts` | Existing quality catalog/codec with a pinned supplemental physical table package | [Catalysts](ordinary-catalysts.md) |
| `--ordinary-domain unarmed-data` | Target Characters with the existing verified player metadata archive | [Unarmed data](ordinary-unarmed.md) |
| `--ordinary-domain uniques` | Structured unique->base->mods/roll/variant relation from the pinned retained unique catalog, with target base verification | [Uniques](ordinary-uniques.md) |

```sh
mise run adapter -- \
  --ordinary-facts /absolute/path/to/F \
  --facts-manifest-sha256 56e71e00a72c8079d100b64861fc030206b12aaeb5ad655ccb4ab4e6726332d0 \
  --version 0.5.5.5 \
  --out /absolute/path/to/existing-parent/fresh-candidate
```

The output parent must exist; the leaf must not exist, even as an empty directory
or dangling symlink. Linux/macOS directory handles enforce the shared `facts`
output guard's input and tracked `release/` protections. Use a path outside those
protected directories, such as `.cache/ordinary-stats-mods`. Arguments are required,
cannot repeat, and cannot be combined with another adapter mode (`--tree`,
`--emit-special-derived`).

An invalid, missing-value or repeated `--ordinary-domain` is an error. Omitting
it preserves the Stats/Mods JSON, marker and receipt content except for the
compiled implementation revision. All domains share the verification/output
boundary, with their own table subsets. The remaining sections describe Stats/Mods.

`--mode strict|forward` (default `strict`) selects whether a per-entity content
gap fails the run or is recorded in the receipt's `conversion.coverage`; see
[strict and forward mode](ordinary-coverage.md).

Additional inputs depend on the selected domain:

| Options | Domain requirements |
| --- | --- |
| Quality-only options | Require gem-quality |
| Codec options | Optional for base-items field ownership. Required for stat-set-codec, gem-effects, skill-stat-map, skill-overrides, minions, spectres, granted-effect-minions, passive-tree, runtime-constants, socketables, stat-descriptions, unarmed-data or uniques |
| Paired `--player-context` and `--player-manifest-sha256` | Required only by unarmed-data |
| `--item-descriptions` | Required by socketables and stat-descriptions; rejected by other domains |
| Paired `--supplement` and `--catalog-policy` paths/SHA256 pins | Required by catalysts. Tree refresh v2 also accepts the paired supplement with its explicit policy; other domains reject it |
| The two branch-codec options | Required by skill-stat-map and skill-overrides; rejected by every other domain |

## Input and checks

The first supported source is the existing `repoe-native-facts/v4` envelope
(`items-actors-bc` acquisition), international patch `0.5.5.5`. That is an input
format identity, not a new output profile. The existing verifier still checks
the externally supplied manifest SHA **before parsing**, producer/schema/decoder
pins, embedded `source-lock.json`, selected lock entry and acquisition evidence.
`--version` must equal the declared `source_identity.game_patch`; it cannot
relabel another patch. The selected manifest binds the lock, so another lock
argument or an implicit search for a different package is unnecessary.

Only these payloads are read, retained as authenticated bytes, and parsed:

- `source-lock.json`
- `tables/Stats.json`
- `tables/Mods.json`
- `tables/ModType.json`
- `tables/ModFamily.json`
- `tables/Tags.json`

Other files remain manifest inventory; their bytes and relationships are not
certified by this conversion. No projected `items.json`, skill/tree/actor
payloads, legacy package, vendor extraction, download or CURRENT lookup is used.

Physical documents use the existing table reader's `columns`, `physical_fields`,
validation and `rows[{_row,values}]` checks. `_row` must match its zero-based
physical position in these exact bytes. Duplicate JSON keys, duplicate physical
rows, empty/duplicate stable IDs, missing fields, changed column types or foreign
key destinations, unresolved required references and malformed ranges fail
before output is reserved. Groups also require nonempty, unique `ModType.Name`.
The ordinary converter declares its own consumed columns, without requiring
unrelated native projection fields.

## Mapping to the existing DTOs

| Output | Source and handling |
| --- | --- |
| `StatDef.id` | `Stats.Id`, never `_row` |
| `is_local` | Required `IsLocal` boolean; null is an error |
| `semantic`, `category` | `Semantic`, `Category`: optional raw unsigned metadata, including zero; no classification lookup or semantic inference |
| `ModDef.id`, `name` | `Mods.Id`, `Name`; empty/null name becomes absent |
| `mod_type`, `group` | Optional raw `ModType` row number retained for schema compatibility; that physical row's `ModType.Name` becomes `group` |
| `domain`, `generation_type`, `level` | `Domain`, optional `GenerationType`, `Level`; checked unsigned conversions, no clamp or invented zero |
| `stats` | All `Stat1` through `Stat8` join **Stats.Id**; signed `StatNMin` and `StatNMax` become the range in source slot order |
| `families` | `Families` joins **ModFamily.Id**, independent of `group`; null stays unknown, empty stays explicitly empty |
| `tags` | `Tags` joins `Tags.Id`, preserving source order |
| `spawn_weights` | Equal-length `SpawnWeight_Tags`/`SpawnWeight_Values` join `Tags.Id`; order and zero weights are preserved |

All DTO fields are covered. Negative stat values and ranges crossing zero are
valid; inverted ranges, null endpoints on any slot, unsigned-field negatives or
overflow fail. A null stat reference denotes no stat, even when unused endpoints
are nonzero. Such endpoints are retained in `conversion.unassigned_stat_ranges`
in the receipt, with the source mod ID, physical row and slot; they are not
applied to Stats row zero. The legacy shell rule (no name and no bound stats) is
applied only after field/reference validation, and every omitted mod is listed
in `conversion.filtered_shells`.

The eight-slot physical contract is explicit. An unhandled `StatN…` field,
including a ninth slot, fails instead of silently truncating it. Known hardmode
ranges, implicit tags, generation weights and other fields outside the ordinary
DTO remain in the pinned source payload; this mode does not add their semantics.
The receipt and source manifest retain the exact source/payload identities for
following those facts. `source_row` references `tables/Mods.json#/rows/N/values`.

## Output and adoption boundary

```text
fresh-candidate/
  _domain_candidate.json
  base/stats.json
  base/mods.json
  source-manifest.json
  source-lock.json
  producer-receipt.json
```

The ordinary JSON files are sorted by stable ID. The receipt records actual
source/selected payload fingerprints, target, output sizes/hashes, field mapping,
omissions and the adapter's compiled source-content revision (`sha256:…`). It
copies acquisition status/evidence without upgrading it. A checkout's later Git
HEAD is not substituted for the implementation that produced the bytes.

The existing `_domain_candidate.json` marker is written first; no runtime
`manifest.json` is emitted. Existing package sealing/publication refuses this
marker. `producer-receipt.json` is written last; an interrupted directory is
incomplete and is never reused. `complete_runtime: false` and `adoption:
"not-adopted"` separate conversion from complete-package integration and actual
use. Target-compatible remaining domains/assets are still needed for a complete
ordinary runtime package.

## Shared reader for subsequent producers

Within this tool, reuse:

```rust,ignore
use crate::facts::reader::{self, Tables};

let facts = reader::open(input, expected_manifest_sha256, version, selected_tables)?;
let tables = Tables::selected(&facts, selected_tables)?;
let values = tables.row("Stats", physical_row)?;
```

`reader::open` returns `VerifiedFacts`, containing the verified manifest/lock,
selected immutable bytes and parsed documents. `Tables::selected` accepts
`&[&'static str]`; `row(table, physical_row)` returns that row's `values`, and
`len(table)` is for already selected table names. Column/schema metadata remains
available in `facts.documents["tables/Table.json"]`. Consumers declare their
field contracts and perform domain joins after this shared verification; they
must not reinterpret `_row` as a stable ID or reopen unverified payload bytes.
It is the adapter's one physical reader (`src/facts/`), not another parser in
the engine. Full-tree `native_stats` and later item/skill producers should reuse
it, adding the appropriate selected tables and ordinary domain conversions.

## Focused validation

The synthetic fixture reuses the existing v4 trust envelope and only provides
the selected files. Assertions deserialize output into the **original DTOs**,
check eight slots, signed/zero/null values, family/group separation, sorted IDs
versus physical references, receipt hashes, determinism, source failures and
output protection.

The original implementation handoff and its unrun status are retained below.

<details>
<summary>Historical implementation handoff: coordinator commands (unrun)</summary>

Coordinator commands (not run by the implementation worker):

```sh
mise exec -- cargo test --locked --manifest-path tools/pobr-data-adapter/Cargo.toml ordinary_facts::tests
mise exec -- cargo test --locked --manifest-path tools/pobr-data-adapter/Cargo.toml facts::
```

</details>
