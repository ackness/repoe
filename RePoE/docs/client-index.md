# Fixed client index discovery

Implementation: `python -B -m RePoE.client_index`.
See [ownership and compatibility](client-sources.md#ownership-and-compatibility)
for the one-time source and historical protocol names.

`mise run client:locate` maps an explicit list of paths to bundle locations
in a selected international PoE2 patch. Its `selection.json` is an input to
[draft acquisition](client-source-draft.md). Discovery, acquisition, source review,
RePoE facts, PoBR adaptation and runtime adoption remain separate steps.

This command never selects the latest patch, downloads a full client, decodes DAT
tables or updates `sources.lock.json`/`CURRENT`. It reuses `RangeCache`, `Ranges`,
`Bundle` and the explicit external decoder from [strict acquisition](client-sources.md).
No PyPoE Python module is imported.

## Request and commands

The request schema is `pobr-client-index-request/v1`. All fields below are
required; extra fields, duplicate JSON keys, invalid paths or decoder pins fail.
Replace decoder placeholders with actual fixed dependency identities. The patch
is an example of a separate candidate, not a runtime default.

```json
{
  "schema": "pobr-client-index-request/v1",
  "game": "poe2",
  "realm": "international",
  "game_patch": "0.5.5.5",
  "decoder": {
    "repository": "https://github.com/repoe-fork/pypoe",
    "revision": "<40 lowercase hex digits>",
    "pyooz_version": "<locked version>",
    "uv_lock_sha256": "<64 lowercase hex digits>"
  },
  "resources": ["Data/Balance/SkillGems.datc64", "Data/Balance/GrantedEffectLabels.datc64"]
}
```

Choose the patch deliberately using separately retained version evidence. Paths use the same portable spelling, locale-space, case collision
and file/directory rules as draft acquisition. Limits: 128 paths, 32 MiB per
selected resource, 64 MiB selected raw total. No raw hashes are accepted as inputs.
The fixed resource cap includes patch 0.5.5.5's 30,380,428-byte
`stat_descriptions.csd`; index parsing, HTTP/cache budgets and decoder/worker
limits are unchanged.

```sh
mise run client:locate -- --request /path/to/request.json \
  --cache .cache/client-index/ranges --out .cache/client-index/first \
  --decoder-python /path/to/repoe/.venv/bin/python \
  --decoder-lock /path/to/repoe/uv.lock \
  --mode online --network-budget-bytes 67108864

# Replay to a new root; no HTTP opener is created.
mise run client:locate -- --request /path/to/request.json \
  --cache .cache/client-index/ranges --out .cache/client-index/replay \
  --decoder-python /path/to/repoe/.venv/bin/python \
  --decoder-lock /path/to/repoe/uv.lock --mode offline

# Acquire the located resources in a separate stage with its own budget.
mise run client:draft -- --selection .cache/client-index/first/selection.json \
  --cache .cache/game-resources/ranges --out .cache/game-resources/raw \
  --decoder-python /path/to/repoe/.venv/bin/python \
  --decoder-lock /path/to/repoe/uv.lock \
  --mode online --network-budget-bytes 8388608
```

Index discovery can consume substantial bandwidth because it searches every file
record; it does not assume sorted hashes. If a patch exceeds the 64 MiB compressed
range/cache cap, the command fails rather than raising it or switching sources.
Only `https://patch-poe2.poecdn.com/<patch>/Bundles2/_.index.bin` is available to its
range reader; resource payloads are acquired later. The directory-name bundle is
not downloaded for path enumeration.

Optional `--archive <root> --ledger <successful-ranges.jsonl>` imports archived
index ranges with the existing status/header/validator/body checks. Both arguments
are required together. A selected failed request, non-range response or invalid
entry rejects import. For research logs containing failed probes, explicitly
select successful range records and preserve the original ledger hash, excluded
entry hashes and reasons. Invalid selected entries are never silently discarded.
Import records the supplied ledger identity, not authenticity of an earlier capture.

## Format and evidence boundary

Supported layout: little-endian bundle table, `<QIII>` file records and directory
table whose first record is the empty root. Its hash determines the current
MurmurHash64A seed; legacy FNV indexing is rejected. The hash routine follows
Austin Appleby's [public-domain algorithm](https://github.com/aappleby/smhasher/blob/master/src/MurmurHash2.cpp).
The parser/hash implementation does not copy GPL PyPoE source. Format observations
are cross-checked against fixed client bytes and the pinned upstream reader.

Duplicate selected hashes, requested-name collisions, missing paths, invalid bundle
joins and out-of-bounds slices fail. Case-insensitive, non-cryptographic hashes do
not prove caller spelling or exclude unrelated colliding paths. Patch/realm and
the empty-root convention are assumptions; directory names and complete index
semantics are not certified. Index consistency is not upstream authentication.

Parsing caps: 100,000 bundles, 8,000,000 files and 250,000 directory records. The
reader retains one decompressed chunk; the file table is spooled to temporary disk
(at most 160,000,000 bytes) and searched after deriving the seed. Existing bundle,
chunk, worker, HTTP, timeout and budget limits remain. Proof records decoded chunk
hashes, exact parsed-prefix/file-table hashes, counts and selected physical record
indices/locations. It does not claim the complete index was parsed as one file.

Output must be absent and separate from data, cache and source/decoder/archive
inputs. Files: exact `request.json`, `index-locations.json`, acquisition-compatible
`selection.json`, completion-last `index-receipt.json`. The receipt fingerprints
these files, tools, actual decoder, archive input and compressed ranges with network
counters. Existing outputs are refused; interruption may leave incomplete output.
Use trusted local directories with no concurrent writers.

Status is always `unreviewed-index-locations`, `production_ready: false`. The
selection binds proof as opaque evidence; acquisition does not independently
repeat discovery or read the proof. Preserve and review the chain. Located paths
and observed raw hashes do not approve a source lock, complete domain coverage,
gameplay units, Chinese-client equivalence or runtime adoption.

## Diagnostic inspection

The default `locations(bundle, paths)` and `discover(...)` remain strict: one
missing name raises, and discovery emits no selection or completion receipt.
Call `inspect_locations(bundle, paths)` to obtain `(matched, missing, framing)`
explicitly, without catching exceptions or reading frame locals. It retains all
framing, requested/selected hash collision and selected-size guards. All-missing
inspection is valid diagnostic evidence; malformed or conflicting input fails.

For the full explicit request/cache/decoder interface, use `inspect_index(...)`
with the same arguments as `discover(...)`, or add `--diagnostic` to
`python -B -m RePoE.client_index` / `mise run client:locate`. It writes only the
exact `request.json` and `index-diagnostic.json`. The latter has schema
`repoe-client-index-diagnostic/v1`, status `diagnostic-index-inspection`,
`diagnostic: true`, `production_ready: false`, `source_approval_claimed: false`
and `selection_emitted: false`. It preserves the whole requested list, matched
records, ordered missing names, framing and decoded-chunk evidence, actual
compressed ranges, decoder/tool fingerprints and network counters.

Inspection never writes `selection.json`, `index-locations.json` or
`index-receipt.json`, even if every path matches. CLI missing results exit **2**;
all-matched inspection exits 0 but remains diagnostic. Validation/I/O failures
exit 1. The same absent-output, safe-path, input-separation, cache/network limits
and final request/tool/decoder checks apply. Offline misses do not become absent
resource observations; they remain failures. The command never changes source
acceptance or CURRENT. To acquire a successful subset, the caller must explicitly
write a new request and run strict discovery; missing names are never silently
filtered into a successful selection.
