"""Build and verify native PoE2 schema candidates without replacing PyPoE data."""

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _inputs(root):
    schema = (root / "schema/poe2.json").read_bytes()
    checksum = (root / "schema/SHA256SUMS").read_text().split()
    if (
        len(checksum) != 2
        or checksum[1] != "schema/poe2.json"
        or not re.fullmatch(r"[a-f0-9]{64}", checksum[0])
        or _sha(schema) != checksum[0]
    ):
        raise ValueError("Prepared schema checksum mismatch")
    source = json.loads((root / "schema/source.json").read_bytes())
    if (
        source["schema_version"] != 1
        or source["kind"] != "build-tool-schema-input"
        or json.loads(schema)["version"] != source["schema_format"]
    ):
        raise ValueError("Unsupported schema input receipt")
    project = tomllib.loads((root / "pyproject.toml").read_text())
    pins = [
        match
        for dependency in project["project"]["dependencies"]
        if (match := re.fullmatch(r"(?i:pypoe)\s*@\s*git\+(https://[^@\s]+)@([a-f0-9]{40})", dependency))
    ]
    if len(pins) != 1:
        raise ValueError("PyPoE must be pinned to one HTTPS Git source with a full revision")
    source_url, revision = pins[0].groups()
    package = importlib.metadata.distribution("PyPoE")
    installed = json.loads(package.read_text("direct_url.json") or "{}")
    if (
        installed.get("vcs_info", {}).get("commit_id") != revision
        or installed.get("url") != source_url
        or installed.get("dir_info", {}).get("editable")
    ):
        raise ValueError("Installed PyPoE differs from the noneditable Git pin; run mise run setup")
    package_root = Path(importlib.util.find_spec("PyPoE").origin).parent
    # Native conversion never reads the installed legacy data specifications.
    pypoe_files = {
        path.relative_to(package_root).as_posix(): _sha(path.read_bytes())
        for path in sorted(package_root.rglob("*.py"))
        if not path.is_relative_to(package_root / "poe/file/specification/data")
    }
    producer = {
        name: _sha((root / name).read_bytes())
        for name in [
            "RePoE/schema_candidate.py",
            "pyproject.toml",
            "uv.lock",
            "schema/source.json",
            "schema/SHA256SUMS",
        ]
    }
    return {
        "schema_sha256": _sha(schema),
        "source": source,
        "pypoe_revision": revision,
        "pypoe_sources": pypoe_files,
        "producer": producer,
        "python": sys.version.split()[0],
    }, schema


def _native_specification(schema):
    # Calls the pinned upstream converter; no legacy adaptation or copied parser.
    from PyPoE.poe.file.specification.generation import import_dat_schema as converter

    tables = converter._load_dat_schema_tables(schema.decode("utf-8"), 2)
    text = converter._convert_tables(tables, {}, 2)
    namespace = {"__name__": "repoe_native_schema"}
    exec(compile(text, "<verified-native-schema>", "exec"), namespace)
    specification = namespace["specification"]
    specification.validate()
    if len(specification) != len(tables):
        raise ValueError("Native conversion changed the table inventory")
    for table in tables:
        converted = specification[f"{table.name}.dat"]
        expected = sum(2 if column.interval else 1 for column in table.columns)
        if len(converted.fields) != expected or converted.virtual_fields:
            raise ValueError(f"Native conversion lost columns or added compatibility views: {table.name}")
    return text.encode("utf-8"), specification


def _document(inputs, raw, specification):
    return {
        "schema_version": 1,
        "kind": "repoe-schema-candidate",
        "mode": "client-native",
        "inputs": inputs,
        "files": {"specification.py": _sha(raw)},
        "validation": {
            "structural": "passed",
            "tables": len(specification),
            "physical_fields": sum(len(table.fields) for table in specification.values()),
            "compatibility_views": 0,
        },
        "game_patch": None,
        "publication": "blocked: client decoding and per-module compatibility not certified",
    }


def load_candidate(directory, *, root=None):
    """Verify bytes against locked inputs, then return a strictly validated spec.

    Regeneration prevents a forged receipt from authorizing arbitrary Python in a
    supplied candidate. Only converter output from the pinned schema is executed.
    """
    root = Path(root) if root is not None else ROOT
    directory = Path(directory)
    inputs, schema = _inputs(root)
    raw, specification = _native_specification(schema)
    document = json.loads((directory / "candidate.json").read_bytes())
    if document != _document(inputs, raw, specification):
        raise ValueError("Schema candidate provenance or validation differs from locked inputs")
    if (directory / "specification.py").read_bytes() != raw:
        raise ValueError("Schema candidate content differs from the verified converter output")
    if _inputs(root)[0] != inputs:
        raise ValueError("Schema inputs changed during verification")
    return specification


def create_candidate(output, *, root=None):
    root = Path(root) if root is not None else ROOT
    output = Path(output).resolve()
    cache = (root / ".cache").resolve()
    if output == cache or not output.is_relative_to(cache):
        raise ValueError("Schema candidates must be new directories beneath this checkout's .cache/")
    if output.exists():
        raise FileExistsError(f"Refusing to replace an existing schema candidate: {output}")
    inputs, schema = _inputs(root)
    raw, specification = _native_specification(schema)
    document = _document(inputs, raw, specification)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".schema-", dir=output.parent) as temporary:
        staging = Path(temporary) / "candidate"
        staging.mkdir()
        (staging / "specification.py").write_bytes(raw)
        (staging / "candidate.json").write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if _inputs(root)[0] != inputs:
            raise ValueError("Schema inputs changed during generation")
        # Reserve without replacing even an empty concurrent directory. The
        # receipt is the last completion marker; partial output is never valid.
        output.mkdir()
        os.link(staging / "specification.py", output / "specification.py")
        os.link(staging / "candidate.json", output / "candidate.json")
    return document


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = create_candidate(args.out)
    except (ValueError, OSError) as error:
        parser.exit(1, f"Schema candidate rejected: {error}\n")
    print(f"Native schema candidate: {args.out} ({result['validation']['tables']} tables; not published)")


if __name__ == "__main__":
    main()
