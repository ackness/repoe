# Selected native tables

`tables:candidate` adds explicit physical DAT tables to an existing fact workflow
without changing or regenerating an earlier profile. It uses the same pinned
schema, PyPoE source verification, DAT framing checks and `_decode_dat` as native
facts. No client discovery, downloader, gameplay projection or translation engine
is added.

The schema-1 source entry must contain the exact selected `Data/Balance/*.datc64`
resources, their observed bytes/SHA256, explicit game/patch/realm, decoder/schema
pins and acquisition status/evidence. Supply the complete source-lock fingerprint
externally. At most 128 tables, 32 MiB each and 64 MiB raw total are accepted.
Raw hashes are integrity pins; a proposed lock remains a draft until separately
reviewed. The command does not promote status or update active data.

```sh
mise run tables:candidate -- --source-lock /absolute/proposed-lock.json \
  --expected-source-lock-sha256 "$LOCK_SHA" --source explicit-source \
  --raw /absolute/raw-root --out .cache/selected-tables/first
```

The new output must be inside this checkout's `.cache`, outside raw inputs and
absent. `tables.json` contains the existing full physical table documents, keyed
by exact table name; `source-lock.json` retains original bytes. The completion-last
`manifest.json` (`repoe-native-tables/v1`) records producer/schema/decoder identities,
raw and output hashes, row counts and all external reference dependencies. Available
internal numeric references are checked; absent target tables are explicitly
unresolved. They are not inferred or fetched. Every row, unknown field, source
order, signed value, null and repeated reference remains available.

Consumers verify the manifest externally, require matching game/patch/realm and
pin any additional fact package used to resolve foreign rows. A source row number
has meaning only inside the exact referenced raw resource; joining a different
patch or rebased table by ordinal is invalid. Display names are not stable IDs.
No released membership, unit, quality multiplier or application policy follows
from successful decoding alone.

Repeat the same invocation with a fresh output for deterministic offline replay.
Existing candidates and all original native fact profiles remain unchanged.
Focused regression: `mise exec -- uv run --locked --offline python -B -m unittest
discover -s tests -p test_native_tables.py -v`.
