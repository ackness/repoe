# Fork history and clone size

On 2026-11-03 this fork's history was cut at upstream snapshot
`aa9fa7c394b18a7a89f913f86703112b3f9d20f1`. Its complete source tree is retained as
the new root, `9a843c6449053b8f51e9beea7fa371eee6f685f5`. Subsequent development
and publication commits keep their trees, authors, dates, messages and merge
structure. Their parent IDs change; signatures bound to rewritten ancestry are
removed rather than presented as valid signatures of the new commits.

## Why the old clone was large

The upstream repository used to commit automated game-data exports, including
large JSON files in multiple languages. Removing those files from the current
tree did not remove their older versions from Git history.

Before the cut, a full clone had a 2.17 GiB Git object pack, while its checked-out
files occupied about 8.8 MiB. Objects under the historical `RePoE/data/` path
accounted for approximately 2,111 MiB of packed object bytes. These were old
exports, rather than a requirement of the current source checkout.

## Commit and artifact migration

[`publication/history-rewrite-20261103.json`](../../publication/history-rewrite-20261103.json)
maps retained original commits to their new IDs. For any retained historical
commit `old`, `commits[old]` locates a commit with exactly the same Git tree.
The file also records the old and new annotated tag objects and their targets.

Four artifact tags inherited the pre-fork history and were moved once as part
of this explicit migration:

- `handoff/mac-fk-targets-20261101` (since retired; no live lock names it)
- `handoff/native-crafting-20261101`
- `handoff/rollback-0.5.5.4.2-20261101` (since retired with the 0.5.5.4.2
  rollback)
- `handoff/windows-sc-20261101`

Their files, archive bytes, SHA-256 values and manifest contents are unchanged.
The six other artifact tags already had independent histories and retain their
original targets. Future publications continue to use immutable artifact tags.

Publication sequence 2 updates the four affected RePoE role locations and the
translation owner's display-source binding. PoBR's current and rollback locks,
publication references and version-observer pin use the migrated locations.
The game runtime and release identities remain unchanged.

Old publication declarations, source locks, manifests and frozen decoder
receipts preserve the producer IDs recorded when they were created. Those IDs
are historical evidence, not current retrieval locations. To inspect the same
producer source after this cut, resolve its original ID through the commit map;
the source bytes and recorded file digests are identical. New publication
descriptors point directly at retrievable new commits.

## Updating an existing checkout

A fresh clone avoids retaining old branches, reflogs or tags that still keep
the removed history reachable:

```sh
git clone https://github.com/ackness/repoe.git
```

Preserve any local work before replacing an older checkout. A normal fetch
does not delete its old objects or automatically accept the four moved tags.
Consumers must update the pinned commit together with its tag and publication
descriptor; changing a tag name alone is insufficient.

For source-only work, a partial clone can defer blobs until needed:

```sh
git clone --filter=blob:none https://github.com/ackness/repoe.git
```

Offline publication checks may require additional pinned artifact objects.
Clone size and GitHub's reported storage can differ: server-side retention of
pull-request refs and unreachable objects is managed by GitHub.
