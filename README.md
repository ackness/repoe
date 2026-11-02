# RePoE

Repository of Path of Exile resources for tool developers.

## PoBR-maintained fork

This fork is maintained as the game-fact exporter for PoBR. The upstream parser
remains the base; PoBR calculation rules and the independent Chinese translation
repository are maintained separately.

[`Independent data publication`](RePoE/docs/data_publication.md) packages pinned
exports and clearly identified historical compatibility bytes into standalone
RePoE Git artifacts. Language inputs stay in the translation repository; PoBR
imports temporary build inputs and retains its own policies and interpretation.

[`Client acquisition`](RePoE/docs/client-sources.md) is owned and implemented here:
[official PoE2 version observation](RePoE/docs/client-version.md), fixed-source
replay/cache import, [unreviewed drafts](RePoE/docs/client-source-draft.md),
[bounded index lookup and diagnostic inspection](RePoE/docs/client-index.md), and
[offline source rebinding/verification](RePoE/docs/source-rebinding.md).
Run `python -B -m RePoE.client_sources`, `RePoE.client_source_draft`,
`RePoE.client_index`, `RePoE.client_version` or `RePoE.source_rebinding` with `--help`
from this checkout. The matching mise tasks are `client:source`, `client:draft`,
`client:locate`, `client:version` and `source:rebind`; they use the selected Python
directly without environment setup. PoE2 parser default discovery uses the official
TCP endpoint; explicit `--file` bypasses discovery, and PoE1 behavior is unchanged.
The SDK uses the standard library and explicit package imports; native decoding
requires a separately selected, fingerprinted external environment. Historical
`pobr-*` wire names stay compatible. Acquisition and inspection do not approve a
source or adopt active data; language production remains in the translation library.

Development uses mise + uv. `mise.toml` requests the latest stable Python and uv;
the committed `mise.lock` selects exact versions. Refresh them explicitly with
`mise lock --bump --platform linux-x64,macos-arm64 python uv`. Standard project
metadata lives in `pyproject.toml`, and `uv.lock` fixes the resolved dependencies,
including a full PyPoE Git revision. Run from this checkout after `mise trust` and
`mise install --locked`:

```sh
mise bootstrap --only packages
mise run setup
mise run check
mise run schema:candidate -- --out .cache/schema/example
```

`setup` uses `uv sync --locked` to create `.venv`; its first run needs dependency
downloads. The frozen Pillow dependency may build from source on a new Python;
the bootstrap packages supply its required JPEG/zlib headers and Linux compiler.
Keep any receipt-bound decoder environment unchanged; validate an upgrade in a
separate directory with `UV_PROJECT_ENVIRONMENT=.cache/toolchain-python315 mise run setup`.
PyPoE is a noneditable Git dependency, not a sibling checkout. `check`
runs the offline lock check, fixed schema checksum, Ruff lint/format checks,
regression tests and CLI smoke test. Pull requests and master pushes run that
same check in a read-only GitHub Actions job after installing the locked tools,
declared host packages and frozen dependencies. CI does not acquire a client,
export production data, publish artifacts or change source acceptance. Passing
these offline checks does not certify a real client or activate a PoBR package. `mise run test` and `mise run lint` are also
available separately. Generated `RePoE/model/` files are excluded from regular
lint/format; update them explicitly with `mise run models:generate -- [schema paths]`,
which invokes the locked generator with Ruff formatting. The schema/model generator
and PyPoE retain their own transitive dependencies; our workflow does not invoke
Poetry, Flake8 or Black.

The local PoE2 schema input and provenance are in [`schema/`](schema/README.md).
`schema:candidate` creates a new, validated client-native candidate under `.cache/`,
without modifying installed PyPoE files or downloading game resources. To explicitly
try it against a selected client, use a separate output directory:

```sh
mise exec -- uv run --locked --offline repoe passives --poe2 \
  --file /path/to/client --outdir .cache/exports/example \
  --schema-candidate .cache/schema/example
```

Candidate generation and verification require this source checkout, its locked
environment and schema inputs; they are not a standalone wheel feature. Client
decoding and each exporter module still need patch-specific validation. Existing
modules may require further native field adaptation; generation success is not a
full export or publication approval. The default CLI path retains the upstream
specification for compatibility.

For a separate, offline eight-DAT + default-PSG facts candidate, use
`mise run facts:candidate -- --source-lock <lock> --source <key> --raw <root> --out <new-dir>`.
All inputs are explicit and raw bytes are verified in place. The versioned
[`repoe-native-facts/v1` contract](RePoE/docs/native_facts.md) preserves every
physical column plus passive/graph/class and quality relationships and diagnostics.
This partial 0.5.5.5 candidate is not a production snapshot or runtime PoBR pack;
it does not change the default exporter path or active data.

The explicit `--profile core-skills-a0` option adds seven skill metadata/cost/level
tables using the same producer and validator. Its
[`repoe-native-facts/v2` contract](RePoE/docs/native_core_skills.md) retains all
physical facts, ordered level context and acquisition status without inferring
gameplay units or application rules. It remains a partial, non-production package.

