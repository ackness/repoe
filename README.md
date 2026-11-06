# RePoE

**English** | [简体中文](README.zh-CN.md)

Game data for Path of Exile tool developers. This fork maintains the PoE2 client exporters and game-data packages used by [PoBR](https://github.com/ackness/pobr), while retaining the upstream PoE1 and PoE2 parsers.

RePoE reads client resources, preserves their identities and relationships, and turns selected facts into versioned JSON packages. Each package records its source bytes, producer and validation scope.

## Start here

| You want to… | Read |
| --- | --- |
| Consume a published game-data package | [GitHub Releases](https://github.com/ackness/repoe/releases) tagged `game/<patch>-<n>` ([what a Release contains](RELEASING.md#publish)) |
| Set up the exporters or run a local export | [Development](#development) and [exporting data](#exporting-data) below |
| Convert facts into PoBR runtime JSON | [Rust data adapter](tools/pobr-data-adapter/README.md) |
| Build and publish a new PoBR game package | [RELEASING.md](RELEASING.md) (`release:build` → `release:publish` → PoBR `data:bump`) |
| Inspect client resources and their provenance | [Client acquisition](RePoE/docs/client/client-sources.md) and [resource lookup](RePoE/docs/client/client-index.md) |
| Find a domain's schema or validation limits | [Data contracts](#data-contracts) below and the [documentation index](RePoE/docs/README.md) |
| Change code or data here | [AGENTS.md](AGENTS.md) (rules, layout, validation) and [CONTRIBUTING.md](CONTRIBUTING.md) |

## Role in the PoBR ecosystem

RePoE owns client facts and the game package; [poe2-zh-cn-stats](https://github.com/ackness/poe2-zh-cn-stats) owns language data; [PoBR](https://github.com/ackness/pobr) owns calculation and pins both packages. The responsibilities and boundaries are defined once, in PoBR's [data architecture](https://github.com/ackness/pobr/blob/master/docs/data-architecture.md); [data status](https://github.com/ackness/pobr/blob/master/docs/data-status.md) tracks current gaps.

## What is available

| Layer | Contents | Consumer |
| --- | --- | --- |
| Client inputs | Explicit client resources, schema pins, acquisition receipts and resource digests | Exporters and source verification |
| Native facts | DAT rows, passive graphs, gem and item identities, actor relationships, metadata and ordered CSD description branches | Domain adapters and the translation repository |
| Game packages | PoBR runtime JSON, separately identified compatibility inputs and source receipts | PoBR's fixed-input pipeline |
| Legacy exports | Stats, mods, base items, gems, classes, crafting and other upstream JSON formats | Existing PoE tooling |

Packages have different scopes. A successful facts export does not establish complete gameplay semantics. Localized text does not establish numerical equivalence between international and China realms. Some runtime fields still retain explicitly pinned PoB2 or community interpretations; the domain contracts record these limits.

## Consume a published package

Each game package is a GitHub Release `game/<patch>-<n>` with three assets: `pobr-game-<patch>.zip`, its `receipt.json` (producer commit, contract, every input pin and the provenance class of every member) and `SHA256SUMS`. PoBR pins one Release, with the matching language Release, in `pipeline/data.lock.json` (`mise run data:bump`, see PoBR's [RELEASING.md](https://github.com/ackness/pobr/blob/master/RELEASING.md)). Consumers need no Python, Rust, client installation or checkout of this repository.

Packages published before Releases (and the older inputs `release:build` reads) live on orphan commits kept reachable by `handoff/*` tags. Those tags are never moved or deleted ([why](AGENTS.md#never-move-or-rewrite)): `release/<patch>[-<n>]/inputs.lock.json` addresses them by commit, path and SHA-256. New inputs are GitHub Releases `inputs/<patch>-<n>` (`mise run release:inputs`), addressed like game packages by repository, tag, asset and SHA-256.

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

`adapter:keystones` rebuilds the keystone rules of the `reference` package of the highest `release/<patch>[-<n>]/` declaration from its passive tree and compares bytes. Generated `RePoE/model/` files are maintained explicitly with `mise run models:generate -- [schema paths]`.

CI runs `verify.yml` on every pull request and `release-build.yml` when the release build's inputs change; what each runs is described in [AGENTS.md](AGENTS.md#ci).

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
RePoE/parser/                 Upstream PoE1 and PoE2 exporters (the repoe CLI is RePoE/run_parser.py)
RePoE/poe/                    Upstream PyPoE file-format extensions
RePoE/schema/, RePoE/model/   Upstream legacy JSON schemas and their generated models
RePoE/client/                 Patch observation, acquisition, drafts, resource lookup, source envelopes
RePoE/native/                 Native facts, tables, descriptions, inheritance, crafting and player exporters
RePoE/release/                Game-package build, publish and input packaging, and the release jobs
RePoE/trade_snapshot.py       Offline trade-text snapshot reader for stat_translations
RePoE/docs/                   Formats and contracts, grouped like the code (index: RePoE/docs/README.md)
release/                      One pinned declaration per game package (release/<patch>[-<n>]/)
schema/                       Pinned dat-schema and provenance
sources/                      Raw-material source ledger and retained source metadata
tools/pobr-data-adapter/      Rust adapter, its policies/ and per-domain docs/
tests/                        Offline Python regressions: client/, native/, release/, parser/
scripts/                      Maintenance scripts (PyPoE pin reproduction)
.github/workflows/            verify.yml and release-build.yml
.cache/                       Local candidates, exports and release builds; ignored by Git
RePoE/data/                   Default legacy export directory; ignored by Git
```

Which paths are upstream, where new code goes and which files must keep their bytes: [AGENTS.md](AGENTS.md#layout).

## Data contracts

| Topic | Documentation |
| --- | --- |
| Client acquisition and patch observation | [Sources](RePoE/docs/client/client-sources.md), [version](RePoE/docs/client/client-version.md), [drafts](RePoE/docs/client/client-source-draft.md), [lookup](RePoE/docs/client/client-index.md), [verification](RePoE/docs/client/source-rebinding.md), [capture](RePoE/docs/client/client-capture.md) |
| Native skills and gems | [Base facts](RePoE/docs/native/native_facts.md), [core skills](RePoE/docs/native/native_core_skills.md), [gem constraints](RePoE/docs/native/native_gems.md) |
| Items and actors | [Item/actor facts](RePoE/docs/native/native_items_actors.md), [item inheritance](RePoE/docs/native/native_item_inheritance.md), [actor templates](RePoE/docs/native/native_actor_templates.md), [player context](RePoE/docs/native/native_player_context.md) |
| Descriptions and languages | [CSD branches](RePoE/docs/native/native_descriptions.md), [supplemental/localized tables](RePoE/docs/native/native_tables.md), [description relationships](RePoE/docs/native/description_relations.md), [English gem descriptions](RePoE/docs/release/pobr_gem_descriptions.md) |
| Crafting and trees | [Crafting facts](RePoE/docs/native/native_crafting_facts.md), [PoBR crafting catalog](RePoE/docs/release/pobr_crafting_catalog.md), [historical tree selectors](RePoE/docs/release/pobr_historical_trees.md) |
| PoBR runtime conversion | [Adapter modes](tools/pobr-data-adapter/README.md) and [domain policies](tools/pobr-data-adapter/policies/README.md) |
| PoBR runtime domains | [Ordinary-facts domains](tools/pobr-data-adapter/docs/ordinary-facts.md), one `docs/ordinary-<domain>.md` each |
| Legacy JSON formats | [Stats](RePoE/docs/stats.md), [mods](RePoE/docs/mods.md), [items](RePoE/docs/base_items.md), [gems](RePoE/docs/gems.md), [augments](RePoE/docs/augments.md), and [other domain files](RePoE/docs/README.md#legacy-json-formats-repoeparser) |

Apart from [README.zh-CN.md](README.zh-CN.md) and the [gem-quality policy notes](tools/pobr-data-adapter/policies/gem-quality/README.md), the documentation is in English.

## Upstream and credits

The repository starts at the retained upstream fork snapshot. See [history and clone size](RePoE/docs/history.md) for the one-time history cut, commit mapping and existing-checkout migration.

This fork derives from [repoe-fork/RePoE](https://github.com/repoe-fork/RePoE) and [brather1ng/RePoE](https://github.com/brather1ng/RePoE), originally developed for PoESkillTree. Client parsing uses [PyPoE](https://github.com/Project-Path-of-Exile-Wiki/PyPoE) and the [poe-tool-dev DAT schema](https://github.com/poe-tool-dev/dat-schema).

Code licensing is recorded in [LICENSE.md](LICENSE.md); schema attribution is in [schema/](schema/README.md). Path of Exile game data belongs to Grinding Gear Games. Published source and generated data retain their respective upstream rights.
