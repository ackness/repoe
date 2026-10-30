# Fixed schema input

`poe2.json` is the PoE2-only output generated from the dat-schema commit in
`source.json`. `SHA256SUMS` binds its exact bytes; `mise run schema:check` verifies
them without changing the installed PyPoE specification.
The upstream MIT notice is preserved in `LICENSE.dat-schema`.

The source generator includes `createdAt`; regenerating the same commit later
does not produce identical bytes. This repository deliberately retains one fixed
output instead of fetching the mutable `latest` release during export.

To update it, check out the intended dat-schema commit, install its package lock
and generate the schema. Copy the output, update its source receipt and checksum,
review the table/column changes, then run `mise run schema:check` and
`mise run check`. Do not change the checksum merely to accept damaged inputs.

This is a build-tool schema, not a client data snapshot. The newest schema is not
automatically valid for an older client patch. Import success only verifies this
tooling step; real table decoding, source receipts and patch-specific validation
are required before publishing game data. The prepared input does not replace
the default installed specification.

## Native candidates

Run `mise run setup`, then:

```sh
mise run schema:candidate -- --out .cache/schema/example
```

The destination must be new and beneath this checkout's `.cache/`. Generation
uses the fixed upstream converter **without legacy adaptation**: all 1,286 native
tables pass strict specification validation, with physical column counts checked
and no compatibility virtual fields. It never reads or overwrites the installed
legacy data specification, and performs no network fetch.

The receipt records schema/source bytes, the PyPoE Git pin and installed Python
source fingerprints, producer/`uv.lock` fingerprints, Python version and validation
counts. Repeated generation with these same inputs is byte-identical across the
tested independent processes. Changing these inputs requires a new candidate;
an existing candidate is rejected rather than silently refreshed. The receipt
deliberately leaves the client patch unknown and publication blocked.

`repoe ... --poe2 --file ... --outdir ... --schema-candidate ...` verifies the
receipt and payload against regenerated trusted converter output, then supplies
the resulting object to the actual relational reader. It never executes a supplied
candidate's Python file. This mode requires explicit client and output arguments,
strict validation and errors on missing runtime relations. Without the flag, the
upstream reader path remains available. See the root README for an example.

## Why not overwrite PyPoE's default specification?

The fixed upstream importer can download a mutable `latest` asset if no local file
is supplied. Its `-a poe2` adaptation reads the installed specification and normally
overwrites that same file. Its `MapPurchaseCosts` virtual fields use an identity-hashed
set, so `PYTHONHASHSEED` alone cannot stabilize their order. The pinned legacy
specification and its adapted output also have invalid compatibility views (25 views
with 50 missing physical-field references across 14 tables in the audited pin).
Those failures are not 50 missing raw columns or proven current PoBR calculation bugs.

Native generation avoids that adaptation and its implicit baseline entirely. Tests
cover real frozen-schema replay, synthetic binary decoding through the reader,
tampering, input changes, failed output completion, invalid foreign keys and passive
stat fidelity. Synthetic decoding and structural validity do not certify decoding
of an actual client build, PSG geometry, every exporter module or game semantics.
Those remain separate adoption gates; no production game data is switched here.