[`--profile gems-constraints-a1`](RePoE/docs/native_gems.md) expands the same native
ingress to 39 DATs plus PSG. Its v3 facts retain item-based gem identity, nested
effect order, raw requirements, support families and ordered constraint tokens.
It does not select a playable subset or evaluate support/level/quality policy.

The opt-in [`--profile items-actors-bc`](RePoE/docs/native_items_actors.md)
extends the same native ingress to 77 DATs plus PSG. It preserves eight-slot
modifiers, native item/component/socketable joins, constants and actor facts.
It remains partial, unfiltered source inventory; units, complete metadata and
playable catalogue/actor semantics are not certified.

[`Item inheritance`](RePoE/docs/native_item_inheritance.md) exports a separate
pinned `.it` closure with ordered raw fields and source spans. Its opt-in tag
interpretation is identified as pinned community parser behavior, separately
from official literal facts and direct DAT tags.

[`Actor templates`](RePoE/docs/native_actor_templates.md) preserve selected
`.ot`/`.otc` syntax, opaque event RHS and literal parent links. This separate
offline candidate does not merge fields, evaluate effects or project mod lists.

[`tables:candidate`](RePoE/docs/native_tables.md) exports an explicitly selected,
pinned set of additional DAT tables with the same native reader. It preserves
physical facts and unresolved foreign dependencies in a separately identified
package, without regenerating or relabeling an earlier fact profile.
An explicit `--language` exports localized DATs as `repoe-localized-tables/v1`,
with exact locale paths and no English fallback; translation selection remains
the translation repository's responsibility.

The [description-relation observation](RePoE/docs/description_relations.md)
preserves two exact table resources and one missing-resource diagnostic in an
independent draft artifact. Empty/generic rows do not enable PoE2 formatters.

[`Native crafting relationships`](RePoE/docs/native_crafting_facts.md) projects
exactly seven pinned, already exported F77 tables into a separate neutral facts
candidate. It preserves all physical EssenceMods relations, eight Mods stat slots,
raw/hardmode endpoints and full input rows. Currency selection, outcome policy and
runtime adoption remain consumer responsibilities; no new decoding is performed.

[`descriptions:candidate`](RePoE/docs/native_descriptions.md) exports a separate
selected CSD domain from explicitly pinned raw resources. It keeps every ordered
branch, language declaration, restriction, handler token, include and suppression
with UTF-16 byte spans. It does not use the legacy formatter, flatten overrides,
select a translation or execute handlers. Join this domain to native numerical
facts by game stat ID and exact game/patch/realm; international Simplified Chinese
text does not establish CN-realm numerical equivalence.

