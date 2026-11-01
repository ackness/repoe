"""Export explicitly selected DAT64 facts with the existing pinned native reader."""

import argparse
from pathlib import Path
import re
import sys

from RePoE import native_descriptions as envelope
from RePoE import native_facts as facts
from RePoE import schema_candidate
from RePoE.native_tools import pinned_pypoe


ROOT = schema_candidate.ROOT
FORMAT = "repoe-native-tables/v1"
MAX_RAW_BYTES = 64 * 1024 * 1024


def _inputs(source_lock, source, raw, expected_source_lock_sha256):
    lock_bytes = envelope._read(Path(source_lock), 2 * 1024 * 1024)
    if not envelope._digest(expected_source_lock_sha256) or envelope._sha(lock_bytes) != expected_source_lock_sha256:
        raise ValueError("Source lock differs from external expected byte pin")
    lock = envelope._decode(lock_bytes)
    if type(lock.get("schema_version")) is not int or lock["schema_version"] != 1:
        raise ValueError("Unsupported source lock schema")
    selected = lock["sources"][source]
    acquisition = selected.get("acquisition")
    if (
        selected.get("kind") != "official-client-resource-candidate"
        or selected.get("game") != "poe2"
        or not isinstance(selected.get("game_patch"), str)
        or not re.fullmatch(r"\d+(?:\.\d+){2,5}", selected["game_patch"])
        or selected.get("realm") not in {"international", "china"}
        or not isinstance(acquisition, dict)
        or acquisition.get("status") not in {"unreviewed-acquisition-draft", "reviewed-source-input"}
        or not isinstance(acquisition.get("evidence"), list)
        or not acquisition["evidence"]
    ):
        raise ValueError("Explicit patch, realm and acquisition evidence required")
    for entry in acquisition["evidence"]:
        if (
            not isinstance(entry, dict)
            or set(entry) != {"kind", "sha256"}
            or not isinstance(entry["kind"], str)
            or not entry["kind"]
            or not envelope._digest(entry["sha256"])
        ):
            raise ValueError("Invalid acquisition evidence")
    decoder = selected["decoder"]
    for key, value in {
        "repository": "https://github.com/repoe-fork/pypoe",
        "revision": facts.PYPOE,
        "dat_schema_repository": "https://github.com/poe-tool-dev/dat-schema",
        "dat_schema_revision": facts.SCHEMA,
        "schema_sha256": facts.SCHEMA_SHA,
    }.items():
        if decoder.get(key) != value:
            raise ValueError(f"Selected table decoder pin mismatch: {key}")
    resources = selected.get("resources")
    if not isinstance(resources, dict) or not 0 < len(resources) <= 128:
        raise ValueError("Bounded explicit DAT resource inventory required")
    raw_root = Path(raw).resolve(strict=True)
    if not raw_root.is_dir():
        raise ValueError("Raw input root is not a directory")
    verified, names, total = {}, set(), 0
    for name, pin in resources.items():
        match = re.fullmatch(r"Data/Balance/([A-Za-z][A-Za-z0-9_]*)\.datc64", name)
        if not match or name.casefold() in names:
            raise ValueError("Unsafe, duplicate or non-DAT resource")
        names.add(name.casefold())
        if (
            not isinstance(pin, dict)
            or type(pin.get("bytes")) is not int
            or not 0 < pin["bytes"] <= 32 * 1024 * 1024
            or not envelope._digest(pin.get("sha256"))
        ):
            raise ValueError(f"Invalid raw fingerprint: {name}")
        total += pin["bytes"]
        if total > MAX_RAW_BYTES:
            raise ValueError("Selected DAT inventory exceeds byte bound")
        path = raw_root / name
        if not path.resolve(strict=True).is_relative_to(raw_root) or any(
            parent.is_symlink() for parent in [path, *path.parents] if parent != raw_root.parent
        ):
            raise ValueError("Raw resource escapes root or contains symlink")
        data = envelope._read(path, pin["bytes"])
        if len(data) != pin["bytes"] or envelope._sha(data) != pin["sha256"]:
            raise ValueError(f"Raw resource fingerprint mismatch: {name}")
        verified[name] = data
    return lock_bytes, selected, verified, raw_root


def _references(tables):
    """Check available physical targets; retain external dependencies explicitly."""
    external, checked = [], 0
    for name, table in tables.items():
        for column in table["columns"]:
            schema = column["schema"]
            target = (schema.get("references") or {}).get("table")
            if not target or schema["type"] not in {"row", "foreignrow"}:
                continue
            fields = column["physical_fields"]
            if len(fields) != 1:
                raise ValueError("Unsupported foreign reference physical layout")
            field = fields[0]
            occurrences = 0
            for row in table["rows"]:
                value = row["values"][field]
                values = value if schema["array"] else [value]
                for value in values:
                    if value is None:
                        continue
                    if type(value) is not int or value < 0:
                        raise ValueError(f"Invalid physical reference: {name}/{row['_row']}/{field}")
                    occurrences += 1
                    if target in tables:
                        if value >= len(tables[target]["rows"]):
                            raise ValueError(f"Unresolved selected reference: {name}/{row['_row']}/{field}")
                        checked += 1
            if target not in tables:
                external.append({"table": name, "field": field, "target": target, "nonnull_occurrences": occurrences})
    return {"checked_internal_references": checked, "external_references": external}


