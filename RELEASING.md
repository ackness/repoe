# Releasing the PoBR game package

A game package goes from this repository to PoBR in three steps:

```sh
mise run release:build -- --fetch --check  # rebuild from pinned inputs, compare with the expect pin
mise run release:publish -- --yes          # tag game/<patch>-<n> on master, create its GitHub Release
# then, in ackness/pobr (a new patch names both owners; see below):
mise run data:bump ackness/repoe game/<patch>-<n> ackness/poe2-zh-cn-stats locale/<patch>-<m>
```

`data:bump` verifies the Releases, rewrites PoBR's data lock and prepares the
data. It does not commit, push or open a PR: the PoBR maintainer does that. A
new patch needs both owners in one call; a same-patch game-only package is
bumped alone (`mise run data:bump ackness/repoe game/<patch>-<n>`). The PoBR
side is described in PoBR's
[RELEASING.md](https://github.com/ackness/pobr/blob/master/RELEASING.md), and
who owns what across RePoE, the translation repository and PoBR in its
[data architecture](https://github.com/ackness/pobr/blob/master/docs/data-architecture.md#5-更新采用与发布).

## Build

`release:build` builds the adapter (`--locked --release`) and assembles the
complete game part from one declaration directory under `release/`.

| Option | Effect |
| --- | --- |
| `--config release/<dir>` | The declaration to build (default: the highest, see below) |
| `--check` | Exit 1 unless the zip equals the declaration's `expect` pin (without one: its `reference` package) |
| `--fetch` | `git fetch` pinned commits and input tags missing locally, and download pinned Release assets missing from the cache (otherwise Git runs with `GIT_NO_LAZY_FETCH=1` and nothing is downloaded) |
| `--manifest fresh` | Always write a new root `manifest.json` instead of retaining the reference one |
| `--out <dir>` | Output directory, under `.cache/` or outside the checkout (default `.cache/release/<game>-<realm>-<dir>/`) |
| `--cache <dir>` | Input cache (default `.cache/release/`; extracted packages and downloads go under `<dir>/inputs/`) |

The output, replaced on each run, holds `game-build-part.zip`, `receipt.json`
(producer commit and code pins, contract, every input pin, per-job evidence,
the class of every member and the pin of the zip and its root manifest;
`repoe-release-receipt/v2`), `package.json`, `manifest.json`, `SHA256SUMS` and
`work/` (adapter outputs and logs). Nothing is read from the game CDN, a
vendor tree or a checkout's data directories.

### Declarations: one directory per package

`release/<patch>/` declares the first package of a patch (`game/<patch>-1`)
and `release/<patch>-<n>/` the package published as `game/<patch>-<n>`
(`release:publish` refuses any other `<n>`); the default is the highest patch,
then the highest `<n>`. Each directory holds three files:

- `inputs.lock.json` (`repoe-release-inputs/v1`): the `target`, the input
  `packages`, the `facts` envelope, the `reference` package and the `expect`
  pin.
- `domains.json`: the jobs in order: one `adapter` job per
  `pobr-data-adapter --ordinary-facts` domain, plus `special-derived`,
  `historical-trees`, `crafting-catalog` and the final `snapshot-manifest`.
- `frozen-inputs.json`: every member not generated yet (see below).

An input package is pinned by `bytes`, `sha256`, its embedded `manifest` pin
and `expanded_bytes`, and addressed one of two ways:

| Shape | Read from |
| --- | --- |
| `{repository, tag, asset, …}` (no `revision`) | The GitHub Release asset, downloaded anonymously over HTTPS (redirects followed) and cached by SHA-256 under `.cache/release/inputs/downloads/`. `REPOE_RELEASE_BASE_URL` replaces `https://github.com` (a mirror or a local server); `REPOE_RELEASE_TRANSPORT=gh` uses `gh release download` instead (a private repository). |
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
  package that has no exported facts).

Each member is `generated` (a job derived it), `passthrough` (a job emitted
one of its own inputs; undeclared pass-through fails the build) or `frozen`,
and each produced member is `*-identical`, `*-different` or `*-new` against the
reference. The root manifest is retained from the reference only when every
other member is identical, so an unchanged rebuild reproduces the published
zip byte for byte. Otherwise a fresh root manifest is written that depends
only on the members and the declaration: it names no producer commit and no
receipt (the receipt pins the zip instead), so the same declaration gives the
same zip on every commit and `expect` can pin it.

The `snapshot-manifest` job re-pins the members over the reference's own
snapshot. `add` declares a new member (path → domain section),
`contract_version: "adapter"` records the adapter's contract version (PoBR
refuses a newly locked snapshot without one), and `omit` drops entries and
fields another owner declares: the game snapshot does not list the language
owner's `i18n/` files or `languages`. PoBR composes the runtime manifest from
both packages, so a language release does not need a game re-release.

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
| Tag | `game/<patch>-<n>`, annotated, on the master commit that built the package; `<n>` is one above the highest `game/<patch>-*` on `origin`, and must equal the `<n>` the declaration directory names |
| Assets | `pobr-game-<patch>.zip`, `receipt.json`, `SHA256SUMS` |
| Options | `--config release/<dir>`; `--dry-run` (the default) or `--yes`; `--fetch` (pass `--fetch` to the build); `--reuse` (stage the existing build of HEAD if its producer matches); `--allow-different` (a declaration without `expect` whose zip differs from the reference) |

