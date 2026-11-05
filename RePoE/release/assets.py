"""Pinned GitHub Release assets: downloaded anonymously, verified and cached by SHA-256.

A package spec without a Git ``revision`` is a Release asset:
``{repository, tag, asset, bytes, sha256}`` (plus the package's own fields such
as ``manifest`` and ``expanded_bytes``). The default transport is anonymous
HTTPS to ``https://github.com/<repository>/releases/download/<tag>/<asset>``,
which GitHub redirects to its asset storage. ``REPOE_RELEASE_BASE_URL``
replaces ``https://github.com`` (a mirror, or a local server in a rehearsal);
``REPOE_RELEASE_TRANSPORT=gh`` uses ``gh release download`` and its login
instead (a private repository or a draft). The bytes are trusted only after
they match the pin; the cache holds verified bytes under their SHA-256.
"""

import http.client
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.error import HTTPError
from urllib.parse import quote
import urllib.request

from RePoE.pins import pin, require, validate_pin

BASE_URL = "REPOE_RELEASE_BASE_URL"
TRANSPORT = "REPOE_RELEASE_TRANSPORT"
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
TAG = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*")
ASSET = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*")


def is_release(spec):
    """Git packages carry a ``revision`` and a ``path``; every other package is a Release asset."""
    return "revision" not in spec


def validate(spec):
    require(
        isinstance(spec.get("repository"), str) and REPOSITORY.fullmatch(spec["repository"]),
        "Release asset: invalid repository",
    )
    tag = spec.get("tag")
    require(isinstance(tag, str) and TAG.fullmatch(tag) and ".." not in tag, f"Release asset: invalid tag {tag!r}")
    require(isinstance(spec.get("asset"), str) and ASSET.fullmatch(spec["asset"]), "Release asset: invalid name")
    require("path" not in spec, "A Release asset has no Git path")
    validate_pin(spec)


def label(spec):
    return f"{spec['repository']} {spec['tag']} {spec['asset']}"


def url(spec, base=None):
    base = (base or os.environ.get(BASE_URL) or "https://github.com").rstrip("/")
    return f"{base}/{spec['repository']}/releases/download/{quote(spec['tag'], safe='/')}/{quote(spec['asset'])}"


class Transient(Exception):
    """A failure worth retrying: network, HTTP 5xx/429 or a truncated body."""


def https(spec, max_bytes, timeout):
    request = urllib.request.Request(url(spec), headers={"User-Agent": "repoe-release"})
    try:
        # urlopen follows GitHub's redirect to the asset storage host.
        with urllib.request.urlopen(request, timeout=timeout) as response:
            declared = response.headers.get("Content-Length")
            raw = response.read(max_bytes + 1)
    except HTTPError as error:
        error.close()
        if error.code == 429 or error.code >= 500:
            raise Transient(error) from error
        # 404 and other client errors are answers, not outages.
        hint = ""
        if error.code == 404:
            hint = f" (a draft Release or a private repository is not public: set {TRANSPORT}=gh to use gh's login)"
        raise ValueError(f"Cannot download {label(spec)}: {error}{hint}") from error
    except (OSError, http.client.HTTPException) as error:
        raise Transient(error) from error
    require(len(raw) <= max_bytes, f"{label(spec)} is larger than its pin")
    if declared is not None and int(declared) != len(raw):
        raise Transient(f"truncated: {len(raw)} of {declared} bytes")
    return raw


def gh(spec, max_bytes, timeout):
    command = ["gh", "release", "download", spec["tag"], "--repo", spec["repository"]]
    command += ["--pattern", spec["asset"], "--output", "-"]
    try:
        result = subprocess.run(
            command, capture_output=True, check=False, timeout=timeout, env={**os.environ, "GH_PROMPT_DISABLED": "1"}
        )
    except subprocess.TimeoutExpired as error:
        raise ValueError(f"gh release download {label(spec)} did not finish within {timeout} s") from error
    except OSError as error:
        raise ValueError(f"gh is not available for {TRANSPORT}=gh: {error}") from error
    require(result.returncode == 0, f"gh release download {label(spec)} failed: {result.stderr.decode().strip()}")
    require(len(result.stdout) <= max_bytes, f"{label(spec)} is larger than its pin")
    return result.stdout


def download(spec, transport=None, attempts=3, backoff=1.0, timeout=120):
    """The asset's bytes, at most ``spec['bytes']`` of them; not yet verified."""
    transport = transport or os.environ.get(TRANSPORT) or "https"
    require(transport in ("https", "gh"), f"{TRANSPORT} must be https or gh")
    if transport == "gh":
        return gh(spec, spec["bytes"], timeout)
    for attempt in range(1, attempts + 1):
        try:
            return https(spec, spec["bytes"], timeout)
        except Transient as error:
            if attempt == attempts:
                raise ValueError(f"Cannot download {label(spec)} after {attempt} attempts: {error}") from error
            time.sleep(backoff * 2 ** (attempt - 1))


def fetch(spec, cache, online, downloader=download):
    """Verified bytes of a pinned Release asset: from ``cache/downloads/<sha256>``, else downloaded if ``online``."""
    validate(spec)
    expected = {key: spec[key] for key in ("bytes", "sha256")}
    path = Path(cache) / "downloads" / spec["sha256"]
    if path.is_file():
        raw = path.read_bytes()
        require(pin(raw) == expected, f"Corrupt cache entry {path} for {label(spec)}; delete it")
        return raw
    require(online, f"Release asset {label(spec)} is not cached; rerun with --fetch")
    raw = downloader(spec)
    require(pin(raw) == expected, f"{label(spec)} does not match its pin ({pin(raw)})")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.{os.getpid()}.partial")
    partial.write_bytes(raw)
    partial.replace(path)
    return raw
