# Memory locale decoding

The interface now supports the fixed nine tables and a separately identified
[v2 decoded-language ingress](decoded_locale_tables.md). The original two-table
invocation below remains usable for a bounded first probe. Historical receipts
retain their original two-table source hashes and comparison policy.

`native_locale_probe.py` is a bounded diagnostic interface for already-extracted
Words/Ascendancy DAT64 buffers. It uses only hashlib/json/struct, defines functions
without executing acquisition or IO, and can be injected as source into an existing
Python process. No Windows installation or disk copy is needed. This is not a
production candidate exporter, patch detector or source-admission bypass.

```python
namespace = {}
exec(reviewed_probe_source, namespace)  # transfer the reviewed source string
words = namespace["decode_table"](
    "Words",
    already_extracted_words_bytes,
    expected_bytes=472064,
    expected_sha256="88867218a823236c1c9667bd510c892003aa118464dfe48bbe5f4432c917619c",
)
ascendancy = namespace["decode_table"](
    "Ascendancy",
    already_extracted_ascendancy_bytes,
    expected_bytes=12771,
    expected_sha256="78656ac3382e0eaf307156f16ab22c4c1a4b6f19813e5bbd30fc5ad5096852fc",
)
# Keep full results in memory; summarize before transferring bounded output.
```

Those two raw pins are observations from the root-coordinated Windows probe,
not authentication or version claims. Preserve its actual index/client/resource
paths and unknown patch/realm. To compare the same client's default tables,
first record their independent raw bytes/SHA-256, then decode them with those
explicit pins and call `compare_pair(default, localized)` for each table.

The fixed schema revision is `6034b071846ef61b39046ebdb59e6d5717179509`, exact
schema SHA `50e098543345cf8323aeb294e2cfef1b6b44842faccf560ada935cebe22727df`.
Embedded layouts are regression checked against its native converter. Words has
64 physical bytes per row, seven columns; Ascendancy has 165 bytes, 19 columns.
The decoder checks external raw pins before framing, exact marker/width, bounded
arrays/pointers, explicit UTF-16LE termination/decoding, booleans and source order. It retains all
columns, unknown fields, nulls and repeated array values. Foreign-reference
second words are separate wire observations. It does not resolve external FKs.

For Words report complete HASH32 keys/duplicates/row order, Wordlist, Text, Text2,
Inflection and both spawn-weight arrays. Pair by observed unique HASH32, never by
translated text. For Ascendancy report complete Id keys/duplicates/row order,
ClassNo, Character, Name, FlavourText, Unknown0, Disabled, BaseAscendancy and all
other physical fields/FKs. Character references Characters, BaseAscendancy is
self-referential, UIArt references PassiveSkillTreeUIArt, and the three sound
references target SoundEffects. These are physical indices in these exact bytes.

`compare_pair` reports duplicate/null keys, missing keys, and every difference
outside Words' Text/Text2/Inflection or Ascendancy's Name/FlavourText. It preserves
differences instead of forcing a match. Record raw hashes and canonical complete
table/rows hashes, schema/probe source fingerprints and the comparisons. A zero
structural difference or matching Spark/default table hash does not certify the
client patch, realm, or equivalence to the international numerical source. Those
identities require independent root evidence before localized production export.

Reports sort common and missing keys by type name and string value to remain
deterministic. A literal U+FEFF at a string's start remains text. The pinned native
reader uses BOM-sensitive `utf-16`; the four checked English/TW physical tables
have no resulting row differences under explicit UTF-16LE. Preserve and report a
future literal-BOM difference rather than silently removing the character.
