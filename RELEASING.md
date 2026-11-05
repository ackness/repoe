# Releasing the PoBR game package

A game package goes from this repository to PoBR in three steps:

```sh
mise run release:build -- --fetch --check  # rebuild from pinned inputs, compare with the expect pin
mise run release:publish -- --yes          # tag game/<patch>-<n> on master, create its GitHub Release
# then, in ackness/pobr:
mise run data:bump ackness/repoe game/<patch>-<n>   # pin it, prepare data, open the PR
```

Who owns what across RePoE, the translation repository and PoBR is described
once, in PoBR's [data architecture](https://github.com/ackness/pobr/blob/master/docs/data-architecture.md).

## Build

`release:build` builds the adapter (`--locked --release`) and assembles the
complete game part from one declaration directory under `release/` (default:
the highest; `--config release/<dir>` picks another).

| Option | Effect |
| --- | --- |
| `--check` | Exit 1 unless the zip equals the declaration's `expect` pin (without one: its `reference` package) |
| `--fetch` | `git fetch` pinned commits and input tags missing locally, and download pinned Release assets missing from the cache (otherwise Git runs with `GIT_NO_LAZY_FETCH=1` and nothing is downloaded) |
| `--manifest fresh` | Always write a new root `manifest.json` instead of retaining the reference one |

Output, replaced on each run, is `.cache/release/<game>-<realm>-<dir>/`:
`game-build-part.zip`, `receipt.json` (producer commit and code pins,
contract, every input pin, per-job evidence, the class of every member and
the pin of the zip and its root manifest; `repoe-release-receipt/v2`),
`package.json`, `manifest.json`, `SHA256SUMS` and `work/` (adapter outputs
and logs). Nothing is read from the game CDN, a vendor tree or a checkout's
data directories.

### Declarations: one directory per package

`release/<patch>/` declares the first package of a patch (`game/<patch>-1`)
and `release/<patch>-<n>/` the package published as `game/<patch>-<n>`
(`release:publish` refuses any other `<n>`); the default is the highest patch,
then the highest `<n>`. Each directory holds three files:

- `inputs.lock.json` (`repoe-release-inputs/v1`): the input `packages`, the
  `facts` envelope, the `reference` package and the `expect` pin.
- `domains.json`: the jobs in order: one `adapter` job per
  `pobr-data-adapter --ordinary-facts` domain, plus `special-derived`,
  `historical-trees`, `crafting-catalog` and the final `snapshot-manifest`.
- `frozen-inputs.json`: every member not generated yet (see below).

An input package is pinned by `bytes`, `sha256`, its embedded `manifest` pin
and `expanded_bytes`, and addressed one of two ways:

| Shape | Read from |
| --- | --- |
| `{repository, tag, asset, …}` (no `revision`) | The GitHub Release asset, downloaded anonymously over HTTPS (redirects followed) and cached by SHA-256 under `.cache/release/inputs/downloads/`. `REPOE_RELEASE_BASE_URL` replaces `https://github.com` (a mirror or a local rehearsal server); `REPOE_RELEASE_TRANSPORT=gh` uses `gh release download` instead (a private repository). |
| `{repository, tag, revision, path, …}` | A Git blob at a commit kept reachable by a `handoff/*` tag; the tag must peel to `revision`. |

