"""Acquire/export an explicit, byte-pinned historical official Git tree input.

Only opaque original bytes are retained. Source declarations are not new Git
origin observations, patch applicability decisions, or redistribution approval.
"""

import argparse
import io
import math
from pathlib import Path
import re
import stat
import subprocess
import sys
import urllib.request
import zipfile

from . import data_publication as pub
from . import source_io as sio

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "https://github.com/grindinggear/poe2-skilltree-export"
MAX_BYTES = 16 * 1024 * 1024
MAX_PLAN = 64 * 1024
PRODUCERS = (
    "RePoE/__init__.py",
    "RePoE/official_tree_input.py",
    "RePoE/source_io.py",
    "RePoE/data_publication.py",
)
FORMAT = "repoe-official-tree-input/v1"


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _path(path):
    return pub.safe_path(path)


def _read(path, cap):
    return sio.read_file(_path(path), cap)


def _pin(raw):
    return {"bytes": len(raw), "sha256": sio.sha256(raw)}


def _pinned(path, expected):
    raw = _read(path, expected["bytes"])
    _require(_pin(raw) == expected, "Input bytes/SHA-256 mismatch")
    return raw


def _revision(value):
    _require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value), "Full Git revision required")
    return value


def validate_plan(plan):
    """Validate a fully explicit historical source; never infer an identity."""
    _require(
        isinstance(plan, dict)
        and set(plan) == {"schema", "source", "input", "publication"}
        and plan["schema"] == "repoe-official-tree-plan/v1",
        "Unsupported explicit source plan",
    )
    source = plan["source"]
    _require(
        isinstance(source, dict)
        and set(source)
        == {"kind", "repository", "revision", "path", "sha256", "upstream_version", "game_patch", "realm", "rights"},
        "Exact source identity required (no consumer corrections)",
    )
    _require(
        source["kind"] == "official-passive-tree"
        and source["repository"] == REPOSITORY
        and source["path"] == "data.json"
        and source["game_patch"] is None
        and source["realm"] == "international"
        and isinstance(source["upstream_version"], str)
        and re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", source["upstream_version"]),
        "Unsupported historical source identity",
    )
    _revision(source["revision"])
    sio.digest(source["sha256"])
    rights = source["rights"]
    _require(
        isinstance(rights, dict)
        and set(rights) == {"owner", "terms", "scope"}
        and all(isinstance(value, str) and value for value in rights.values()),
        "Explicit original rights declaration required",
    )
    expected = plan["input"]
    _require(isinstance(expected, dict) and set(expected) == {"bytes", "sha256"}, "Exact input pin required")
    pub.validate_pin(expected)
    _require(0 < expected["bytes"] <= MAX_BYTES and expected["sha256"] == source["sha256"], "Input pin/bound mismatch")
    publication = plan["publication"]
    _require(
        isinstance(publication, dict)
        and set(publication) == {"repository", "path", "ref"}
        and publication["repository"] == "ackness/repoe",
        "Independent RePoE publication required",
    )
    pub.relative(publication["path"])
    _require(publication["path"].endswith("/data.zip"), "ZIP artifact path required")
    ref = publication["ref"]
    _require(
        isinstance(ref, str)
        and re.fullmatch(r"refs/heads/handoff/[A-Za-z0-9._/-]+", ref)
        and all(part and not part.startswith(".") and not part.endswith((".", ".lock")) for part in ref.split("/"))
        and ".." not in ref,
        "Invalid local handoff ref",
    )


def _plan(path, expected_sha256):
    sio.digest(expected_sha256)
    raw = _read(path, MAX_PLAN)
    _require(sio.sha256(raw) == expected_sha256, "Plan SHA-256 mismatch")
    plan = sio.decode(raw)
    validate_plan(plan)
    return raw, plan


def source_url(source):
    """Construct exactly one immutable raw Git blob URL, never a branch/index."""
    _require(
        source["repository"] == REPOSITORY and source["path"] == "data.json",
        "Unsupported fixed Git source",
    )
    revision = _revision(source["revision"])
    return f"https://raw.githubusercontent.com/grindinggear/poe2-skilltree-export/{revision}/data.json"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Redirects are forbidden for the fixed Git blob")


