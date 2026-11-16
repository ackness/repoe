"""Validate pinned local prepare-patch inputs without acquiring or exporting anything."""

import os
from pathlib import Path
import re

from RePoE.client import sources as _client
from RePoE.native import facts as _facts, tables as _tables
from RePoE.release import inputs as _inputs, pins as _pins

SCHEMA = "repoe-prepare-patch/v1"

_MAX_JSON_BYTES = 2 * 1024 * 1024
_MAX_RETAINED_BYTES = 64 * 1024 * 1024
_MAX_TOTAL_RETAINED_BYTES = 256 * 1024 * 1024
_ID = re.compile(r"[a-z][a-z0-9-]{0,63}")
_PORTABLE_PART = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_. -]{0,254}")
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
}
_EXPORT_FIELDS = {
    "facts": {"id", "kind", "source", "package", "destination", "profile"},
    "tables": {"id", "kind", "source", "package", "destination", "language"},
    "descriptions": {"id", "kind", "source", "package", "destination"},
    "item-inheritance": {"id", "kind", "source", "package", "destination"},
    "crafting": {"id", "kind", "facts", "package", "destination"},
}


def _fields(value, expected, label):
    _pins.require(isinstance(value, dict) and set(value) == set(expected), f"Invalid {label} fields")


def _text(value, label):
    _pins.require(
        isinstance(value, str) and value and all(ord(character) >= 32 and ord(character) != 127 for character in value),
        f"Invalid {label}",
    )
    return value


def _input_path(value, parent):
    path = Path(_text(value, "input path"))
    return _pins.safe_path(path if path.is_absolute() else parent / path)


def _expected_pin(record, cap):
    expected = {key: record[key] for key in ("bytes", "sha256")}
    _pins.byte_pin(expected)
    _pins.require(expected["bytes"] <= cap, "Input byte pin exceeds byte bound")
    return expected


def _pinned_file(record, parent, cap):
    expected = _expected_pin(record, cap)
    path = _pins.regular(_input_path(record["path"], parent))
    raw = _pins.pinned(_client.read_file(path, cap), expected)
    record["path"] = path
    return raw


def _package(value):
    _pins.require(
        isinstance(value, str)
        and _inputs.NAME.fullmatch(value)
        and value.casefold() != "previous"
        and value.upper() not in _RESERVED_NAMES,
        "Invalid or reserved input package name",
    )
    return value


def _destination(value):
    path = _pins.relative(value)
    _pins.require(
        all(
            _PORTABLE_PART.fullmatch(part)
            and not part.endswith((".", " "))
            and part.split(".")[0].upper() not in _RESERVED_NAMES
            for part in path.parts
        ),
        "Unsafe portable destination",
    )
    _pins.require(path.parts[0].casefold() != "manifest.json", "Package root manifest.json is reserved")
    return path


def _validate_exports(exports):
    _pins.require(isinstance(exports, list) and 1 <= len(exports) <= 32, "Expected 1..32 exports")
    identifiers, source_names, facts, crafting = set(), [], [], []
    for position, export in enumerate(exports):
        _pins.require(isinstance(export, dict), "Export must be an object")
        kind = export.get("kind")
        _pins.require(isinstance(kind, str) and kind in _EXPORT_FIELDS, "Unsupported export kind")
        _fields(export, _EXPORT_FIELDS[kind], f"{kind} export")
        identifier = _text(export["id"], "export id")
        _pins.require(_ID.fullmatch(identifier) and identifier not in identifiers, "Invalid or duplicate export id")
        identifiers.add(identifier)
        package = _package(export["package"])
        if kind == "crafting":
            _pins.require(
                package == "crafting" and export["destination"] == ".", "Invalid crafting package/destination"
            )
            _text(export["facts"], "crafting facts reference")
            crafting.append((position, export))
            continue
        _pins.require(package.casefold() != "crafting", "Only the crafting export may target the crafting package")
        _destination(export["destination"])
        source = _text(export["source"], "export source")
        if source not in source_names:
            source_names.append(source)
        if kind == "facts":
            _pins.require(export["profile"] == _facts.ITEMS_ACTORS_PROFILE, "Unsupported facts profile")
            facts.append((position, export))
        elif kind == "tables":
            _pins.require(export["language"] in _tables.LANGUAGES, "Unsupported table language")
    _pins.require(len(facts) == 1 and len(crafting) == 1, "Exactly one facts and one crafting export are required")
    facts_position, facts_export = facts[0]
    crafting_position, crafting_export = crafting[0]
    _pins.require(
        crafting_position > facts_position and crafting_export["facts"] == facts_export["id"],
        "Crafting must follow and reference the facts export",
    )
    return source_names


def _validate_retained(retained):
    _pins.require(isinstance(retained, list) and len(retained) <= 512, "Expected at most 512 retained files")
    total = 0
    for record in retained:
        _fields(record, {"path", "package", "destination", "bytes", "sha256"}, "retained file")
        package = _package(record["package"])
        _pins.require(package.casefold() != "crafting", "Retained files cannot target the crafting package")
        destination = _destination(record["destination"])
        _pins.require(destination.suffix == ".json", "Retained destinations must end in .json")
        total += _expected_pin(record, _MAX_RETAINED_BYTES)["bytes"]
        _pins.require(total <= _MAX_TOTAL_RETAINED_BYTES, "Retained file total exceeds byte bound")


