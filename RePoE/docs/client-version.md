# Official PoE2 client version observation

RePoE owns patch discovery alongside the [source acquisition SDK](client-sources.md).
`RePoE.client_version` uses only the Python standard library and `RePoE.source_io`;
it imports no PyPoE, requests, decoder, Node helper or consumer checkout. The
one-time protocol reference is `ackness/pobr@8cfcd68b64ee579b7b002dec46e060f7cd88ef82`,
`pipeline/query-patch-version.mjs` and its tests. The Python implementation requires
HTTPS and ASCII numeric patch components.

## Query and parser integration

```python
from RePoE.client_version import parse_response, query

result = query()  # Explicit network operation: {"cdn": "https://.../", "version": "..."}
# Pure offline parser; returns the same two fields or None while incomplete:
result = parse_response(captured_bytes)
```

`query(*, host="patch.pathofexile2.com", port=13060, timeout=8.0)` sends exactly
handshake bytes `01 07` over one TCP connection. DNS, connection, handshake and
reads share an absolute monotonic deadline, at most eight seconds. A shorter
positive timeout and a different TCP address support local fake servers. Only
the first resolved address is attempted; failures propagate without retries,
alternate services, old cache lookups or database export. The DNS wait is bounded
by a daemon resolver thread; a late resolver result cannot open a connection.
The system resolver itself may finish after the caller's deadline.

The response cap is 65,536 received bytes, including the binary prefix. Reads
accumulate across arbitrary TCP and UTF-16LE boundaries. Both byte alignments
are searched for a complete `https://patch-poe2.poecdn.com/<numeric-patch>/` root,
where a patch has at least two dot-separated ASCII decimal components. Missing
components are never filled with zero. HTTP, relative URLs, different hosts,
ports, credentials and incomplete trailing slashes do not establish a root.
EOF, close, socket errors, over-cap responses and deadline expiry before a
complete root all fail. Success closes the connection immediately, without
waiting for EOF. TCP chunks are not protocol message boundaries.

`RePoE.parser.util.get_cdn_url(2)` now takes `query()["cdn"]`. Its existing console
message remains part of the exporter interface. Explicit `run_parser --file`
continues to bypass discovery. The PoE1 branch retains its existing third-party
behavior; this module implements only PoE2.

## CLI and optional raw observation

Run from this checkout with any supported Python, without environment setup:

```sh
python -B -m RePoE.client_version --help
# These commands perform a network query when explicitly invoked:
python -B -m RePoE.client_version
mise run client:version -- --out .cache/client-version/new-observation
# Local test endpoint override:
python -B -m RePoE.client_version --host 127.0.0.1 --port 13060 --timeout 1
```

Successful stdout is exactly one JSON object with `cdn` and `version`, also when
`--out` is supplied. Errors use stderr and a nonzero exit, with no success JSON.
No logs are mixed into stdout. The default query writes no files.

`observe(*, host=..., port=..., timeout=..., out=None)` returns an `Observation`
with `result` (the two fields), `raw` (exact bytes received), and `receipt`.
An optional fresh `out` directory is claimed exclusively before querying.
Existing outputs and symlink paths are rejected; outputs must be separate from
producer files and production data. Failed invocations may leave an incomplete
directory, but never write a success receipt.

The optional directory contains:

- `response.bin`: the unmodified received prefix through the read containing a
  complete root. This is **not necessarily the entire server message**; no bytes
  after connection closure are claimed.
- `observation.json`: completion marker, schema `repoe-client-version-observation/v1`,
  written last after rechecking response bytes and producer pins. It records
  requested host/port, connected peer, handshake hex, start/observation UTC times,
  deadline, cap, discovered root/version, actual received byte count and SHA-256,
  and producer code SHA-256s for `RePoE/__init__.py`, `RePoE/client_version.py` and
  `RePoE/source_io.py`, plus the running Python version. These pins identify the
  implementation bytes, not an independently authenticated environment. Consumers
  must select their own exact repository revision and file pins.

An observation says only what the selected endpoint advertised at that time.
The TCP exchange is unauthenticated. It does not certify client build, realm,
language, complete raw resources, decoder compatibility or game semantics.
No language is inferred from the CDN hostname. It does not create or approve a
source lock, change source acceptance or target locks, update `CURRENT`, or adopt
production data. Those remain explicit downstream decisions. Offline parsing of
historical bytes is never a new freshness observation.

## Focused offline validation

```sh
# Standard library only; fake TCP binds exclusively to loopback:
python -B -S -m unittest discover -s tests -p test_client_version.py -v
# Separately, in an already prepared exporter environment:
python -B -m unittest discover -s tests -p test_client_version_util.py -v
```

Tests cover the original five protocol cases, every prefix split on both UTF-16
alignments, exact/over-cap boundaries, DNS and socket errors, silent and dripping
timeouts, shared deadline accounting, client resource closure, raw/producer
mutation, receipt completion order, standalone CLI streams, PoE1 preservation and
explicit-file bypass. They acquire no live patch or CDN resources.
