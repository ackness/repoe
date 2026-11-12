# Policy identity rebinding

`mise run policy:rebind` creates the policies for a new patch and a new
`domains.json`. Run it after staging the new inputs with `release:inputs`:

```sh
mise run policy:rebind -- --config release/0.5.5.5-3 \
  --staged .cache/release/publish/inputs-poe2-international-<new> \
  --patch <new> --domains-out release/<new>/domains.json
```

`--config` is the old declaration directory. `--staged` contains `lock.json`
and `assets/` as written by `release:inputs`; no network access is attempted.
Old inputs must already be cached or available as pinned local Git blobs.
`--cache` overrides `.cache/release/inputs`; `--policies` overrides
`tools/pobr-data-adapter/policies` for rehearsals. The staged facts package
must contain exactly one fresh `repoe-native-facts/v4` candidate. Historical
old declarations using the original/rebound envelope are supported too.

The command verifies the packages and facts using the release build's readers.
It matches members by their package name and relative path and derives both
manifest and payload identities, including description payloads, supplements,
inheritance and player context. The old facts identities both map to the new
candidate's manifest. Byte pins update their `bytes` and `sha256` together.
Every occurrence of the same old hash must have the same new byte pin, even
across packages and facts identities. Job references cannot establish which
policy field owns identical old bytes; different possible new identities
refuse with `ambiguous-counterpart`. A removed pinned member
refuses with `missing-counterpart`. An unrecognized manifest identity refuses
with `unknown-identity`. Historical hashes outside the input inventory remain
recorded evidence. Packages absent from the stage are carried unchanged from
the old declaration, so stage every refreshed package.

Only complete JSON values change. Prose, historical patch values and policy
rules remain as recorded. Each policy's report lists JSON pointer paths,
old → new values, and matching package members, so reviewers can see which
pinned payloads changed. Templates use the existing release materializer to
expand retained bindings and calculate their new `expect` byte pins.

The new policy names replace the old patch prefix with `--patch`.
The new domains file receives those references, the new target, job output
paths and snapshot-manifest member. Its `previous:` source references retain
their original paths. `inputs.lock.json` and `frozen-inputs.json` still need
the edits in [RELEASING step 3](../../../RELEASING.md#3-declare-the-package),
including replacing the historical `facts.archive` / `facts.handoff` fields
with `facts.root` for a fresh candidate.
Rebinding identities does not certify new content or refresh codec rules.

All destinations are preflighted and created exclusively. Existing policies,
declarations and inputs are never overwritten; a failed preflight creates no
output policy or domains file. Choose fresh paths for another run.
