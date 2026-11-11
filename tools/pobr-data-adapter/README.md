# pobr-data-adapter

Converts pinned RePoE facts into the runtime JSON that PoBR loads (`base/`,
`overlay/` and `generated/` files of a game package), using the domain policies
in [`policies/`](policies). The tool and the policies moved here from PoBR
(`tools/pobr-data-adapter`, `pipeline/policies`), so PoBR now only consumes the
published packages through its `pipeline/data.lock.json`.

It is a standalone Cargo workspace inside this Python repository. PoBR's data
types come from the immutable contract tag `contract/1.1` of `ackness/pobr`
(`contract/<n>.<m>`, where n is `pobr_data::CONTRACT_VERSION`); `Cargo.lock`
pins the resolved commit `ac3c5c92`. Production code depends on `pobr-data`
only. The engine crates `pobr-core`, `pobr-gamedata`, `pobr-item` and
`pobr-tree` are dev-dependencies for the tests that check how PoBR consumes the
output, and they must name the same tag: two tags compile two copies of
`pobr-data` whose types do not match. When PoBR publishes a new contract tag,
bump all five entries in `Cargo.toml` together and adapt the tests to engine API
changes; never move an existing tag. `mise run adapter:check` fails if a PoBR
crate other than `pobr-data` reaches the normal dependency tree, or if the
locked PoBR crates resolve to more than one commit.

A pin bump changes the release receipt, not the published bytes; the
snapshot manifest records the `contract_version` the adapter was compiled
against (`--contract-version`).

## Configuration ownership

| Configuration | Owner |
|---|---|
| JSON domain policies in `policies/` | RePoE; original policies moved byte-for-byte, later corrections are reviewed here |
| `Cargo.toml`, `Cargo.lock`, Rust toolchain, adapter tasks and CI | RePoE; the PoBR engine-crate tag is an explicit dependency |
| Runtime data types, Rust calculation rules and the eleven owned shared rule/config files | PoBR |
| Language pairing, reviewed supplements and display projections | The translation repository |
| Consumer artifact pins, expected runtime/release identities and local adoption | PoBR's `pipeline/data.lock.json` and consumer tooling |

The raw-material source ledger lives in this repository as
[`sources/sources.lock.json`](../../sources/README.md), copied on 2026-11-03
from PoBR's `pipeline/imports/sources.lock.json` with its entries, hashes and
provenance unchanged. It is not an adapter policy or an adapter input.

The separate special-currency catalog projector, including currency prefixes and
selection/aggregation policy, now runs in RePoE as the `crafting-catalog` job of
`mise run release:build` (see [RePoE/docs/release/pobr_crafting_catalog.md](../../RePoE/docs/release/pobr_crafting_catalog.md));
the game part carries the projected catalog.

The bounded [historical attribute selector projection](../../RePoE/docs/release/pobr_historical_trees.md)
also runs in RePoE, as the `historical-trees` job of `mise run release:build`. It
repairs the four byte-pinned retained `base/passive_trees/0_1..0_4.json` trees
using a reviewed identity policy, without reviving the retired Lua extractor or
reading a consumer snapshot/vendor.

## Commands

Run from the repository root. Rust is pinned once in `rust-toolchain.toml`;
mise reads it locally, and CI installs it with rustup.

```sh
mise run adapter -- --ordinary-facts <F> --facts-manifest-sha256 <HEX> --version <patch> --out <fresh-directory> ...
mise run adapter:check       # fmt, clippy -D warnings, cargo test, pobr-data-only normal deps
mise run adapter:keystones   # rebuild the published package's special_derived.json and compare bytes
```

The modes are `--ordinary-facts` (current domains), `--tree` (historical
official tree package) and `--emit-special-derived` (keystone rules from a
prepared `passive_tree.json`). Each mode documents its arguments and guards:

- ordinary domains: [ordinary-facts.md](docs/ordinary-facts.md) and the
  `ordinary-*.md` file for each domain;
- passive tree: [ordinary-passive-tree.md](docs/ordinary-passive-tree.md).

The output guards refuse to write under this repository's tracked `release/`
or the selected input directories. Some domain documents retain the earlier
PoBR term "production `data/`" for that protected location. `CURRENT` is
PoBR's runtime pointer; the adapter never reads or writes it. The domain
documents' PoBR source links point at the `engine-crates/20261102` tag.

The ordinary domains read their input through `src/facts/`: the verifier of the
pinned RePoE facts envelope (`repoe-native-facts/v4`) and its source lock, the
selected-table and supplement readers, the player context archive verifier and
the guarded output directory.

Each domain candidate's receipt names its output by a schema ID from the one
registry in `src/schema_id.rs` (`adapter.output_schema`, for example
`runes/v1` or `passive_tree/v1`), in the contract crate's `<name>/v1` style and
never as a `pobr_data` Rust type path. Where a member declares its own
`_meta.schema`, the converter writes it from the same constant, so the two
agree (spellings are kept as published, e.g. `monster-resistances/v1`).
Policies name selected input files by the same IDs (`game_constants/v1`,
`passive_tree/v1`, …); the type-path spellings older policies used were
rewritten for game 0.5.5.5-2 and are no longer accepted.

The schema-4 (native runtime) modes `--native-facts` and `--native-runtime` were
removed on 2026-11-04, after PoBR deleted its schema-4 loader; Git history keeps
them.

`adapter:keystones` checks the `reference` package of the highest
`release/<patch>[-<n>]/inputs.lock.json` (the published game package). A
Release asset `{repository, tag, asset, bytes, sha256}` is downloaded
anonymously and verified; a Git blob `{revision, path, bytes, sha256}` must
have a `handoff/<name>` tag on `origin` that peels to its commit. A pull
request that moves `reference` to a new release therefore runs the check on
the new package. To check a candidate before publishing it, pass `--pin
<file>` with either shape.

## Assembling a package

Each domain run produces one domain candidate. `mise run release:build` runs every
declared domain against pinned inputs and assembles the complete game part; see
[RELEASING.md](../../RELEASING.md).

The PoB2-derived parser and special-rule bytes in the published game package
are frozen. New parser capability goes into PoBR's Rust rules, not here.
