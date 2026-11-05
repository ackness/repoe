"""Turn an owner-run local client capture into raw resources, a capture receipt and a source lock.

The owner copies the China (Tencent) client's index and bundles with the committed
``capture-sc.ps1``. This command verifies that copy against its own ``capture.json`` and
``SHA256SUMS``, locates explicit game paths in the captured index, and extracts them with
the same bundle, index and decoder code as ``client:source`` (a local byte source replaces
HTTP ranges). Patch and realm are owner declarations. Raw bytes stay under ``.cache/``;
only candidates derived from them are ever published.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import subprocess

from . import index as client_index
from . import source_draft as draft
from . import sources as client

ROOT = draft.ROOT
SCRIPT = Path(__file__).with_name("capture-sc.ps1")
CAPTURE_SCHEMA = "pobr-sc-client-capture/v1"
REQUEST_SCHEMA = "repoe-client-capture-request/v1"
RECEIPT_SCHEMA = "repoe-client-capture-receipt/v1"
STATUS = "unreviewed-acquisition-draft"
CAPTURE_JSON = "capture.json"
SUMS = "SHA256SUMS"
BUNDLES = "Bundles2"
INDEX = "_.index.bin"
RECEIPT = "capture-receipt.json"
LOCK = "source-lock.json"
REQUEST_COPY = "request.json"
RAW = "raw"
REALMS = {"china"}
LANGUAGES = ("Simplified Chinese", "Traditional Chinese")
MAX_FILES = 4096
MAX_FILE = client.MAX_BUNDLE_COMPRESSED
# Decoder declaration tables:candidate requires; tests pin it to RePoE.native.facts.
DECODER = {
    "repository": "https://github.com/repoe-fork/pypoe",
    "revision": "66d1d7442c5718260e1a8efd24989d22987e91af",
    "dat_schema_repository": "https://github.com/poe-tool-dev/dat-schema",
    "dat_schema_revision": "6034b071846ef61b39046ebdb59e6d5717179509",
    "schema_sha256": "50e098543345cf8323aeb294e2cfef1b6b44842faccf560ada935cebe22727df",
}
# Host paths of the machine that ran the decoder: not needed to reproduce, never published.
HOST_DECODER_FIELDS = ("executable", "module_path", "uv_lock_path")
# Numeric releases and conventional prereleases only; never carry arbitrary executable metadata.
VERSION = re.compile(r"[0-9]{1,6}(?:\.[0-9]{1,6}){1,5}(?:-(?:alpha|beta|rc)[0-9]{0,3})?")
LIMITS = [
    "game_patch and realm are owner declarations, not verified; the executable version is what capture-sc.ps1 observed.",
    "Hashes show the files are the ones the owner hashed (transfer integrity), not that they are authentic.",
    "Index path hashes are case-insensitive, non-cryptographic Murmur64A matches.",
    "capture.json is pinned by SHA-256 only; its client_root and timestamps are not copied.",
    "raw/ holds client bytes for local candidates only and is never published.",
]


def fields(value, required, label):
    draft.fields(value, required, label)
    return value


def count(value, label, high=MAX_FILE):
    if type(value) is not int or not 0 <= value <= high:
        raise ValueError(f"Invalid {label}")
    return value


def capture_path(name):
    """A path relative to ``Bundles2/`` as capture-sc.ps1 writes it."""
    path = client.relative(draft.text(name, "capture path", 512))
    if not name.endswith(".bin"):
        raise ValueError(f"Unexpected capture file: {name}")
    return path.as_posix()


def file_pin(entry, label):
    return {"bytes": count(entry["bytes"], label + " bytes"), "sha256": client.digest(entry["sha256"])}


def load_capture(root, expected_sha256):
    """Validate ``capture.json`` and ``SHA256SUMS`` against each other; no file bytes are read here."""
    raw = client.read_file(root / CAPTURE_JSON, 4 * client.MIB)
    if client.sha256(raw) != client.digest(expected_sha256):
        raise ValueError(f"capture.json SHA-256 {client.sha256(raw)} differs from the expected {expected_sha256}")
    capture = fields(
        client.decode(raw),
        (
            "schema",
            "realm_declared",
            "captured_utc",
            "client_root",
            "index",
            "executables",
            "files",
            "total_bytes",
            "script_sha256",
        ),
        "capture.json",
    )
    if capture["schema"] != CAPTURE_SCHEMA:
        raise ValueError("Unsupported capture schema")
    if capture["realm_declared"] not in REALMS:
        raise ValueError("Unsupported declared realm")
    if not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z", draft.text(capture["captured_utc"], "capture time", 32)):
        raise ValueError("Invalid capture time")
    draft.text(capture["client_root"], "client root")
    script = client.sha256(client.read_file(SCRIPT, client.MIB))
    if client.digest(capture["script_sha256"]) != script:
        raise ValueError(f"capture.json script_sha256 differs from the committed {SCRIPT.name} ({script})")
    entries = capture["files"]
    if not isinstance(entries, list) or not 2 <= len(entries) <= MAX_FILES:
        raise ValueError("Invalid capture file list")
    files, folded = {}, set()
    for entry in entries:
        fields(entry, ("path", "bytes", "sha256", "mtime_utc"), "capture file")
        name = capture_path(entry["path"])
        if name.casefold() in folded:
            raise ValueError(f"Duplicate capture file: {name}")
        folded.add(name.casefold())
        files[name] = file_pin(entry, name)
    if capture["total_bytes"] != sum(pin["bytes"] for pin in files.values()):
        raise ValueError("capture.json total_bytes differs from its files")
    index = fields(capture["index"], ("path", "bytes", "sha256", "mtime_utc"), "capture index")
    if index["path"] != INDEX or files.get(INDEX) != file_pin(index, INDEX):
        raise ValueError("capture.json index differs from its file entry")
    executables = capture["executables"]
    if not isinstance(executables, list) or len(executables) > 8:
        raise ValueError("Invalid capture executables")
    observed = []
    for exe in executables:
        fields(exe, ("name", "bytes", "sha256", "file_version", "product_version", "mtime_utc"), "executable")
        name = draft.text(exe["name"], "executable name", 128)
        if not re.fullmatch(r"PathOfExile[A-Za-z0-9_]*\.exe", name):
            raise ValueError("Unexpected executable name")
        versions = {
            key: exe[key]
            for key in ("file_version", "product_version")
            if isinstance(exe[key], str) and VERSION.fullmatch(exe[key])
        }
        observed.append({"name": name, **file_pin(exe, name), **versions})
    sums_raw = client.read_file(root / SUMS, client.MIB)
    sums = {}
    lines = sums_raw.decode("ascii").split("\n")
    if lines[-1] != "":
        raise ValueError("SHA256SUMS must end with a newline")
    for line in lines[:-1]:
        match = re.fullmatch(r"([a-f0-9]{64})  " + BUNDLES + r"/(.+)", line)
        if not match:
            raise ValueError(f"Malformed SHA256SUMS line: {line!r}")
        name = capture_path(match.group(2))
        if name in sums:
            raise ValueError(f"Duplicate SHA256SUMS path: {name}")
        sums[name] = match.group(1)
    if sums != {name: pin["sha256"] for name, pin in files.items()}:
        raise ValueError("SHA256SUMS and capture.json name different files or hashes")
    summary = {
        "schema": capture["schema"],
        "realm_declared": capture["realm_declared"],
        "captured_utc": capture["captured_utc"],
        "capture_json": {"bytes": len(raw), "sha256": client.sha256(raw)},
        "sha256sums": {"bytes": len(sums_raw), "sha256": client.sha256(sums_raw)},
        "script_sha256": script,
        "total_bytes": capture["total_bytes"],
        "files": dict(sorted(files.items())),
        "omitted_fields": ["client_root", "mtime_utc"],
    }
    observed_client = {
        "index": {"path": INDEX, **files[INDEX]},
        "executables": observed,
        "verification": "reported by capture-sc.ps1 on the owner's machine; observed, not verified",
    }
    return summary, observed_client, raw, sums_raw


def hash_file(path, cap):
    """Stream one regular, non-symlink file; return its pin."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > cap:
            raise ValueError(f"Not a bounded regular file: {path}")
        digest, size = hashlib.sha256(), 0
        while chunk := stream.read(client.MIB):
            digest.update(chunk)
            size += len(chunk)
    return {"bytes": size, "sha256": digest.hexdigest()}