Either way the bytes are used only after they match the pin. Game packages
(`game/<patch>-<n>`) and new input packages (`inputs/<patch>-<n>`, see
[Input packages](#input-packages)) are Release assets; older inputs stay Git
blobs.

- `reference` names the package members are compared with: the last
  published game package. It is usually also the `frozen-inputs.json`
  `source` and the `snapshot-manifest` template.
- `expect.package` (`{bytes, sha256}`) pins the zip this declaration must
  produce. Write it after the first build, from the printed pin; change it
  whenever an intended change moves the bytes, so review sees the move.
  Without it `--check` compares with `reference` (an unchanged rebuild).
- `facts` may be omitted when no `adapter` job runs (a replay of an old
  package, see [A new game patch](#a-new-game-patch)).

Each member is `generated` (a job derived it), `passthrough` (a job emitted
one of its own inputs; undeclared pass-through fails the build) or `frozen`,
and each produced member is `*-identical`, `*-different` or `*-new` against the
reference. The root manifest is retained from the reference only when every
other member is identical, so an unchanged rebuild reproduces the published
zip byte for byte. Otherwise a fresh root manifest is written that depends
only on the members and the declaration: it names no producer commit and no
receipt (the receipt pins the zip instead), so the same declaration gives the
same zip on every commit and `expect` can pin it.

Declarations today:

| Directory | Package | Reference | `--check` |
| --- | --- | --- | --- |
| `release/0.5.5.5-2/` | the 0.5.5.5-2 data batch (new `base/active_skill_types.json`, `game_constants.base_maximum_rage`, native packets for every eligible passive node): 33 generated, 4 pass-through, 26 frozen | Release `game/0.5.5.5-1` (`3edc9b1e…`) | `expect` `c46df616…` (4559376 bytes) |

`game/0.5.5.5-1` itself (32 generated, 4 pass-through, 26 frozen, zip
`3edc9b1e…`) was declared by `release/0.5.5.5/` until the 0.5.5.5-2 batch
changed the passive-tree policy and adapter in place. The declaration is in
Git history at `407ed52`, the commit `game/0.5.5.5-1` tags and its receipt
names as producer; it is unchanged up to `66c8c96`, where it still
reproduces the Release byte for byte with `reference` read from the Release
asset as well as from the handoff blob.

The `snapshot-manifest` job re-pins the members over the reference's own
snapshot. `add` declares a new member (path → domain section),
`contract_version: "adapter"` records the adapter's contract version, and
`omit` drops entries and fields another owner declares: from 0.5.5.5-2 the
game snapshot no longer lists the language owner's `i18n/` files or
`languages`. PoBR composes the runtime manifest from both packages, so a
language release no longer needs a game re-release.

CI (`.github/workflows/release-build.yml`) runs
`release:build -- --config release/<dir> --fetch --check` for every
directory whenever something the build reads changes. Every directory under
`release/` is a claim that the current code still produces its `expect` pin
(or its reference); when a code or policy change moves a published package's
bytes on purpose, add the next `release/<patch>-<n>/` and delete the
superseded directory in the same change rather than let it fail (Git history
and the Release receipt keep it).

## Publish

`release:publish` stages the release:build output of a clean master commit
and, with `--yes`, runs `git tag --annotate`, `git push origin
refs/tags/<tag>` and `gh release create <tag> --verify-tag`. Without `--yes`
(or with `--dry-run`) it only stages the assets, notes and tag message under
`.cache/release/publish/<target>/` and prints the commands.

| Item | Value |
| --- | --- |
| Tag | `game/<patch>-<n>`, annotated, on the master commit that built the package; `<n>` is one above the highest `game/<patch>-*` on `origin`, and must equal the `<n>` of a `release/<patch>-<n>/` declaration |
| Assets | `pobr-game-<patch>.zip`, `receipt.json`, `SHA256SUMS` |
| Options | `--config release/<dir>`, `--reuse` (stage the existing build of HEAD if its producer matches), `--allow-different` (a declaration without `expect` whose zip differs from the reference) |

It refuses a dirty tree, a HEAD not on `origin/master`, a stray local tag, a
missing or unauthenticated `gh`, a declared `<n>` that is not the next one, a
zip that differs from the declaration's `expect` pin, and (without `expect`)
a zip that differs from the reference unless `--allow-different` is given.
Then pin the tag in PoBR with `mise run data:bump ackness/repoe game/<patch>-<n>`.

## Input packages

`release:inputs` packages a patch's extracted inputs (the facts envelope,
codec sources, supplements, tree references: whatever the declaration's jobs
read) and publishes them as the GitHub Release `inputs/<patch>-<n>`, so a
declaration pins them like a game package:

```sh
mise run release:inputs -- --patch <patch> --package ordinary=<dir> [--package crafting=<dir> ...]
mise run release:inputs -- --patch <patch> --package ordinary=<dir> --yes
```

| Item | Value |
| --- | --- |
| Assets | one `repoe-input-<name>-<patch>.zip` per `--package`, and `SHA256SUMS` |
| Zip | every regular file under `<dir>` at its relative path plus a root `manifest.json` (`repoe-release-input/v1`: `name`, `target`, `files` pins); sorted members, fixed timestamps, so the bytes depend only on the files (symlinks and a `manifest.json` in `<dir>` refuse) |
| Tag | `inputs/<patch>-<n>`, annotated, on HEAD; `<n>` is one above the highest `inputs/<patch>-*` on `origin` (game tags are a separate sequence) |
| Output | `.cache/release/publish/inputs-<game>-<realm>-<patch>/`: `assets/`, `release-notes.md`, `tag-message.txt`, and `lock.json`, the `inputs.lock.json` `packages` entries to paste (`{repository, tag, asset, bytes, sha256, manifest, expanded_bytes}`) |

Without `--yes` it only stages and prints the commands. `--yes` has the same
safety and resume rules as `release:publish` (clean tree, HEAD on
`origin/master`, `gh` logged in, no stray local tag, never a second number for
one commit; see [Troubleshooting](#troubleshooting)), so publishing a second
input batch of a patch needs a new commit. Package members are named by the
directory layout: a job option `ordinary:passive-tree/supplement` reads
`passive-tree/supplement/` of the `ordinary` package.

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
   data change: review the diff, put it in the next `release/<patch>-<n>/`
   with its `expect` pin, publish and bump PoBR.

Other frozen bytes: the published package's PoB2-derived parser and
special-rule files stay frozen (new parser capability goes into PoBR's Rust
rules), and pinned policy files keep their bytes; changing a policy is a data
change like any other.

## A new game patch

A runbook, measured on the stage-5 rehearsal (2026-11-05): a replay of
0.5.5.4.2 from its only surviving source, the game package at
`handoff/rollback-0.5.5.4.2-20261101`, through `release:inputs`,
`release:build`, `release:publish` and PoBR `data:bump`, with every
Release served by a local HTTP server (`REPOE_RELEASE_BASE_URL` /
`POBR_RELEASE_BASE_URL`; nothing was tagged or published). Times are wall
clock on the development host, warm Cargo and download caches unless noted.

### Runbook

1. **Export the inputs** (not rehearsed: 0.5.5.4.2 has no client facts; there
   is no measured time). Acquire and export the patch with `client:source`,
   `facts:candidate`, `tables:candidate`, `descriptions:candidate` and
   `source:rebind` (the portable facts envelope `facts` names), then lay out
   one directory per input package with the member paths the jobs will name
   (e.g. `passive-tree/supplement/`, `ordinary-input.zip/ordinary-input.zip`,
   `handoff.json/handoff.json` as in today's `ordinary` package).
2. **Publish the inputs**: `mise run release:inputs -- --patch <patch>
   --package ordinary=<dir> …` (dry run; 3.7 s for one 3.7 MB package of 58
   files), then on a clean master commit `-- --yes`. Paste the printed
   `lock.json` entries into the new declaration's `packages`.
3. **Declare the package**: copy the newest `release/<dir>/` to
   `release/<patch>/`, keep `reference` (and usually `frozen-inputs.json`
   `source` and the snapshot template) on the last published game package,
   point `facts` and the job options at the new packages, update policy pins
   and member paths (`data/<patch>/…`) in `domains.json`, carry
   `frozen-inputs.json` over and replace what you can. Keep
   `contract_version: "adapter"` and the `omit` of `i18n/`/`languages` on the
   `snapshot-manifest` job (see blocker 1).
4. **Build**: `mise run release:build -- --fetch` (adapter `cargo build
   --locked --release` from an empty target directory: 17 s; the build: 26 s
   for 0.5.5.5, 1.7 s for the 0.5.5.4.2 replay; the first run downloads the
   Release inputs, later runs read `.cache/release/inputs/downloads/`
   offline). Explain every `*-different` member by the new facts, not by an
   unintended policy change, then write the printed zip pin into
   `inputs.lock.json` `expect.package` and rerun with `--check`.
5. **Publish**: merge, then on master `mise run release:publish` (dry run:
   3.9 s including the build) and `-- --yes`.
6. **Language owner**: the translation repository publishes
   `locale/<patch>-<n>` for the same target, with `display_texts.json`, and a
   support-display publication for the new trade catalog (blockers 2 and 3).
7. **PoBR**: `mise run data:bump ackness/repoe game/<patch>-<n>
   ackness/poe2-zh-cn-stats locale/<patch>-<n>` (a new target needs both
   owners in one call; verification and lock rewrite 1.1 s with
   `--no-prepare`), then PoBR CI.

### What the rehearsal showed

| Step | Result |
| --- | --- |
| `release:inputs` (rollback package unpacked, 58 files, 50 MB) | Deterministic `repoe-input-rollback-0.5.5.4.2.zip` (3698985 bytes) and `lock.json`; dry run refused only for "HEAD is not on origin/master". |
| `release:build`, input read from the mock `inputs/0.5.5.4.2-1`, reference the handoff Git blob | `special-derived` regenerated identically, snapshot passthrough-identical, 56 frozen; zip byte-identical to the published `c93d17a4…` (retained manifest). |
| Same, plus `contract_version: "adapter"` | Fresh manifest, zip `8a8d7cbb…` (3699280 bytes), pinned with `expect` and reproduced offline. |
| `release:publish` dry run | Staged `pobr-game-0.5.5.4.2.zip`, `receipt.json`, `SHA256SUMS`; refused "not on origin/master" and the 0.5.5.5-2 branch's local PoBR `[patch]`. |
| PoBR `data:bump` (master `0a6a9618`; its game snapshot must still list `i18n/`, which a 0.5.5.4.2 package does) | Releases verified and lock moved to 0.5.5.4.2 with `--no-prepare`; `data:prepare` stops at blocker 3. |

### Blockers a real new patch must clear

1. **Contract declaration** (PoBR, every new package): PoBR refuses a newly
   locked snapshot without `contract_version` (only 0.5.5.5-1's snapshot is
   exempt), so a byte-identical replay of a pre-contract package cannot be
   locked. The snapshot job must declare `contract_version: "adapter"`, which
   makes the package a fresh one.
2. **Display texts** (language owner): PoBR's compact release (recorded
   `release_id`) needs `i18n/<locale>/display_texts.json` in the language
   part; the 0.5.5.4.2 language part has none. On master the game snapshot
   also pins the language files, so adding one also changes the game
   package; the 0.5.5.5-2 batch removes that coupling (PoBR
   `feat/data-batch-consume`).
3. **Support display** (language owner + PoBR): `support_display` in PoBR's
   lock is a Git pin for one target and one trade-catalog SHA-256; it must be
   republished for the new patch, and `data:bump` does not move it (follow-up
   in PoBR).
4. **Client facts** (RePoE): only a patch with an exported facts envelope can
   regenerate its adapter domains; without one (0.5.5.4.2) a replay
   regenerates only package-derived members and freezes the rest (`facts`
   omitted, no `adapter` jobs).
5. **Publishing from the 0.5.5.5-2 branch**: its temporary Cargo `[patch]`
   to a local PoBR checkout blocks `release:publish -- --yes` until PoBR tags
   `contract/1.1`.

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
- **Missing commit, tag or Release asset:** add `--fetch` to `release:build`.
- **Corrupt cache entry:** a cached Release asset no longer matches its pin;
  delete the named file under `.cache/release/inputs/downloads/` and rerun with `--fetch`.
- **`--check` fails after an intended change:** the zip moved; review the
  member classes in the receipt, then update `expect.package` in the same change.
- **Tag names another commit:** an input's `tag` must peel to its locked
  `revision`; fix the lock, never move the tag.
- **Contract tag:** the adapter's PoBR crates must be pinned to an
  `ackness/pobr` tag `contract/<CONTRACT_VERSION>.<m>` in
  `tools/pobr-data-adapter/Cargo.toml`; a pin bump changes the receipt, not
  the zip, so check it with `--check`. A `[patch]` to a local PoBR checkout
  builds (the receipt records `tag: null` and the `local` crates) but
  `release:publish` refuses it.
- **Dirty producer:** any tracked change or untracked file under `RePoE/`,
  `release/`, `tools/pobr-data-adapter/` or the toolchain pins marks the
  receipt `dirty`, and publish refuses it.

`handoff/*` tags are never moved or deleted: older PoBR locks and
`release/<dir>/inputs.lock.json` read pinned commits through them. The
publication index, its `releases/<n>.json` chain and the publication plans
were removed (roadmap 3.5); Git history keeps them.
