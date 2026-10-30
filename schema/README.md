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
are required before publishing game data. The prepared input is not activated.

## Activation constraints

The fixed PyPoE importer accepts `--schema-file`, but omitting it downloads a
mutable `latest` asset. Its `-a poe2` compatibility adaptation also reads the
installed specification; the default output overwrites that same file. This
baseline must be an explicit verified input in a future bootstrap entry point.

`generation/virtual_fields.py` uses a set of `Zip` objects for `MapPurchaseCosts`,
which can change generated order across processes. Pinning the schema or setting
`PYTHONHASHSEED` does not resolve identity hashing. Ordering must be deterministic
before claiming byte-identical replay.

The pinned baseline and experimental generated specification both fail general
validation at `AchievementItemRewards.dat` and have missing virtual-field targets.
These inherited failures need classification against the adopted domain scope;
they are not proven errors in current PoBR calculations. Do not silence validation
or claim the whole specification has passed because an import command succeeded.

Future activation must generate into staging, preserve the previous specification
on failure, verify actual reader consumption, and record schema, pristine baseline,
dependency and resulting specification identities. An external `--output` alone
does not make RePoE use that file. No activation task is provided in this batch.
