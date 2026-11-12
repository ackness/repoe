# Ordinary fact conversion fixture

`physical-tables.json` is a small, synthetic five-table input. It is **not** a
client extraction, full source package or runtime artifact.

Column schemas and interval expansion are drawn from F's selected physical
tables (manifest `56e71e00a72c8079d100b64861fc030206b12aaeb5ad655ccb4ab4e6726332d0`,
lock `d7a59a052109f411a62b1398ac844ff31ca8afd6d4158e3488446a19cb75743f`,
international `0.5.5.5`). Unconsumed columns were removed, source-column ordinals
renumbered, and synthetic byte widths set to 1. This is an adapter fixture, not
evidence of a physical DAT layout. Selected full payload hashes:

- Stats: `bef280b241a844972de0020e57c64cc403ac7e44fddf346b1014d17e1372376a`
- Mods: `9d31219bb40ba9c6651fd627905f091e35978beefa84fcd5a8789a45e819df1b`
- ModType: `c022a02f02cdbd0dc9f5199038bcf1d1133b08d4fa5043087250aa300b5ccf14`
- ModFamily: `1ae7eb6173410bbc08d8efa7b499460a05025ff6f90d90dc53fc2400e0893a26`
- Tags: `feaec2df8e2bba282ef479216665f8dc8e9b724b8538445ee6aab2879e61b13e`

Rows were manually adapted to exercise eight bound slots, all-zero and negative
ranges, crossing zero, raw enum zero versus null, nonalphabetic stable IDs,
different ModType group/ModFamily IDs, ordered tags/weights, unknown/empty
families, unnamed stat-bearing mods and a filtered empty shell. A null eighth
stat has nonzero unused endpoints, as also occurs in the real source; the
receipt must retain those endpoints without inventing a stat.

The test harness reuses `../native-facts/items-actors-bc-synthetic.json` for its
reviewed test envelope/lock structure, reseals the selected fixture payloads,
and leaves all unrelated payloads absent. Its trust values authenticate only
these synthetic test bytes; they do not claim new real-source acquisition.

## Base-item fixture

`base-item-tables.json` uses the same F manifest/lock and compact column-metadata
approach for the eleven selected base-item tables. Its hand-adapted rows are
synthetic, with the validation byte width set to 1 and selected source-column
ordinals renumbered. The seven base IDs have shared display names; component
order differs from base order, and ComponentCharges uses stable string IDs.
The fixture covers all existing item DTO fields, placeholder exclusion and a
UtilityFlask whose inherent charm effect is explicitly unavailable.

Secondary utility values deliberately differ from their primary values and one
is null. These are synthetic retention cases, not a claim that this F has those
differences. Raw UtilityBuff references are copied only as unconverted facts;
no referenced buff table or meaning is supplied by this fixture.

`item-inheritance-producer.json` records the producer source hashes from the
frozen RePoE `repoe-item-inheritance/v1` manifest
`f8642243fc1d04cecb26c1bd770fb9bbfd70574b93c82969f737013be23c8f31`.
It is producer identity, not client bytes. Inheritance tests construct small
synthetic UTF-16LE item chains with ordered tag occurrences, unknown blocks and
explicit rejected roots. Their checks use the existing ordinary loader; they do
not certify official client inheritance semantics.

## Skill fixture

`skill-tables.json` has 78 invented rows across the fifteen selected skill tables,
using the same F's consumed column metadata, renumbered columns and synthetic byte
width 1. It contains no client extraction or complete runtime artifact. GPL's
optional `BaseMultiplier` column is absent, as in this F; a separate test adds a
synthetic declaration to exercise the existing fallback.

Attack/support/minion/compound records use deliberately permuted foreign keys,
repeated display names, source levels out of numeric order, labels, signed values,
null active/label/name fields, repeated stats and flags, and a filtered gem with
an otherwise retained effect. Additional-set merging must pair source positions
before sorting levels. Synthetic nonpositive cost divisors and a falling listed
requirement exercise the existing normalization and receipt policies; they are
not claims about this F's values.

A mutation test mirrors the real `MAASBaronEndgameBasic` reference shape: one
primary plus three occurrences of the same additional set. Table identities and
level keys remain unique; ordered-reference multiplicity must survive. A test-only
flattened directory compares the original raw Path wrappers on the same invented
rows. The production fact path never writes or reads such a directory.

## Quality source vectors

`quality-source-vectors.json` is a compact transcription of all 429 rows from
`GrantedEffectQualityStats`, with physical effect/stat references resolved to IDs.
Each record is `[effect_id, ordinary [stat_id, signed_permille] pairs, ordinary
scopes, additional pairs, additional scopes]`; original row/channel/array order
is preserved. It contains source facts, not consumer calculation expectations.

Original F manifest: `56e71e00a72c8079d100b64861fc030206b12aaeb5ad655ccb4ab4e6726332d0`.
The three exact input pins are:

- `GrantedEffects.json`: 6314332 bytes, `528b7162a9f2efdffd7c92e698c3c903873e03ffc97bdef31f31ee6fcefd53e8`.
- `Stats.json`: 11634008 bytes, `bef280b241a844972de0020e57c64cc403ac7e44fddf346b1014d17e1372376a`.
- `GrantedEffectQualityStats.json`: 94479 bytes, `21ceebb7af0c53708f01097001d209753078b4c34e9c6a6f70d68bd6946c22af`.

The retained ordinary archive preserves these tables and the original envelope
under `provenance/original-{manifest,source-lock}.json`. The prepared facts manifest
has a different identity; this fixture asserts only the selected source payloads.
Tests verify the full 424/5 policy partition and every published rate, occurrence,
channel and scope, including Snipe's unresolved native position 3.

## Fixed producer identities

`selected-tables-producer.json`, `selected-tables-producer-21ace02.json`,
`item-inheritance-producer.json` and `../native-facts/player-context-manifest.json`
are read by production code (`include_bytes!` in `src/facts/reader/selected.rs`,
`src/ordinary_facts/base_items/inheritance/source.rs` and `src/facts/player.rs`),
like the producer map in `src/facts/trust.rs`. They are the producer identities
sealed into the pinned RePoE packages, keyed by the file paths of the producing
commit (`RePoE/native_*.py`, before the exporters moved to `RePoE/native/`).
Keep their bytes; they are frozen and never extended. A package exported by the
current tree records new paths and hashes and carries `producer_receipt`: it is
accepted with the commit in its export receipt, never by an identity added beside
these. Target, schema, decoder and payload checks still apply. Re-validating
an old package runs at its producer commit
([native facts](../../../../../RePoE/docs/native/native_facts.md#producer-identity-and-re-validation)).