def raise_error(error):
    raise error


def verify_files(root, files):
    """Every file on disk is listed, is a regular file and matches its listed size and hash."""
    root = client.safe_path(root)
    top = {entry.name for entry in os.scandir(root)}
    if top != {CAPTURE_JSON, SUMS, BUNDLES}:
        raise ValueError(f"Unexpected capture contents: {', '.join(sorted(top - {CAPTURE_JSON, SUMS, BUNDLES}))}")
    for name in (CAPTURE_JSON, SUMS, BUNDLES):
        info = (root / name).lstat()
        expected = stat.S_ISDIR if name == BUNDLES else stat.S_ISREG
        if not expected(info.st_mode):
            raise ValueError(f"Not a plain capture entry (symlink or special file): {name}")
    base = root / BUNDLES
    found, directories = set(), set()
    expected_directories = {p.as_posix() for name in files for p in Path(name).parents if p != Path(".")}
    for current, folders, names in os.walk(base, followlinks=False, onerror=raise_error):
        for name in [*folders, *names]:
            path = Path(current) / name
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise ValueError(f"Symlink in capture: {path.relative_to(root)}")
            if name in names and not stat.S_ISREG(info.st_mode):
                raise ValueError(f"Not a regular file: {path.relative_to(root)}")
            if name in folders:
                directories.add(path.relative_to(base).as_posix())
        for name in names:
            found.add((Path(current) / name).relative_to(base).as_posix())
            if len(found) > MAX_FILES:
                raise ValueError("Capture holds too many files")
    if found != set(files):
        extra, missing = sorted(found - set(files)), sorted(set(files) - found)
        raise ValueError(f"Capture files differ from capture.json: extra {extra}, missing {missing}")
    if directories != expected_directories:
        raise ValueError(
            f"Capture directories differ from capture.json: extra {sorted(directories - expected_directories)}"
        )
    for name, pin in files.items():
        if hash_file(base / name, MAX_FILE) != pin:
            raise ValueError(f"Size or SHA-256 mismatch: {BUNDLES}/{name}")


