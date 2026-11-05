# pobr-data-adapter

Converts pinned RePoE facts into the runtime JSON that PoBR loads (`base/`,
`overlay/` and `generated/` files of a game package), using the domain policies
in [`policies/`](policies). The tool and the policies moved here from PoBR
(`tools/pobr-data-adapter`, `pipeline/policies`), so PoBR now only consumes the
published packages through its `pipeline/data.lock.json`.

It is a standalone Cargo workspace inside this Python repository. PoBR's data
types come from the immutable contract tag `contract/1.0` of `ackness/pobr`
(`contract/<n>.<m>`, where n is `pobr_data::CONTRACT_VERSION`); `Cargo.lock`
pins the resolved commit `95d71c6f`. Production code depends on `pobr-data`
only. The engine crates `pobr-core`, `pobr-gamedata`, `pobr-item` and
`pobr-tree` are dev-dependencies for the tests that check how PoBR consumes the
output, and they must name the same tag: two tags compile two copies of
`pobr-data` whose types do not match. When PoBR publishes a new contract tag,
bump all five entries in `Cargo.toml` together and adapt the tests to engine API
changes; never move an existing tag. `mise run adapter:check` fails if a PoBR
crate other than `pobr-data` reaches the normal dependency tree, or if the
locked PoBR crates resolve to more than one commit.

Changing the pin does not change the published bytes by itself: `contract/1.0`
(from `engine-crates/20261102`, `174ca6fb`) reproduced the published game part
exactly. The sealed manifest does not record a contract version yet; adding
one changes package bytes, so it waits for the next published release.

## Configuration ownership

| Configuration | Owner |
|---|---|
| JSON domain policies in `policies/` | RePoE; original policies moved byte-for-byte, later corrections are reviewed here |
| `Cargo.toml`, `Cargo.lock`, Rust toolchain, adapter tasks and CI | RePoE; the PoBR engine-crate tag is an explicit dependency |
| Runtime data types, Rust calculation rules and the eleven owned shared rule/config files | PoBR |
| Language pairing, reviewed supplements and display projections | The translation repository |
| Consumer artifact pins, expected runtime/release identities and local adoption | PoBR's `pipeline/data.lock.json` and consumer tooling |

PoBR's historical `pipeline/imports/sources.lock.json` still combines raw-source
and acquisition evidence with downstream retained-input acceptance decisions.
It is not an adapter policy or a runtime input of PoBR's import pipeline.
Rehoming that ledger must separate producer evidence from consumer acceptance
while retaining original hashes and provenance; it is separate from the completed
policy move.

The separate special-currency catalog projector, including currency prefixes and
selection/aggregation policy, now runs in RePoE as the `crafting-catalog` job of
`mise run release:build` (see [RePoE/docs/pobr_crafting_catalog.md](../../RePoE/docs/pobr_crafting_catalog.md));
the game part carries the projected catalog.

The bounded [historical attribute selector projection](../../RePoE/docs/pobr_historical_trees.md)
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

- ordinary domains: [ordinary-facts.md](ordinary-facts.md) and the
  `ordinary-*.md` file for each domain;
- passive tree: [ordinary-passive-tree.md](ordinary-passive-tree.md).

The ordinary domains read their input through `src/facts/`: the verifier of the
pinned RePoE facts envelope (`repoe-native-facts/v4`) and its source lock, the
selected-table and supplement readers, the player context archive verifier and
the guarded output directory.

Each domain candidate's receipt names its output by a stable schema ID
(`adapter.output_schema`, for example `pobr-runes/v1` or
`pobr-passive-tree/v1`; see `src/schema_id.rs`), not by a `pobr_data` Rust
type path. Policies pinned before the IDs existed still spell selected-file
schemas as type paths; the adapter accepts those as legacy aliases.

The schema-4 (native runtime) modes `--native-facts` and `--native-runtime` were
removed on 2026-11-04, after PoBR deleted its schema-4 loader; Git history keeps
them.

`adapter:keystones` checks the `reference` package of the highest
`release/<patch>/inputs.lock.json` (the published game package), by commit,
path, bytes and SHA-256, and requires its `handoff/<name>` tag on `origin` to
peel to that commit. A pull request that moves `reference` to a new release
therefore runs the check on the new package. To check a candidate before
publishing it, pass
`--pin <file>` with `{revision, path, bytes, sha256[, tag]}`.

## Assembling a package

Each domain run produces one domain candidate. `mise run release:build` runs every
declared domain against pinned inputs and assembles the complete game part; see
[RELEASING.md](../../RELEASING.md).

## Reading the moved documents

The mode documents were written in PoBR and keep their wording. In this
repository:

- "production `data/`" is the tracked `release/` directory (formerly
  `publication/`, retired with the publication index). The output guards
  refuse to write under it, as they refused PoBR's `data/`.
- `CURRENT` is PoBR's runtime pointer. This tool never reads or writes it.
- Links to PoBR source point at the `engine-crates/20261102` tag, the pin
  when they were moved; `contract/1.0` replaced it.

One scope decision from the move applies to every mode: the PoB2-derived
parser and special-rule bytes in the published game package are frozen. New
parser capability goes into PoBR's Rust rules, not here.

## Move verification (2026-11-02)

- `mise run adapter:check`: 380 Rust tests (the same count as in PoBR), fmt and
  clippy clean, 9 Python smoke tests.
- The ordinary replay used PoBR's last orchestrator (`7cb90dce:pipeline/runtime/ordinary`)
  with this build of the binary. It produced the six declared domains
  (stat-descriptions, passive-tree, base-items, minions, spectres,
  skill-overrides), and their 8 output files are byte-identical to PoBR's
  prepared `handoff/native-crafting-20261101` data.
- `mise run adapter:keystones`: `special_derived.json` (11909 B, `d18157d9…`) is
  byte-identical to the one in that package.
- The implementation fingerprints in receipts changed by design. They no longer
  hash PoBR crate sources, which a git dependency cannot `include_bytes!`. They
  hash this crate's sources and `Cargo.lock`, and the lock fixes the PoBR commit.
