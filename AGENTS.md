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
| `ackness/repoe` (here) | Client acquisition and decoding, native facts, `tools/pobr-data-adapter` and its policies, the `game/<patch>-<n>` and `inputs/<patch>-<n>` Releases |
| [`ackness/poe2-zh-cn-stats`](https://github.com/ackness/poe2-zh-cn-stats) | Term templates, translations and the `locale/<patch>-<n>` Releases |
| [`ackness/pobr`](https://github.com/ackness/pobr) | Data contracts (`contract/*` tags), stat meaning, the engine and app; pins both owners' Releases in `pipeline/data.lock.json` |

## Layout

The fork's code is grouped into three packages by role.

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
| `release/` (directory names and files) | Receipts, Releases and tags cite each declaration, so a superseded one stays as a record and is never deleted (which ones CI rebuilds: [CI](#ci)). The fresh root manifest embeds the declaration path (`release/0.5.5.5-3/frozen-inputs.json`), so moving it changes the zip |
| `schema/` | `SHA256SUMS` and the native exporters pin `poe2.json`; update it only by the procedure in [schema/README.md](schema/README.md) |
| Adapter policies (`tools/pobr-data-adapter/policies/**`), including the `/Users/claw/...` strings in the passive-tree policies | Declarations, receipts and adapter tests pin their bytes; those strings are recorded provenance, not configuration. A change is a new policy file |
| Historical producer identities: the producer map in `src/facts/trust.rs`, `tests/fixtures/ordinary-facts/*-producer*.json`, `tests/fixtures/native-facts/player-context-manifest.json`, `HISTORICAL_PRODUCERS` in `RePoE/release/crafting_catalog.py` | Keyed by the `RePoE/native_*.py` paths of the commits that sealed the pinned packages. They are a frozen record of what the 0.5.5.5 packages were sealed with; no new identity is added beside them ([fixed producer identities](tools/pobr-data-adapter/tests/fixtures/ordinary-facts/README.md#fixed-producer-identities)) |
| `sources/sources.lock.json`, `sources/retained-buff-source-reconciliation.v1.json` | Copied verbatim from PoBR with recorded pins ([sources/README.md](sources/README.md)); exporters and tests read them |
| `RePoE/native/locale_probe.py` | Transfer receipts pin its SHA-256 (`decoder.source_sha256`) |
| `RePoE/client/china-text-request.json` | The published `inputs/0.5.5.5-1` capture receipt records its SHA-256 (`31a997fa…`, 2095 bytes) and the package carries a copy; a request for another capture is a new file |
| `RePoE/docs/history-rewrite-20261103.json` | The commit map of the one-time history rewrite ([history](RePoE/docs/history.md)) |
| `RePoE/model/` contents | Generated: `mise run models:generate -- [schema paths]`, never edited by hand |

Tags are never moved or deleted: `handoff/*`, `game/*` and `inputs/*` here
(PoBR locks and `inputs.lock.json` read pinned commits and assets through
them) and PoBR's `contract/*` (the adapter's `Cargo.toml` pins one). A moved
tag silently changes what a lock resolves to; a mistake is fixed by a new tag
or a new declaration, never by rewriting the old one.

### Producer identity and re-validation

A facts package keeps the producer identity it was sealed with, so
re-validating a historical package runs at its producer commit, in its own
worktree. A new export is identified by its commit instead: its manifest
carries the constant `producer_receipt`, and the exporter writes
`<out>.export-receipt.json` beside the candidate directory with the commit,
whether the exporters' code or environment was dirty, and whether the run was
a `--rehearsal` ([export receipt](RePoE/docs/native/native_facts.md#export-receipt)).
An exporter refuses a dirty checkout without `--rehearsal`; `release:inputs`
and `release:build` require the field and the receipt, and a rehearsal or
dirty export is never built or published (the crafting export is not receipted
yet). The adapter accepts receipted manifests without comparing the historical
producer hashes; its target, schema, decoder and payload checks still apply.
The rule and the procedure are in
[native facts](RePoE/docs/native/native_facts.md#producer-identity-and-re-validation);
the new-patch work is in [RELEASING.md](RELEASING.md#a-new-game-patch).

## Commands

Run everything from the repository root through mise.

```sh
mise trust && mise install --locked
mise bootstrap --only packages            # C compiler for source-only dependencies
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
`descriptions:candidate`, `client:source`, …; `source:rebind` is only for the
historical 0.5.5.5 envelope). Nothing tags,
pushes or creates a Release without `--yes`.

## Common pitfalls

Symptom, cause, fix.

- `gh` shows or edits the wrong PR or Release: this is a fork and `gh` can resolve
  to the upstream repository (`gh repo view` prints `repoe-fork/repoe`). Pass
  `-R ackness/repoe` on every `gh` command.
- `uv run` in a new worktree tries to create `.venv` and fails offline on
  uncached wheels (for example NumPy for CPython 3.15): the worktree has no
  environment. Run `mise run setup` with network, or reuse an existing
  environment read-only with `UV_NO_SYNC=1 UV_PROJECT_ENVIRONMENT=<path to .venv>`.
- Every `mise` call fails with `Read-only file system`: mise records trust of a
  new worktree's `mise.toml` under `~/.local/state/mise/trusted-configs`, which is
  read-only in some sandboxes. Set `MISE_STATE_DIR` and `MISE_CACHE_DIR` to
  writable temporary directories.
- `PermissionError: [Errno 1] Operation not permitted` in `tests.client.test_version`
  or in `tests.release` tests that start a loopback HTTP server, and
  `tests/test_packaging.py` failing because `uv build --offline` cannot get `uv_build`:
  the environment forbids sockets or network. These are not regressions;
  report those tests as not run.
- A request or lock file looks free to edit but a published receipt pins its
  bytes (see the [never-move table](#never-move-or-rewrite)). Before editing one,
  check whether a published receipt or package pins it; if so, add a new file.
- An exporter (`facts:candidate`, `tables:candidate`, …) exits 1 with
  `Refusing to export from a dirty checkout`: a file under the exporters' code
  or environment is uncommitted (the message lists the paths). Commit it, or
  pass `--rehearsal` for an export that `release:build` and the publish
  commands refuse. Tests that export in-process call `checkout()` from
  `tests/client/test_export_receipt.py`; subprocess runs pass `--rehearsal`.
- Never move or delete a tag, and never rewrite anything in the
  [never-move table](#never-move-or-rewrite); fix mistakes with a new tag, file
  or declaration.

## Validation by change type

| Change | Run |
| --- | --- |
| Documentation only | Check relative links and anchors; no tests |
| Python in `RePoE/client/`, `RePoE/native/`, `RePoE/parser/` | `mise run check`; `RePoE/__init__.py`, `client/__init__.py`, `client/export_receipt.py`, `client/source_io.py` and `client/source_rebinding.py` are release-build inputs, so also the release row below |
| `RePoE/release/`, `release/`, the adapter or its policies | `mise run check`, `mise run adapter:check`, `mise run adapter:keystones`, and `release:build -- --config release/<dir> --fetch --check` for every declaration (CI does this too) |
| Adapter comments or docs inside `src/` | As above: `implementation_sha256` includes the sources, so the receipt's `implementation_revision` moves while the zip must not; `implementation_revision_covers_every_production_source` requires every non-test Rust source to be hashed or explicitly excluded with a reason |
| `schema/` | `mise run schema:check`, then the procedure in [schema/README.md](schema/README.md) |
| `RePoE/schema/*.json` | `mise run models:generate -- <paths>`, then `mise run check` |
| `mise.toml`, workflows, `build.CODE` | `mise run check` (`test_release_workflow_paths_cover_the_build_code` in `tests/release/test_build.py` guards the `release-build.yml` paths list against `build.CODE`) |

Say what you ran and what you did not; never present a review as a passing
test. Real-data steps (`facts:validate` on a client export, Windows-only
tests) are not run by CI; state when they were skipped.

## CI

| Workflow | Job | Runs |
| --- | --- | --- |
| `verify.yml` (every PR and master push) | `verify` | `mise run check` |
| | `adapter` | `mise run adapter:check`, `mise run adapter:keystones` |
| `release-build.yml` (only when a path the build reads changes; the workflow's `paths` list is guarded by `tests/release/test_build.py`, which compares it with `build.CODE`) | `release` | `release:build -- --config release/<dir> --fetch --check` for every declaration directory today (see below) |

Policy: CI must rebuild only the newest published declaration (normally the
one PoBR's `pipeline/data.lock.json` pins) and any unpublished ones; superseded declarations,
their Releases and tags stay as records and are not rebuilt forever. Until the
workflow is narrowed it still loops over every `release/*/`. Until the first 1.0
game package is published, `release/0.5.5.5-3` keeps reproducing byte for byte
as the regression guard.

`release-build.yml` does not run for changes outside its `paths`, so edits to
`RePoE/docs/` or root documents skip it; documents under `release/` or
`tools/pobr-data-adapter/` (for example the adapter's `docs/`) still trigger it.

## Commits and pull requests

- One branch and worktree per change. Never `git stash`: worktrees share it.
- Subjects `type(scope): imperative lowercase summary` (`fix(release): …`,
  `docs: …`, `refactor(native): …`); the body says why.
- Moves first, then edits, in separate commits, so review sees the renames.
- PRs state the problem, the result, what was run and what was not.
- Merge with a merge commit, once the branch is up to date with master and CI
  passed on its head. Releases and tags are published from master only
  ([RELEASING.md](RELEASING.md)).
- Code, comments and documentation are in English (the Chinese gem-quality
  policy notes under `tools/pobr-data-adapter/policies/gem-quality/` are an
  older exception); `README.zh-CN.md` mirrors
  `README.md` in Simplified Chinese, with the language switcher under both
  titles.
