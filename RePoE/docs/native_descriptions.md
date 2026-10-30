# Selected native description facts

The offline `descriptions:candidate` task produces `repoe-native-descriptions/v1`
from an explicit, complete literal include closure. It is a domain of the same
RePoE fact ingress, separate from DAT/PSG decoding. It uses only Python's standard
library and does not import the legacy PyPoE/RePoE translation renderer, query
APIs, enumerate client directories or fetch resources.

```sh
mise run descriptions:candidate -- \
  --source-lock /path/to/description-sources.lock.json \
  --expected-source-lock-sha256 <trusted-sha256-of-exact-lock-bytes> \
  --source <selected-key> --raw /path/to/raw-root \
  --out .cache/new-descriptions-candidate
```

The expected lock digest is mandatory. Deriving it from an untrusted lock and
immediately accepting it supplies no authentication. The schema-1 lock's selected
source has kind `official-client-resource-candidate`, `game: poe2`, an explicit
nonempty `game_patch`, realm `international` or `china`, ordered unique `roots`,
and a `resources` object keyed by canonical `Data/StatDescriptions/*.csd` paths.
Every resource declares positive `bytes` and lowercase SHA-256. The acquisition
declaration contains status `unreviewed-acquisition-draft` or
`reviewed-source-input` and nonempty `{kind,sha256}` evidence. These are preserved
caller declarations, not approvals by the parser. China is an identity channel;
the actual source acceptance currently covers an international candidate only.

All raw fingerprints are checked before parsing. Duplicate JSON keys, unsafe
resource paths, symlink components, missing files, invalid UTF-16, malformed
branches, unsupported directives, missing/cyclic/deep includes and resources
outside the selected literal closure fail without a completed output. Limits
are 128 files, 32 MiB per file, 64 MiB total and sixteen include edges. Raw
resources require BOM UTF-16LE. No silent parse gaps or partial branch export
are accepted. Unused siblings outside the explicit resource inventory are not
read and are not part of this package's source claim.

The output has `descriptions.json`, `diagnostics.json`, exact `source-lock.json` and a completion-last
`manifest.json`. Existing output directories and symlinks are never replaced.
Outputs must be new directories under this checkout's `.cache/` and outside raw
input. Publication uses exclusive, directory-relative POSIX operations and
directory identity checks. An I/O failure or observed namespace change may
leave an incomplete directory; a consumer must check the manifest and all
payload hashes. This is not an OS sandbox against arbitrary directory moves.

`descriptions.json` uses `repoe-native-description-branches/v1`. Each file retains
its exact raw size/hash, encoding and ordered records:

- Description headers retain ordered IDs and all language groups and branches,
  including duplicate IDs/groups/branches and empty groups. `stat_index` maps
  each file's stat IDs to description record occurrences; it selects no winner.
- Each branch retains condition tokens, `table_only`/`gem_quality` and other
  restrictions, original template/markup/literal backslash sequences, placeholder
  index and format tokens, ordered raw quantifier tokens and lexical name/argument
  groups. `%`, `-d` and other formats are retained without rendering. No numeric
  transformation, argument interpretation, range selection or units are inferred.
  Every brace-delimited token remains present. Unrecognized placeholder syntax
  and unmatched braces have explicit diagnostics and raw spans; they are not
  repaired or discarded, and do not invalidate an otherwise parseable raw branch.
- Explicit language names, including `Simplified Chinese`, are retained without
  a fixed language whitelist. The implicit default has `declared_language: null`;
  it is not stamped as observed English or as a requested fallback translation.
- Includes retain their literal and slash-normalized target spelling and source
  position. `no_description`, `no_identifiers`, captions and blank records remain
  ordered facts. Suppressions and overrides are not flattened or applied.

Record/group/branch spans identify the original raw file using zero-based
inclusive `byte_start`, exclusive `byte_end`, and one-based inclusive line
numbers. Offsets include the two-byte BOM. File records cover the remaining
source bytes contiguously; astral characters use their actual UTF-16 width.
Description slices additionally carry SHA-256. Raw line/header fields exclude
line terminators; spans retain them. Placeholder character spans count Unicode
code points within the original template. They describe recognized placeholder
syntax only; the raw template always remains authoritative.

`native_csd.iter_records(files, root)` traverses includes at their lexical position
and yields occurrence references with their complete include chain. Repeated
includes remain repeated occurrences, exposing local versus inherited origins.
It does not apply a cache's precedence, suppression or formatter policy. A future
renderer must define and separately verify those decisions rather than inheriting
the legacy renderer's known restrictions/language losses.

The manifest binds all payload sizes/hashes, exact lock/selected-source identities,
raw resources, Python version and four producer/dependency file fingerprints.
No machine paths, timestamps or mutable discovery requests enter output. Identical
inputs, producer bytes and Python version produce identical package bytes.
The complete raw archive must remain available for byte-span references; this
domain does not duplicate the raw files or certify the acquisition evidence.

Every package is partial, `production_ready: false`, and has no runtime data
manifest. A downstream package joins descriptions and numerical facts only under
an explicit matching game/patch/realm identity, preserving source distinctions.
Presence of international Simplified Chinese text does not prove CN numerical
data or CN-client tooltip equality. Description filenames and restrictions do
not resolve Snipe quality scopes, stat-set numbering, game units or server formulas.
