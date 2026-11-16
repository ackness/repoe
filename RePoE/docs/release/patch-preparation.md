# Local patch preparation

`mise run release:prepare-patch` prepares local input candidates from one
externally pinned recipe: preflight inputs, derive an export lock, acquire
selected sources, export and validate candidates, assemble input packages and
stage them for review. This is the first local slice of candidate orchestration,
not the complete new-patch workflow. It stops before input publication and
creates no formal release declaration.

## Before writing the recipe

Perform [version observation](../client/client-version.md) and
[resource discovery](../client/client-index.md) separately. For a
non-rehearsal run, complete [source review](../client/client-source-draft.md)
before writing the recipe: review the exact target, resource paths, raw byte
pins, bundle locations, decoder and schema. The runner does not discover
sources, select a latest patch or carry out that review.

Before creating any output, a non-rehearsal run requires every selected
source's `acquisition.status` to be `reviewed-source-input`.
`unreviewed-acquisition-draft` is allowed only with `--rehearsal`; the runner
never promotes it automatically. Checking the recorded status does not
certify that source review occurred. Every selected source must match the
recipe's `game`, `realm` and `game_patch`.
The facts source must contain exactly the `items-actors-bc` profile's DAT
tables and default `Metadata/PassiveSkillGraph.psg`, not a superset containing
all supplements. See [the profile contract](../native/native_items_actors.md).

Use one writer in its own worktree. Prepare the existing exporter and decoder
environments first; the recipe is not a dependency-installation or shell-step
interface. Keep downloaded raw data separate from scripts and package roots.
Leave published, tagged or formally adopted inputs, recipes, declarations,
policies and receipts byte-identical; use new files for new evidence. Never
move or delete immutable tags to make a candidate fit.

## Invocation

Run from the repository root:

```sh
mise run release:prepare-patch -- \
  --recipe /absolute/path/to/recipe.json \
  --expected-recipe-sha256 <externally-recorded-recipe-sha256> \
  --out .cache/patch-preparation/<new-run> \
  --range-cache .cache/client-sources/cache
```

| Option | Contract |
| --- | --- |
| `--recipe`, `--expected-recipe-sha256` | Required recipe and externally supplied SHA-256 of its exact bytes |
| `--out` | A new run directory, strictly below this worktree's `.cache/`; not `.cache/` itself, an external path or a shared target |
| `--mode offline\|online` | Defaults to `offline`; offline never falls back to downloading missing ranges |
| `--network-budget-bytes <n>` | Online requires an explicit total budget across all selected sources, at most 134217728 bytes; it does not reset for each source |
| `--range-cache <dir>` | Optional existing bounded compressed-range cache strictly below this worktree's `.cache/`; not `.cache/` itself, an external path or a raw-data/script directory |
| `--resume` | Resume with identical recipe, settings, producer and per-source installed decoder identities |
| `--rehearsal` | Allow unreviewed draft sources; preserve rehearsal and dirty identity in export receipts, blocking publication |

For network acquisition, explicitly add `--mode online
--network-budget-bytes <n>`. Existing resource, range, cache, selected-raw and
decoder limits still apply; this option cannot raise them. The
[fixed-source acquisition contract](../client/client-sources.md) describes
those limits and cache verification. No concurrent writer may share the run
directory or its outputs.

Without `--rehearsal`, dirty exporter code or environment refuses before any
acquisition. Rehearsal never strips or upgrades that identity. A later clean
export is a new run, not a promotion of a rehearsal receipt.

## Recipe v1

The top-level fields are exactly `schema`, `target`, `source_lock`, `decoder`,
`exports` and `retained`. Paths in `source_lock.path`, `decoder.lock.path` and
`retained[].path` resolve relative to the recipe file unless absolute.
`decoder.python` must be an absolute executable path. File pins are supplied
by the caller and checked before use: `bytes` is a JSON integer byte count,
and `sha256` is the file's 64-character lowercase SHA-256. The runner does not
choose or invent pins.

