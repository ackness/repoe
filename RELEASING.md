# Releasing the PoBR game package

`mise run release:build` rebuilds the complete game part that PoBR pins
(`game-build-part.zip`) from pinned inputs, and tells you, member by member,
which bytes the code in this repository derived, which a producer only carried
over from one of its inputs, and which are still copied from a frozen input.

```sh
mise run release:build                    # build the adapter, then the package of the highest patch
mise run release:build -- --config release/0.5.5.5  # a specific patch declaration
mise run release:build -- --fetch         # fetch missing pinned commits from origin first
mise run release:build -- --check         # exit 1 unless the zip equals the reference package
mise run release:build -- --manifest fresh  # always write a new root manifest.json
```

Without `--config`, the build uses the highest game patch directory under
`release/` (directories are named by patch and compared numerically, so
`0.10.0` is above `0.9.1`; a directory named otherwise is an error). There is
no separate "current" pointer to keep in sync: adding `release/<new patch>/`
makes it the default.

Output (under `.cache/release/<game>-<realm>-<patch>/`, replaced on each run):

| File | Content |
| --- | --- |
| `game-build-part.zip` | The package, written with the publication tools' zip convention |
| `receipt.json` | How it was built: producer commit, code and adapter pins, every input package and file pin, every job's evidence and the class of every member |
| `package.json` | What was built: the `receipt.json`, root manifest and zip pins, and whether the zip equals the reference package |
| `manifest.json`, `SHA256SUMS` | Copies of the root manifest and the zip/receipt/package hashes |
| `work/` | Adapter outputs, materialized policies, per-job logs and the portable adapter receipts the receipt pins |

Paths in `receipt.json` are relative to the repository (sources, declarations)
or to the output directory (portable adapter receipts), so the same checkout
gives the same receipt in any location and cache directory. The adapter
writes the absolute path of its facts input into its own
`work/jobs/<job>/producer-receipt.json`; the receipt pins a copy under
`work/receipts/` with that path replaced by `facts:<identity>`. The one pin
that still depends on the machine is `producer.adapter_binary` (a compiled
binary); a declaration outside the repository is recorded by absolute path.

Pinned inputs are extracted once into `.cache/release/inputs/`, keyed by
SHA-256, and re-verified on every run. Nothing is read from a checkout's data
directories, a vendor tree or the game CDN; `--fetch` only runs
`git fetch --depth=1 origin <commit>` for a pinned commit, and
`git fetch origin refs/tags/<tag>` for a package's publication tag, that is
missing locally. Without `--fetch`, Git runs with `GIT_NO_LAZY_FETCH=1`, so a
partial clone cannot fetch missing objects behind the build's back.

A package's `tag` must name its locked `revision`; a tag that names another
commit fails the build. The receipt records each tag as `verified` or, when
the tag is not present locally and `--fetch` was not given,
`not-present-locally`. The producer is `dirty` (with `dirty_paths`) on any
tracked change and on any untracked file under `RePoE/`, `release/`,
`tools/pobr-data-adapter/` or the toolchain pins.

## Declarations

Everything the build reads is declared in `release/<patch>/`:

- `inputs.lock.json`: the input packages (handoff tag, commit, path, bytes,
  SHA-256, embedded manifest pin), the facts envelope inside the ordinary
  package with its two facts identities, and the `reference` package the
  result is compared against (the currently published game package).
- `domains.json`: the producer jobs, in order. `adapter` jobs run one
  `pobr-data-adapter --ordinary-facts` domain; file options name a package
  member (`ordinary:…`, `legacy:…`), a policy under
  `tools/pobr-data-adapter/policies` (`policy:…`) or an earlier job's output
  (`job:<id>:…`), and their `--…-sha256` partner is computed from those
  bytes. A policy object (`{"policy", "bindings", "rebind", "expect"}`)
  expands a retained template and/or rebinds the facts-manifest pointer to
  the job's facts identity; `expect` pins the result. The other job kinds are
  `special-derived`, `historical-trees`, `crafting-catalog` and the final
  `snapshot-manifest`, which re-pins `data/<patch>/manifest.json` over the
  assembled members and keeps the template's other fields and locale
  (`i18n/`) pins. A job whose output carries input content over declares
  `"passthrough": "<why>"` (see member classes).
- `frozen-inputs.json`: every member that is not generated yet, with its
  SHA-256, category (one of its declared `categories`), origin, why it is
  frozen and what would let it go; none of these may be empty. Its
  bytes are copied from the `source` package. The number of entries is the
  progress measure; shrink it, never grow it silently.

