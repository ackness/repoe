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
the zip's pin), `package.json`, `manifest.json`, `SHA256SUMS` and `work/`
(adapter outputs and logs). Nothing is read from the game CDN, a vendor tree
or a checkout's data directories.

### Declarations: one directory per package

`release/<patch>/` declares the first package of a patch and
`release/<patch>-<n>/` the package published as `game/<patch>-<n>`
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
changed the passive-tree policy and adapter in place; that declaration is in
Git history at `66c8c96`, where it still reproduces the Release byte for byte
(with `reference` read from the Release asset as well as from the handoff
blob). Its receipt names the producer commit.

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
   `data:bump` in PoBR.
5. **Not possible yet (roadmap phase 5):** moving `reference` to the new
   package. `reference` must be an input package read as a Git blob at a
   commit kept by a `handoff/*` tag (`build.py` `open_package`/`git_blob`
   read it with `git cat-file`; `adapter:keystones` `check_tag` requires its
   path under that tag), and a Release-only package is neither. Until
   `release:build` can read Release assets, a build that differs from its
   reference cannot pass `--check`, so CI's per-directory check fails for
   that patch; plan the phase-5 change before the first data-changing
   release.

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
  the zip, so check it with `--check`. A `[patch]` to a local PoBR checkout
  builds (the receipt records `tag: null` and the `local` crates) but
  `release:publish` refuses it.
- **Dirty producer:** any tracked change or untracked file under `RePoE/`,
  `release/`, `tools/pobr-data-adapter/` or the toolchain pins marks the
  receipt `dirty`, and publish refuses it.

`handoff/*` tags are never moved or deleted: PoBR's lock and
`release/<patch>/inputs.lock.json` read pinned commits through them. The
publication index, its `releases/<n>.json` chain and the publication plans
were removed (roadmap 3.5); Git history keeps them.
