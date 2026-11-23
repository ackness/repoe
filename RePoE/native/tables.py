"""Export explicitly selected DAT64 facts with the existing pinned native reader."""

import argparse
from pathlib import Path
import re
import sys

from RePoE.client import export_receipt
from RePoE.client.limits import MAX_RESOURCE, MAX_SELECTED_RAW
from RePoE.native import envelope, facts, schema_candidate
from RePoE.native.tools import pinned_pypoe


ROOT = schema_candidate.ROOT
FORMAT = "repoe-native-tables/v1"
LOCALIZED_FORMAT = "repoe-localized-tables/v1"
LANGUAGES = ("English", "Simplified Chinese", "Traditional Chinese")


def _inputs(source_lock, source, raw, expected_source_lock_sha256, language="English"):
    lock_bytes, selected = envelope.load_source_lock(source_lock, source, expected_source_lock_sha256)
    if language not in LANGUAGES or selected.get("language", "English") != language:
        raise ValueError("Selected source language differs from explicit language")
    prefix = "Data/Balance/" + ("" if language == "English" else language + "/")
    envelope.validate_source_identity(selected, numeric_patch=True)
    envelope.validate_decoder(
        selected,
        {
            "repository": "https://github.com/repoe-fork/pypoe",
            "revision": facts.PYPOE,
            "dat_schema_repository": "https://github.com/poe-tool-dev/dat-schema",
            "dat_schema_revision": facts.SCHEMA,
            "schema_sha256": facts.SCHEMA_SHA,
        },
        error="Selected table decoder pin mismatch",
        include_key=True,
    )
    pattern = re.compile(re.escape(prefix) + r"([A-Za-z][A-Za-z0-9_]*)\.datc64")

    def validate_name(name):
        if not pattern.fullmatch(name):
            raise ValueError("Unsafe, duplicate or non-DAT resource")

    verified, raw_root = envelope.verify_raw_resources(
        raw,
        selected.get("resources"),
        max_files=128,
        max_resource_bytes=MAX_RESOURCE,
        max_total_bytes=MAX_SELECTED_RAW,
        validate_name=validate_name,
        check_case_collision=True,
        inventory_error="Bounded explicit DAT resource inventory required",
        case_collision_error="Unsafe, duplicate or non-DAT resource",
        total_error="Selected DAT inventory exceeds byte bound",
    )
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


def _payloads(lock_bytes, selected, verified, source, language="English"):
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
            tables[name]["raw_resource"] = resource
        if inputs != schema_candidate._inputs(ROOT)[0]:
            raise ValueError("Native schema/tool inputs changed during decoding")
    producer = {
        **inputs["producer"],
        **{
            name: envelope._sha((ROOT / name).read_bytes())
            for name in [
                "RePoE/native/tables.py",
                "RePoE/native/facts.py",
                "RePoE/native/dat.py",
                "RePoE/native/tools.py",
                "RePoE/native/envelope.py",
                "schema/pypoe-sources.json",
            ]
        },
    }
    payloads = {"tables.json": facts._json(tables), "source-lock.json": lock_bytes}
    manifest = {
        "format": FORMAT if language == "English" else LOCALIZED_FORMAT,
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
        export_receipt.FIELD: export_receipt.SCHEMA,
        "row_key": facts.ROW_KEY,
        "summary": {"tables": {name: len(table["rows"]) for name, table in tables.items()}, **_references(tables)},
        "scope": "Selected physical DAT tables only. Preserve every field/order/null; no gameplay, localization or release-membership inference. External references require separately pinned inputs. Source status is not promoted.",
        "files": {name: {"bytes": len(raw), "sha256": envelope._sha(raw)} for name, raw in payloads.items()},
    }
    if language != "English":
        manifest["source_identity"]["language"] = language
        manifest["scope"] += " Locale is explicit; no fallback to English, cross-locale joins or translation selection."
    payloads["manifest.json"] = facts._json(manifest)
    return manifest, payloads


def create_candidate(
    *, source_lock, expected_source_lock_sha256, source, raw, out, language="English", rehearsal=False
):
    sys.dont_write_bytecode = True
    output = Path(out).absolute()
    cache = ROOT.resolve(strict=True) / ".cache"
    if output.exists() or output.is_symlink():
        raise FileExistsError("Refusing to replace selected-table output")
    if output.resolve() == cache or not output.resolve().is_relative_to(cache):
        raise ValueError("Selected-table candidate must be inside this checkout's .cache")
    seal = export_receipt.begin(output, "RePoE.native.tables", rehearsal=rehearsal)
    args = (source_lock, source, raw, expected_source_lock_sha256, language)
    lock_bytes, selected, verified, raw_root = _inputs(*args)
    if output.resolve().is_relative_to(raw_root):
        raise ValueError("Selected-table output cannot be inside raw input")
    manifest, payloads = _payloads(lock_bytes, selected, verified, source, language)
    if _inputs(*args)[:3] != (lock_bytes, selected, verified):
        raise ValueError("Selected raw inputs changed during decoding")
    for name, digest in manifest["producer"].items():
        if envelope._sha((ROOT / name).read_bytes()) != digest:
            raise ValueError("Selected-table producer changed during decoding")
    envelope._publish(output, raw_root, payloads, root=ROOT)
    seal(payloads["manifest.json"])
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["source-lock", "expected-source-lock-sha256", "source", "raw", "out"]:
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--language", choices=LANGUAGES, default="English")
    export_receipt.add_rehearsal_option(parser)
    args = parser.parse_args()
    try:
        manifest = create_candidate(**vars(args))
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, f"Selected native tables rejected: {error}\n")
    print(f"{manifest['format']}: {manifest['summary']['tables']}; partial candidate, not adopted")


if __name__ == "__main__":
    main()
