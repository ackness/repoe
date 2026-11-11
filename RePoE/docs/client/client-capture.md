# Local client capture

Implementation: `python -B -m RePoE.client.capture`; the owner's copy script is
[`RePoE/client/capture-sc.ps1`](../../client/capture-sc.ps1).

The China (Tencent) client ships official Simplified Chinese text that the
international CDN does not have, and there is no CDN to read it from. Instead,
the owner copies the needed files from a local install on Windows, and
`mise run client:capture` turns that copy into raw resources, a capture
receipt and a schema-1 source lock. The existing `descriptions:candidate` and
`tables:candidate` then read those resources, and `release:inputs` publishes
only their derived text ([RELEASING.md](../../../RELEASING.md#china-client-capture-input)).
For `china_text`, `release:inputs` enforces that procedure's exact file
allowlist, candidate formats and manifest pins before staging. Extra or
missing members name the offending file; capture directories and raw members
are rejected.

This command decodes no DAT or CSD and adds nothing to `sources/`. It locates
paths with `inspect_locations` from [index discovery](client-index.md) and reads
bundles with `Bundle` and the external decoder from
[strict acquisition](client-sources.md), unchanged; only the byte source
differs: verified local files instead of HTTP ranges.

## 1. Owner: capture on Windows

Close the game and the launcher (an update rewrites the index and bundles), then:

```powershell
powershell -ExecutionPolicy Bypass -File capture-sc.ps1 -ClientRoot '<install dir>' -OutRoot '<out dir>'
```

The script is read-only on the client. It copies `Bundles2\_.index.bin`, every
`Bundles2\Folders\data\**` bundle and a short list of extra bundles, checks
that the index did not change during the copy, and writes `capture.json`
(`pobr-sc-client-capture/v1`: install path, index and executable identity,
every file's size, SHA-256 and timestamp, and the script's own SHA-256) and
`SHA256SUMS`. Send the `sc-capture-<UTC time>` folder and the printed
`capture.json` SHA-256.

The committed script is byte-exact (`.gitattributes` marks it `-text`) and its
SHA-256 is part of every capture: a capture made with another script version
is refused. A changed script is a new commit, and its captures name the new
hash.

## 2. Verify and extract

```sh
mise run client:capture -- \
  --capture .cache/sc-capture/sc-capture-20261105T133039Z \
  --expect-capture-sha256 b06de636564022ad29faf2f25ecdf3dacd9a8e1fd85f582d827c938d5cde9042 \
  --request RePoE/client/china-text-request.json \
  --game-patch 0.5.5.5 \
  --out .cache/china-capture-0.5.5.5 \
  --decoder-python "$PWD/.venv/bin/python" --decoder-lock uv.lock
```

| Option | Meaning |
| --- | --- |
| `--capture` | The capture folder: exactly `capture.json`, `SHA256SUMS` and `Bundles2/` |
| `--expect-capture-sha256` | The `capture.json` SHA-256 the owner stated, received separately from the folder |
| `--request` | `repoe-client-capture-request/v1`: `{"schema", "resources": [game paths]}`, 1 to 128 paths |
| `--game-patch` | The target patch the capture is declared to be; recorded, not verified |
| `--out` | A new directory beneath this checkout's `.cache/` |
| `--decoder-python`, `--decoder-lock` | The external pyooz environment, as for `client:source` |

The next collection uses two requests:

- [`china-text-request-2.json`](../../client/china-text-request-2.json): the 27
  top-level stat-description files and default and Simplified Chinese
  `ActiveSkills`, `GemEffects`, `ItemClasses` and `MonsterVarieties` tables.
- [`china-names-request-1.json`](../../client/china-names-request-1.json): default
  and Simplified Chinese `AlternateQualityTypes`, `Ascendancy`, `BaseItemTypes`,
  `Characters`, `Mods`, `PassiveSkills` and `Words` tables.

The 0.5.5.5 receipt pins the original
[`china-text-request.json`](../../client/china-text-request.json), used in the
historical example above. Request filenames and bytes stay fixed once receipts
record them. Paths must be `Data/StatDescriptions/**.csd`, `Data/Balance/<Table>.datc64` or
`Data/Balance/{Simplified,Traditional} Chinese/<Table>.datc64`.

### Next collection order

Merge the separate size-cap PR before the owner makes the next copy. Keep the
game and launcher closed until that copy is complete. `capture-sc.ps1` copies
the client once; it does not take a request. Process that same folder in this order:

1. Run `client:capture` with `china-text-request-2.json`, as in
   [RELEASING.md](../../../RELEASING.md#china-client-capture-input). One missing
   requested path fails the whole extraction before any output is written. If
   the error names `Data/Balance/Simplified Chinese/ItemClasses.datc64` as missing,
   retry with the published `china-text-request.json` and a fresh output path.
   That preserves the original text inputs; B9 waits for a later client update.
2. After the main request (or its fallback) succeeds, run the names request
   against the same folder and `capture.json` SHA-256, with a separate output:

   ```sh
   mise run client:capture -- --capture <folder> --expect-capture-sha256 <sha> \
     --request RePoE/client/china-names-request-1.json --game-patch <patch> \
     --out .cache/china-names-<patch> --decoder-python "$PWD/.venv/bin/python" \
     --decoder-lock uv.lock > .cache/china-names-<patch>-diagnostic.txt 2>&1
   ```

   If it fails, bring back that diagnostic text file and retain the captured
   folder. The command emits no diagnostic JSON or completion receipt on a
   missing-path failure. This does not affect the successful main output.

The two successful receipts must match in `capture.capture_json.sha256`,
`observed_client.index.sha256` and the captured file inventory. They bind both
requests to the same copied bytes; this does not authenticate a client build.
Both outputs have their own source locks and the same source names, so keep
their raw roots, receipts and candidates separate. Names publication needs a
later packaging update; do not replace the main capture evidence with the names
receipt. If a required bundle was not copied, retain the named `-Extra` argument
for a new owner copy.

Checks, all before any output is written:

- `capture.json` has the expected SHA-256, schema `pobr-sc-client-capture/v1`,
  realm `china`, and a `script_sha256` equal to the committed `capture-sc.ps1`.
- `capture.json` and `SHA256SUMS` list the same files and hashes; its `index`
  entry and `total_bytes` agree with the file list.
- The folder holds exactly the listed files, every one a regular file whose size
  and SHA-256 match. Extra or missing files, symlinks (including a symlinked
  folder), special files and unsafe paths (`..`, backslashes, drive letters)
  are refused.
- Every requested path is in the captured index, and its bundle is in the
  capture. A missing bundle names the `-Extra` argument to rerun the script with.
- Each bundle's framing matches its file size, its raw size equals the index's,
  and each extracted resource has the index's length.
- An existing `--out` is refused, never reused or replaced.

Files are hashed once in a stream and again when loaded for decoding, so a file
changed in between is refused. Each selected bundle and its cached bytes are
released after its resources are extracted. Immediately before writing the
completion lock, the complete capture inventory is checked again: paths,
sizes, SHA-256, plain files and directories, with no extra or missing entries
or symlinks. This includes bundles that the request never reads.

## Output

| Path | Contents |
| --- | --- |
| `raw/<game path>` | The extracted client resources: the candidates' `--raw` root. Local only, never published |
| `capture-receipt.json` | `repoe-client-capture-receipt/v1`, below |
| `request.json`, `SHA256SUMS` | Byte copies of the request and the capture's `SHA256SUMS` |
| `source-lock.json` | Schema-1 source lock; written last, so it marks completion |

The receipt holds what reproduction needs and nothing about the owner's machine:

- `capture`: the `capture.json` and `SHA256SUMS` pins, the script SHA-256, the
  capture time and every file's size and SHA-256. `client_root` and the
  timestamps are omitted (`omitted_fields`); the `capture.json` SHA-256 still
  pins the original.
- `observed_client`: the index identity and the executable name, size, SHA-256
  and portable versions, as the script observed them (0.5.5.172 for the first
  capture). Each version must have 2–6 numeric components (1–6 digits each),
  optionally followed by `-alpha`, `-beta` or `-rc` and up to three digits.
  Other values, including paths, usernames and absent versions, are omitted;
  the original capture's SHA-256 still pins that metadata.
- `game_patch` and `realm` with `declared_not_verified`.
- `index` framing, per-bundle identities and per-resource
  `{bundle, uncompressed_offset, uncompressed_length, bytes, sha256}`.
- The decoder receipt without its host paths; `identity_sha256` is recomputed
  from the identity after removing those paths. The SHA-256 of each tool
  (`capture.py`, the index, source and draft modules, `capture-sc.ps1`) and the
  limits.

The source lock has one source per kind of resource, because
`descriptions:candidate` takes only CSDs and `tables:candidate` only one
language directory:

| Source | Resources |
| --- | --- |
| `china-stat-descriptions` | The CSDs, all of them `roots` |
| `china-default` | `Data/Balance/*.datc64` |
| `china-simplified-chinese` | `Data/Balance/Simplified Chinese/*.datc64` (`language` set) |

Each source is an `official-client-resource-candidate` with status
`unreviewed-acquisition-draft`, the declared `game_patch` and `realm`,
`declared_not_verified`, the pinned decoder declaration `tables:candidate`
requires, and evidence `client-capture-json`, `client-capture-receipt` and
`local-index` (SHA-256 each). The chain from the owner's file to a candidate is
therefore: `capture.json` SHA-256 → receipt → lock evidence → candidate
manifest (`source_identity.acquisition`) → input package manifest → zip pin.

Rerunning on the same capture and request writes byte-identical receipt and
lock, including when an equivalent decoder environment is moved to another
location. The full decoder identity is still checked locally for changes
during extraction.

## Limits

- Patch and realm are owner declarations. The executable version is observed,
  not verified; the target is chosen by the owner (0.5.5.5 for the first
  capture, built 0.5.5.172).
- Hashes prove transfer integrity (these are the files the owner hashed), not
  authenticity.
- Index path hashes are case-insensitive, non-cryptographic Murmur64A matches.
- The selected raw total is bounded by the index reader's 64 MiB, with 32 MiB
  per resource, during `client:capture` extraction. These limits are not checked
  by the owner's PowerShell copy script; the candidate exporters also bound
  their selected inputs. The original China request used 64,459,708 bytes.
  The 0.5.5.8 international default/Traditional Chinese proxy estimates the
  main request at 64,829,502 bytes and names at 45,380,276 bytes, separately.
  Actual China sizes and the next patch can differ. Keep the requests separate
  and merge the size-cap PR before the next capture.
- `descriptions:candidate`'s fixed limits sentence ("International Simplified
  Chinese text is not CN-realm…") also appears in China manifests; read the
  manifest's `realm` instead.
