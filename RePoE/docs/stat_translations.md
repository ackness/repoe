### `stat_translations.json`

Maps stat ids together with their values to human-readable text. This is the text
that appears on items in-game. 

The file only completely covers equipment item stats (everything but chest, gem, 
area, sextant, passive skill tree, leaguestone and monster stats). The files 
in the `stat_translations` folder cover other stats:

- `areas.json` covers stats on areas.
- `atlas.json` covers sextant stats as shown on the Atlas.
- `strongbox.json` covers stats on strongboxes.
- `passive_skill.json` covers stats on the passive skill tree.
- `passive_skill_aura.json` covers stats of auras provided by stats on the passive
  skill tree.
- `monster.json` covers stats on monsters.
- `support_gem.json` covers stats on support gems.
- `skill.json` and all other files ending in `skill` cover stats
  on active skill gems and other skills. Each skill is fully described by one of
  these files. Which one depends on the skill.

The file is an array of translation objects. Each object contains one more stat
ids that are translated together (`ids`) and the translation information (only to
English, `English`). A combination of ids may only appear once.

The translation information is stored in an array under `English`. Each array element
is an object that contains information about when that object is used for translation
in `conditions`. The other fields describe how the translation is formatted.
 
The first array element whose condition applies is used for translation. `conditions`
is an array that contains an element for each id (same applies to the other array
fields). The value of the stat with the ith id is checked against the ith condition.
A condition has the fields `min` and `max`. If `min` is not specified, it is
negative infinity. If `max` is not specified, it is positive infinity. The stat value
`v` matches the condition iff `min <= v <= max`. If `negated` is present and true, the
condition result is negated. The first translation for which
all `conditions` elements match the stat values is used for translation.

Stat values may be a range instead of a single value (e.g. `(10 to 20)`). In that case,
the first condition that matches both values in the range (e.g. 10 and 20) is taken.
If no condition matches both values, the first condition that matches at least one
value is taken.

If no translation matches the values, it is not displayed. If the combination of stat
ids has no entry, it is not displayed. If the stat ids only have entries with more
that have more ids ("partial" matches), the values for missing ids are set to 0. If
all values are 0, the stats are not displayed.

If the entry for the ids has the field `hidden` set to `true`, the translation is not
actually displayed in in-game tooltips (e.g. the implicit movement speed penalties
on body armours and shield). The Wiki suffixes these with " (Hidden)", for example.
These ids were manually translated in PyPoE.

Once the correct translation entry matching the stat ids and values is found, the text
can be created with the information found in the fields `string`, `formats` and
`index_handlers`. Values are inserted into `string` by replacing `{i}` entries with
them. `i` references the value of the stat id with the (zero-based) index `i`. Before
being inserted, they may be modified. How is defined in `formats` and `index_handlers`.

`formats` define the value formatting:

- `#`: value is inserted unchanged
- `+#`: value is prepended with a '+' character, iff the value (or all values if the
  stat value is a range) is (are) positive
- `ignored`: the value is not referenced in the format string

Range values are inserted as `(value1 to value2)`. If both values of the range are
negative, the '-' character is moved outside the parentheses (e.g. `(-20, -10)` is
formatted as `-(20 to 10)`). 

