# Forward release builds

The [content comparison report](content-diff.md) owns cross-patch byte
classification, identity exclusions, stable entity/reference comparison and
bounded receipt evidence. It is available in strict and forward builds.

## Forward mode

To collect content gaps across a new patch, add `"adapter_mode": "forward"`
at the top level of its `domains.json`. Omit the field for a strict build;
any value other than `"forward"` is a configuration error. The declaration
chooses the mode, so the same declaration always selects the same behavior.

Forward builds pass `--mode forward` to every ordinary adapter job. Strict
builds keep their existing command lines, receipts and package bytes.
The adapter's [coverage format](../../../tools/pobr-data-adapter/docs/ordinary-coverage.md)
defines the issue fields and four actions.

## Jobs and failures

A forward build attempts every job whose dependencies succeeded. Dependencies
are `job:<id>:<output>` references, including nested policy inputs,
`special-derived`'s `tree`, and `gem-descriptions`' `gem_effects` and
`granted_effects`. If a dependency failed or was skipped, the job is skipped
too. Independent jobs continue. The snapshot manifest depends on all the
member-producing jobs and runs after them and the frozen members.

A failed job's outputs are never made available to dependants, even if its
producer wrote files before validation failed. Its logs and files remain
under `work/` for diagnosis.

Forward receipts record each job's declared `kind` and
`status`: `succeeded`, `failed` with `error`, or `skipped` with the
unavailable `dependencies`. Adapter jobs also record their declared `domain`,
including on failure and skip; the job ID does not identify its domain.
If any job fails,
the build writes `receipt.json`, prints all failures, skips and collected
issues in one report, and exits 1 before writing the zip or `package.json`.
Such a receipt describes an incomplete build and has no `package` pin.
Configuration errors and invalid pinned input packages still stop the build
before jobs start.

## Coverage

Only forward builds add a top-level `coverage` object to `receipt.json`:
its `format` is `pobr-build-coverage/v1`.

`jobs` copies `counts` and `issues` from each available adapter receipt's
`conversion.coverage`; jobs without adapter coverage have no entry.
`totals` sums all four actions across those jobs. `open_tree_issues` counts
issues whose domain is `passive-tree` and whose action is `quarantined` or
`emitted-with-gap`. Multiple issues for the same entity each count.
`retained-legacy` and `listed` do not contribute.

Both successful and failed builds print counts by job and issue kind and
every issue with its observed values. The report derives open tree issue
counts and distinct issue-entity counts from those records, rather than
trusting the summary. An entity may be a node ID, table or ascendancy: the
aggregate does not count individual nodes. Coverage issues alone do not
fail `release:build`. A strict receipt has no `coverage` key.

## D40 publication refusal

`release:publish` refuses any staged receipt with an open tree issue or a
failed/skipped passive-tree adapter or special-derived job. `listed` and
`retained-legacy` tree issues do not block, and non-tree issues add no
publication restriction. A failed unrelated job still prevents a build zip
under the producer-failure rule above.

The gate reads actual issue records and structured job kind/domain/status.
A stale or forged zero `open_tree_issues` summary cannot override them.
Missing coverage on a receipt that retains forward job metadata, missing
adapter coverage/status/domain, and malformed forward
evidence refuse with a diagnostic. Historical strict and native export
receipts without forward evidence keep their existing checks.

The dry-run plan shows the refusal while retaining local staging for review.
The central staged-receipt check runs again immediately before publication
commands. `--allow-different`, `--reuse`, a matching `expect` pin, resumed
tags/drafts and an existing matching Release cannot bypass D40. The existing
rehearsal, dirty producer and provenance checks remain in force. Forward tree
output with open issues is local policy drafting material.

## Drafting passive-tree policies

Run `mise run release:policy-draft -- --receipt <build-directory>/receipt.json`
to write `passive-tree.draft.json` and `summary.json` under
`.cache/release/<build id>/policy-draft/`, where the build ID is the receipt's
directory name. The command prints the same JSON summary, with issue counts
by kind and entry counts by type. `drafted` counts issues handled by draft
entries, including multiple issues merged into one entry. The input issue
count equals `drafted` plus the `blocked` and `unhandled` counts.
`--out <dir>` selects another destination;
paths inside the repository must be under `.cache/`, and neither output file
may already exist.

The emitter reads only the build receipt's `coverage.jobs` issues for
`passive-tree`. It copies observed hashes verbatim into `placement_rebase`,
`ascendancy_frames`, `compatibility_bindings` and `context_columns` entries.
Changed `excluded-definition` issues become `excluded` updates; `stale-exclusion`
issues become `excluded_removals` keyed by node ID, identifying entries to remove
during review. Other issue kinds remain verbatim in `unhandled`. Quarantined
issues remain verbatim in `blocked`, with the note
"needs a newer official reference or an exclusion".

Every drafted entry has `review: "unreviewed"` and `reason: ""`. Reviewers must
choose new ascendancy offsets (`dx` and `dy` are null), column neutral or
constant values (also null), and verify candidate text and exclusion decisions.
Nonempty candidate lines have `origin: "official-reference"`; missing or empty
lines have `origin: "manual"`. These files are review material, not accepted
policies. The emitter never opens facts, tree files or policies.

Review drafts into new policies, with `review: "reviewed"` and nonblank
reasons, and rerun the build to confirm the closing decisions. The
[passive-tree policy specification](../../../tools/pobr-data-adapter/docs/ordinary-passive-tree.md)
owns the geometry, text and context-column entry contracts. In particular,
pin the old PassiveSkills table explicitly as a package/member input and
authorize its digest in `context_baseline`; preserve that old evidence while
replacing target facts. Baseline authentication alone grants no normalization
approval: `context_columns` requires a separate reviewed decision.

Review data-axis policies and declaration pins separately from code changes.
The new-patch procedure in [RELEASING.md](../../../RELEASING.md#a-new-game-patch)
owns the provisional 1.0 `0_5` label agreement and the later coupled refresh of
policy/native packets, carried passive jewels and PoBR's compatibility table.
This workflow does not create a 1.0 declaration or a consumer table entry.