def load_request(path):
    raw = client.read_file(path, client.MIB)
    request = fields(client.decode(raw), ("schema", "resources"), "capture request")
    if request["schema"] != REQUEST_SCHEMA:
        raise ValueError("Unsupported capture request schema")
    paths = request["resources"]
    if not isinstance(paths, list) or not 1 <= len(paths) <= 128:
        raise ValueError("Expected 1..128 resource paths")
    draft.resource_paths(paths)
    groups = {}
    for name in paths:
        groups.setdefault(classify(name), []).append(name)
    return paths, groups, raw


def classify(name):
    """The source a path belongs to: stat descriptions, default tables or one locale's tables."""
    if name.startswith("Data/StatDescriptions/") and name.endswith(".csd"):
        return "stat-descriptions"
    match = re.fullmatch(r"Data/Balance/(?:([^/]+)/)?[A-Za-z][A-Za-z0-9_]*\.datc64", name)
    if match and match.group(1) is None:
        return "default"
    if match and match.group(1) in LANGUAGES:
        return match.group(1)
    raise ValueError(f"Unsupported capture resource (stat descriptions or default/zh tables only): {name}")


class LocalRanges:
    """The ``Ranges``/``RangeCache`` surface ``sources.Bundle`` reads, over verified in-memory files."""

    request_cap = client.MAX_RANGE

    def __init__(self):
        self.files = {}
        self.cache = self

    def add(self, url, raw):
        self.files[url] = raw

    def info(self, url):
        return (len(self.files[url]),)

    def read(self, url, start, length):
        raw = self.files[url]
        if start < 0 or length < 1 or start + length > len(raw):
            raise ValueError(f"Read outside captured file: {url} {start}+{length}")
        return raw[start : start + length]


def tools():
    paths = [Path(__file__), SCRIPT, Path(client_index.__file__), Path(draft.__file__), Path(client.__file__)]
    paths.append(Path(client.source_io.__file__))
    return {
        path.resolve().relative_to(draft.ROOT).as_posix(): client.sha256(client.read_file(path, 2 * client.MIB))
        for path in paths
    }


