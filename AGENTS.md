# Repository guidelines

Rules for people and agent tools changing this repository. Release procedure:
[RELEASING.md](RELEASING.md); documentation index:
[RePoE/docs/README.md](RePoE/docs/README.md). Where this page and the code or
its regression tests disagree, the code and tests win; fix this page.

## Scope

This fork of RePoE exports Path of Exile 2 client facts and publishes the game
package PoBR consumes. It keeps the upstream PoE1/PoE2 exporters working but
adds nothing beyond that purpose: no calculation, no translation, no consumer
features. Of the client languages only English, Simplified Chinese (`zh-CN`)
and Traditional Chinese (`zh-TW`) matter; do not add work for other locales.

## Which repository owns a change

RePoE is the producer in a three-repository split. Ownership and boundaries are
defined once, in PoBR's
[data architecture](https://github.com/ackness/pobr/blob/master/docs/data-architecture.md)
(also [which repository owns a fix](https://github.com/ackness/pobr/blob/master/CONTRIBUTING.md#which-repository-owns-the-fix)):

| Repository | Owns |
| --- | --- |
| `ackness/repoe` (here) | Client acquisition and decoding, native facts, `tools/pobr-data-adapter` and its policies, the `game/<patch>-<n>` Releases |
| [`ackness/poe2-zh-cn-stats`](https://github.com/ackness/poe2-zh-cn-stats) | Term templates, translations, the `locale/<patch>-<n>` Releases and their support display |
| [`ackness/pobr`](https://github.com/ackness/pobr) | Data contracts (`contract/*` tags), stat meaning, the engine and app; pins both owners' Releases in `pipeline/data.lock.json` |

## Layout

Upstream paths stay where upstream has them; the fork's code lives in three
packages by role.

| Path | Origin | Contents |
| --- | --- | --- |
| `RePoE/parser/`, `RePoE/run_parser.py` | upstream | The `repoe` CLI and its PoE1/PoE2 exporters (`parser/poe2/` imports every module in it as an exporter) |
| `RePoE/poe/`, `RePoE/schema/`, `RePoE/model/` | upstream | PyPoE file extensions, the legacy JSON schemas and their generated models |
| `RePoE/docs/*.md` (top level) | upstream | Legacy JSON formats |
| `RePoE/client/` | fork | Patch observation, fixed-source acquisition, drafts, index lookup, source envelopes; reads the endpoint, CDN or archives, decodes nothing |
| `RePoE/native/` | fork | Exporters that decode pinned raw resources into facts candidates |
| `RePoE/release/` | fork | Game-package build, publish and input packaging, and the Python jobs the build runs; reads only pinned packages |
| `RePoE/trade_snapshot.py` | fork | Offline trade-text snapshot reader for `stat_translations` |
| `release/<patch>[-<n>]/` | fork | One pinned declaration per game package |
| `tools/pobr-data-adapter/` | fork | Rust adapter (facts → PoBR runtime JSON), `policies/`, `docs/ordinary-*.md` |
| `schema/`, `sources/` | fork | The pinned dat-schema; the raw-material source ledger |
| `tests/` | both | `tests/<package>/test_<module>.py` for `client/`, `native/`, `release/`, `parser/` |

Put new code in the package of its role, its test under `tests/<package>/` and
its document under `RePoE/docs/<package>/`. The one exception is
`trade_snapshot.py`: upstream `parser/poe2/stat_translations.py` and
`run_parser.py` import it, and inside `parser/poe2/` it would be loaded as an
exporter (pulling in PyPoE), so it stays at the top of `RePoE/`.

## Never move or rewrite

These bytes or paths are pinned by published packages, receipts or consumers.
Changing them breaks a release declaration or a consumer's check, usually far
from the edit.

| What | Why |
| --- | --- |
| `release/` (directory names and files) | Each declaration is a claim CI rebuilds; the fresh root manifest embeds the declaration path (`release/0.5.5.5-2/frozen-inputs.json`), so moving it changes the zip |
| `schema/` | `SHA256SUMS` and the native exporters pin `poe2.json`; update it only by the procedure in [schema/README.md](schema/README.md) |
| Adapter policies (`tools/pobr-data-adapter/policies/**`), including the `/Users/claw/...` strings in the passive-tree policies | Declarations, receipts and adapter tests pin their bytes; those strings are recorded provenance, not configuration. A change is a new policy file |
| Historical producer identities: the producer map in `src/facts/trust.rs`, `tests/fixtures/ordinary-facts/*-producer*.json`, `tests/fixtures/native-facts/player-context-manifest.json`, `PRODUCERS` in `RePoE/release/crafting_catalog.py` | Keyed by the `RePoE/native_*.py` paths of the commits that sealed the pinned packages; a new export adds its identity beside them ([fixed producer identities](tools/pobr-data-adapter/tests/fixtures/ordinary-facts/README.md#fixed-producer-identities)) |
| `sources/sources.lock.json`, `sources/retained-buff-source-reconciliation.v1.json` | Copied verbatim from PoBR with recorded pins ([sources/README.md](sources/README.md)); exporters and tests read them |
| `RePoE/native/locale_probe.py` | Transfer receipts pin its SHA-256 (`decoder.source_sha256`) |
| `RePoE/docs/history-rewrite-20261103.json` | The commit map of the one-time history rewrite ([history](RePoE/docs/history.md)) |
| Upstream paths (`RePoE/parser/`, `RePoE/model/`, `RePoE/schema/`, `RePoE/poe/`, `RePoE/run_parser.py`, the upstream docs) | Keep merges from upstream possible |
| `RePoE/model/` contents | Generated: `mise run models:generate -- [schema paths]`, never edited by hand |

Tags are never moved or deleted: `handoff/*`, `game/*` and `inputs/*` here
(PoBR locks and `inputs.lock.json` read pinned commits and assets through
them) and PoBR's `contract/*` (the adapter's `Cargo.toml` pins one).

### Producer identity and re-validation

A facts package names each producing file by its repository path at export
time. The pinned 0.5.5.5 envelope was produced at `e4140122`, retained as
`ebcfa93be668109e576c80c2bdf2c44b23d523c6`, when the exporters were
`RePoE/native_*.py`. `facts:validate` requires the replayed producer to equal
the package's, so re-validating that envelope (or a package derived from it)
runs at the producer commit, in its own worktree:

```sh
git worktree add ../repoe-ebcfa93 ebcfa93be668109e576c80c2bdf2c44b23d523c6
```

Details: [native facts](RePoE/docs/native/native_facts.md#producer-identity-and-re-validation).
The first export from the current tree must add its identity to the consumers
above ([a new game patch](RELEASING.md#a-new-game-patch)).

## Commands

Run everything from the repository root through mise.

```sh
mise trust && mise install --locked
mise bootstrap --only packages            # compiler, JPEG and zlib headers for Pillow
mise run setup                            # uv sync --locked into .venv
mise run check                            # uv lock, schema:check, lint, test, CLI
mise run test                             # offline regression suite only
mise exec -- python -B -m unittest tests.native.test_facts -v   # one module
mise run adapter:check                    # cargo fmt, clippy, test, engine-deps check
mise run adapter:keystones                # keystone rules of the reference package of the highest declaration
mise run release:build -- --fetch --check # rebuild the highest declaration, compare with expect
mise run release:publish -- --fetch       # dry run: build, check, stage, list refusals
```

`mise tasks` lists the exporter tasks (`facts:candidate`, `tables:candidate`,
`descriptions:candidate`, `client:source`, `source:rebind`, …). Nothing tags,
pushes or creates a Release without `--yes`.

## Validation by change type

| Change | Run |
| --- | --- |
| Documentation only | Check relative links and anchors; no tests |
| Python in `RePoE/client/`, `RePoE/native/`, `RePoE/parser/` | `mise run check`; `RePoE/__init__.py`, `client/__init__.py`, `client/source_io.py` and `client/source_rebinding.py` are release-build inputs, so also the release row below |
| `RePoE/release/`, `release/`, the adapter or its policies | `mise run check`, `mise run adapter:check`, `mise run adapter:keystones`, and `release:build -- --config release/<dir> --fetch --check` for every declaration (CI does this too) |
| Adapter comments or docs inside `src/` | As above: `implementation_sha256` includes the sources, so the receipt's `implementation_revision` moves while the zip must not |
| `schema/` | `mise run schema:check`, then the procedure in [schema/README.md](schema/README.md) |
| `RePoE/schema/*.json` | `mise run models:generate -- <paths>`, then `mise run check` |
| `mise.toml`, workflows, `build.CODE` | `mise run check` (`tests/release/test_build.py` ties the release workflow's paths to the build's imports) |

Say what you ran and what you did not; never present a review as a passing
test. Real-data steps (`facts:validate` on a client export, Windows-only
tests) are not run by CI; state when they were skipped.

## CI

| Workflow | Job | Runs |
| --- | --- | --- |
| `verify.yml` (every PR and master push) | `verify` | `mise run check` |
| | `adapter` | `mise run adapter:check`, `mise run adapter:keystones` |
| `release-build.yml` (only when a path the build reads changes: `RePoE/release/**`, the `RePoE/client` modules it imports, `release/**`, `tools/pobr-data-adapter/**`, mise and toolchain files) | `release` | `release:build -- --config release/<dir> --fetch --check` for every declaration |

## Commits and pull requests

- One branch and worktree per change. Never `git stash`: worktrees share it.
- Subjects `type(scope): imperative lowercase summary` (`fix(release): …`,
  `docs: …`, `refactor(native): …`); the body says why.
- Moves first, then edits, in separate commits, so review sees the renames.
- PRs state the problem, the result, what was run and what was not.
- Merge with a merge commit, once the branch is up to date with master and CI
  passed on its head. Releases and tags are published from master only
  ([RELEASING.md](RELEASING.md)).
- Code, comments and documentation are in English; `README.zh-CN.md` mirrors
  `README.md` in Simplified Chinese, with the language switcher under both
  titles.
