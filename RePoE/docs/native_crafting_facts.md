# Native crafting relationship facts

`RePoE.native_crafting_facts` is an offline, standard-library-only projection of
exactly seven already exported F77 tables. It emits
`repoe-native-crafting-facts/v1`, `status: partial-candidate` and
`production_ready: false`. It performs no raw decoding or acquisition and does
not validate the other F77 payloads, the full foreign-key closure or gameplay.

```sh
mise exec -- python -B -m RePoE.native_crafting_facts \
  --facts /path/to/pinned/facts \
  --expected-manifest-sha256 <externally-recorded-sha256> \
  --out .cache/crafting/new-candidate
```

Python API:
`create_candidate(*, facts, expected_manifest_sha256, out) -> manifest`.
`project(tables) -> projection` accepts a dictionary of the seven complete native
table documents without performing I/O; its caller owns input authentication.

## Input identity and failure boundary

The externally pinned manifest must identify a partial `repoe-native-facts/v4`
`items-actors-bc` export with the exact native schema/specification and decoder
revision. Its source must declare PoE2, patch, realm, acquisition evidence,
source-lock and selected-source identities. These are inherited declarations;
this operation does not independently observe a client, verify acquisition
evidence documents, authenticate raw resource bytes or promote source status.

Language is optional inherited metadata, not an eligibility gate for these
physical-ID/numeric joins. Missing or null language remains unknown; an explicit
nonempty string is preserved as a declaration without verification. No English
default or inference from names/paths is made. `observation` records the nullable
declaration and `source_language_independently_observed: false`; absence in the
original source identity is preserved. The original raw tables are not translated.

Only these paths are consumed and verified against the manifest's byte lengths
and SHA-256 values:

- `tables/BaseItemTypes.json`
- `tables/ItemClasses.json`
- `tables/Mods.json`
- `tables/Stats.json`
- `tables/Essences.json`
- `tables/EssenceTargetItemCategories.json`
- `tables/EssenceMods.json`

The per-file limit is 64 MiB; the combined limit is 96 MiB. Physical table names,
resource paths, source-column order, flattened physical fields, complete row
fields, validation row counts and consecutive zero-based `_row` identities are
checked. Actual string IDs in BaseItemTypes, ItemClasses, Mods, Stats and
EssenceTargetItemCategories must be nonempty and unique; they are not trimmed.
Numeric row indices, including zero, are exact integers, never booleans.

All declared foreign references **between the selected seven tables** are checked
for bounds. Required crafting relationships also require their native schema
target and array shape. Missing fields, malformed relationships and unresolved
nonnull selected references reject generation before output. External reference
fields remain listed in `summary.external_reference_fields`, without closure or
semantic claims. Null references remain null and are counted; missing required
join owners also produce diagnostics. Empty category lists do not imply a
wildcard.

## Output contract

The fresh output directory contains seven flat `<Table>.json` files copied
byte-for-byte, `input-manifest.json` copied byte-for-byte, `crafting.json` and a
completion-last `manifest.json`. Raw references use
`{"payload":"Mods.json","pointer":"/rows/0/values"}`. Every unconsumed source
field and original column/schema metadata remains available through the copied
table. A physical reference is `{"table":"Mods","row":0,"id":"..."}` when
the target has an actual string ID, or just table/row otherwise. Rows are
ephemeral identities within these exact input bytes.

`crafting.json` contains source-ordered collections:

| Collection | Fields |
| --- | --- |
| `essences` | `essence`, `raw`, `currency` (BaseItemTypes reference) |
| `categories` | `category`, `raw`, `item_classes` |
| `mods` | Every physical Mods row: `mod`, `raw`, `level_raw`, `has_hardmode_values_raw`, `slots` |
| `essence_mods` | Every physical EssenceMods row: `source`, `raw`, `essence`, `currency`, `target_category`, `item_classes`, `mod`, `display_mod`, `outcome_mods`, `outcome_mod_weights_raw` |
| `diagnostics` | Source-bound null join, inverted interval and unresolved outcome/weight alignment records |
| `summary` | Seven table row counts, checked/null selected references, external reference fields, diagnostic counts and zero unresolved selected references on success |

Ordered reference arrays contain `{source_slot, target}` entries, with zero-based
source positions. Duplicate rows and repeated array entries remain separate.
`item_classes: null` means the category owner is null; `[]` means a known category
has an empty physical class list. No deduplication, sorting, filtering, mod
aggregation or currency-name policy is applied.

Every Mods row has exactly eight explicit `slots`, numbered 1 through 8. Each
contains `stat` (nullable Stats row and stable ID), `min_raw`, `max_raw`,
`min_hardmode_raw` and `max_hardmode_raw`. Values come from native `StatN`,
`StatNMin`, `StatNMax`, `StatNMinHardmode` and `StatNMaxHardmode`; legacy
`StatNValue` is not read. Null stat slots retain their endpoints. Null/zero and
negative endpoints remain distinct. Inverted intervals remain in source order
with a diagnostic; hardmode flags do not select, replace or erase either channel.

`Mod`, `DisplayMod` and `OutcomeMods` remain separate physical relationships.
`outcome_mod_weights_raw` retains the independent original array. Unequal lengths
produce `outcome_weight_alignment_unresolved`; they are never zipped, padded,
truncated or converted into probabilities. Empty outcomes never trigger a
fallback to Mod. Consumer interpretation of any of these fields needs separate
evidence.

The output manifest binds the exact input manifest, seven input payload pins,
seven declared raw resource identities, inherited source/acquisition declaration,
original schema/decoder/producer metadata, current producer source fingerprints,
Python version, output pins, summary and scope. The full input manifest retains
unconsumed declarations as historical context; their presence is not verification.
Only the seven selected raw resource declarations appear in output
`source_identity.raw_resources`. Producer files and selected inputs are checked
again before publication. No timestamps or absolute input paths affect bytes.

Candidates must use a new directory beneath this checkout's `.cache`. Input
symlinks, output replacement, output within the input package and unsafe output
namespaces are refused using the existing native publication helper. A failed
write may leave an incomplete directory; without the last manifest it is not a
completed candidate, and it cannot be overwritten by a retry.

## Consumer and historical boundary

PoBR owns currency prefixes, essence/alloy labels, UI selection, aggregation,
text rendering, numerical interpretation and any Mod/OutcomeMods fallback. This
export does not certify official crafting eligibility, success probabilities,
craft coexistence or runtime adoption. A self-consistent manifest does not
accept a source or update global locks or CURRENT.

The retained historical crafting output (31,192 bytes, SHA-256
`6153ccd3eee148312fac673c9669896c66c8ab1cf712167a5e836544821a4202`)
still has unknown original execution inputs, patch and realm. A new candidate,
consumer projection or byte match does not establish historical regeneration
or equivalence. The historical output is not an input or fallback here.

## Focused verification

```sh
mise exec -- python -B -m unittest discover -s tests -p test_native_crafting_facts.py -v
mise exec -- uv run --locked --offline ruff check RePoE/native_crafting_facts.py tests/test_native_crafting_facts.py
mise exec -- uv run --locked --offline ruff format --check RePoE/native_crafting_facts.py tests/test_native_crafting_facts.py
```

Synthetic tests cover all eight slots and hardmode values, null/zero/negative and
inverted ranges, duplicate/order retention, independent mod relations, weight
misalignment, identity/FK/schema/pin failures, raw-copy/output pins, fresh-process
determinism, changed inputs, output freshness, symlinks and failed publication.
Actual seven-table generation remains a separate bounded evidence operation;
full native decoding and runtime/engine validation are outside this producer.
