"""Small standard-library file, JSON and fixed-source primitives.

Shared by acquisition and portable envelope verification; no HTTP client, decoder
or acquisition module is imported here. Public APIs are re-exported by client_sources.
One-time source: ackness/pobr@0d6fe696d21fcc8ed60b42ad93e7cb5aaa40f819,
pipeline/client_sources.py. Historical wire names remain compatible.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import urlsplit

MIB = 1024 * 1024
OFFICIAL_HOST = "patch-poe2.poecdn.com"


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()


def decode(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError(f"Non-JSON number: {value}")

    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)


def digest(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("Invalid SHA-256")
    return value


def relative(name):
    if (
        not isinstance(name, str)
        or not name
        or "\\" in name
        or ":" in name
        or any(part in {"", ".", ".."} for part in name.split("/"))
    ):
        raise ValueError(f"Unsafe relative path: {name!r}")
    return Path(name)


def safe_path(path):
    path = Path(os.path.abspath(path))
    # Do not resolve away symlinks (including a dangling destination).
    for part in [*reversed(path.parents), path]:
        if part.is_symlink():
            raise ValueError(f"Symlinks are not allowed: {part}")
    return path


def read_file(path, cap):
    path = safe_path(path)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > cap:
            raise ValueError(f"Input is not a bounded regular file: {path}")
        raw = stream.read(cap + 1)
    if len(raw) > cap:
        raise ValueError(f"Input exceeds cap: {path}")
    return raw


def write_new(path, raw):
    path = safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_path(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
    except BaseException:
        # Only unlink after our exclusive create succeeded. A failed receipt
        # write must not leave a completion marker; never unlink a prior file.
        path.unlink()
        raise


def official_url(url, base):
    if not isinstance(url, str):
        raise ValueError("Missing official source URL")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != OFFICIAL_HOST
        or parsed.query
        or parsed.fragment
        or not url.startswith(base)
        or not re.fullmatch(r"[A-Za-z0-9_./-]+", parsed.path)
        or any(p in {".", "..", ""} for p in parsed.path[1:].split("/"))
    ):
        raise ValueError(f"URL is outside the fixed official source: {url}")
    return url
