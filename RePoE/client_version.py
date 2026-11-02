"""Observe the PoE2 patch endpoint's advertised CDN root (standard library only).

Protocol reference: ackness/pobr@8cfcd68b64ee579b7b002dec46e060f7cd88ef82,
pipeline/query-patch-version.mjs. This observation does not authenticate a client.
"""

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import ipaddress
import json
import math
from pathlib import Path
import queue
import re
import socket
import sys
import threading
import time

from . import source_io


HOST = "patch.pathofexile2.com"
PORT = 13060
HANDSHAKE = bytes.fromhex("0107")
TIMEOUT = 8.0
MAX_RESPONSE = 65536
RECEIPT = "observation.json"
_ROOT = re.compile(r"https://patch-poe2\.poecdn\.com/([0-9]+(?:\.[0-9]+)+)/")


def parse_response(raw: bytes) -> dict[str, str] | None:
    """Find the first complete HTTPS root on either UTF-16LE byte alignment.

    An incomplete trailing code unit is retained by the caller for the next read.
    None means no complete root yet, never a guessed or zero-filled version.
    """
    if len(raw) > MAX_RESPONSE:
        raise ValueError("Patch response exceeds 64 KiB")
    for offset in (0, 1):
        end = len(raw) - (len(raw) - offset) % 2
        text = raw[offset:end].decode("utf-16le", errors="surrogatepass")
        match = _ROOT.search(text)
        if match:
            return {"cdn": match[0], "version": match[1]}
    return None


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Patch discovery timed out (absolute deadline)")
    return remaining


def _address(host, port, deadline):
    # getaddrinfo has no timeout. Bound our wait without allowing a late DNS
    # result to open a socket. Numeric test endpoints need no resolver thread.
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        resolved = queue.SimpleQueue()

        def resolve():
            try:
                resolved.put(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))
            except (OSError, UnicodeError) as error:
                resolved.put(error)

        threading.Thread(target=resolve, daemon=True, name="repoe-patch-dns").start()
        try:
            addresses = resolved.get(timeout=_remaining(deadline))
        except queue.Empty:
            raise TimeoutError("Patch discovery timed out during DNS") from None
        if isinstance(addresses, (OSError, UnicodeError)):
            raise addresses
        if not addresses:
            raise OSError("Patch endpoint has no TCP address")
        family, kind, protocol, _, address = addresses[0]
        return family, kind, protocol, address
    family = socket.AF_INET6 if ip.version == 6 else socket.AF_INET
    return family, socket.SOCK_STREAM, 0, (str(ip), port)


def _exchange(host, port, timeout):
    if not isinstance(host, str) or not host or len(host) > 253 or any(c.isspace() or ord(c) < 32 for c in host):
        raise ValueError("Expected a TCP hostname or IP address")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("TCP port must be in 1..65535")
    if (
        not isinstance(timeout, (int, float))
        or isinstance(timeout, bool)
        or not math.isfinite(timeout)
        or not 0 < timeout <= TIMEOUT
    ):
        raise ValueError("Deadline must be positive and at most 8 seconds")
    deadline = time.monotonic() + timeout
    family, kind, protocol, address = _address(host, port, deadline)
    _remaining(deadline)
    # One connection only: no retry, alternate endpoint or version cache.
    with socket.socket(family, kind, protocol) as connection:
        try:
            connection.settimeout(_remaining(deadline))
            connection.connect(address)
            connection.settimeout(_remaining(deadline))
            connection.sendall(HANDSHAKE)
            raw = bytearray()
            while True:
                connection.settimeout(_remaining(deadline))
                chunk = connection.recv(min(4096, MAX_RESPONSE + 1 - len(raw)))
                _remaining(deadline)
                if not chunk:
                    raise ValueError("Patch response ended without a complete official CDN URL")
                raw.extend(chunk)
                result = parse_response(raw)
                _remaining(deadline)
                if result is not None:
                    peer = connection.getpeername()
                    return result, bytes(raw), {"address": peer[0], "port": peer[1]}
        except TimeoutError:
            raise TimeoutError("Patch discovery timed out (absolute deadline)") from None


def query(*, host=HOST, port=PORT, timeout=TIMEOUT) -> dict[str, str]:
    """Return exactly cdn/version; failure propagates and all sockets close."""
    return _exchange(host, port, timeout)[0]


@dataclass(frozen=True)
class Observation:
    result: dict[str, str]
    raw: bytes
    receipt: dict


def _producer_pins():
    package = Path(__file__).absolute().parent
    return {
        "RePoE/" + path.name: source_io.sha256(source_io.read_file(path, source_io.MIB))
        for path in (package / "__init__.py", Path(__file__), Path(source_io.__file__))
    }


def _utc():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def observe(*, host=HOST, port=PORT, timeout=TIMEOUT, out=None) -> Observation:
    """Keep exact received bytes and metadata; optionally complete a fresh directory.

    The raw prefix ends at the read containing a complete root, not necessarily
    at the server's message boundary. A failed invocation has no success receipt.
    """
    pins = _producer_pins()
    output = None
    if out is not None:
        output = source_io.safe_path(out)
        package = Path(__file__).absolute().parent
        protected = [package.parent / "data", package / "data", *(package.parent / p for p in pins)]
        if any(output == p or output.is_relative_to(p) or p.is_relative_to(output) for p in protected):
            raise ValueError("Observation output must be separate from data and producer files")
        output.parent.mkdir(parents=True, exist_ok=True)
        source_io.safe_path(output)
        output.mkdir()  # Exclusive claim; existing and symlink outputs fail before networking.
    started = _utc()
    result, raw, peer = _exchange(host, port, timeout)
    completed = _utc()
    receipt = {
        "schema": "repoe-client-version-observation/v1",
        "status": "endpoint-version-observation",
        "endpoint": {"host": host, "port": port, "peer": peer},
        "handshake_hex": HANDSHAKE.hex(),
        "started_at_utc": started,
        "observed_at_utc": completed,
        "deadline_seconds": timeout,
        "response_cap_bytes": MAX_RESPONSE,
        **result,
        "response": {"path": "response.bin", "bytes": len(raw), "sha256": source_io.sha256(raw)},
        "producer": {"module": "RePoE.client_version", "code_sha256": pins, "python": sys.version},
        "scope": "Endpoint-advertised version at observation time only; received prefix, not a complete message. "
        "Does not authenticate client build, realm, language, all raw resources or semantics; "
        "does not accept a source, select a target or adopt active data.",
    }
    if output is not None:
        source_io.write_new(output / "response.bin", raw)
        if source_io.read_file(output / "response.bin", MAX_RESPONSE) != raw:
            raise ValueError("Response bytes changed before completion")
    if _producer_pins() != pins:
        raise ValueError("Producer files changed during observation")
    if output is not None:
        source_io.write_new(output / RECEIPT, source_io.encoded(receipt))  # Completion last.
    return Observation(result, raw, receipt)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=HOST, help="TCP endpoint override (e.g. a local fake server)")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--timeout", type=float, default=TIMEOUT, help="Absolute deadline in seconds, at most 8")
    parser.add_argument(
        "--out", type=Path, help="Fresh directory for response.bin and completion-last observation.json"
    )
    args = parser.parse_args(argv)
    try:
        options = {"host": args.host, "port": args.port, "timeout": args.timeout}
        result = query(**options) if args.out is None else observe(**options, out=args.out).result
    except (OSError, ValueError) as error:
        parser.exit(1, f"client_version: {error}\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
