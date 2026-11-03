# RePoE

Game data for Path of Exile tool developers. This fork maintains the PoE2 client exporters and game-data packages used by [PoBR](https://github.com/ackness/pobr), while retaining the upstream PoE1 and PoE2 parsers.

RePoE reads client resources, preserves their identities and relationships, and turns selected facts into versioned JSON packages. Each package records its source bytes, producer and validation scope.

## Start here

| You want to… | Read |
| --- | --- |
| Consume a published game-data package | [Publication index](publication/index.json) and [consumer contract](RePoE/docs/publication_index.md) |
| Set up the exporters or run a local export | [Development](#development) and [exporting data](#exporting-data) below |
| Convert facts into PoBR runtime JSON | [Rust data adapter](tools/pobr-data-adapter/README.md) |
| Inspect client resources and their provenance | [Client acquisition](RePoE/docs/client-sources.md) and [resource lookup](RePoE/docs/client-index.md) |
| Find a domain's schema or validation limits | [Data contracts](#data-contracts) below |

## Role in the PoBR ecosystem

| Repository | Responsibility |
| --- | --- |
| **RePoE** | Client acquisition and decoding, raw facts and relationships, source evidence, and conversion into published game-data packages |
| [poe2-zh-cn-stats](https://github.com/ackness/poe2-zh-cn-stats) | Language pairing, translation conflicts, reviewed supplements and runtime language files |
| [PoBR](https://github.com/ackness/pobr) | Calculation rules, build import, player-facing workflows, and adoption of fixed data releases |

Fix missing client facts here, language pairing in the translation repository, and calculation behavior in PoBR. The shared [data architecture](https://github.com/ackness/pobr/blob/master/docs/data-architecture.md) defines ownership; [data status](https://github.com/ackness/pobr/blob/master/docs/data-status.md) tracks current gaps.

## What is available

| Layer | Contents | Consumer |
| --- | --- | --- |
| Client inputs | Explicit client resources, schema pins, acquisition receipts and resource digests | Exporters and source verification |
| Native facts | DAT rows, passive graphs, gem and item identities, actor relationships, metadata and ordered CSD description branches | Domain adapters and the translation repository |
| Game packages | PoBR runtime JSON, separately identified compatibility inputs and source receipts | PoBR's fixed-input pipeline |
| Legacy exports | Stats, mods, base items, gems, classes, crafting and other upstream JSON formats | Existing PoE tooling |

Packages have different scopes. A successful facts export does not establish complete gameplay semantics. Localized text does not establish numerical equivalence between international and China realms. Some runtime fields still retain explicitly pinned PoB2 or community interpretations; the domain contracts record these limits.

## Consume a publication

1. Read [`publication/index.json`](publication/index.json) at a fixed source commit.
2. Fetch its descriptor using the declared full commit, path, byte length and SHA-256.
3. Fetch the required component artifacts at their own fixed commits and verify their declared files and digests.

The index covers six roles: `game`, `crafting`, `ordinary`, `display_source`, `source_verifier` and `test_fixtures`. Individual roles may use different producer revisions. The source branch is a discovery entry point; its HEAD is not a data-package version.

PoBR records adopted publications in `pipeline/data.lock.json`. Consumers of published JSON do not need Python, Rust, a client installation or a sibling checkout of this repository. Large artifacts live at `handoff/*` tags and may be absent from the default branch's working tree.

See [publication ordering and validation](RePoE/docs/publication_index.md) and [packaging and artifact retention](RePoE/docs/data_publication.md). Index registration records completed deliveries; it does not collect a fresh client, produce data, upload artifacts or adopt them in PoBR.

For later publication sequences, the registration API checks each changed artifact against local Git objects and its `handoff/*` tag on origin. It can draft the next descriptor while retaining unchanged roles; see the publication contract for those commands.

## Development

Install [mise](https://mise.jdx.dev/) and run these commands from the repository root:

```sh
mise trust
mise install --locked
mise bootstrap --only packages
mise run setup
mise run check
```

`mise.lock` pins Python and uv; `uv.lock` pins Python dependencies, including PyPoE's full Git revision. `setup` creates `.venv` with `uv sync --locked`. First-time setup needs network access; Linux compiler/JPEG/zlib packages support the pinned Pillow release when a wheel is unavailable.

`check` validates the dependency lock and schema checksum, runs Ruff and the offline regression suite, and checks the CLI. It does not download a client or publish data. Use `mise run test` or `mise run lint` for a narrower check.

The Rust adapter is a separate Cargo workspace with its own lock and root `rust-toolchain.toml`:

```sh
mise run adapter -- --help
mise run adapter:check
mise run adapter:keystones
```

The last command checks the published game package against its declared remote tag. CI runs both the Python checks and adapter checks. Generated `RePoE/model/` files are maintained explicitly with `mise run models:generate -- [schema paths]`.

## Exporting data

For a legacy exporter, select a local client and a separate output directory:

```sh
mise exec -- uv run --locked --offline repoe --help
mise exec -- uv run --locked --offline repoe stat_translations --poe2 \
  --file /path/to/client --outdir .cache/exports/client-descriptions
```

PoE2 `stat_translations` reads client descriptions by default. Optional offline trade-text associations require an explicitly supplied snapshot; see the [description contract](RePoE/docs/stat_translations.md#poe2-offline-trade-candidates). `uv --offline` only controls dependency resolution: `--file` selects local client data, and other exporter modules may have their own network behavior.

Native exporters use explicit source locks and verified raw resources. For example:

```sh
mise run facts:candidate -- --source-lock /path/to/source-lock.json \
  --source SOURCE_KEY --raw /path/to/raw-resources --out .cache/facts/example
```

The default native profile covers eight DAT tables and PSG. Opt-in `core-skills-a0`, `gems-constraints-a1` and `items-actors-bc` profiles expand the exported facts; their contracts specify the inputs, schema and limits. For other domains, use the matching [contract](#data-contracts) rather than treating a partial profile as a complete game snapshot.

Client decoding uses a separately selected, fingerprinted environment. Keep receipt-bound environments unchanged; test toolchain upgrades in a separate environment. [`schema/`](schema/README.md) documents the fixed schema and candidate workflow.

## Repository layout

```text
RePoE/parser/                 Upstream PoE1 and PoE2 exporters
RePoE/native_*.py             Native facts, descriptions and metadata exporters
RePoE/client_*.py             Client discovery, acquisition and resource lookup
RePoE/source_rebinding.py     Offline source verification
RePoE/docs/                   Domain formats and producer contracts
schema/                       Pinned decoding schema and provenance
tools/pobr-data-adapter/      Rust runtime-data adapter and domain policies
publication/index.json        Current owner-publication discovery entry point
publication/releases/         Ordered publication descriptors
tests/                        Offline Python regressions
.cache/                       Local candidates and intermediate exports
RePoE/data/                   Default legacy export directory; ignored by Git
```

## Data contracts

| Topic | Documentation |
| --- | --- |
| Client acquisition and patch observation | [Sources](RePoE/docs/client-sources.md), [version](RePoE/docs/client-version.md), [drafts](RePoE/docs/client-source-draft.md), [lookup](RePoE/docs/client-index.md), [verification](RePoE/docs/source-rebinding.md) |
| Native skills and gems | [Base facts](RePoE/docs/native_facts.md), [core skills](RePoE/docs/native_core_skills.md), [gem constraints](RePoE/docs/native_gems.md) |
| Items and actors | [Item/actor facts](RePoE/docs/native_items_actors.md), [item inheritance](RePoE/docs/native_item_inheritance.md), [actor templates](RePoE/docs/native_actor_templates.md), [player context](RePoE/docs/native_player_context.md) |
| Descriptions and languages | [CSD branches](RePoE/docs/native_descriptions.md), [supplemental/localized tables](RePoE/docs/native_tables.md), [description relationships](RePoE/docs/description_relations.md) |
| Crafting and trees | [Crafting facts](RePoE/docs/native_crafting_facts.md), [PoBR crafting catalog](RePoE/docs/pobr_crafting_catalog.md), [historical official trees](RePoE/docs/official_tree_input.md) |
| PoBR runtime conversion | [Adapter modes](tools/pobr-data-adapter/README.md) and [domain policies](tools/pobr-data-adapter/policies/README.md) |
| Legacy JSON formats | [Stats](RePoE/docs/stats.md), [mods](RePoE/docs/mods.md), [items](RePoE/docs/base_items.md), [gems](RePoE/docs/gems.md), [augments](RePoE/docs/augments.md), and [other domain files](RePoE/docs) |

## Upstream and credits

The repository starts at the retained upstream fork snapshot. See [history and clone size](RePoE/docs/history.md) for the one-time history cut, commit mapping and existing-checkout migration.

This fork derives from [repoe-fork/RePoE](https://github.com/repoe-fork/RePoE) and [brather1ng/RePoE](https://github.com/brather1ng/RePoE), originally developed for PoESkillTree. Client parsing uses [PyPoE](https://github.com/Project-Path-of-Exile-Wiki/PyPoE) and the [poe-tool-dev DAT schema](https://github.com/poe-tool-dev/dat-schema).

Code licensing is recorded in [LICENSE.md](LICENSE.md); schema attribution is in [schema/](schema/README.md). Path of Exile game data belongs to Grinding Gear Games. Published source and generated data retain their respective upstream rights.