PoE2 `stat_translations` exports client descriptions by default, without querying
the trade API. Optional trade text associations require an explicitly supplied,
previously captured snapshot. It reads the existing
[poe2-zh-cn-stats schema-1 snapshot format](https://github.com/ackness/poe2-zh-cn-stats/blob/main/src/sources.mjs)
(`manifest.json` and `raw/trade-en.json.gz`), not translation worksheets. No sibling
checkout, collector, API access or translation dependency is needed at runtime:

```sh
# Pure client descriptions:
mise exec -- uv run --locked --offline repoe stat_translations --poe2 \
  --file /path/to/local/client --outdir .cache/exports/client-only

# Explicit English international text candidates; replace the digest with a
# manifest.json SHA-256 from a trusted source lock:
mise exec -- uv run --locked --offline repoe stat_translations --poe2 \
  --file /path/to/local/client --outdir .cache/exports/trade-candidates \
  --trade-snapshot /path/to/snapshot \
  --trade-snapshot-sha256 'REPLACE_WITH_TRUSTED_MANIFEST_SHA256' --trade-realm international
```

The expected manifest digest is optional; internal response checksums alone
establish consistency, not authenticity. Snapshot validation precedes client
loading, CDN discovery and output writes. Invalid or unsupported requested inputs
fail without falling back to client-only export. English international input is
the supported first slice; China, other languages and `--language all` with a
trade snapshot are rejected. Client-only language exports retain their existing
support. `stat_translations.provenance{,.min}.json` binds the consumed input bytes
and produced output bytes. Text matches are candidates, not proof of game stat
identity or calculation correctness. See the [description domain contract](RePoE/docs/stat_translations.md#poe2-offline-trade-candidates)
for validation, scope, provenance and replay commands.

`uv --offline` controls package resolution only. Select a local client with
`--file` to avoid client/CDN networking; other exporter modules may still have
their own network behavior. This change does not certify real-client decoding,
identify the client patch or refresh published/active data.

Passive export now reads every supplied stat slot, including zero and negative
values, and rejects duplicate stat IDs or missing values instead of truncating
or silently overwriting them. This is a general reader correction, not a table
of hardcoded node values. It does not repair missing graph membership or geometry.

PoE2 augment export retains each regular and bonded stat's raw `value` and the
category's stable `target_item_classes` IDs alongside the existing display fields.
It rejects unequal stat/value arrays and duplicate base/category identities.
See the [augment output contract](RePoE/docs/augments.md) for compatibility and
offline fixture coverage; real-client and gameplay validation remain separate.

The original RePoE documentation follows.

Forked from [brather1ng/RePoE](https://github.com/brather1ng/RePoE).

Contains data about stats, mods, base items, gems and more. See the `data`
folder for those files and the `docs` folder for their documentation.

For the actual GGPK parsing, [PyPoE](https://github.com/Project-Path-of-Exile-Wiki/PyPoE) is used,
with a specification generated from the [schema](https://github.com/poe-tool-dev/dat-schema)
provided by poe-tool-dev.

Developed to supply [PoESkillTree](https://github.com/PoESkillTree/PoESkillTree) with the
game data information it requires. If you need other files converted, feel free to
open an Issue or Pull Request for that. The source data files can be inspected with
[poe-dat-viewer](https://snosme.github.io/poe-dat-viewer/).

## Cross-repository contract

The shared target architecture and ownership rules live in
[PoBR data architecture](https://github.com/ackness/pobr/blob/master/docs/data-architecture.md).
This repository owns raw client decoding, faithful facts/relationships and provenance;
PoBR owns normalization, applicability policy, Rust semantics and player workflows.
The [translation repository](https://github.com/ackness/poe2-zh-cn-stats) owns language
pairing and curation, not numerical stat identity. Repair exporter omissions here,
then hand consumers the fixed producer revision, schema, artifact digest, patch/realm,
changed fields and actual validation limits. A merged exporter or verified byte replay
does not approve a source or activate a PoBR runtime package.

## Files

When running locally generated json data is exported to ./RePoE/data/. Each file has a
formatted and a compact version. The formatted versions complement their descriptions
in the [RePoE/docs](RePoE/docs) folder.

For hosted data exports see the
[gh-pages](https://repoe-fork.github.io/) index.

Note that the file formats are not final, they may change at any time, e.g. when the format
of files in the GGPK changes.

The following data is currently available:

- `stats.json`: Describes stat ids. Defines whether they are local and whether they
  are aliased depending on main-hand or off-hand.
- `mods.json`: Describes mod ids. Defines which items they can appear on and what
  stats with what values they have.
- `crafting_bench_options.json`: Describes master crafting options. Defines which
  masters can craft them at which level on which items.
- `npc_master.json`: Describes the master's signature mods and on which items they
  can appear.
- `gems.json`: Describes skill gems and skill gem effects only provided by mods.
- `gem_tags.json`: Simple object that contains all gem tags with their internal id as
  keys and their translation as value.
- `base_items.json`: Describes base item types. Contains information applicable to
  all item types, e.g. inventory size, item class and tags, as well as attribute
  requirements and properties.
- `tags.json`: Lists all possible item tags. These are the tags used in `base_items.json` and 
  `mods.json`.
- `item_classes.json`: Defines the item class ids and the tags added to items when they are
  Shaper/Elder items.
- `augments.json` (PoE2): Describes socketable augments with raw regular/bonded
  stat values, stable target item class IDs and display text; see
  [the output documentation](RePoE/docs/augments.md).
- `essences.json`: Describes essences. Defines the mods they spawn on items of the different
  item classes and general information like level and tier.
- `default_monster_stats.json`: Describes the stat base values of monsters at specific levels.
- `characters.json`: Describes the stat base values of the different player character classes.
- `flavour.json`: Table containing the flavour text used throughout the game.
- `fossils.json`: Describes fossils. Defines the mods they spawn, the tags they affect, and 
  auxiliary effects of the fossils.
- `mod_types.json`: Describes the types of mods with sell price information and the tags
  relevant for fossil crafting.
- `cluster_jewels.json`: Describes how cluster jewels can be generated and how they influence the passive tree. 
- `cluster_jewel_notables.json`: Lists the notable and keystone passive skills that can appear on cluster jewels.
- `cost_types.json`: Defines the resource cost types used in `gems.json`.
- `active_skill_types.json`: List the active skill types used in `gems.json`.
- `uniques.json`: Lists the names and art files of unique items - this is the only information
included in the data files.
- `mercenary_builds.json`: Describes mercenary builds with their skill pools, extra stats and weapon types. Infamous builds are their own entries, marked `is_infamous`.
- `mercenary_classes.json`: Describes mercenary classes with their house, attribute and monster varieties.
- `mercenary_skills.json`: Describes mercenary skills keyed by granted effect id, with their possible supports and per-level data.
- `mercenary_supports.json`: Describes mercenary supports with their tier, family, stats and stat text.
- `mercenary_flavour_text.json`: Lists mercenary flavour text with the tag weights that select it.

## Credits

- [Grinding Gear Games](http://www.grindinggear.com/) for [Path of Exile](https://www.pathofexile.com/).
  The contents of all `data` files obviously belong to them.
- [OmegaK2](https://github.com/OmegaK2/) for [PyPoE](https://github.com/OmegaK2/PyPoE).
- [Project PoE Wiki](poewiki.net) for updating PyPoE to handle the latest data format.
- [Path of Exile Tool Devs](https://github.com/poe-tool-dev/) for maintaining a standardised
  data schema.