It refuses a dirty tree, a HEAD not on `origin/master`, a stray local tag, a
missing or unauthenticated `gh`, a declared `<n>` that is not the next one, a
zip that differs from the declaration's `expect` pin, an adapter built against
a local PoBR checkout, and (without `expect`) a zip that differs from the
reference unless `--allow-different` is given. A dry run still builds and
stages, then lists every refusal and exits 1, so on a branch
`mise run release:publish -- --fetch` is the one command that builds, checks
the pin and the sequence number, and shows what would be published.

Then pin the tag in PoBR: `mise run data:bump ackness/repoe game/<patch>-<n>
ackness/poe2-zh-cn-stats locale/<patch>-<m>` for a new patch, or
`mise run data:bump ackness/repoe game/<patch>-<n>` for another package of
the same patch.

## Input packages

`release:inputs` packages a patch's extracted inputs (the facts envelope,
codec sources, supplements, tree references: whatever the declaration's jobs
read) and publishes them as the GitHub Release `inputs/<patch>-<n>`, so a
declaration pins them like a game package:

```sh
mise run release:inputs -- --patch <patch> --package ordinary=<dir> [--package <name>=<dir> ...]
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

Several checks still name 0.5.5.5 or the identity of the exporter that
produced its facts, so the first new patch starts with code changes. Below, `<new>` is the new patch and `game/0.5.5.5-2` the last
published package. The work lands as separate PRs, each merged before the
next step:

1. **Exporter and trust PR** (step 0): the code changes below, with tests.
2. **Publish the inputs** (steps 1–2) from master after that merge.
3. **Declaration PR** (steps 3–4): `release/<new>/` with its `expect` pin.
4. **Publish** `game/<new>-1` (step 5) from master after that merge.
5. **PoBR PR** (step 6), after the translation repository has published
   `locale/<new>-<m>`.

### 0. Code changes

| What | Where | Change |
| --- | --- | --- |
| Accepted source patch | `RePoE/native/facts.py` (`game_patch != "0.5.5.5"`), `tools/pobr-data-adapter/src/facts/trust.rs` (`("game_patch", "0.5.5.5")`), `src/facts/player.rs` (`identity["game_patch"] == "0.5.5.5"`) | Accept `<new>` as well; the 0.5.5.5 envelope must still verify |
| Exporter identity | the producer map in `trust.rs`; the `include_bytes!` fixtures `tests/fixtures/ordinary-facts/selected-tables-producer*.json`, `item-inheritance-producer.json` and `tests/fixtures/native-facts/player-context-manifest.json` | Add the new export's identity (current `RePoE/native/` paths and hashes) beside the historical one; never edit the historical bytes ([fixed producer identities](tools/pobr-data-adapter/tests/fixtures/ordinary-facts/README.md#fixed-producer-identities)) |
| Crafting producer | `PRODUCERS` in `RePoE/release/crafting_catalog.py` | Accept `RePoE/native/crafting_facts.py` and `RePoE/native/descriptions.py` beside the historical keys |
| Crafting package transport | `crafting_catalog.facts_document`, `release:inputs` | The crafting job reads the package's own root `manifest.json` (`repoe-native-crafting-facts/v1`) and needs `publication`, `producer` and `input_manifest` on the lock entry, while `release:inputs` reserves the root `manifest.json` and prints none of those keys: decide how a new crafting package is published |
| Frozen members and snapshot template | `RePoE/release/build.py` | A frozen member is read at its own path (`data/<new>/…`) from the single `frozen-inputs.json` `source`, and the snapshot template must have `poe_version == <new>`; `game/0.5.5.5-2` holds `data/0.5.5.5/…` with `poe_version` 0.5.5.5. Either map the old paths in code or carry the frozen bytes and the template in an input package under `data/<new>/` |
| Schema constants (only if the dat schema changes) | `trust.rs` (`DECODER_PIN_SHA`, `SCHEMA_REVISION`, `SCHEMA_SHA`, the native specification pin), `RePoE/native/decoded_tables.py` (`SPEC_SHA`), `native/locale_probe.py` (`SCHEMA_REVISION`, `SCHEMA_SHA256`), `native/crafting_facts.py` (`SCHEMA`), `native/facts.py` (`SCHEMA`, `SCHEMA_SHA`) | Add the new schema beside the pinned one |

`RePoE/native/locale_probe.py` is pinned by its own bytes (`decoded_tables.py`
compares a transfer receipt's `decoder.source_sha256` with it), so an edit
rejects every existing transfer receipt. Re-validating the 0.5.5.5 envelope
keeps working only at its producer commit
([native facts](RePoE/docs/native/native_facts.md#producer-identity-and-re-validation)).

### 1. Export the inputs

Acquire and export the patch with `client:source`, `facts:candidate`,
`tables:candidate`, `descriptions:candidate`, `RePoE.native.item_inheritance`,
`RePoE.native.crafting_facts` and `source:rebind`
([native docs](RePoE/docs/README.md)), then lay out one directory per input
package. The `ordinary` package of `release/0.5.5.5-2/` has this layout; a job
option `ordinary:<path>` names a path in it:

| Path | Content | Produced by |
| --- | --- | --- |
| `ordinary-input.zip/ordinary-input.zip`, `handoff.json/handoff.json` | The portable facts envelope that `facts.archive` and `facts.handoff` name | `facts:candidate`, `facts:validate`, `source:rebind` |
| `<domain>/supplement/` (`stat-descriptions`, `passive-tree`, `minions`, `spectres`) | `tables.json`, `manifest.json`, `source-lock.json` (`repoe-native-tables/v1`) | `tables:candidate` |
| `base-items/supplement/` | `inheritance.json`, `manifest.json`, `source-lock.json` (`repoe-item-inheritance/v1`) | `RePoE.native.item_inheritance` |
| `passive-tree/tree-descriptions/`, `stat-descriptions/item-descriptions/` | `descriptions.json`, `manifest.json` (`repoe-native-descriptions/v1`) | `descriptions:candidate` |
| `<domain>/codec-source/*.json` | The 0.5.5.4.2 runtime files the codec policies pin (byte-identical to the `legacy` package's) | copied |
| `skill-overrides/branch-codec/stat_set_labels.json` | The 0.5.5.4.2 stat-set labels | copied |
| `passive-tree/tree-reference/official-tree-<sha>.json` | GGG's passive-tree export the tree policy cross-checks | downloaded, pinned by the policy |
| `retained-policy-bindings/passive-tree-v4.json` | Bindings the passive-tree policy template is rebound with | carried |
| `publication-provenance/` | Manifests of the packages the inputs were taken from | carried |

The `crafting` package holds the seven tables, `crafting.json`,
`input-manifest.json` and its own `manifest.json`
([crafting facts](RePoE/docs/native/native_crafting_facts.md)).

### 2. Publish the inputs

`mise run release:inputs -- --patch <new> --package ordinary=<dir> …` (dry
run), then on a clean master commit `-- --yes`. Paste the printed `lock.json`
entries into the new declaration's `packages`.

### 3. Declare the package

Copy `release/0.5.5.5-2/` to `release/<new>/` and change what names the patch,
and only that:

| Occurrence | In `release/<new>/` |
| --- | --- |
| `target.game_patch` in the three files | `<new>` |
| Job outputs and frozen keys `data/0.5.5.5/…`, the `snapshot-manifest` `member` | `data/<new>/…` |
| `policy:<domain>/0.5.5.5-*.json` | New `policy:<domain>/<new>-*.json` files whose `version` / `target.game_patch` is `<new>` (the adapter checks them against the facts). Never edit the 0.5.5.5 policies: `release/0.5.5.5-2/` and the adapter tests pin their bytes |
| Policy templates (`rebind`, `expect`) | New `expect` pins of the rebound policies |
| `packages.ordinary`, `packages.crafting`, `facts` (including `identities`) | The new input packages and envelope |
| `packages.previous` | `game/0.5.5.5-2` (the `reference` and the frozen `source`) |
| `packages.legacy` and its `legacy:data/0.5.5.4.2/…` options, `historical-attributes-v1.json` | Unchanged: the 0.5.5.4.2 inputs (codec sources, historical trees) stay |
| The snapshot template `previous:data/0.5.5.5/manifest.json` | A template with `poe_version` `<new>` (see step 0) |
| `contract_version: "adapter"` and the `omit` of `i18n/`/`languages` | Unchanged |
| `handoff/*` paths and tags in `release/0.5.5.5-2/` | Unchanged: they are historical and stay readable |

Keep `release/0.5.5.5-2/` while it still reproduces; CI builds both.

### 4. Build, check and dry-run

```sh
mise run release:publish -- --fetch
```

This builds the declaration, compares it with `expect`, checks the sequence
number and stages the assets in one run; on a branch it also refuses with
"HEAD … is not on origin/master", which is expected there. Explain every
`*-different` member by the new facts, not by an unintended policy change,
then write the printed zip pin into `inputs.lock.json` `expect.package` and
rerun: the only refusals left must be the branch ones. Open the declaration
PR; `release-build.yml` rebuilds it.

### 5. Publish

After the merge, on master: `mise run release:publish -- --fetch` (dry run)
and `mise run release:publish -- --yes`.

### 6. Language owner and PoBR

The translation repository publishes `locale/<new>-<m>` for the same target,
with its display texts and a support-display publication bound to the new
trade catalog
([its RELEASING.md](https://github.com/ackness/poe2-zh-cn-stats/blob/main/RELEASING.md)).
Then in PoBR: `mise run data:bump ackness/repoe game/<new>-1
ackness/poe2-zh-cn-stats locale/<new>-<m>` and the PR described in PoBR's
[RELEASING.md](https://github.com/ackness/pobr/blob/master/RELEASING.md).

A patch without exported client facts can still be replayed: omit `facts`
and the `adapter` jobs, and only the package-derived members are regenerated
while the rest stay frozen.

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
  `release:publish` refuses it, so a batch that needs new contract fields
  waits for PoBR to tag them first.
- **Dirty producer:** any tracked change or untracked file under `RePoE/`,
  `release/`, `tools/pobr-data-adapter/` or the toolchain pins marks the
  receipt `dirty`, and publish refuses it.

Tags are never moved or deleted: this repository's `handoff/*`, `game/*` and
`inputs/*` (PoBR locks and `release/<dir>/inputs.lock.json` read pinned
commits and Release assets through them) and PoBR's `contract/*` (the
adapter's `Cargo.toml` pins one).
