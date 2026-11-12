# Forward release builds

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

Forward receipts record each job's `status`: `succeeded`, `failed` with
`error`, or `skipped` with the unavailable `dependencies`. If any job fails,
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

Both successful and failed builds print counts by job and issue kind,
every issue with its observed values, and open tree issue and entity counts.
Coverage issues alone do not fail `release:build`; publication applies its
own acceptance rules. A strict receipt has no `coverage` key.

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