def _timeout(timeout):
    _require(
        isinstance(timeout, (int, float))
        and not isinstance(timeout, bool)
        and math.isfinite(timeout)
        and 0 < timeout <= 30,
        "HTTP timeout must be finite and within (0, 30] seconds",
    )


def _http_body(source, expected, timeout):
    """Run only inside the deadline-bounded worker (mocked directly in tests)."""
    _timeout(timeout)
    url = source_url(source)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    request = urllib.request.Request(
        url, headers={"Accept-Encoding": "identity", "User-Agent": "RePoE historical input"}
    )
    with opener.open(request, timeout=timeout) as response:
        _require(response.status == 200 and response.geturl() == url, "Wrong fixed Git response identity/status")
        headers = {}
        for name, value in response.headers.items():
            name = name.lower()
            _require(name not in headers, "Duplicate HTTP header")
            headers[name] = value
        _require(
            "transfer-encoding" not in headers
            and headers.get("content-length") == str(expected["bytes"])
            and headers.get("content-encoding", "identity").lower() == "identity",
            "Expected bounded identity HTTP body",
        )
        # Reject chunked framing above: read(n) must not consume unbounded trailers.
        raw = response.read(expected["bytes"] + 1)
    _require(_pin(raw) == expected, "Downloaded bytes/SHA-256 mismatch")
    return raw


def _download(source, expected, timeout):
    # urllib's socket timeout alone cannot bound DNS or a slowly dripping body.
    # A short-lived stdlib worker gives the whole request a kill/reap deadline.
    _timeout(timeout)
    worker = (
        "import sys; from RePoE.official_tree_input import _http_body; "
        "from RePoE.source_io import decode; "
        "p=decode(sys.stdin.buffer.read()); "
        "sys.stdout.buffer.write(_http_body(p['source'],p['input'],p['timeout']))"
    )
    result = subprocess.run(
        [sys.executable, "-B", "-S", "-c", worker],
        cwd=ROOT,
        input=sio.encoded({"source": source, "input": expected, "timeout": timeout}),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=True,
    )
    _require(_pin(result.stdout) == expected, "Downloaded bytes/SHA-256 mismatch")
    return result.stdout


def _disjoint(output, *inputs):
    _require(
        all(not output.is_relative_to(path) and not path.is_relative_to(output) for path in inputs),
        "Output overlaps an input/cache/producer",
    )


def _cache_path(cache, plan):
    cache = _path(cache)
    _require(cache.is_relative_to(ROOT / ".cache"), "RePoE repository cache required")
    path = _path(cache / plan["input"]["sha256"] / "data.json")
    _require(all(not parent.exists() or parent.is_dir() for parent in path.parents), "Corrupt cache directory")
    return path


def _acquire(plan, cache, offline, timeout):
    path = _cache_path(cache, plan)
    if path.exists():
        # A present corrupt cache is an error even when online; never repair it.
        _pinned(path, plan["input"])
        return path, "existing-cache"
    _require(offline is False, "Offline cache miss; no source fallback")
    raw = _download(plan["source"], plan["input"], timeout)
    sio.write_new(path, raw)
    _pinned(path, plan["input"])
    return path, "fixed-git-blob-http"


def acquire(plan_path, plan_sha256, cache, *, offline=True, timeout=15):
    """Return a verified cache entry; only explicit online mode permits HTTP."""
    plan_raw, plan = _plan(plan_path, plan_sha256)
    cache = _path(cache)
    _disjoint(cache, _path(plan_path), *(_path(ROOT / name) for name in PRODUCERS))
    path, transport = _acquire(plan, cache, offline, timeout)
    _require(_read(plan_path, MAX_PLAN) == plan_raw, "Source plan changed during acquisition")
    _pinned(path, plan["input"])
    return {"path": str(path), **plan["input"], "transport": transport}


def _committed(revision, name):
    return subprocess.check_output(["git", "-C", str(ROOT), "cat-file", "blob", f"{revision}:{name}"])


