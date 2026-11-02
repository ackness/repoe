# pobr-data-adapter

Converts pinned RePoE facts into the runtime JSON that PoBR loads (`base/`,
`overlay/` and `generated/` files of a game package), using the domain policies
in [`policies/`](policies). The tool and the policies moved here from PoBR
(`tools/pobr-data-adapter`, `pipeline/policies`), so PoBR now only consumes the
published packages through its `pipeline/data.lock.json`.

It is a standalone Cargo workspace inside this Python repository. PoBR's data
types come from the immutable, non-release tag `engine-crates/20261102` of
`ackness/pobr` (`pobr-data`, `pobr-core`, `pobr-gamedata`; `pobr-item` and
`pobr-tree` for tests). `Cargo.lock` pins the resolved commit `174ca6fb`. When
PoBR changes a runtime type, create a new tag there and bump all five entries in
`Cargo.toml` together; never move an existing tag.

## Commands

Run from the repository root. Rust is pinned once in `rust-toolchain.toml`;
mise reads it locally, and CI installs it with rustup.

```sh
mise run adapter -- --ordinary-facts <F> --facts-manifest-sha256 <HEX> --version <patch> --out <fresh-directory> ...
mise run adapter:check       # fmt, clippy -D warnings, cargo test, Python smoke tests
mise run adapter:keystones   # rebuild the published package's special_derived.json and compare bytes
```

The modes are `--ordinary-facts` (current domains), `--tree` (historical
official tree package), `--emit-special-derived` (keystone rules from a
prepared `passive_tree.json`), and the frozen schema-4 branch `--native-facts` /
`--native-runtime`. Each mode documents its arguments and guards:

- ordinary domains: [ordinary-facts.md](ordinary-facts.md) and the
  `ordinary-*.md` file for each domain;
- passive tree: [ordinary-passive-tree.md](ordinary-passive-tree.md);
- schema 4: [native-facts.md](native-facts.md), [native-runtime.md](native-runtime.md).

`adapter:keystones` reads the game package named in
[`tests/keystone-package.json`](tests/keystone-package.json) by commit, path,
bytes and SHA-256. A new game package must pass it before it is published; then
update the pin to that package.

## Reading the moved documents

The mode documents were written in PoBR and keep their wording. In this
repository:

- "production `data/`" is the tracked `publication/` directory. The output
  guards refuse to write under it, as they refused PoBR's `data/`.
- `CURRENT` is PoBR's runtime pointer. This tool never reads or writes it.
- Links to PoBR source point at the `engine-crates/20261102` tag.

Two scope decisions from the move apply to every mode:

- The PoB2-derived parser and special-rule bytes in the published game package
  are frozen. New parser capability goes into PoBR's Rust rules, not here.
- The native schema-4 branch is frozen. Its producers moved here for
  reproducibility, and PoBR's full-build calculation still rejects schema 4.

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
