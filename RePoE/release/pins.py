"""Byte pins, strict JSON and safe-path helpers shared by the release build and exporters."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat

ROOT = Path(__file__).resolve().parents[2]
HEX = re.compile(r"[0-9a-f]{64}")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def constant(value):
        raise ValueError(f"Invalid JSON constant: {value}")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def validate_pin(expected):
    require(
        isinstance(expected, dict)
        and type(expected.get("bytes")) is int
        and expected["bytes"] >= 0
        and isinstance(expected.get("sha256"), str)
        and HEX.fullmatch(expected["sha256"]),
        "Invalid byte pin",
    )


def byte_pin(value):
    """Validate an exact ``{bytes, sha256}`` pin with no other fields."""
    require(isinstance(value, dict) and set(value) == {"bytes", "sha256"}, "Invalid byte pin fields")
    require(type(value["bytes"]) is int and value["bytes"] >= 0, "Invalid bytes")
    require(isinstance(value["sha256"], str) and HEX.fullmatch(value["sha256"]), "Invalid sha256")


def pinned(raw, expected):
    validate_pin(expected)
    require(pin(raw) == {key: expected[key] for key in ("bytes", "sha256")}, "Byte pin mismatch")
    return raw


def relative(name):
    require(
        isinstance(name, str)
        and name
        and "\\" not in name
        and ":" not in name
        and all(ord(c) >= 32 and ord(c) != 127 for c in name),
        "Unsafe member path",
    )
    path = PurePosixPath(name)
    require(
        bool(path.parts)
        and not path.is_absolute()
        and path.as_posix() == name
        and ".." not in path.parts
        and "." not in path.parts,
        "Unsafe member path",
    )
    return path


def safe_path(path):
    path = Path(path).absolute()
    require(".." not in path.parts and all(not p.is_symlink() for p in (path, *path.parents)), "Symlink/unsafe path")
    return path


def regular(path):
    path = safe_path(path)
    require(stat.S_ISREG(path.stat().st_mode), "Regular file required")
    return path


def archive_manifest(archive, spec):
    entries = archive.infolist()
    names = [entry.filename for entry in entries]
    require(len(names) == len(set(names)) and "manifest.json" in names, "Duplicate/missing archive member")
    for entry in entries:
        relative(entry.filename)
        require(
            not entry.is_dir() and stat.S_IFMT(entry.external_attr >> 16) in (0, stat.S_IFREG),
            "Non-regular archive member",
        )
    require(
        type(spec.get("expanded_bytes")) is int and sum(e.file_size for e in entries) == spec["expanded_bytes"],
        "Expanded size mismatch",
    )
    raw = pinned(archive.read("manifest.json"), spec["manifest"])
    manifest = decode(raw)
    require(set(names) == {"manifest.json", *manifest["files"]}, "Archive inventory mismatch")
    for name, expected in manifest["files"].items():
        relative(name)
        validate_pin(expected)
        require(archive.getinfo(name).file_size == expected["bytes"], "Member size mismatch")
    return raw, manifest