def source_lock(receipt_sha, summary, observed, game_patch, groups, resources):
    evidence = [
        {"kind": "client-capture-json", "sha256": summary["capture_json"]["sha256"]},
        {"kind": "client-capture-receipt", "sha256": receipt_sha},
        {"kind": "local-index", "sha256": observed["index"]["sha256"]},
    ]
    realm = summary["realm_declared"]
    sources = {}
    for group, names in sorted(groups.items()):
        source = {
            "kind": "official-client-resource-candidate",
            "game": "poe2",
            "game_patch": game_patch,
            "realm": realm,
            "acquisition": {"status": STATUS, "evidence": evidence},
            "decoder": DECODER,
            "declared_not_verified": ["game_patch", "realm"],
            "scope": "Owner-captured local client files (capture-sc.ps1, client:capture); not a production source.",
            "resources": {name: resources[name] for name in sorted(names)},
        }
        if group == "stat-descriptions":
            source["roots"] = sorted(names)
        elif group != "default":
            source["language"] = group
        sources[f"{realm}-{group.lower().replace(' ', '-')}"] = source
    return {"schema_version": 1, "sources": sources}


def decoder_receipt(decoder):
    """Fingerprint only the portable identity; keep the full identity for local re-verification."""
    identity = {k: v for k, v in decoder.identity.items() if k not in HOST_DECODER_FIELDS}
    return {
        **{k: v for k, v in decoder.receipt.items() if k not in HOST_DECODER_FIELDS},
        "identity_sha256": client.sha256(client.encoded(identity)),
    }