This is a template, not executable JSON: replace every angle-bracket token
with reviewed values, leaving byte counts as numbers. Source keys are
illustrative and must exist in the pinned acquisition lock. The export list
illustrates each supported kind, not a complete release input inventory;
include every supplement and reference required by the intended consumers.

```text
{
  "schema": "repoe-prepare-patch/v1",
  "target": {"game": "poe2", "realm": "international", "game_patch": "<new>"},
  "source_lock": {
    "path": "acquisition.lock.json",
    "bytes": <source-lock-bytes>,
    "sha256": "<source-lock-sha256>"
  },
  "decoder": {
    "python": "/absolute/path/to/decoder/.venv/bin/python",
    "lock": {
      "path": "/absolute/path/to/decoder/uv.lock",
      "bytes": <decoder-lock-bytes>,
      "sha256": "<decoder-lock-sha256>"
    }
  },
  "exports": [
    {"id": "native-facts", "kind": "facts", "source": "target-facts", "package": "ordinary", "destination": "facts", "profile": "items-actors-bc"},
    {"id": "tree-tables", "kind": "tables", "source": "target-tree-tables", "package": "ordinary", "destination": "passive-tree/supplement", "language": "English"},
    {"id": "tree-descriptions", "kind": "descriptions", "source": "target-tree-descriptions", "package": "ordinary", "destination": "passive-tree/tree-descriptions"},
    {"id": "item-inheritance", "kind": "item-inheritance", "source": "target-item-inheritance", "package": "ordinary", "destination": "base-items/supplement"},
    {"id": "crafting-tables", "kind": "crafting", "facts": "native-facts", "package": "crafting", "destination": "."}
  ],
  "retained": [
    {"path": "retained/stat_set_labels.json", "package": "ordinary", "destination": "skill-overrides/branch-codec/stat_set_labels.json", "bytes": <retained-file-bytes>, "sha256": "<retained-file-sha256>"}
  ]
}
```

| Export kind | Required fields and restrictions |
| --- | --- |
| `facts` | Exactly one: `id`, `source`, `package`, `destination`, `profile: "items-actors-bc"` |
| `tables` | `id`, `source`, `package`, `destination`, `language`; language is exactly `English`, `Simplified Chinese` or `Traditional Chinese` |
| `descriptions`, `item-inheritance` | `id`, `source`, `package`, `destination` |
| `crafting` | Exactly one, after facts: `id`, `facts` naming the facts export's ID, `package: "crafting"`, `destination: "."`; no separate source |

Each export also has its `kind`. Use distinct recipe-chosen IDs; none is a
fixed literal. The facts package and destination are also recipe choices;
`ordinary` and `facts` above are examples. Crafting consumes the preceding
facts output by its ID, while its package `crafting` and root `.` are fixed.
The source set is derived from the exports' `source` keys, not a second
source list in the recipe. Only selected sources are acquired and checked
against the recipe's target, required export profiles and source-review gate.
Acquired bytes are verified against the acquisition lock; supplemental exports
use the derived export lock.

Destinations are package-relative. Export roots and their sibling
`<root>.export-receipt.json` paths must not overlap other destinations;
retained files must not overwrite either. The crafting root and its sibling
receipt stay together under the existing input-packaging rules. `retained`
may be empty; otherwise each entry pins one explicit JSON file for any
package except `crafting` or `previous`, with exactly `path`, `package`,
`destination`, `bytes` and `sha256`. Old codec/reference files are examples,
not the only allowed JSON inputs. There is no directory copy or automatic
copying of raw resources, scripts or old target facts.

The runner calls the fixed `create_candidate` functions in
`RePoE.native.facts`, `RePoE.native.tables`, `RePoE.native.descriptions`,
`RePoE.native.item_inheritance` and `RePoE.native.crafting_facts` serially.
Recipes cannot supply arbitrary commands, shell steps or alternate exporters.

## Execution order

The order is fixed: pin/preflight → export-lock → acquire selected → native
exports/validate → assemble → stage.