`index_handlers` are applied to values before formatting. These change the actual
values, see 
[`PyPoE.poe.file.translations`, line 2071ff](https://github.com/OmegaK2/PyPoE/blob/dev/PyPoE/poe/file/translations.py#L2071)
for their Python definitions.
If, for example, `divide_by_one_hundred` is a handler for a value, the value must
be divided by 100 before being formatted.

### PoE2 offline trade candidates

The PoE2 exporter reads client CSD descriptions and quantifiers. Its default
client-only scope makes no trade API request: `trade_stats` is `null` in formatted
output and absent in compact output. Description IDs, conditions, formats and
handlers keep the existing schema. This section describes PoE2; the historical
file names and coverage notes above are not a certification of PoE2 coverage.

`repoe stat_translations --poe2 --trade-snapshot /canonical/local/snapshot`
opts in to candidate associations using an existing **schema-1**
`poe2-zh-cn-stats` snapshot. It consumes `manifest.json` and the selected
`raw/trade-en.json.gz` response. Both official trade source declarations and the
English/Chinese URL configuration must match that collector's contract; all
source declarations must have valid, unique keys and paths and valid metadata.
Only the selected English response's file, compression, body and catalog are
verified and consumed. Unselected Chinese responses, supplemental pages and
translation worksheets are not export inputs and their bytes are not certified.
The snapshot can be copied anywhere; no sibling repository is required.

`--trade-snapshot-sha256` optionally fixes the SHA-256 of the exact **manifest
bytes**, including whitespace, from a trusted source lock. The manifest's selected
source `sha256` and `bytes` describe the **decompressed response**, as in the
existing collector. The importer also fingerprints the actual compressed file.
Its canonical local directory, manifest and selected raw path must exist without
symlinks in any component; `..`, absolute/escaping raw paths, duplicate sources,
non-regular files and malformed JSON/catalogs are rejected. The manifest is capped
at 1 MiB, compressed input at 16 MiB + 64 KiB and decompressed body at the existing
collector's 16 MiB limit. Gzip integrity, response hash/length and output-model
compatibility are checked before any client loading or output writes. New trade
entry fields require explicit schema support; they are not silently discarded.

The only supported association language/realm is **English/international**.
`--trade-realm international` is the default declaration when a snapshot is used;
China, non-English and `--language all` combinations are rejected. This declaration
does not prove that the supplied client belongs to that realm or patch. The CLI
also rejects a snapshot when the selected modules (after `--resume-from`) omit
`stat_translations`, and rejects a digest/realm option without a snapshot. Missing,
corrupt or unsupported explicitly requested input never falls back to client-only.
Validation errors preserve previous output bytes and create no export directory.

Matching retains the existing exact text, multiline partial text, option text and
numeric-placeholder fallback behavior. Candidates are sorted deterministically
and preserve full trade IDs **and their English text branches**; the same trade
ID can legitimately have multiple texts. Trade IDs, numeric suffixes and text
similarity are not game stat identity evidence. Neither a checksum nor a text
association establishes game semantics, units, scope or calculation correctness.

Each completed export writes `stat_translations.provenance.json` and
`stat_translations.provenance.min.json`, containing the same data, including nulls:

- `mode`, `language`, `game`, and client `game_patch: null` (unknown).
- `trade_snapshot: null` for client-only exports; otherwise the manifest schema,
  snapshot ID/capture time, original `game_patch` (including unknown/null), actual
  manifest hash/length, optional trusted expected digest, full selected source
  metadata (URL, fetch time, HTTP metadata and declared body identity), and actual
  compressed/decompressed response hash/length, language and realm.
- `outputs`, a relative-path map to SHA-256/byte lengths of every description,
  `stat_value_handlers` and `stats_by_file` formatted/compact file written in this
  invocation. Writers close files before hashing; the sidecar does not hash itself.

The sidecar binds this invocation's outputs and consumed trade evidence. It is not
a full client/schema/toolchain source lock, and HTTP Last-Modified is not a game
patch. It does not inventory old files in a reused output directory. Export into
a fresh candidate directory and require successful completion before adoption:
client parsing or filesystem failures after input validation can still leave
partial outputs, and an older sidecar must not be treated as a success marker.
This slice does not change published/active data or establish complete game,
translation or China-realm coverage.

`mise run check` runs synthetic snapshot replay, actual CLI wiring, network guards,
hash-seed/process determinism, malformed input and previous-output preservation
tests. To additionally exercise the fixed real snapshot locally, supply its
canonical directory explicitly (it is not downloaded or required by normal tests):

```sh
REPOE_TEST_TRADE_SNAPSHOT=/path/to/20261012T081820011Z mise run check
```

That optional test pins manifest SHA-256
`97f77435167945c52637a2b7314ab3a073c8bd1b20738267c051d96f58c7645b`
and verifies the 853,713-byte English body
`3e601b7b31c4a5569912c7a35406a8a754453baf08f9e8702d0f73775cff6e82`
(8,303 entries). It tests the real trade catalog against synthetic client
descriptions with networking blocked; it does not test real-client CSD decoding.
The committed small fixture is synthetic and is not game evidence.
