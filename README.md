# RePoE

Repository of Path of Exile resources for tool developers.

## PoBR-maintained fork

This fork is maintained as the game-fact exporter for PoBR. The upstream parser
remains the base; PoBR calculation rules and the independent Chinese translation
repository are maintained separately.

Development uses mise + uv. `mise.toml` selects Python and uv; standard project
metadata lives in `pyproject.toml`, and `uv.lock` fixes the resolved dependencies,
including a full PyPoE Git revision. Run from this checkout after `mise trust` and
`mise install`:

```sh
mise run setup
mise run check
mise run schema:candidate -- --out .cache/schema/example
```

`setup` uses `uv sync --locked` to create `.venv`; its first run needs dependency
downloads. PyPoE is a noneditable Git dependency, not a sibling checkout. `check`
runs the offline lock check, fixed schema checksum, Ruff lint/format checks,
regression tests and CLI smoke test. `mise run test` and `mise run lint` are also
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
