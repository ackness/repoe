# Releasing the PoBR game package

A game package goes from this repository to PoBR in three steps:

```sh
mise run release:build -- --check          # rebuild from pinned inputs, compare with the reference
mise run release:publish -- --yes          # tag game/<patch>-<n> on master, create its GitHub Release
# then, in ackness/pobr:
mise run data:bump ackness/repoe game/<patch>-<n>   # pin it, prepare data, open the PR
```

Who owns what across RePoE, the translation repository and PoBR is described
once, in PoBR's [data architecture](https://github.com/ackness/pobr/blob/master/docs/data-architecture.md).

## Build

`release:build` builds the adapter (`--locked --release`) and assembles the
complete game part from the declaration in `release/<patch>/` (default: the
highest patch directory; `--config release/<patch>` picks another).

| Option | Effect |
| --- | --- |
| `--check` | Exit 1 unless the zip equals the declaration's `reference` package |
| `--fetch` | `git fetch` pinned commits and input tags missing locally (otherwise Git runs with `GIT_NO_LAZY_FETCH=1`) |
| `--manifest fresh` | Always write a new root `manifest.json` instead of retaining the reference one |

Output, replaced on each run, is `.cache/release/<game>-<realm>-<patch>/`:
`game-build-part.zip`, `receipt.json` (producer commit and code pins,
contract, every input pin, per-job evidence and the class of every member),
`package.json`, `manifest.json`, `SHA256SUMS` and `work/` (adapter outputs and
logs). Nothing is read from the game CDN, a vendor tree or a checkout's data
directories; inputs are Git blobs at pinned commits, extracted once into
`.cache/release/inputs/`.

`release/<patch>/` holds three declarations:

- `inputs.lock.json`: input packages (repository, tag, commit, path, bytes,
  SHA-256, embedded manifest pin), the facts envelope and the `reference`
  package (the currently published game package).
- `domains.json`: the jobs in order: one `adapter` job per
  `pobr-data-adapter --ordinary-facts` domain, plus `special-derived`,
  `historical-trees`, `crafting-catalog` and the final `snapshot-manifest`.
- `frozen-inputs.json`: every member not generated yet (see below).

Each member is `generated` (a job derived it), `passthrough` (a job emitted
one of its own inputs; undeclared pass-through fails the build) or `frozen`,
and each produced member is `*-identical`, `*-different` or `*-new` against the
reference. The root manifest is retained from the reference only when every
other member is identical, so an unchanged rebuild reproduces the published
zip byte for byte. 0.5.5.5: 32 generated, 4 pass-through, 26 frozen, zip
`3edc9b1e…` identical to `game/0.5.5.5-1`.

CI (`.github/workflows/release-build.yml`) runs
`release:build -- --config release/<patch> --fetch --check` for every patch
directory whenever something the build reads changes. Every directory under
`release/` is a claim that it still reproduces its reference; delete a
superseded patch's directory rather than let it fail (Git history keeps it).

## Publish

`release:publish` stages the release:build output of a clean master commit
and, with `--yes`, runs `git tag --annotate`, `git push origin
refs/tags/<tag>` and `gh release create <tag> --verify-tag`. Without `--yes`
(or with `--dry-run`) it only stages the assets, notes and tag message under
`.cache/release/publish/<target>/` and prints the commands.

| Item | Value |
| --- | --- |
| Tag | `game/<patch>-<n>`, annotated, on the master commit that built the package; `<n>` is one above the highest `game/<patch>-*` on `origin` |
| Assets | `pobr-game-<patch>.zip`, `receipt.json`, `SHA256SUMS` |
| Options | `--config release/<patch>`, `--reuse` (stage the existing build of HEAD if its producer matches), `--allow-different` (new patch or intended data change) |

It refuses a dirty tree, a HEAD not on `origin/master`, a stray local tag, a
missing or unauthenticated `gh`, and a zip that differs from the reference
unless `--allow-different` is given. Then pin the tag in PoBR with
`mise run data:bump ackness/repoe game/<patch>-<n>`.

