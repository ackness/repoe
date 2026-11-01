# Decoded language observations v2

`repoe-localized-tables/v2` separates an observed client's language bytes from
the independently pinned English target to which some text is applicable.
`source_identity.game_patch` and `realm`, and `observed_client.game_patch` and
`realm`, remain null. `target_binding` alone carries the known target identity.
An accepted text binding does not certify the source patch, realm or numerical
equivalence. Existing v1 exporters and their known-identity guards are unchanged.

The two stages have distinct provenance: Windows executes the reviewed
`native_locale_probe.py` standard-library memory decoder; Mac runs
`native_decoded_tables.py` to validate a decoded transfer. Mac does not claim to
redecode original raw DAT bytes or execute PyPoE for this transfer. The pinned
native reader is used separately for local oracle validation and English targets.

## Fixed schema and physical inventory

Nine selected tables, 351 physical fields: Words7/64 bytes per row,
Ascendancy19/165, BaseItemTypes34/360, ActiveSkills40/338, Mods81/693,
Characters66/640, PassiveSkills70/487, ItemClasses28/150,
AlternateQualityTypes6/66. Their layouts and original-column SHA-256 values are
embedded in the memory decoder and regression checked against fixed schema
`6034b071846ef61b39046ebdb59e6d5717179509`, bytes SHA
`50e098543345cf8323aeb294e2cfef1b6b44842faccf560ada935cebe22727df`.
The corresponding native specification SHA is
`c9417f03e2205ff649721c3dbf9620ee0c703bf905b3cf53469ce3eda86f1e25`.

Every row, ordinal, physical column, unknown value, ordered array and null is
preserved. Parsing is explicit UTF-16LE, bounded and pin-before-parse. Foreign
reference second words stay in separate wire observations. These words are
decimal strings in the receiver's `wire-observations.json`; receipt integers must
be safe exact integers. Schema metadata retains its original localized flags;
those flags do not define this version's explicit text policy.

## Windows memory interface and bounded text transfer

Inject the reviewed source string into the existing process. Do not install,
write files or acquire additional unrelated resources. The caller records exact
raw hashes and actual indexed path spelling before calling `decode_table`.

```python
namespace = {}
exec(reviewed_source_string, namespace)
transfer = namespace["MemoryTransfer"](
    observed_client={"game": "poe2", "game_patch": None, "realm": None, "index_sha256": actual_index_sha256},
    decoder_source_sha256=reviewed_source_sha256,
    python_version=actual_python_version,
    evidence=[{"kind": "root-observed-client-acquisition", "sha256": receipt_sha256}],
)
# Repeat for each selected table; release the raw/decoded pair after add_pair.
default = namespace["decode_table"](
    table_name, default_bytes, expected_bytes=default_pin["bytes"], expected_sha256=default_pin["sha256"]
)
localized = namespace["decode_table"](
    table_name, localized_bytes, expected_bytes=localized_pin["bytes"], expected_sha256=localized_pin["sha256"]
)
summary = transfer.add_pair(
    default, localized, default_resource=actual_default_indexed_path, localized_resource=actual_sc_indexed_path
)
receipt = transfer.receipt()  # metadata only; hash the exact encoded bytes
part = transfer.part(table_name, 0)  # fetch only explicitly requested parts
```

Actual `data/balance/simplified chinese/...` spelling is retained. Case folding
checks canonical membership and collisions without rewriting raw identities.
`add_pair` stores compressed bodies in memory rather than all decoded pairs.
It returns only table name, part count and byte counts. Start with these compact
statistics and the receipt; never print the whole in-memory transfer implicitly.

Each table pair is canonical UTF-8 JSON plus LF, compressed with zlib level9,
then base64 encoded into at most24KiB ASCII parts. A part is exactly
`{table,index,data}`; collect its canonical JSON as one line on Mac. The receipt
pins every part, compressed body, decoded body, raw default/SC resource, column
schema, index and decoder source/runtime. No raw client bytes are transferred.
Large physical integers remain opaque inside base64 and are parsed only by
Python on Mac; do not JSON-roundtrip those values through JavaScript numbers.