def capture(capture_root, expected_capture_sha256, request_path, game_patch, output, python, decoder_lock):
    capture_root, request_path = client.safe_path(capture_root), client.safe_path(request_path)
    output = client.safe_path(output)
    if output.exists():
        raise FileExistsError(f"Refusing to reuse existing output: {output}")
    cache = ROOT.resolve() / ".cache"
    if output == cache or not output.is_relative_to(cache):
        raise ValueError("Capture output must be beneath this checkout's .cache/ (raw client bytes stay local)")
    inputs = [capture_root, request_path, client.safe_path(decoder_lock)]
    if any(output == p or output.is_relative_to(p) or p.is_relative_to(output) for p in inputs):
        raise ValueError("Output must be separate from the capture, request and decoder inputs")
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){2,5}", draft.text(game_patch, "game patch", 64)):
        raise ValueError("Expected an explicit numeric game patch")
    paths, groups, request_raw = load_request(request_path)
    summary, observed, capture_raw, sums_raw = load_capture(capture_root, expected_capture_sha256)
    files = summary["files"]
    verify_files(capture_root, files)
    identity = tools()
    decoder = client.ExternalDecoder(python, decoder_lock, {"decoder": DECODER})

    ranges = LocalRanges()

    def opened(name):
        url = f"capture:{BUNDLES}/{name}"
        if url not in ranges.files:
            raw = client.read_file(capture_root / BUNDLES / name, MAX_FILE)
            if {"bytes": len(raw), "sha256": client.sha256(raw)} != files[name]:
                raise ValueError(f"Capture file changed after verification: {name}")
            ranges.add(url, raw)
        return url

    index_url = opened(INDEX)
    index_bundle = client.Bundle(index_url, ranges, decoder)
    matched, missing, framing = client_index.inspect_locations(index_bundle, paths)
    if missing:
        raise ValueError("Paths not found in the captured index: " + ", ".join(missing))
    chunks = framing.pop("decoded_chunks")
    framing.update(
        decoded_chunk_count=len(chunks),
        decoded_chunks_sha256=client.sha256(client.encoded(chunks)),
        index_raw_bytes=index_bundle.size,
    )
    del index_bundle
    ranges.files.pop(index_url)
    by_bundle = {}
    for name in paths:
        by_bundle.setdefault(matched[name]["bundle_name"], []).append(name)
    bundles, resources, extracted = {}, {}, {}
    for bundle_name, names in by_bundle.items():
        file = bundle_name + ".bundle.bin"
        if file not in files:
            raise ValueError(
                f"{names[0]}: the index places it in {file}, which the capture lacks; "
                f"rerun capture-sc.ps1 with -Extra '{file}'"
            )
        url = opened(file)
        bundle = client.Bundle(url, ranges, decoder)
        try:
            bundles[bundle_name] = {
                "file": file,
                **files[file],
                "raw_bytes": bundle.size,
                "chunk_size": bundle.chunk_size,
                "chunks": len(bundle.sizes),
            }
            for name in names:
                record = matched[name]
                if bundle.size != record["bundle_raw_bytes"]:
                    raise ValueError(
                        f"{file}: raw size {bundle.size} differs from the index {record['bundle_raw_bytes']}"
                    )
                raw = bundle.read(record["offset"], record["length"])
                if len(raw) != record["length"]:
                    raise ValueError(f"{name}: extracted {len(raw)} bytes, the index says {record['length']}")
                extracted[name] = raw
                resources[name] = {
                    "sha256": client.sha256(raw),
                    "bytes": len(raw),
                    "bundle": bundle_name,
                    "uncompressed_offset": record["offset"],
                    "uncompressed_length": record["length"],
                }
        finally:
            ranges.files.pop(url)
            del bundle
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "status": STATUS,
        "production_ready": False,
        "game": "poe2",
        "game_patch": game_patch,
        "realm": summary["realm_declared"],
        "declared_not_verified": ["game_patch", "realm"],
        "capture": summary,
        "observed_client": observed,
        "request": {"bytes": len(request_raw), "sha256": client.sha256(request_raw), "resources": len(paths)},
        "index": {"file": INDEX, **files[INDEX], "framing": framing},
        "bundles": dict(sorted(bundles.items())),
        "resources": dict(sorted(resources.items())),
        "decoder": decoder_receipt(decoder),
        "tools": identity,
        "limits": LIMITS,
    }
    receipt_raw = client.encoded(receipt)
    lock_raw = client.encoded(source_lock(client.sha256(receipt_raw), summary, observed, game_patch, groups, resources))

    output.parent.mkdir(parents=True, exist_ok=True)
    client.safe_path(output)
    output.mkdir()
    for name, raw in extracted.items():
        client.write_new(output / RAW / client.relative(name), raw)
    # Recheck the inputs and the written bytes before the completion files.
    for name, raw in extracted.items():
        if client.read_file(output / RAW / name, client.MAX_RESOURCE) != raw:
            raise ValueError(f"Raw output changed before completion: {name}")
    if (
        client.read_file(capture_root / CAPTURE_JSON, 4 * client.MIB) != capture_raw
        or client.read_file(capture_root / SUMS, client.MIB) != sums_raw
        or client.read_file(request_path, client.MIB) != request_raw
        or tools() != identity
        or client.read_file(decoder.lock_path, 2 * client.MIB) != decoder.lock_bytes
        or client.decode(decoder.run([], b"", 65536)) != decoder.identity
    ):
        raise ValueError("Capture, request, tools or decoder changed before completion")
    client.write_new(output / REQUEST_COPY, request_raw)
    client.write_new(output / SUMS, sums_raw)
    client.write_new(output / RECEIPT, receipt_raw)
    verify_files(capture_root, files)
    client.write_new(output / LOCK, lock_raw)  # completion marker, last
    return receipt, receipt_raw, lock_raw


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--capture", required=True, type=Path, help="capture-sc.ps1 output directory")
    parser.add_argument("--expect-capture-sha256", required=True, help="SHA-256 of capture.json the owner states")
    parser.add_argument("--request", required=True, type=Path, help=f"{REQUEST_SCHEMA} path list")
    parser.add_argument("--game-patch", required=True, help="declared target patch, e.g. 0.5.5.5")
    parser.add_argument("--out", required=True, type=Path, help="new directory beneath .cache/")
    parser.add_argument("--decoder-python", required=True, type=Path)
    parser.add_argument("--decoder-lock", required=True, type=Path, help="External environment's uv.lock")
    args = parser.parse_args(argv)
    try:
        receipt, receipt_raw, lock_raw = capture(
            args.capture,
            args.expect_capture_sha256,
            args.request,
            args.game_patch,
            args.out,
            args.decoder_python,
            args.decoder_lock,
        )
    except (ValueError, OSError, KeyError, TypeError, struct.error, UnicodeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"client_capture: {error}\n")
    lock = json.loads(lock_raw)
    print(
        json.dumps(
            {
                "status": STATUS,
                "receipt_sha256": client.sha256(receipt_raw),
                "source_lock_sha256": client.sha256(lock_raw),
                "sources": {key: len(source["resources"]) for key, source in lock["sources"].items()},
                "out": str(args.out),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