## Frozen inputs and how to replace one

`frozen-inputs.json` lists each member still copied from an earlier package,
with its SHA-256, category (`unpinned-input`, `pob2-derived`,
`migrated-constants`, `shared-overlay`), origin, why it is frozen and what
would let it go. Its length is the progress measure: shrink it, never grow it
silently. To replace a frozen member:

1. Add (or extend) a job in `domains.json` that produces the member, with its
   policy under `tools/pobr-data-adapter/policies/` if it needs one.
2. Delete the member's entry from `frozen-inputs.json`.
3. Run `release:build`. A `generated-identical` member is a pure provenance
   change and the zip still reproduces. A `generated-different` member is a
   data change: review the diff, publish with `--allow-different`, bump PoBR,
   then move `reference` to the new package.

Other frozen bytes: the published package's PoB2-derived parser and
special-rule files stay frozen (new parser capability goes into PoBR's Rust
rules), and pinned policy files keep their bytes; changing a policy is a data
change like any other.

## A new game patch

1. Export the new client facts and supplements (`client:source`,
   `facts:candidate`, `tables:candidate`, `descriptions:candidate`) and make
   each input package addressable by commit, path and SHA-256, kept reachable
   by a tag that is never moved. The plan-based packager used for 0.5.5.5
   (`RePoE.data_publication`) was retired; it is in Git history at
   `bd4c1994e3932ed914219dac4d2495878e826cf6` until a replacement lands
   (roadmap phase 5).
2. Copy `release/<old patch>/` to `release/<new patch>/`. Point
   `inputs.lock.json` at the new packages, keep `reference` on the last
   published game package, update policy pins and member paths in
   `domains.json`, and carry `frozen-inputs.json` over, replacing what you can.
3. `mise run release:build` (the new directory is now the default). Explain
   every `*-different` member by the new facts, not by an unintended policy
   change.
4. Merge to master, `release:publish -- --allow-different --yes`, then
   `data:bump` in PoBR. Afterwards set `reference` to the new package so CI
   checks what PoBR pins.

## Troubleshooting

`release:publish -- --yes` never gives a commit a second sequence number, so
rerunning it resumes:

| HEAD already has | Rerun does |
| --- | --- |
| an unpushed local `game/<patch>-<k>` | push it, then create the Release |
| `game/<patch>-<k>` on `origin`, no Release | create the Release for `<k>` |
| a draft Release with every staged asset (a create killed mid-upload) | publish the draft (`gh release edit --draft=false`) |
| a draft Release with other or missing assets | refuse: delete it with `gh release delete <tag> --repo ackness/repoe --yes` (keeps the tag) and rerun |
| a published Release | compare assets: equal is "already published" (exit 0), different is an error |

- **Stale `--reuse`:** the cached build's producer (commit, declarations, code
  pins, adapter binary, contract) differs from the checkout; rerun without it.
- **Missing commit or tag:** add `--fetch` to `release:build`.
- **Tag names another commit:** an input's `tag` must peel to its locked
  `revision`; fix the lock, never move the tag.
- **Contract tag:** the adapter's PoBR crates must be pinned to an
  `ackness/pobr` tag `contract/<CONTRACT_VERSION>.<m>` in
  `tools/pobr-data-adapter/Cargo.toml`; a pin bump changes the receipt, not
  the zip, so check it with `--check`.
- **Dirty producer:** any tracked change or untracked file under `RePoE/`,
  `release/`, `tools/pobr-data-adapter/` or the toolchain pins marks the
  receipt `dirty`, and publish refuses it.

`handoff/*` tags are never moved or deleted: PoBR's lock and
`release/<patch>/inputs.lock.json` read pinned commits through them. The
publication index, its `releases/<n>.json` chain and the publication plans
were removed (roadmap 3.5); Git history keeps them.
