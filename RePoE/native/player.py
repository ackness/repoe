"""Export pinned player-source context without choosing actor inheritance or formulas."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys

from RePoE.native import descriptions as io
from RePoE.native import facts
from RePoE.native import metadata
from RePoE.native import schema_candidate
from RePoE.native.tools import pinned_pypoe


ROOT = Path(__file__).resolve().parents[2]
TABLES = ("StartingPassiveSkills", "KeywordPopups")
PARENT_TABLES = ("Characters", "PassiveSkills", "Stats", "ClassPassiveSkillOverrides")
LIMITS = [
    "Source facts only; no source approval or runtime calculation admission.",
    "AO literal inheritance and the independent generic OT root remain distinct; no actor binding or stat merge.",
    "Starting relations do not allocate nodes, grant innate stats or interpret a flavour-text trait.",
    "Pool initialization offsets, accuracy baseline, attribute requirements and server cadence are not inferred.",
    "All metadata values remain lexical; glossary text is retained, not executed as a formula.",
]


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _integer(value):
    return type(value) is int and value >= 0


def _safe(name):
    if (
        not isinstance(name, str)
        or len(name) > 512
        or any(char in name for char in "\\:\x00")
        or any(ord(char) < 32 for char in name)
        or any(part in {"", ".", ".."} for part in name.split("/"))
    ):
        raise ValueError("Unsafe player-source path")


def _rows(document, name):
    rows = document.get("rows")
    if document.get("table") != name or not isinstance(rows, list):
        raise ValueError(f"Missing physical table {name}")
    ids = set()
    for index, row in enumerate(rows):
        if row.get("_row") != index or not isinstance(row.get("values"), dict):
            raise ValueError(f"Invalid physical order in {name}")
        if "Id" in row["values"]:
            identity = row["values"]["Id"]
            if not isinstance(identity, str) or not identity or identity in ids:
                raise ValueError(f"Invalid/duplicate stable ID in {name}")
            ids.add(identity)
    return rows


def _parent(directory, expected):
    directory = Path(directory).resolve(strict=True)
    manifest_bytes = io._read(directory / "manifest.json", 1024 * 1024)
    if not io._digest(expected) or _sha(manifest_bytes) != expected:
        raise ValueError("Parent facts differ from external expected manifest pin")
    manifest = io._decode(manifest_bytes)
    if (
        manifest.get("format") != "repoe-native-facts/v4"
        or manifest.get("profile") != "items-actors-bc"
        or manifest.get("production_ready") is not False
    ):
        raise ValueError("Expected a partial native v4 parent")
    files = manifest.get("files")
    if not isinstance(files, dict) or not 0 < len(files) <= 256:
        raise ValueError("Invalid parent payload inventory")
    expected_paths = {"manifest.json"}
    retained, total = {}, 0
    for name, fp in sorted(files.items()):
        _safe(name)
        expected_paths.add(name)
        if not isinstance(fp, dict) or not _integer(fp.get("bytes")) or not io._digest(fp.get("sha256")):
            raise ValueError("Invalid parent payload fingerprint")
        total += fp["bytes"]
        if total > 256 * 1024 * 1024:
            raise ValueError("Parent facts exceed total byte limit")
        path = directory / name
        if any(p.is_symlink() for p in [path, *path.parents] if p != directory.parent):
            raise ValueError("Parent facts contain symlink components")
        # Retain exactly consumed table bytes; stream other archive payloads.
        if name in {f"tables/{table}.json" for table in PARENT_TABLES}:
            data = io._read(path, fp["bytes"])
            actual, length = _sha(data), len(data)
            retained[name] = data
        else:
            digest, length = hashlib.sha256(), 0
            if not path.is_file():
                raise ValueError("Parent payload is not regular")
            with path.open("rb") as stream:
                while chunk := stream.read(65536):
                    length += len(chunk)
                    if length > fp["bytes"]:
                        raise ValueError("Parent payload grew beyond its fingerprint")
                    digest.update(chunk)
            actual = digest.hexdigest()
        if actual != fp["sha256"] or length != fp["bytes"]:
            raise ValueError(f"Parent payload fingerprint mismatch: {name}")
    observed = set()
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise ValueError("Parent inventory contains a symlink")
        if path.is_file():
            observed.add(path.relative_to(directory).as_posix())
    if observed != expected_paths:
        raise ValueError("Parent inventory differs from manifest")
    tables = {name: io._decode(retained[f"tables/{name}.json"]) for name in PARENT_TABLES}
    for name, table in tables.items():
        _rows(table, name)
    return directory, manifest_bytes, manifest, tables


def _inputs(lock_path, source, raw_root, expected):
    lock_bytes = io._read(Path(lock_path), 1024 * 1024)
    if not io._digest(expected) or _sha(lock_bytes) != expected:
        raise ValueError("Player source lock differs from external expected byte pin")
    lock = io._decode(lock_bytes)
    if lock.get("schema_version") != 1:
        raise ValueError("Unsupported player source lock")
    selected = lock["sources"][source]
    acquisition = selected.get("acquisition", {})
    if (
        selected.get("kind") != "official-client-resource-candidate"
        or selected.get("profile") != "player-context-a2"
        or selected.get("game") != "poe2"
        or selected.get("realm") not in {"international", "china"}
        or not isinstance(selected.get("game_patch"), str)
        or not selected["game_patch"]
        or acquisition.get("status") != "unreviewed-acquisition-draft"
        or not isinstance(acquisition.get("evidence"), list)
        or not acquisition["evidence"]
    ):
        raise ValueError("Explicit player source identity/acquisition declaration required")
    for item in acquisition["evidence"]:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("kind"), str)
            or not item["kind"]
            or not io._digest(item.get("sha256"))
        ):
            raise ValueError("Invalid player acquisition evidence")
    decoder = selected["decoder"]
    if (
        decoder.get("revision") != facts.PYPOE
        or decoder.get("dat_schema_revision") != facts.SCHEMA
        or decoder.get("schema_sha256") != facts.SCHEMA_SHA
    ):
        raise ValueError("Player decoder/schema pin mismatch")
    resources = selected["resources"]
    if not isinstance(resources, dict) or not 2 < len(resources) <= 32:
        raise ValueError("Bounded player resource inventory required")
    raw_root = Path(raw_root).resolve(strict=True)
    verified, total = {}, 0
    for name, fp in sorted(resources.items()):
        _safe(name)
        if name not in {f"Data/Balance/{table}.datc64" for table in TABLES}:
            metadata.resource_path(name)
        if (
            not isinstance(fp, dict)
            or not _integer(fp.get("bytes"))
            or not 0 < fp["bytes"] <= 8 * 1024 * 1024
            or not io._digest(fp.get("sha256"))
        ):
            raise ValueError("Invalid player raw fingerprint")
        total += fp["bytes"]
        if total > 16 * 1024 * 1024:
            raise ValueError("Player raw resource byte limit exceeded")
        path = raw_root / name
        if not path.resolve(strict=True).is_relative_to(raw_root) or any(
            p.is_symlink() for p in [path, *path.parents] if p != raw_root.parent
        ):
            raise ValueError("Player raw resource escapes root or has symlink components")
        data = io._read(path, fp["bytes"])
        if len(data) != fp["bytes"] or _sha(data) != fp["sha256"]:
            raise ValueError(f"Player raw identity mismatch: {name}")
        verified[name] = data
    for name in TABLES:
        if f"Data/Balance/{name}.datc64" not in verified:
            raise ValueError(f"Missing player table {name}")
    return raw_root, lock_bytes, selected, verified


def _tables(verified):
    with pinned_pypoe() as decoder:
        prepared, schema = schema_candidate._inputs(ROOT)
        if (
            prepared["pypoe_revision"] != facts.PYPOE
            or _sha(schema) != facts.SCHEMA_SHA
            or prepared["source"]["revision"] != facts.SCHEMA
        ):
            raise ValueError("Prepared player schema identity mismatch")
        spec_bytes, spec = schema_candidate._native_specification(schema)
        tables = {row["name"]: row for row in json.loads(schema)["tables"]}
        decoded = {
            name: facts._decode_dat(name, verified[f"Data/Balance/{name}.datc64"], spec, tables[name])
            for name in TABLES
        }
    return decoded, {
        "revision": facts.PYPOE,
        "schema_revision": facts.SCHEMA,
        "schema_sha256": facts.SCHEMA_SHA,
        "specification_sha256": _sha(spec_bytes),
        "trusted_source_pin_sha256": decoder["pin_sha256"],
        "sources": decoder["sources"],
    }


def _ref(table, row, values):
    local = table in TABLES
    return {
        "origin": "player" if local else "parent",
        "table": table,
        "row": row,
        "id": values.get("Id"),
        "payload": f"{table}.json" if local else f"tables/{table}.json",
        "pointer": f"/rows/{row}/values",
    }


def _project(selected, tables, parents, files):
    character_id = selected["character_id"]
    characters = _rows(parents["Characters"], "Characters")
    matches = [(i, row["values"]) for i, row in enumerate(characters) if row["values"]["Id"] == character_id]
    if len(matches) != 1:
        raise ValueError("Selected character must resolve by exact stable ID")
    character_row, character = matches[0]
    roots = selected["metadata_roots"]
    if (
        set(roots) != {"character_ao", "generic_stats_ot"}
        or roots["character_ao"] != character["AOFile"]
        or PurePosixPath(roots["character_ao"]).suffix != ".ao"
        or PurePosixPath(roots["generic_stats_ot"]).suffix != ".ot"
    ):
        raise ValueError("Explicit distinct AO and generic OT roots required")
    heights = metadata.validate_closure(files, list(roots.values()))
    starts = _rows(tables["StartingPassiveSkills"], "StartingPassiveSkills")
    passives = _rows(parents["PassiveSkills"], "PassiveSkills")
    stats = _rows(parents["Stats"], "Stats")
    stat_ids = {row["values"]["Id"]: i for i, row in enumerate(stats)}
    start_relations = []
    for i, entry in enumerate(starts):
        targets = []
        for index in entry["values"]["PassiveSkills"]:
            if not _integer(index) or index >= len(passives):
                raise ValueError("Starting option references an unavailable passive")
            targets.append(_ref("PassiveSkills", index, passives[index]["values"]))
        start_relations.append({"source": _ref("StartingPassiveSkills", i, entry["values"]), "options": targets})
    start = character["StartingPassive"]
    if not _integer(start) or start >= len(starts):
        raise ValueError("Selected starting relation is unavailable")
    metadata_stats, diagnostics = [], []
    for path, file in files.items():
        for i, assignment in enumerate(file["assignments"]):
            if not assignment["plain_stats_scope"]:
                continue
            key = assignment["key_raw"]
            stat_row = stat_ids.get(key)
            metadata_stats.append(
                {
                    "path": path,
                    "assignment": i,
                    "key_raw": key,
                    "value_raw": assignment["value_raw"],
                    "scope": assignment["scope"],
                    "stat": None if stat_row is None else _ref("Stats", stat_row, stats[stat_row]["values"]),
                }
            )
            if stat_row is None:
                diagnostics.append(
                    {"code": "unresolved_metadata_stat_id", "path": path, "assignment": i, "key_raw": key}
                )
        diagnostics.extend({**item, "path": path} for item in file["diagnostics"])
    overrides = _rows(parents["ClassPassiveSkillOverrides"], "ClassPassiveSkillOverrides")
    selected_overrides = [
        _ref("ClassPassiveSkillOverrides", i, row["values"])
        for i, row in enumerate(overrides)
        if row["values"]["CharacterToOverrideFor"] == character_row
    ]
    context = {
        "format": "repoe-native-player-context-facts/v1",
        "character": {"source": _ref("Characters", character_row, character), "values": character},
        "starting_relation": start_relations[start],
        "all_starting_relations": start_relations,
        "selected_class_overrides": selected_overrides,
        "metadata_roots": roots,
        "literal_closure_heights": heights,
        "metadata_stats": metadata_stats,
        "binding_policy": "none; AO inheritance and independent OT root are not combined or applied",
        "allocation_policy": "none; starting choices are raw relationships, not automatic grants",
    }
    summary = {
        "characters_selected": 1,
        "starting_rows": len(starts),
        "starting_option_references": sum(len(r["options"]) for r in start_relations),
        "keyword_rows": len(_rows(tables["KeywordPopups"], "KeywordPopups")),
        "metadata_files": len(files),
        "metadata_lines": sum(len(f["records"]) for f in files.values()),
        "plain_stats_assignments": len(metadata_stats),
        "diagnostics": len(diagnostics),
    }
    return context, summary, diagnostics


def create_candidate(
    *, source_lock, source, raw, out, expected_source_lock_sha256, parent_facts, expected_parent_manifest_sha256
):
    output = Path(out).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError("Refusing existing player candidate")
    if not output.resolve().is_relative_to(ROOT / ".cache"):
        raise ValueError("Player candidates must be under this checkout's .cache/")
    raw_root, lock_bytes, selected, verified = _inputs(source_lock, source, raw, expected_source_lock_sha256)
    parent_root, parent_bytes, parent, parents = _parent(parent_facts, expected_parent_manifest_sha256)
    if output.resolve().is_relative_to(raw_root) or output.resolve().is_relative_to(parent_root):
        raise ValueError("Player output cannot modify input packages")
    for key in ["game", "realm", "game_patch"]:
        if parent["source_identity"][key] != selected[key]:
            raise ValueError(f"Player/parent {key} mismatch")
    tables, decoder = _tables(verified)
    files = {
        name: metadata.parse_metadata(name, data)
        for name, data in sorted(verified.items())
        if name.startswith("Metadata/")
    }
    context, summary, diagnostics = _project(selected, tables, parents, files)
    identity = {
        "source": source,
        "source_lock_sha256": _sha(lock_bytes),
        "selected_source_sha256": _sha(io._json(selected)),
        "game": selected["game"],
        "realm": selected["realm"],
        "game_patch": selected["game_patch"],
        "acquisition": selected["acquisition"],
        "raw_resources": {name: {"bytes": len(data), "sha256": _sha(data)} for name, data in sorted(verified.items())},
    }
    payloads = {f"{name}.json": io._json(doc) for name, doc in tables.items()}
    payloads.update(
        {
            "metadata.json": io._json({"format": "repoe-native-metadata-archive/v1", "files": files}),
            "player_context.json": io._json(context),
            "diagnostics.json": io._json({"diagnostics": diagnostics}),
            "source-lock.json": lock_bytes,
            "parent-manifest.json": parent_bytes,
        }
    )
    producer_paths = [
        "RePoE/__init__.py",
        "RePoE/native/__init__.py",
        "RePoE/native/player.py",
        "RePoE/native/metadata.py",
        "RePoE/native/descriptions.py",
        "RePoE/native/csd.py",
        "RePoE/native/facts.py",
        "RePoE/native/dat.py",
        "RePoE/native/tools.py",
        "RePoE/native/schema_candidate.py",
        "pyproject.toml",
        "uv.lock",
        "schema/pypoe-sources.json",
        "schema/source.json",
        "schema/SHA256SUMS",
    ]
    manifest = {
        "format": "repoe-native-player-context/v1",
        "status": "partial-candidate",
        "production_ready": False,
        "source_identity": identity,
        "parent": {
            "manifest_sha256": expected_parent_manifest_sha256,
            "source_identity": parent["source_identity"],
            "validation_scope": "all parent payload byte identities plus consumed physical tables; no independent parent semantic re-audit",
        },
        "decoder": decoder,
        "producer": {name: _sha((ROOT / name).read_bytes()) for name in producer_paths},
        "python_version": sys.version.split()[0],
        "summary": summary,
        "limits": LIMITS,
        "files": {name: {"bytes": len(data), "sha256": _sha(data)} for name, data in payloads.items()},
    }
    payloads["manifest.json"] = io._json(manifest)
    io._publish(output, raw_root, payloads)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["source-lock", "raw", "out", "parent-facts"]:
        parser.add_argument(f"--{name}", required=True, type=Path)
    for name in ["source", "expected-source-lock-sha256", "expected-parent-manifest-sha256"]:
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args()
    try:
        result = create_candidate(**vars(args))
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, f"Player context rejected: {error}\n")
    print(f"{result['format']}: {args.out}; {result['summary']}; partial, no actor binding")


if __name__ == "__main__":
    main()