def _producer(revision):
    _revision(revision)
    kind = subprocess.check_output(["git", "-C", str(ROOT), "cat-file", "-t", revision]).strip()
    _require(kind == b"commit", "Producer revision must name an actual commit")
    files = {}
    for name in PRODUCERS:
        raw = _read(ROOT / name, 1024 * 1024)
        _require(raw == _committed(revision, name), f"Producer differs from committed revision: {name}")
        files[name] = _pin(raw)
    return {
        "repository": "ackness/repoe",
        "revision": revision,
        "module": "RePoE.official_tree_input",
        "files": files,
    }


def _archive(raw, manifest_raw):
    buffer = io.BytesIO()
    # Stored members make replay independent of the installed zlib version.
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, body in (("data.json", raw), ("manifest.json", manifest_raw)):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, body)
    return buffer.getvalue()


def export(plan_path, plan_sha256, cache, output, producer_revision, *, offline=True, timeout=15):
    """Create a fresh completion-last package, rechecking all mutable inputs."""
    plan_path, cache, output = map(_path, (plan_path, cache, output))
    _require(output.is_relative_to(ROOT / ".cache") and not output.exists(), "Fresh RePoE cache output required")
    _disjoint(output, plan_path, cache, *(ROOT / name for name in PRODUCERS))
    _disjoint(cache, plan_path, *(ROOT / name for name in PRODUCERS))
    plan_raw, plan = _plan(plan_path, plan_sha256)
    producer = _producer(producer_revision)
    path, _ = _acquire(plan, cache, offline, timeout)
    raw = _pinned(path, plan["input"])
    manifest = {
        "schema": FORMAT,
        "status": "historical-diagnostic-candidate",
        "production_ready": False,
        "source": plan["source"],
        "plan": _pin(plan_raw),
        "producer": producer,
        "files": {"data.json": plan["input"]},
        "limits": [
            "Original bytes and retained source declaration; no new Git-origin attestation or acquisition receipt.",
            "Unknown game_patch; upstream_version does not establish current client/patch applicability.",
            "No semantic correction, source approval, redistribution approval or runtime adoption.",
            "Consumer corrections, domain adapters, quarantine and language remain outside this input package.",
        ],
    }
    manifest_raw = sio.encoded(manifest)
    archive_raw = _archive(raw, manifest_raw)
    result = {
        "schema": "repoe-data-package/v1",
        "publication": "local-only",
        **plan["publication"],
        **_pin(archive_raw),
        "manifest": _pin(manifest_raw),
        "expanded_bytes": len(raw) + len(manifest_raw),
        "plan": _pin(plan_raw),
    }
    output.mkdir(parents=True, exist_ok=False)
    sio.write_new(output / "data.zip", archive_raw)
    sio.write_new(output / "manifest.json", manifest_raw)
    _pinned(output / "data.zip", _pin(archive_raw))
    _pinned(output / "manifest.json", _pin(manifest_raw))
    _require(_read(plan_path, MAX_PLAN) == plan_raw, "Source plan changed during export")
    _pinned(path, plan["input"])
    _require(_producer(producer_revision) == producer, "Producer changed during export")
    # package.json is the completion marker; partial failures never write it.
    sio.write_new(output / "package.json", sio.encoded(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("acquire", "export"):
        command = sub.add_parser(name)
        command.add_argument("--plan", type=Path, required=True)
        command.add_argument("--plan-sha256", required=True)
        command.add_argument("--cache", type=Path, required=True)
        command.add_argument(
            "--online", action="store_true", help="Permit one fixed Git blob HTTP request on cache miss"
        )
        command.add_argument("--timeout", type=float, default=15)
        if name == "export":
            command.add_argument("--out", type=Path, required=True)
            command.add_argument("--producer-revision", required=True)
    args = parser.parse_args()
    options = {"offline": not args.online, "timeout": args.timeout}
    if args.command == "acquire":
        result = acquire(args.plan, args.plan_sha256, args.cache, **options)
    else:
        result = export(args.plan, args.plan_sha256, args.cache, args.out, args.producer_revision, **options)
    print(sio.encoded(result).decode(), end="")


if __name__ == "__main__":
    main()