Bounds: 32MiB per raw table, 100000 rows, 16million decoded scalar/array visits,
128MiB per decoded pair, 16MiB compressed per table, 256MiB decoded and32MiB
compressed in total. Receiver JSONL is at most48MiB, with at most1024 parts per
table. Missing, duplicate, extra, corrupt or reordered-index parts, invalid
types/schema and trailing or oversized compressed streams reject publication.
Part arrival order is irrelevant; declared indices and exact pins are required.

## Offline ingest

The caller pins `transfer-receipt.json` and `parts.jsonl` as observed transfer
artifacts. `target-lock.json` selects the exact English package for each selected
table, using its external manifest pin:

```json
{"format":"repoe-language-target-lock/v1","tables":{"Ascendancy":{
  "package":"/absolute/path/to/english-package","manifest_sha256":"<64 hex>"
}}}
```

Allowed English packages are existing native facts v4 or selected tables v1
(including explicit English localized v1). They retain strict known matching
game/patch/realm, complete columns, schema and payload/raw pins. Target locks
must exactly cover the transfer's selected tables.

```sh
python -B -m RePoE.native_decoded_tables \
  --transfer-receipt /path/to/receipt.json \
  --expected-transfer-receipt-sha256 <external-sha256> \
  --parts /path/to/parts.jsonl \
  --target-lock /path/to/target-lock.json \
  --expected-target-lock-sha256 <external-sha256> \
  --out .cache/decoded-language/new-candidate
```

Publication is completion-last, exclusive, under this checkout's `.cache/`.
Manifest files pin `tables.json` (SC), `default-tables.json`,
`target_binding.json`, `wire-observations.json`, original transfer receipt and
target lock. Both tables payloads use the established full physical table shape:
`table/raw_resource/physical_fields/columns/rows/validation` with unchanged source
column metadata. Row addresses are diagnostic locations, never match identities.

## Text binding contract

Policy `stable-key-current-english-all-nontext/v1` uses Words.HASH32 or the other
eight tables' Id, retaining all duplicate/missing occurrences. It accepts only
three unique occurrences with the current English values equal, source default
versus SC nontext values equal, and target nontext values equal. Resource-bound
records additionally have an exact default raw identity equal to the target;
otherwise the binding is record-bound. Physical foreign-reference values are
compared without claiming cross-client reference semantics.

The exact18 text fields are BaseItemTypes(Name,Inflection),
ActiveSkills(DisplayedName,Description,ShortDescription,WebsiteDescription),
Mods(Name), Words(Text2,Inflection), Characters(Name,Description,TraitDescription),
Ascendancy(Name,FlavourText), PassiveSkills(Name,FlavourText), ItemClasses(Name),
AlternateQualityTypes(Description). Every remaining physical field is nontext.
Words.Text and Wordlist remain identity/nontext; Text is also retained in the
binding's English object. Empty Inflection stays empty and unresolved by the
language consumer; this producer never infers grammar from Text2.

`target_binding.json` contains `{policy_id,target_identity,tables}`. Each table
contains `{key_field,text_fields,nontext_fields,target_pins,
source_default_raw_equals_target,records}`. Each record has the agreed
`table/key_field/id/decision/binding_kind/reason_codes/source_default_rows/
source_localized_rows/target_rows/english/comparison`, plus `differing_fields`.
Comparison values are null when duplicate/missing records prevent comparison.
Rejected records are complete evidence, and no first duplicate is selected.

`target_pins` contains target game/patch/realm/language, `manifest_sha256`,
`payload`, `payload_bytes`, `payload_sha256`, `table_pointer` (`/T` or empty),
`raw_resource`, `raw_identity`, full three-part `schema`, and `columns_sha256`.
The column pin hashes canonical original schema-column objects, not wrappers.
The manifest repeats these table pins and text/nontext field arrays and binds
the full binding file. Consumers can independently reconstruct every decision
from the two complete source tables and pinned target, rather than trust booleans.