def _reserve(reservations, package, destination):
    parts = tuple(part.casefold() for part in destination.split("/"))
    existing = reservations.setdefault(package.casefold(), [])
    _pins.require(
        all(parts[: len(other)] != other and other[: len(parts)] != parts for other in existing),
        f"Destination collision in package {package}: {destination}",
    )
    existing.append(parts)


def _validate_layout(exports, retained):
    packages = sorted({record["package"] for record in [*exports, *retained]})
    _pins.require(
        len(packages) == len({package.casefold() for package in packages}), "Case-collision between input package names"
    )
    reservations = {}
    for export in exports:
        if export["kind"] != "crafting":
            _reserve(reservations, export["package"], export["destination"])
            _reserve(reservations, export["package"], export["destination"] + ".export-receipt.json")
    for record in retained:
        _reserve(reservations, record["package"], record["destination"])
    return packages


def _load_sources(source_lock, names, target, exports):
    selected = {}
    for name in names:
        try:
            source, digest = _client.load_source(source_lock["path"], name)
        except (KeyError, TypeError, UnicodeError, RecursionError) as error:
            raise ValueError(f"Invalid or missing selected source: {name}") from error
        _pins.require(digest == source_lock["sha256"], "Source lock changed after pin verification")
        _pins.require(
            all(source.get(key) == value for key, value in target.items()), "Source target differs from recipe"
        )
        acquisition = source.get("acquisition")
        _pins.require(
            isinstance(acquisition, dict)
            and acquisition.get("status") in ("unreviewed-acquisition-draft", "reviewed-source-input")
            and isinstance(acquisition.get("evidence"), list)
            and acquisition["evidence"],
            "Selected source needs acquisition status and nonempty evidence",
        )
        for evidence in acquisition["evidence"]:
            _fields(evidence, {"kind", "sha256"}, "acquisition evidence")
            _text(evidence["kind"], "acquisition evidence kind")
            _client.digest(evidence["sha256"])
        selected[name] = source
    for export in exports:
        if export["kind"] == "facts":
            source = selected[export["source"]]
            _pins.require(source.get("profile") == export["profile"], "Source facts profile differs from recipe")
            resources = {f"Data/Balance/{table}.datc64" for table in _facts.profile_tables(export["profile"])}
            _pins.require(set(source["resources"]) == resources | {_facts.PSG}, "Facts source resource closure differs")
        elif export["kind"] == "tables":
            _pins.require(
                selected[export["source"]].get("language", "English") == export["language"],
                "Source language differs from explicit table language",
            )
    return selected


def load_recipe(path: str | Path, expected_sha256: str) -> dict:
    """Return a verified recipe without executing commands or changing source status.

    The original mapping is preserved, with ``source_lock.path``,
    ``decoder.lock.path``, ``decoder.python`` and each ``retained[*].path``
    replaced by absolute ``Path`` objects. The executable keeps its symlink
    spelling. Retained inputs must be JSON objects or arrays; only their
    destination filenames, not the original filenames, must end in ``.json``.
    Added fields are ``pin`` (the recipe's actual bytes/SHA-256),
    ``source_names`` (unique export sources in first-appearance order),
    ``sources`` (those complete validated source entries) and ``packages``
    (the sorted unique export/retained package names).
    """
    _client.digest(expected_sha256)
    path = _pins.regular(path)
    raw = _client.read_file(path, _MAX_JSON_BYTES)
    actual_pin = _pins.pin(raw)
    _pins.require(actual_pin["sha256"] == expected_sha256, "Recipe SHA-256 mismatch")
    try:
        recipe = _pins.decode(raw)
    except (UnicodeError, RecursionError) as error:
        raise ValueError("Invalid recipe JSON") from error
    _fields(recipe, {"schema", "target", "source_lock", "decoder", "exports", "retained"}, "recipe")
    _pins.require(recipe["schema"] == SCHEMA, "Unsupported prepare-patch recipe schema")
    target = recipe["target"]
    _fields(target, {"game", "realm", "game_patch"}, "target")
    _pins.require(target["game"] == "poe2" and target["realm"] == "international", "Unsupported recipe target")
    _client.numeric_patch(target["game_patch"])
    _fields(recipe["source_lock"], {"path", "bytes", "sha256"}, "source lock")
    decoder = recipe["decoder"]
    _fields(decoder, {"python", "lock"}, "decoder")
    _fields(decoder["lock"], {"path", "bytes", "sha256"}, "decoder lock")
    python = Path(_text(decoder["python"], "decoder Python executable"))
    _pins.require(
        python.is_absolute() and python.is_file() and os.access(python, os.X_OK), "Invalid decoder executable"
    )
    decoder["python"] = python.absolute()
    source_names = _validate_exports(recipe["exports"])
    _validate_retained(recipe["retained"])
    packages = _validate_layout(recipe["exports"], recipe["retained"])
    _pinned_file(recipe["source_lock"], path.parent, _MAX_JSON_BYTES)
    _pinned_file(decoder["lock"], path.parent, _MAX_JSON_BYTES)
    for record in recipe["retained"]:
        raw = _pinned_file(record, path.parent, _MAX_RETAINED_BYTES)
        try:
            retained = _pins.decode(raw)
        except (UnicodeError, RecursionError) as error:
            raise ValueError("Invalid retained JSON") from error
        _pins.require(isinstance(retained, (dict, list)), "Retained JSON must be an object or array")
    sources = _load_sources(recipe["source_lock"], source_names, target, recipe["exports"])
    return {**recipe, "pin": actual_pin, "source_names": source_names, "sources": sources, "packages": packages}