Export-lock derivation runs before the source-acquisition loop and preserves
the standalone [`client:export-lock`](../client/client-sources.md#export-locks)
whole-ledger validation. Every entry in the acquisition lock, including
unselected historical entries, must satisfy the converter's structural
acquisition requirements, including raw byte pins and acquisition locations.
A malformed unrelated entry fails before any source acquisition; selecting
fewer sources does not bypass that validation. Structural validation does not
apply the recipe's target, profile or review gate to unselected sources, nor
does it acquire them.

Native exports and validation follow acquisition. Only then are package roots
assembled and passed to tagless input staging. Published or pinned historical
ledgers remain immutable; use a new valid lock rather than rewriting one to
pass conversion.

## Resume and retained evidence

For a retry, repeat the original command with `--resume`, retaining its
`--out` and every original setting, including mode, budget, cache and rehearsal
choice. Recipe bytes, producer identity and every selected source's installed
decoder identity must also be identical. A changed recipe, setting, producer
or decoder requires a new run directory.

The run intent pins the `identity_sha256` from each selected source's
`RePoE.client.sources.ExternalDecoder` receipt. It fingerprints the installed
native decompressor module, distribution `METADATA`, `WHEEL` and `RECORD`,
and Python identity; an unchanged Python path and `uv.lock` alone are
insufficient. These measured identities belong to the run intent, not extra
recipe fields. The runner rechecks them between steps, before acquisition
and on resume. A mismatch refuses acquisition or resume rather than replacing
the recorded identity.

Network accounting persists across attempts. A successful acquisition charges
its reported reserved bytes. If an online acquisition fails or crashes, the
remaining budget is conservatively charged to that attempt. `--resume` keeps
that charge; a new attempt directory does not reset the run's allowance.

Resume verifies every completed output's byte pins before reuse; tampering
rejects the run instead of silently regenerating trusted evidence. A failed
or incomplete attempt remains intact and retry work uses a new attempt
directory. Do not delete or overwrite earlier attempts to force a resume.
Per-output logs and evidence remain available for diagnosis.

`progress.json` records progress and resumable work. `report.json` records
the local outputs, pins and publication-boundary result. Follow their output
paths rather than copying the entire run directory into an input package.

## The publication boundary

Local packaging calls `RePoE.release.inputs.stage(..., tag=None)`. Its stage
contains package ZIPs and `assets/SHA256SUMS`, deliberately no `lock.json`
or assigned input tag. No tag, push, GitHub Release or final formal declaration
is created.

| Report status | Meaning |
| --- | --- |
| `awaiting-input-publication` | Local staging reached the publication gate without reported export-receipt issues; publication is still a separate action |
| `blocked-input-publication` | The report lists the exact export-receipt issues, such as rehearsal, dirty identity or an export commit not established on `origin/master` |

Both report `published: false` and `production_ready: false`. Package fields
returned by staging retain their existing meanings, including crafting's
`publication: "published"` field. That field is packaging metadata, not proof
of a published Release; the preparation report keeps the pending publication
boundary explicit. Neither report status certifies source review, full
consumer coverage or production readiness.

The remaining gates are manual and already have their own commands:

1. Resolve receipt issues through the normal clean-producer and code-review
   workflow. Use [input publication](../../../RELEASING.md#2-publish-the-inputs)
   with the reported package roots: dry run first, then explicitly authorized
   `release:inputs --yes` from clean master. Verify the real Release, assets
   and lock entries; preparation does not reserve an `inputs/<patch>-<n>` tag.
2. After input publication, run [policy rebinding](policy-rebinding.md) and
   [declaration derivation](declaration-derivation.md) against the real
   `release:inputs` stage. The tagless preparation stage cannot substitute for
   their required `lock.json`. Never fabricate that lock or publication pins.
3. Complete [forward build and policy review](forward-build.md), review the
   changed fields and carried evidence, and pin `expect` from the actual build
   at the normal declaration gate. Preparation does not run these steps,
   approve policies or auto-set declaration pending/publication markers or
   `expect` pins. Existing immutable history stays unchanged.