def _payloads(lock_bytes, selected, verified, source):
    with pinned_pypoe() as tools:
        inputs, schema = schema_candidate._inputs(ROOT)
        spec_raw, spec = schema_candidate._native_specification(schema)
        if inputs["schema_sha256"] != facts.SCHEMA_SHA or inputs["pypoe_revision"] != facts.PYPOE:
            raise ValueError("Installed schema/decoder differs from selected native pins")
        schemas = {table["name"]: table for table in envelope._decode(schema)["tables"]}
        tables = {}
        for resource, raw in sorted(verified.items()):
            name = Path(resource).stem
            if name not in schemas:
                raise ValueError(f"Selected table has no native schema: {name}")
            tables[name] = facts._decode_dat(name, raw, spec, schemas[name])
        if inputs != schema_candidate._inputs(ROOT)[0]:
            raise ValueError("Native schema/tool inputs changed during decoding")
    producer = {
        **inputs["producer"],
        **{
            name: envelope._sha((ROOT / name).read_bytes())
            for name in [
                "RePoE/native_tables.py",
                "RePoE/native_facts.py",
                "RePoE/native_dat.py",
                "RePoE/native_tools.py",
                "RePoE/native_descriptions.py",
                "schema/pypoe-sources.json",
            ]
        },
    }
    payloads = {"tables.json": facts._json(tables), "source-lock.json": lock_bytes}
    manifest = {
        "format": FORMAT,
        "status": "partial-candidate",
        "production_ready": False,
        "source_identity": {
            "source": source,
            "source_lock_sha256": envelope._sha(lock_bytes),
            "selected_source_sha256": envelope._sha(facts._json(selected)),
            **{key: selected[key] for key in ["kind", "game", "game_patch", "realm", "acquisition"]},
            "raw_resources": {
                name: {"bytes": len(raw), "sha256": envelope._sha(raw)} for name, raw in sorted(verified.items())
            },
        },
        "schema": {
            "revision": facts.SCHEMA,
            "sha256": inputs["schema_sha256"],
            "native_specification_sha256": envelope._sha(spec_raw),
            "compatibility_views": 0,
        },
        "decoder": {
            "pypoe_revision": inputs["pypoe_revision"],
            "python": inputs["python"],
            "sources": tools["sources"],
            "trusted_source_pin_sha256": tools["pin_sha256"],
        },
        "producer": producer,
        "row_key": facts.ROW_KEY,
        "summary": {"tables": {name: len(table["rows"]) for name, table in tables.items()}, **_references(tables)},
        "scope": "Selected physical DAT tables only. Preserve every field/order/null; no gameplay, localization or release-membership inference. External references require separately pinned inputs. Source status is not promoted.",
        "files": {name: {"bytes": len(raw), "sha256": envelope._sha(raw)} for name, raw in payloads.items()},
    }
    payloads["manifest.json"] = facts._json(manifest)
    return manifest, payloads


def create_candidate(*, source_lock, expected_source_lock_sha256, source, raw, out):
    sys.dont_write_bytecode = True
    output = Path(out).absolute()
    cache = ROOT.resolve(strict=True) / ".cache"
    if output.exists() or output.is_symlink():
        raise FileExistsError("Refusing to replace selected-table output")
    if output.resolve() == cache or not output.resolve().is_relative_to(cache):
        raise ValueError("Selected-table candidate must be inside this checkout's .cache")
    args = (source_lock, source, raw, expected_source_lock_sha256)
    lock_bytes, selected, verified, raw_root = _inputs(*args)
    if output.resolve().is_relative_to(raw_root):
        raise ValueError("Selected-table output cannot be inside raw input")
    manifest, payloads = _payloads(lock_bytes, selected, verified, source)
    if _inputs(*args)[:3] != (lock_bytes, selected, verified):
        raise ValueError("Selected raw inputs changed during decoding")
    for name, digest in manifest["producer"].items():
        if envelope._sha((ROOT / name).read_bytes()) != digest:
            raise ValueError("Selected-table producer changed during decoding")
    envelope._publish(output, raw_root, payloads)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["source-lock", "expected-source-lock-sha256", "source", "raw", "out"]:
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    try:
        manifest = create_candidate(**vars(args))
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, f"Selected native tables rejected: {error}\n")
    print(f"{FORMAT}: {manifest['summary']['tables']}; partial candidate, not adopted")


if __name__ == "__main__":
    main()
