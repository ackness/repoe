# Fixed official-client resource acquisition

Implementation: `python -B -m RePoE.client_sources`.
See [ownership and compatibility](client-sources.md#ownership-and-compatibility)
for the one-time source and historical protocol names.

`client_sources.py` acquires **every resource in one explicitly selected source**
from `sources.lock.json`. It produces a new raw root with direct game-relative
paths (`Data/Balance/*.datc64`, `Metadata/PassiveSkillGraph.psg`) suitable for
`RePoE.native_facts --raw`. It does not run the fact exporter or Rust adapter.
A selected source is a bounded input, not a claim of complete domain or
foreign-key coverage. Production `data/`, `CURRENT`, schema and defaults are untouched.

All paths below are explicit examples; there is no current/latest lookup or fallback.

```sh
# Caller selects an existing external RePoE environment. No install/sync occurs.
mise run client:source -- acquire \
  --source-lock /path/to/sources.lock.json --source official-client-0.5.5.5 \
  --cache .cache/client-sources/cache --out .cache/client-sources/raw \
  --decoder-python /Users/claw/codes/repoe/.venv/bin/python \
  --decoder-lock /Users/claw/codes/repoe/uv.lock --mode offline
```

Offline mode never constructs an HTTP opener. Missing or corrupt cached inputs
fail; they do not trigger downloads. For online acquisition, explicitly select
`--mode online --network-budget-bytes 67108864` (or a smaller budget). Only exact
locked bundle URLs on `https://patch-poe2.poecdn.com/<locked-patch>/Bundles2/` are
requested. All redirects are rejected, including redirects within that host.
There is no index, CDN enumeration, client download or version discovery.

The online budget is cumulative **per invocation**, including reservations for
failed requests, with a hard ceiling of 64 MiB. Each request reserves its requested
length plus one overflow-detection byte before network access. The default body
cap is 4 MiB; `--max-request-bytes` can lower it. Each response must be 206 with
exact Content-Range, Content-Length, identity encoding and a strong ETag.
Transfer-Encoding is rejected before body reads; chunked trailers cannot bypass
the fixed-length body budget. Case-insensitive duplicate header names are
rejected in both online responses and archive entries before normalization. Total
size and ETag must remain identical across all cached and new ranges for that URL;
existing validators are sent using If-Match. Corrupt cache entries fail closed.
HTTP timeouts are 25 seconds; failed requests are not retried automatically.

The reader independently interprets only the 60-byte bundle header, size table and
selected chunks. Before table allocation or decompression it bounds counts, sizes,
offsets and total length, checks redundant sizes, supported encoders (8/9/12), flags,
reserved fields, chunk count and the compressed size sum. Limits are 4,096 chunks,
512 MiB declared bundle raw size, 256 MiB compressed total, 1 MiB decompressed and
2 MiB compressed per chunk, 32 MiB per resource and 64 MiB selected raw bytes.
The fixed resource cap admits patch 0.5.5.5's 30,380,428-byte
`Data/StatDescriptions/stat_descriptions.csd`. It has no caller override and does
not raise HTTP/cache budgets or decoder/worker limits. Strict raw size/hash pins
remain required, including for resources above 16 MiB.
Raw-size eligibility does not establish support for a bundle's encoder or framing.
Those declared bundle totals do not authorize downloading the full bundle.

Encoder **8 is Kraken** in the bundle compressor enum. The fixed
[PyPoE enum](https://github.com/repoe-fork/pypoe/blob/66d1d7442c5718260e1a8efd24989d22987e91af/PyPoE/poe/file/bundle.py)
is a format reference only; no PyPoE source is copied or imported. Bundle compressor
IDs differ from the native chunk stream's decoder IDs: Kraken chunks use decoder
type 6. The existing [pyooz 0.0.8 binding](https://github.com/zao/pyooz/blob/f27d04f6d9000654b79eb07a251a98e02a7136e3/ooz/ooz_bindings.cpp)
calls the decoder and checks the requested output length; its pinned
[ooz submodule](https://github.com/zao/ooz/blob/2480701c664d33efa6c0165ff214cb44b991199f/kraken.cpp)
already dispatches stream type 6 to Kraken. Acceptance passes the original chunk
bytes unchanged to the same `ExternalDecoder`; it does not translate IDs, rewrite
payloads, upgrade the decoder, or admit other compressor enums.

The [retained actual header/table fixtures](../../tests/test_client_sources.py) preserve
the 0.5.5.5 international `Folders/data/F5` and `Folders/data/4C` framing. The
corresponding selected stat, passive-skill and skill description roots were
reconstructed with the existing pyooz 0.0.8 native module and replayed byte-for-byte
under OS-denied network access. These are decompression and source-byte observations,
not trusted raw pins or CSD semantic certification. Fixtures contain no compressed
payload and unit tests use synthetic decoders; real native acceptance requires the
explicit environment and archived ranges. Upstream ooz does not claim fuzz safety;
the existing isolation, identity and size checks remain the trust boundary, not a
claim of arbitrary malformed-input safety.

## Compressed cache and archive import

The cache contains `blobs/<body-sha256>.bin` and
`ranges/<url-sha256>/<start>-<end>.json`. Immutable range records retain the exact
source URL, range, total, ETag, body hash and acquisition provenance. Reads verify
body sizes/hashes and reconstruct from covering ranges; overlapping ranges must
agree. A replay receipt lists the actual compressed ranges used. Cache inputs,
lock inputs, archive paths and output paths reject symlinks and path traversal.
Use local directories without concurrent writers; this is not an adversarial
filesystem sandbox. Decoder interpreter symlinks (normal for a venv) are allowed.

Previously archived HTTP bodies can be imported without executing archive code:

```sh
mise run client:source -- import-archive \
  --source-lock /path/to/sources.lock.json --source official-client-0.5.5.5 \
  --cache .cache/client-sources/cache \
  --archive-root /absolute/path/to/client-source-proof \
  --archive-ledger /absolute/path/to/client-source-proof/downloads.jsonl
```

The supported JSONL ledger has one object per response: `url`, `method: "GET"`,
`status: 206`, `final_url`, `headers` (Content-Range, Content-Length, ETag),
`path` relative to archive root, `downloaded_bytes`, and `sha256`.
Only exact selected URLs are imported; unrelated entries are ignored. Selected
failures, unsafe paths, bad hashes, overlapping conflicts or validator drift fail.
The importer preserves original evidence and writes a separate cache. It neither
imports raw outputs nor trusts archive scripts. `imports/*.json` is written last.

## External decoder and completion evidence

The caller must provide both an absolute decoder Python executable and its
`uv.lock`. The fixed subprocess protocol uses `-I -S -B`, excludes CWD/PYTHONPATH
and site startup hooks, and adds only that environment's installed library path.
It imports the native `ooz` extension after checking its distribution RECORD;
it never imports RePoE/PyPoE or candidate code. The installed pyooz version must
match uv.lock, whose PyPoE repository/revision must match the source declaration.
No GPL PyPoE or ooz implementation is copied into this script or Rust core.
External dependencies retain their own licenses and distribution requirements.

The receipt records the actual module SHA-256, distribution METADATA/WHEEL/RECORD
hashes, Python identity, uv.lock hash and locked package fingerprint. Module identity
is checked again before every decode. The native call receives a bounded expected
output size and its result length must match exactly. Each child has CPU (10 s),
wall time (25 s) and output file (2 MiB) limits. Linux also enforces a 256 MiB
address-space limit. Darwin rejects address-space/data/RSS limits; the receipt
explicitly reports `address_space_bytes: null` there. The output-size and other
limits still apply; no process-memory sandbox is claimed on Darwin.

Every raw file must match the selected lock's bytes/SHA-256 before it is written.
The output root must be absent, separate from cache, lock inputs and production
`data/`. Existing outputs are never replaced, including partial failed runs.
`client-sources.json` is written last, after rechecking written resources and lock
inputs. An output without this receipt is incomplete; retain it for diagnosis or
choose another new output root. There is no extra raw staging/copy directory.

The caller trusts the reviewed source/schema lock and explicitly supplied decoder
environment. Cache hashes, distribution RECORD and local fingerprints establish
integrity/identity, **not independent authenticity**. The source's schema declaration
is recorded, but acquisition does not parse tables or certify schema semantics,
game facts, geometry or gameplay. An installed wheel's upstream artifact hash is
not independently verified by comparing its installed RECORD.

For a future fixed source, separately discover/review its exact resource paths,
raw bytes/hashes, bundle URLs and uncompressed offsets/lengths, and pin its decoder
and schema. Add that reviewed source through the source-lock maintenance process,
then run this same command with its key and a new raw root.
[Index discovery](client-index.md) and [unreviewed acquisition](client-source-draft.md)
are separate commands; scheduling, full-domain export and production adoption
remain separate work.

```sh
python -B -m unittest discover -s tests -p 'test_client_sources.py' -v
```

Tests use synthetic framing and fake HTTP, including offline replay, 200 responses,
redirects, validator drift, malformed frames, budgets, tampering and failed outputs.
Real ooz reconstruction is a separate offline acceptance check with
the external environment and archived ranges; unit tests need neither dependency.

## Ownership and compatibility

RePoE owns acquisition, location-only drafts, bounded index lookup and source
rebinding. These modules use only the standard library and explicit sibling
imports inside the RePoE package. Running them never imports or reads a PoBR
checkout or historical cache script. The decoder is the explicitly selected
external native environment, not an extra worker file or an implicit dependency.
Language production belongs to the translation repository; PoBR imports pinned
temporary game/language inputs for its own adapters and CI.

One-time migration source: [ackness/pobr commit
0d6fe696d21fcc8ed60b42ad93e7cb5aaa40f819](https://github.com/ackness/pobr/commit/0d6fe696d21fcc8ed60b42ad93e7cb5aaa40f819).
The original `pipeline/client_sources.py`, `client_source_draft.py`,
`client_index.py` and `source_rebinding.py` were migrated with their four test
suites and topic contracts. The observed encoder-8 header/table fixture from that
same commit is retained inline in `tests/test_client_sources.py`; it contains no
compressed resource payload. MurmurHash64A retains Austin Appleby’s public-domain
attribution and reference in the [index contract](client-index.md).

Historical `pobr-*` schema identifiers, cache layout, receipt fields and the HTTP
User-Agent are protocol names retained for old inputs. They do not imply a PoBR
runtime dependency. Original public function signatures and default strict
behavior remain compatible. `RePoE.client_sources` re-exports `decode`, `digest`,
`encoded`, `official_url`, `read_file`, `relative`, `safe_path`, `sha256` and
`write_new` from `RePoE.source_io`. The latter contains only the small standard
library file/JSON/URL primitives; `source_rebinding` uses it directly. Draft and
index tool fingerprints and final code checks cover the helper as well.

Python API mapping (replace old top-level imports):

```python
from RePoE import client_sources, client_source_draft, client_index, source_rebinding
# Existing argument order/defaults are unchanged:
# client_sources.acquire(...) / import_archive(...)
# client_source_draft.collect(...)
# client_index.locations(...) / discover(...)
# source_rebinding.create(...) / verify(...)
```

All four entry points run from this checkout with `python -B -m RePoE.<module>`;
`mise run client:source`, `client:draft`, `client:locate` and `source:rebind` are
thin aliases and do not sync or install an environment. No source acceptance,
semantic closure, translation choice or active-data adoption follows from SDK
migration or successful byte replay.
