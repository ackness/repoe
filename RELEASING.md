# Releasing the PoBR game package

A game package goes from this repository to PoBR in three steps:

```sh
mise run release:build -- --fetch --check  # rebuild from pinned inputs, compare with the expect pin
mise run release:publish -- --yes          # tag game/<patch>-<n> on master, create its GitHub Release
# then pin the tag in ackness/pobr with `mise run data:bump` (step 6)
```

The `data:bump` command is in [step 6](#6-language-owner-and-pobr). The PoBR
side is described in PoBR's [RELEASING.md](https://github.com/ackness/pobr/blob/master/RELEASING.md), and
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
  `packages`, the `facts` input, the `reference` package and the `expect`
  pin.
- `domains.json`: the jobs in order: one `adapter` job per
  `pobr-data-adapter --ordinary-facts` domain, plus `special-derived`,
  `historical-trees`, `crafting-catalog`, `gem-descriptions` (from
  `release/0.5.5.5-3/` on; [English gem descriptions](RePoE/docs/release/pobr_gem_descriptions.md))
  and the final `snapshot-manifest`.
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

- `reference` names the published game package members are compared with
  (the one before this declaration's package). It is usually also the
  `frozen-inputs.json` `source` and the `snapshot-manifest` template.
- `expect.package` (`{bytes, sha256}`) pins the zip this declaration must
  produce. Write it after the first build, from the printed pin; change it
  whenever an intended change moves the bytes, so review sees the move.
  Without it `--check` compares with `reference` (an unchanged rebuild).
- `facts` may be omitted when no `adapter` job runs (a replay of an old
  package that has no exported facts).

For a fresh export, `facts.root` is the path of one `facts:candidate` output
directory inside the declared package. Both identity names use that root's
`manifest.json` SHA-256:

```json
{
  "facts": {
    "package": "ordinary",
    "root": "facts",
    "identities": {
      "original": "<facts/manifest.json SHA-256>",
      "rebound": "<the same SHA-256>"
    }
  }
}
```

The build checks both declared identities against the packaged manifest and
verifies its file pins. The root is a relative path within the package and
cannot be combined with `handoff` or `archive`.

Existing declarations keep the historical envelope shape unchanged:
`facts: {package, handoff, archive, identities}`. `facts.handoff` names the
`pobr-ordinary-source-handoff/v1` document and `facts.archive` its portable
ZIP, both inside the declared package. Its `original` and `rebound`
identities differ because it proves the 0.5.5.5 source-lock correction
([source rebinding](RePoE/docs/client/source-rebinding.md)); new exports use
`root`.

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
When the template comes from an earlier game package, its `poe_version`
must equal that package's root manifest `target.game_patch`; the new
snapshot records the declaration's target patch. Any other version mismatch
is refused.

A declaration directory claims that the code produces its `expect` pin (or
its reference); when a code or policy change moves a published package's bytes
on purpose, add the next `release/<patch>-<n>/`. A superseded declaration
directory stays in place, as do its Release and tag; its receipt is the
evidence of what it produced. Which declarations CI keeps rebuilding is set in
[AGENTS.md](AGENTS.md#ci).

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

Then pin the tag in PoBR with `data:bump` (command in
[step 6](#6-language-owner-and-pobr); another package of an already pinned
patch is bumped alone).

## Input packages

`release:inputs` packages a patch's extracted inputs (the facts root or envelope,
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
| Zip | every regular file under `<dir>` at its relative path plus a root `manifest.json` (`repoe-release-input/v1`: `name`, `target`, `files` pins); `crafting` keeps its exported root manifest instead. Sorted members and fixed timestamps make the bytes depend only on the files. Symlinks and a root `manifest.json` in other packages refuse |
| Tag | `inputs/<patch>-<n>`, annotated, on HEAD; `<n>` is one above the highest `inputs/<patch>-*` on `origin` (game tags are a separate sequence) |
| Output | `.cache/release/publish/inputs-<game>-<realm>-<patch>/`: `assets/`, `release-notes.md`, `tag-message.txt`, and `lock.json`, the `inputs.lock.json` `packages` entries to paste (`{repository, tag, asset, bytes, sha256, manifest, expanded_bytes}`) |

Without `--yes` it only stages and prints the commands. `--yes` has the same
safety and resume rules as `release:publish` (clean tree, HEAD on
`origin/master`, `gh` logged in, no stray local tag, never a second number for
one commit; see [Troubleshooting](#troubleshooting)), so publishing a second
input batch of a patch needs a new commit. Package members are named by the
directory layout: a job option `ordinary:passive-tree/supplement` reads
`passive-tree/supplement/` of the `ordinary` package.

Before staging succeeds, every facts, supplement, descriptions and tables
manifest must declare the requested `--patch`, `--realm` (default
`international`) and `--game` (default `poe2`). This includes the facts
inside a historical envelope ZIP. An error names the file, the expected
value and the actual value. Packaging and the lock/notes files are prepared
in a temporary directory; a failure keeps the previous successful staging.

For `--package crafting=<crafting export>`, the ZIP retains the
`repoe-native-crafting-facts/v1` root `manifest.json` and its file pins.
Its lock entry also includes `publication: "published"`, `producer` and
`input_manifest`, derived from the exporter manifest, for the crafting
build job. `publication` describes the Release input that the entry will
pin; a dry run still publishes nothing.

## China client capture input

The China (Tencent) client's official text has no CDN, so it reaches PoBR as
an input package built from the owner's local capture
([client capture](RePoE/docs/client/client-capture.md)). Only derived text is
published: the raw DAT, CSD and bundle bytes stay under `.cache/` (a licence
constraint), and the receipt carries no install path. One `inputs/<patch>-<n>`
Release is made per China update; older ones are never touched.

Follow the [request order and fallback](RePoE/docs/client/client-capture.md#next-collection-order)
on that one copy: main text first, then the independent names request.

```sh
CAP=.cache/china-capture-<patch>; PKG=.cache/china-text-<patch>
# 1. The owner runs RePoE/client/capture-sc.ps1 and sends the folder and the capture.json SHA-256.
mise run client:capture -- --capture <folder> --expect-capture-sha256 <sha> \
  --request RePoE/client/china-text-request-2.json --game-patch <patch> --out $CAP \
  --decoder-python "$PWD/.venv/bin/python" --decoder-lock uv.lock
L=$CAP/source-lock.json; S=$(shasum -a 256 $L | cut -d' ' -f1)
# 2. Derived candidates, written straight into the package directory.
mise run descriptions:candidate -- --source-lock $L --expected-source-lock-sha256 $S \
  --source china-stat-descriptions --raw $CAP/raw --out $PKG/stat-descriptions/china
mise run tables:candidate -- --source-lock $L --expected-source-lock-sha256 $S \
  --source china-default --raw $CAP/raw --out $PKG/display-tables/default
mise run tables:candidate -- --source-lock $L --expected-source-lock-sha256 $S \
  --source china-simplified-chinese --language "Simplified Chinese" \
  --raw $CAP/raw --out $PKG/display-tables/simplified-chinese
# 3. The capture identity, then the package (dry run; --yes on a clean master commit).
mkdir $PKG/capture && cp $CAP/capture-receipt.json $CAP/request.json $CAP/SHA256SUMS $PKG/capture/
mise run release:inputs -- --realm china --patch <patch> --package china_text=$PKG
```

| Package member | Producer |
| --- | --- |
| `capture/capture-receipt.json`, `capture/request.json`, `capture/SHA256SUMS` | `client:capture` (hashes and the path list; `capture.json` itself is pinned by SHA-256 only, because it names the install path) |
| `stat-descriptions/china/{descriptions,diagnostics,source-lock,manifest}.json` | `descriptions:candidate`: the four files the translation repository's native reader requires |
| `display-tables/{default,simplified-chinese}/{tables,source-lock,manifest}.json` | `tables:candidate`: `repoe-native-tables/v1` and `repoe-localized-tables/v1`, derived JSON, not `.datc64` |

`release:inputs` enforces this exact derived-file allowlist for `china_text`,
checks the candidate formats and their manifest file pins, and requires both
capture JSON files to have the expected schemas. It rejects extra or missing
members before staging, naming the file; passing `$CAP` itself or adding any
raw CSD, DAT or bundle member fails. The capture's original `capture.json`
is also refused because it contains the install path.
The package name becomes the lock key, so it is `china_text` (letters, digits
and underscores). `--realm china` sets the package target's realm; the patch is
the owner's declared target. Publishing a second input batch for the same patch
(as for `inputs/0.5.5.5-2`, the international Traditional Chinese tables) needs
a new master commit, because `--yes` never gives one commit a second `inputs/`
number.

Published client-text inputs (the translation repository's `official_*` jobs
pin these):

| Tag | Realm | Asset | Bytes | SHA-256 | Root manifest SHA-256 |
| --- | --- | --- | --- | --- | --- |
| `inputs/0.5.5.5-1` | china | `repoe-input-china_text-0.5.5.5.zip` | 20301700 | `56dd27a77fad3c505188f7f696db7763ca28436725db454a4360cdbd4e1ce234` | `90806f0996568683b775a3d88fec847a83fd65a60026bca0427c3e90da50c333` |
| `inputs/0.5.5.5-2` | international | `repoe-input-intl_text-0.5.5.5.zip` | 926093 | `8ef802ff76a449329908c7ab8af6f7957d818887550c479db5586c4d65afd95b` | `586293a4d940b450c57446ab50190747ec29d45b9e6b55cf60c8826aa8b3eb13` |

`inputs/0.5.5.5-2` (package `intl_text`) holds the 0.5.5.5 international
default and Traditional Chinese `GemEffects`, `ActiveSkills` and
`MonsterVarieties` tables as
`display-tables/{default,traditional-chinese}/{tables,source-lock,manifest}.json`.
It has no capture members: the tables come from `tables:candidate` on a source
lock of the international CDN (`patch-poe2.poecdn.com`, sources `intl-default`
and `intl-traditional-chinese`), packaged with
`release:inputs -- --realm international --package intl_text=<dir>`. Only
`china_text` has the allowlist check above.

For the next collection, use [intl-text-request.json](RePoE/client/intl-text-request.json):
both sources also include `ItemClasses`. The unreviewed 0.5.5.8
[acquisition lock](sources/intl-text.lock.json) retains the rehearsal pins for
offline replay; select `intl-default` and `intl-traditional-chinese` when
exporting. For another patch, update the request and collect fresh pins through
step 1 below. The published 0.5.5.5 locks stay unchanged. China's main request
[`china-text-request-2.json`](RePoE/client/china-text-request-2.json) likewise adds
default and Simplified Chinese `ItemClasses`. The separate
[`china-names-request-1.json`](RePoE/client/china-names-request-1.json) collects
`AlternateQualityTypes`, `Ascendancy`, `BaseItemTypes`, `Characters`, `Mods`,
`PassiveSkills` and `Words` pairs from the same capture. Keep their extraction
outputs and receipts separate; publishing the names needs a later packaging
update. The predecessor `china-text-request.json` stays byte-identical because
the 0.5.5.5 capture pins it.

## Frozen inputs and how to replace one

`frozen-inputs.json` lists each member still copied from an earlier package,
with its SHA-256, category (`unpinned-input`, `pob2-derived`,
`migrated-constants`, `shared-overlay`), origin, why it is frozen and what
would let it go. Never add an entry silently. The number of entries is not a
progress measure: a rule member carried forward unchanged is correct, not debt.
To replace a frozen member:

1. Add (or extend) a job in `domains.json` that produces the member, with its
   policy under `tools/pobr-data-adapter/policies/` if it needs one.
2. Delete the member's entry from `frozen-inputs.json`.
3. Run `release:build`. A `generated-identical` member is a pure provenance
   change and the zip still reproduces. A `generated-different` member is a
   data change: review the diff, put it in the next `release/<patch>-<n>/`
   with its `expect` pin, publish and bump PoBR.

When the source package declares a different patch, a frozen destination
`data/<target>/X` reads `data/<source patch>/X`, using the source package's
root manifest `target.game_patch`. Other paths keep their names. The
declared byte and SHA-256 pins still have to match.

Other frozen bytes: the published package's PoB2-derived parser and
special-rule files stay frozen (new parser capability goes into PoBR's Rust
rules), and pinned policy files keep their bytes; changing a policy is a data
change like any other.

## A new game patch

The source-patch checks accept any numeric patch; what still gates a new patch
is the identity of the exporter that produced the 0.5.5.5 facts and, if the dat
schema changes, the schema constants. The first new patch therefore starts with
code changes. Below,
`<new>` is the new patch and `game/0.5.5.5-3` the last published package. The
work lands as separate PRs, each merged before the
next step:

1. **Exporter and trust PR** (step 0): the code changes below, with tests.
2. **Publish the inputs** (steps 1–2) from master after that merge.
3. **Declaration PR** (steps 3–4): `release/<new>/` with its `expect` pin.
4. **Publish** `game/<new>-1` (step 5) from master after that merge.
5. **PoBR PR** (step 6), after the translation repository has published
   `locale/<new>-<m>`.

### 0. Code changes

This table lists only the checks that gate accepting a new patch. `0.5.5.5`
mentions (comments and tests) do not block it.

Client acquisition, index selections (including China captures), CSD export and
selected DAT export share `RePoE/client/limits.py`: 64 MiB per raw resource and
128 MiB selected raw total. Network reservations per invocation, checked cache
bodies and archive imports each have a separate 128 MiB cap. Existing command
summaries report utilisation; bundle/chunk bounds and decoded JSON/legacy
transfer limits are independent. The byte-pinned `native/locale_probe.py` keeps
its historical bounds for transfer re-validation.

| What | Where | Change |
| --- | --- | --- |
| Exporter identity | the producer map in `trust.rs`; the `include_bytes!` fixtures `tests/fixtures/ordinary-facts/selected-tables-producer*.json`, `item-inheritance-producer.json` and `tests/fixtures/native-facts/player-context-manifest.json` | The producer table and the three fixtures are the frozen historical acceptance of the 0.5.5.5 packages: never edit them and do not add identities beside them. A new patch is meant to be checked by `target` only, with the producer identified by the commit in the receipt (clean tree); that check is not implemented yet, so until it lands a new export fails the producer identity check ([fixed producer identities](tools/pobr-data-adapter/tests/fixtures/ordinary-facts/README.md#fixed-producer-identities)) |
| Crafting producer | `PRODUCER_KEY_SETS` in `RePoE/release/crafting_catalog.py` | Nothing while the exporters stay where they are: it already accepts the historical keys and the current `RePoE/native/` keys (a test keeps them equal to `native/crafting_facts.PRODUCERS`); add a set only if the exporters move again |
| Schema constants (only if the dat schema changes) | `trust.rs` (`DECODER_PIN_SHA`, `SCHEMA_REVISION`, `SCHEMA_SHA`, the native specification pin), `RePoE/native/decoded_tables.py` (`SPEC_SHA`), `native/locale_probe.py` (`SCHEMA_REVISION`, `SCHEMA_SHA256`), `native/crafting_facts.py` (`SCHEMA`), `native/facts.py` (`SCHEMA`, `SCHEMA_SHA`) | Add the new schema beside the pinned one |

`RePoE/native/locale_probe.py` is pinned by its own bytes (`decoded_tables.py`
compares a transfer receipt's `decoder.source_sha256` with it), so an edit
rejects every existing transfer receipt. Re-validating the 0.5.5.5 envelope
keeps working only at its producer commit
([native facts](RePoE/docs/native/native_facts.md#producer-identity-and-re-validation)).

### 1. Export the inputs

Locate the patch's explicit paths with `client:locate`, collect them with
`client:draft`, then write an acquisition lock from the observed `bytes`,
`sha256`, `bundle_url`, `uncompressed_offset` and `uncompressed_length`
([index](RePoE/docs/client/client-index.md),
[draft](RePoE/docs/client/client-source-draft.md)). Replay each source strictly
with `client:source -- acquire`, then derive the export lock:

```sh
mise run client:export-lock -- --source-lock <acquisition-lock> \
  --expected-source-lock-sha256 <sha256> --out <export-lock>
```

Use the acquisition lock for `facts:candidate` and the export lock for
`tables:candidate`, `descriptions:candidate` and `RePoE.native.item_inheritance`.
Collect all seven side inputs with the facts in the same acquisition: the
four supplements' tables (`stat-descriptions`, `passive-tree`, `minions`,
`spectres`), both descriptions and item inheritance. Export crafting from
those facts with `RePoE.native.crafting_facts`
([native docs](RePoE/docs/README.md)), then lay out one directory per input
package. Copy the new `facts:candidate` output into `ordinary/facts/` and
declare `facts.root: "facts"` as described above. `source:rebind` is only
for the historical 0.5.5.5 source-lock correction envelope, not a step for
a new patch. A job option `ordinary:<path>` names a path in this layout:

| Path | Content | Produced by |
| --- | --- | --- |
| `facts/` | One complete candidate output directory, including `manifest.json` and `source-lock.json`; `facts.root` names it | `facts:candidate`, `facts:validate` |
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
([crafting facts](RePoE/docs/native/native_crafting_facts.md)). Export it
from the same ordinary facts root: its `input_package.manifest` pins that
root's manifest. Package the directory directly with
`--package crafting=<crafting export>`; keep its root manifest.

### 2. Publish the inputs

`mise run release:inputs -- --patch <new> --package ordinary=<dir> …` (dry
run), then on a clean master commit `-- --yes`. Paste the printed `lock.json`
entries into the new declaration's `packages`.

### 3. Declare the package

Copy `release/0.5.5.5-3/` to `release/<new>/` and change what names the patch,
and only that. It is `release/0.5.5.5-2/` plus the `gem-descriptions` job
(`overlay/gem_descriptions.json`). In the new declaration `previous` is
`game/0.5.5.5-3`:

| Occurrence | In `release/<new>/` |
| --- | --- |
| `target.game_patch` in the three files | `<new>` |
| Job outputs and frozen keys `data/0.5.5.5/…`, the `snapshot-manifest` `member` | `data/<new>/…` |
| `policy:<domain>/0.5.5.5-*.json` | New `policy:<domain>/<new>-*.json` files whose `version` / `target.game_patch` is `<new>` (the adapter checks them against the facts). Never edit the 0.5.5.5 policies: `release/0.5.5.5-2/`, `release/0.5.5.5-3/` and the adapter tests pin their bytes |
| Policy templates (`rebind`, `expect`) | New `expect` pins of the rebound policies |
| `packages.ordinary`, `packages.crafting`, `facts` (including `identities`) | The new input package entries; `facts.root` names the fresh candidate directory, with `original` and `rebound` both pinned to its manifest |
| `packages.previous` | `game/0.5.5.5-3` (the `reference` and the frozen `source`) |
| `packages.legacy` and its `legacy:data/0.5.5.4.2/…` options, `historical-attributes-v1.json` | Unchanged: the 0.5.5.4.2 inputs (codec sources, historical trees) stay |
| The snapshot template `previous:data/0.5.5.5/manifest.json` | Keep the source package's path and version; the build validates it against that package and writes `<new>` |
| `contract_version: "adapter"` and the `omit` of `i18n/`/`languages` | Unchanged |
| `handoff/*` paths and tags in `release/0.5.5.5-2/` and `release/0.5.5.5-3/` | Unchanged: they are historical and stay readable |

Keep `release/0.5.5.5-2/` and `release/0.5.5.5-3/`: a superseded declaration is
never deleted. Which declarations CI rebuilds is set in [AGENTS.md](AGENTS.md#ci).

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
with its display texts, gem descriptions and monster names built from
`game/<new>-<n>` and the `inputs/<new>-<k>` client-text Releases
([its RELEASING.md](https://github.com/ackness/poe2-zh-cn-stats/blob/main/RELEASING.md)).
Then in `ackness/pobr`:

```sh
mise run data:bump ackness/repoe game/<new>-1 ackness/poe2-zh-cn-stats locale/<new>-<m>
```

A game-only package of an already pinned patch is bumped alone
(`mise run data:bump ackness/repoe game/<patch>-<n>`). `data:bump` verifies the
Releases, rewrites PoBR's data lock and prepares the data; it does not commit,
push or open a PR. The PoBR maintainer does that, as described in PoBR's
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

Tags are never moved or deleted; see
[AGENTS.md](AGENTS.md#never-move-or-rewrite).