Two facts identities exist because the portable envelope rebinds the source
lock (F3). `rebound` (`050fcf93…`) is the envelope's facts root; `original`
(`56e71e00…`) is the same payload bytes with the original manifest and lock
the envelope proves. Each domain uses the identity its published output and
policy were bound to.

## Member classes

Every member has a provenance, and every produced member is also compared
with the reference package:

| Provenance | Meaning |
| --- | --- |
| `generated` | A job derived the bytes from its inputs |
| `passthrough` | A job emitted one of its own inputs: verbatim, with only `_meta` re-stamped, or (the snapshot manifest) a template with only the member pins regenerated |
| `frozen` | Copied from `frozen-inputs.json` |

| Class | Meaning |
| --- | --- |
| `generated-identical`, `passthrough-identical` | Bytes equal the reference package |
| `generated-different`, `passthrough-different` | Bytes differ (the receipt keeps both pins) |
| `generated-new`, `passthrough-new` | The reference package has no such member |
| `frozen` | Copied from `frozen-inputs.json` |

Pass-through is detected, not only declared: an output whose bytes, or whose
JSON payload apart from `_meta`, equal one of the job's own inputs fails the
build unless the job declares `passthrough`, and a declaration with no such
output fails too. The job's receipt evidence names, per member, the input
carried over and how (`verbatim`, `payload-except-_meta`, or `template` with
the carried fields and the number of retained and regenerated pins). A
pass-through job still verifies its input against the target facts, but the
content is the input's, so it is not counted as generated.

The root `manifest.json` is retained from the reference package
(`retained-reference-manifest`) only when every other member is identical, so
an unchanged rebuild reproduces the published zip byte for byte. Otherwise a
fresh `pobr-build-data-part/v1` manifest is written (`fresh-manifest`); it
pins `receipt.json` (`release_build.receipt`), which is complete before the
zip exists, while `package.json` pins the zip. The
published manifest also carries the history of the patches applied to earlier
packages; a fresh build cannot regenerate that history, only the file pins.

## Status for 0.5.5.5 (reference: sequence 7, `3edc9b1e…`)

Of 62 data members, 32 are generated, 4 are pass-through and 26 are frozen;
all 36 produced members are byte-identical to the reference package and the
zip SHA-256 equals the published one. The pass-through members are
`overlay/stat_set_labels.json` and `overlay/skill_stat_map.json` (the
0.5.5.4.2 codec sources, verbatim), `overlay/granted_effect_minions.json`
(the 0.5.5.4.2 payload, `_meta` re-stamped) and `data/0.5.5.5/manifest.json`
(the reference snapshot's `schema_version`, `languages`, `domains` and 13
`i18n/` pins, with 54 member pins regenerated). The frozen categories
are `unpinned-input` (an adapter domain exists, but a selected-table
supplement or the player context archive is pinned only by hash), `pob2-derived`,
`migrated-constants` and `shared-overlay`. See `frozen-inputs.json`.

## A new game patch

1. Acquire and export the new client facts and supplements as usual
   (`client:source`, `facts:candidate`, `tables:candidate`,
   `descriptions:candidate`) and publish them as handoff packages.
2. Copy `release/<old patch>/` to `release/<new patch>/`. Point
   `inputs.lock.json` at the new packages and set `reference` to the last
   published game package. Update policy pins and member paths in
   `domains.json`; carry `frozen-inputs.json` over and replace frozen
   members with jobs where possible.
3. Run `mise run release:build` (the new directory is now the default; the
   old one stays buildable with `--config release/<old patch>`). Review every
   `*-different` member:
   it should be explained by the new facts, not by a changed policy you did
   not intend.
4. Publish `game-build-part.zip` with `receipt.json`, `package.json` and `SHA256SUMS` from a
   tagged commit; PoBR then pins that tag and hash.

CI (`.github/workflows/release-build.yml`) runs
`release:build -- --config release/<patch> --fetch --check` for every patch
directory on a clean checkout whenever a change touches what the build reads
(its Python modules, `release/`, the adapter, the toolchain pins or the
workflow; a test keeps that path list in step with `build.py`'s imports), so a change that makes any declared build stop
reproducing its reference package fails. Every directory under `release/` is
a claim that it still reproduces; when an old patch is superseded and no
longer needs to (for example after an intended adapter change), delete its
directory: Git history keeps it. When a
release is meant to differ (a new patch), publish it first and then move
`reference` to it, so CI checks the package that PoBR actually pins.
