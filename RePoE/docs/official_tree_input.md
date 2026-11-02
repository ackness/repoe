# Historical official tree input

`RePoE.official_tree_input` owns acquisition and independent storage of an
explicit historical official Git tree input. The raw file stays opaque and
byte-identical, including every node and mapping. No parser, client decoder,
language library, PoBR module or third-party Python package is imported.

This is separate from the ordinary 0.5.5.5 F77 DAT/PSG tree. The historical
source declaration names upstream version `0.5.5`, full Git revision
`bd87e6512c92b868542eddfb1ba4ea8b6dc2da36`, `data.json`, and international realm.
`game_patch` remains null. The original GGG rights declaration is retained,
including its unreviewed product redistribution scope. Verifying raw byte pins
does not establish a new observation of Git origin, patch applicability,
semantic correctness, source approval or redistribution permission.

## Explicit acquisition

Authenticate `publication/0.5.5-official-tree-input.plan.json` with an externally
trusted full SHA-256. It uses `repoe-official-tree-plan/v1`, requires exact
`source`, `input: {bytes, sha256}` and `publication: {repository, path, ref}`
fields, and rejects consumer corrections and implicit identity. The source
SHA-256 must equal the input pin; a full lowercase 40-character revision and a
positive length up to 16 MiB are required. Original data is never reserialized.

```sh
python3 -B -S -m RePoE.official_tree_input acquire \
  --plan publication/0.5.5-official-tree-input.plan.json \
  --plan-sha256 <trusted-plan-sha256> --cache .cache/historical-input/cache
```

The explicit cache is under this repository's `.cache`; its entry is
`<cache>/<input-sha256>/data.json`. Default offline mode fails on a miss. A
present corrupt entry fails in both modes and is never repaired through HTTP.
`--online` permits a cache miss to request exactly
`https://raw.githubusercontent.com/grindinggear/poe2-skilltree-export/<full-revision>/data.json`.
There is no branch, CDN, index or old-cache fallback. Redirects, final URL
changes, unexpected status, duplicate headers, encoded/chunked bodies, wrong
length and wrong SHA-256 fail before a cache write. The bounded body is read
by a standard-library worker with a kill/reap wall deadline (`--timeout`,
default 15 seconds, maximum 30); proxy environment settings are ignored.
Cached reuse returns `transport: existing-cache`, without an acquisition receipt.
No live HTTP is required for the original migration.

## Export and handoff

Commit the producer source first. Export requires a real full commit whose four
producer files exactly match the executing checkout: this module,
`source_io.py`, `data_publication.py` and package `__init__.py`. The plan pin is
recorded separately; no artifact digest is embedded back into the producer.

```sh
python3 -B -S -m RePoE.official_tree_input export \
  --plan publication/0.5.5-official-tree-input.plan.json \
  --plan-sha256 <trusted-plan-sha256> --cache .cache/historical-input/cache \
  --producer-revision <committed-full-revision> --out .cache/historical-input/package
python3 -B -S -m RePoE.data_publication git-handoff \
  --package .cache/historical-input/package
```

The Python APIs are `acquire(plan_path, plan_sha256, cache, *, offline=True,
timeout=15)` and `export(plan_path, plan_sha256, cache, output,
producer_revision, *, offline=True, timeout=15)`. The matching mise entry is
`tree:input`. Inputs are fully explicit; no adjacent checkout is consulted.
Unsafe/traversal/symlink paths, overlapping cache/plan/output paths and reused
output directories are rejected. The exporter rechecks input, plan, producer
and written output bytes before writing completion marker `package.json` last.
A failed export may retain partial diagnostics but has no completion marker.

The deterministic ZIP contains exactly `data.json` and `manifest.json`, with
stored regular-file members, fixed permissions and timestamp, no compression
version dependency. The manifest contract is:

```text
schema: repoe-official-tree-input/v1
status: historical-diagnostic-candidate
production_ready: false
source: <original declaration, excluding consumer corrections>
files: {data.json: {bytes, sha256}}
plan: {bytes, sha256}
producer: {repository: ackness/repoe, revision: <full-code-commit>,
           module: RePoE.official_tree_input, files: {<code-path>: {bytes, sha256}}}
limits: <explicit historical/provenance/applicability/rights/consumer boundaries>
```

The source identity still includes its original `sha256` and `rights`. No
correction pairs, DTO, quarantine decisions, runtime manifest, `CURRENT` or full
portable package is included. Consumers retain all domain interpretation.
In particular, moving these bytes does not remove or repair the two reported
Druid orphan override pairs (19680→40837 and 55194→57601).

Sidecars `manifest.json`, `package.json` and the existing publisher's
`git-handoff.json` supply exact ZIP/manifest length and SHA-256,
`expanded_bytes`, repository, path, ref, full artifact revision and local bare
path. The bare artifact commit is orphaned; it contains only the ZIP at the
declared path. It is staged locally without a checkout, remote or push. The
coordinator reviews and publishes it, then pins the exact RePoE Git artifact
for downstream acquisition. The source branch contains only code and metadata.

## Focused regression checks

```sh
python3 -B -S -m unittest discover -s tests -p test_official_tree_input.py -v
```

Small synthetic tests cover fixed-source identity, input/plan/producer pins,
cache corruption, offline misses, mocked HTTP rejection and timeout, path and
output failures, completion-last checks, deterministic replay and fresh local
bare fetch without the original cache. Synthetic producer blob reads are mocked;
the migration's real artifact additionally verifies committed producer blobs.
The original 5 MiB input is packaged once offline after copying the named cache;
all ZIP members and the complete raw byte equality are independently verified
under OS denial of network and PoBR-root reads. Original caching is migration
provenance, not a new HTTP observation. Old domain tests, current native exports,
Rust builds and the full source test suite are outside this change.
