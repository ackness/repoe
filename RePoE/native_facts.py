"""Produce an offline, source-preserving native facts candidate (never a runtime pack)."""

import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import re
import struct
import sys
import tempfile
import warnings

from RePoE import schema_candidate
from RePoE.native_dat import validate_dat
from RePoE.native_tools import pinned_pypoe


FORMAT = "repoe-native-facts/v1"
BASE_PROFILE = "base-v1"
SKILLS_PROFILE = "core-skills-a0"
TABLES = (
    "Characters",
    "ClassPassiveSkillOverrides",
    "GrantedEffectQualityStats",
    "GrantedEffectStatSets",
    "GrantedEffects",
    "PassiveSkillTrees",
    "PassiveSkills",
    "Stats",
)
PSG = "Metadata/PassiveSkillGraph.psg"
RESOURCES = tuple(f"Data/Balance/{name}.datc64" for name in TABLES) + (PSG,)
PYPOE = "66d1d7442c5718260e1a8efd24989d22987e91af"
SCHEMA = "6034b071846ef61b39046ebdb59e6d5717179509"
SCHEMA_SHA = "50e098543345cf8323aeb294e2cfef1b6b44842faccf560ada935cebe22727df"
ROW_KEY = "Zero-based physical source row; ephemeral within these exact raw bytes, never a stable game ID."
LIMITS = [
    "Partial candidate only; forbidden as a production snapshot or runtime-ready PoBR pack.",
    "Only eight physical DAT tables and the Default PSG; no complete foreign-key or metadata closure.",
    "Community schema names and comments are interpretations, not certified gameplay semantics.",
    "No quality application policy, translations, level data, radii or global coordinates are inferred.",
    "Definition existence and default graph membership are distinct; no historical deletion is inferred.",
]


def _json(value):
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def profile_tables(profile):
    if profile == BASE_PROFILE:
        return TABLES
    if profile == SKILLS_PROFILE:
        from RePoE.native_skills import TABLES as skill_tables

        return TABLES + skill_tables
    raise ValueError(f"Unknown native facts profile: {profile}")


def _verified_raw(source_lock, source_name, raw_root, *, profile=BASE_PROFILE):
    resources = tuple(f"Data/Balance/{name}.datc64" for name in profile_tables(profile)) + (PSG,)
    lock_raw = Path(source_lock).read_bytes()
    lock = json.loads(lock_raw)
    if lock.get("schema_version") != 1:
        raise ValueError("Unsupported source lock schema")
    source = lock["sources"][source_name]
    if (
        source.get("kind") != "official-client-resource-candidate"
        or source.get("game") != "poe2"
        or source.get("game_patch") != "0.5.5.5"
        or source.get("realm") != "international"
    ):
        raise ValueError("Expected separate international PoE2 0.5.5.5 candidate source")
    decoder = source["decoder"]
    if (
        decoder.get("revision") != PYPOE
        or decoder.get("dat_schema_revision") != SCHEMA
        or decoder.get("schema_sha256") != SCHEMA_SHA
    ):
        raise ValueError("Source decoder/schema pin mismatch")
    if set(source["resources"]) != set(resources):
        raise ValueError("Source lock must declare exactly the selected profile's DATs and default PSG")
    acquisition = None
    if profile == SKILLS_PROFILE:
        acquisition = source.get("acquisition")
        if (
            source.get("profile") != profile
            or not isinstance(acquisition, dict)
            or acquisition.get("status") not in {"unreviewed-acquisition-draft", "reviewed-source-input"}
            or not isinstance(acquisition.get("evidence"), list)
            or not acquisition["evidence"]
        ):
            raise ValueError("Core skills source needs an explicit profile and acquisition evidence/status")
        for evidence in acquisition["evidence"]:
            if (
                not isinstance(evidence, dict)
                or set(evidence) != {"kind", "sha256"}
                or not isinstance(evidence["kind"], str)
                or not evidence["kind"]
                or not isinstance(evidence["sha256"], str)
                or not re.fullmatch(r"[a-f0-9]{64}", evidence["sha256"])
            ):
                raise ValueError("Invalid acquisition evidence fingerprint")
    raw_root = Path(raw_root).resolve(strict=True)
    verified = {}
    identities = {}
    for name in resources:
        entry = source["resources"][name]
        path = (raw_root / name).resolve(strict=True)
        if not path.is_relative_to(raw_root) or not path.is_file():
            raise ValueError(f"Raw resource path escapes root or is not a file: {name}")
        if type(entry["bytes"]) is not int or entry["bytes"] <= 0 or not re.fullmatch(r"[a-f0-9]{64}", entry["sha256"]):
            raise ValueError(f"Invalid raw identity: {name}")
        raw = path.read_bytes()
        identity = {"bytes": len(raw), "sha256": schema_candidate._sha(raw)}
        if identity != {key: entry[key] for key in identity}:
            raise ValueError(f"Raw hash/size mismatch: {name}")
        verified[name] = raw
        identities[name] = identity
    identity = {
        "source_lock_sha256": schema_candidate._sha(lock_raw),
        "selected_source_sha256": schema_candidate._sha(_json(source)),
        "source": source_name,
        "kind": source["kind"],
        "game": source["game"],
        "game_patch": source["game_patch"],
        "realm": source["realm"],
        "raw_resources": identities,
    }
    if acquisition is not None:
        identity["acquisition"] = acquisition
    return verified, identity


def _columns(table, physical_fields):
    """Bind each original schema column to its exact generated physical field(s)."""
    position = 0
    columns = []
    for index, column in enumerate(table["columns"]):
        width = 2 if column["interval"] else 1
        fields = physical_fields[position : position + width]
        if len(fields) != width:
            raise ValueError(f"Missing physical field for {table['name']} column {index}")
        columns.append({"source_column": index, "schema": column, "physical_fields": fields})
        position += width
    if position != len(physical_fields):
        raise ValueError(f"Unexpected physical fields for {table['name']}")
    return columns


def _decode_dat(name, raw, specification, schema_table):
    row_width = validate_dat(name, raw, specification[f"{name}.dat"].fields)
    from PyPoE.poe.file.dat import DatReader

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        reader = DatReader(f"{name}.datc64", specification=specification, use_dat_value=False, x64=True)
        if reader.cast_size != row_width:
            raise ValueError(f"{name}: decoder/preflight physical row width mismatch")
        reader.read(raw)
        if reader.table_rows and reader.cast_size != reader.table_record_length:
            raise ValueError(
                f"{name}: exact physical row width mismatch: {reader.cast_size}/{reader.table_record_length}"
            )
        fields = list(specification[f"{name}.dat"].fields)
        rows = [{"_row": row.rowid, "values": {field: row[field] for field in fields}} for row in reader]
    if caught:
        raise ValueError(f"{name}: decoder warnings (candidate rejected): {[str(w.message) for w in caught]}")
    return {
        "table": name,
        "raw_resource": f"Data/Balance/{name}.datc64",
        "row_key": ROW_KEY,
        "physical_fields": fields,
        "columns": _columns(schema_table, fields),
        "validation": {
            "rows": len(rows),
            "schema_row_bytes": reader.cast_size,
            "actual_row_bytes": reader.table_record_length,
            "warnings": [],
        },
        "rows": rows,
    }


def _frame_psg(raw):
    """Independent bounded framing check, retaining fields omitted by PSGFile.

    This checks the measured v3/0 binary layout. PSGFile remains the decoder;
    compare every exposed field below rather than accepting framing alone.
    """
    offset = 0

    def take(fmt):
        nonlocal offset
        size = struct.calcsize(fmt)
        if offset + size > len(raw):
            raise ValueError(f"Truncated PSG framing at byte {offset}")
        values = struct.unpack_from(fmt, raw, offset)
        offset += size
        return values

    header = list(take("<BB"))
    if header != [3, 0]:
        raise ValueError(f"Unsupported PSG framing header: {header}")
    orbits = list(take("<" + "B" * take("<B")[0]))
    roots = [dict(zip(("graph_id", "unknown"), take("<II"), strict=True)) for _ in range(take("<I")[0])]
    groups = []
    for group_id in range(take("<I")[0]):
        x, y, flag, unknown1, unknown2, count = take("<ffIIbI")
        nodes = []
        for _ in range(count):
            graph_id, radius, position, count_connections = take("<IIII")
            pairs = [take("<Ii") for _ in range(count_connections)]
            nodes.append(
                {
                    "graph_id": graph_id,
                    "radius": radius,
                    "position": position,
                    "connections": [pair[0] for pair in pairs],
                    "splines": [pair[1] for pair in pairs],
                }
            )
        groups.append(
            {
                "group": group_id,
                "x": x,
                "y": y,
                "flag": flag,
                "unknown1": unknown1,
                "unknown2": unknown2,
                "nodes": nodes,
            }
        )
    if offset != len(raw):
        raise ValueError(f"Trailing PSG bytes: {len(raw) - offset}")
    return {"header": header, "skills_per_orbit": orbits, "roots": roots, "groups": groups, "parsed_bytes": offset}


def _decode_psg(raw):
    from PyPoE.poe.file.psg2 import PSGFile

    framed = _frame_psg(raw)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        reader = PSGFile()
        reader.read(raw)
    if caught:
        raise ValueError(f"PSG decoder warnings (candidate rejected): {[str(w.message) for w in caught]}")
    if (
        list(reader.unk) != framed["header"]
        or list(reader.skills_per_orbit) != framed["skills_per_orbit"]
        or reader.root_passives != [root["graph_id"] for root in framed["roots"]]
        or len(reader.groups) != len(framed["groups"])
    ):
        raise ValueError("PSG decoder/framing header mismatch")
    for group, expected in zip(reader.groups, framed["groups"], strict=True):
        actual = {
            "group": group.id,
            "x": group.x,
            "y": group.y,
            "flag": group.flag,
            "nodes": [
                {
                    "graph_id": node.passive_skill,
                    "radius": node.radius,
                    "position": node.position,
                    "connections": node.connections,
                    "splines": node.splines,
                }
                for node in group.nodes
            ],
        }
        if actual != {key: expected[key] for key in actual}:
            raise ValueError(f"PSG decoder/framing group mismatch: {group.id}")
    framed.update(raw_resource=PSG, warnings=[], radius_semantics="Raw PSG orbit index; physical radii uncertified.")
    return framed


def _resolve(tables, name, index, context):
    if type(index) is not int or not 0 <= index < len(tables[name]["rows"]):
        raise ValueError(f"{context}: dangling required {name} row {index!r}")
    row = tables[name]["rows"][index]
    return {"row": index, "id": row["values"]["Id"]} if "Id" in row["values"] else {"row": index}


def _relationships(tables):
    """Validate acquired joins; enumerate unavailable and unknown targets honestly."""
    diagnostics = []
    for name, table in tables.items():
        for column in table["columns"]:
            schema = column["schema"]
            reference = schema.get("references")
            if not reference and schema["type"] not in ("foreignrow", "row", "enumrow"):
                continue
            for field in column["physical_fields"]:
                occurrences = []
                for row in table["rows"]:
                    raw = row["values"][field]
                    values = raw if isinstance(raw, list) else [raw]
                    for slot, value in enumerate(values):
                        if value is not None:
                            occurrences.append(
                                {"row": row["_row"], "slot": slot if isinstance(raw, list) else None, "value": value}
                            )
                if not occurrences:
                    continue
                target = reference["table"] if reference else None
                if target in tables and schema["type"] != "enumrow":
                    for occurrence in occurrences:
                        value = occurrence["value"]
                        if reference.get("column"):
                            matches = [r for r in tables[target]["rows"] if r["values"][reference["column"]] == value]
                            if len(matches) != 1:
                                raise ValueError(f"{name}.{field}: unresolved {target}.{reference['column']}={value!r}")
                        else:
                            _resolve(tables, target, value, f"{name}[{occurrence['row']}].{field}")
                else:
                    diagnostics.append(
                        {
                            "code": "unavailable_relationship_target" if target else "unknown_relationship_target",
                            "table": name,
                            "field": field,
                            "target": reference,
                            "occurrences": occurrences,
                        }
                    )
    return diagnostics


def _projections(tables, graph):
    diagnostics = _relationships(tables)

    def rows(name):
        return tables[name]["rows"]

    graph_ids = [node["graph_id"] for group in graph["groups"] for node in group["nodes"]]
    if len(graph_ids) != len(set(graph_ids)):
        raise ValueError("Duplicate PSG group node ID")
    members = set(graph_ids)
    roots = [root["graph_id"] for root in graph["roots"]]
    if len(roots) != len(set(roots)) or not set(roots) <= members:
        raise ValueError("Duplicate or unresolved PSG roots")
    for group in graph["groups"]:
        for node in group["nodes"]:
            if not set(node["connections"]) <= members:
                raise ValueError(f"Dangling PSG edge at {node['graph_id']}")
    defaults = [r for r in rows("PassiveSkillTrees") if r["values"]["Id"] == "Default"]
    if len(defaults) != 1 or defaults[0]["values"]["PassiveSkillGraph"] + ".psg" != PSG:
        raise ValueError("Default tree does not identify the acquired PSG")
    graph["tree"] = _resolve(tables, "PassiveSkillTrees", defaults[0]["_row"], "default tree")
    for row in rows("PassiveSkillTrees"):
        if row != defaults[0]:
            diagnostics.append(
                {"code": "unavailable_tree_graph", "tree_row": row["_row"], "path": row["values"]["PassiveSkillGraph"]}
            )

    definitions = []
    by_graph = defaultdict(list)
    for row in rows("PassiveSkills"):
        value = row["values"]
        stats = []
        for slot, stat in enumerate(value["Stats"], 1):
            field = f"Stat{slot}Value"
            if field not in value:
                raise ValueError(f"PassiveSkills[{row['_row']}]: missing {field}")
            stats.append(
                {
                    "slot": slot,
                    "value_field": field,
                    "stat": _resolve(tables, "Stats", stat, field),
                    "value": value[field],
                }
            )
        definition = {
            "definition": _resolve(tables, "PassiveSkills", row["_row"], "passive definition"),
            "graph_id": value["PassiveSkillGraphId"],
            "in_default_graph": value["PassiveSkillGraphId"] in members,
            "stats": stats,
        }
        definitions.append(definition)
        by_graph[value["PassiveSkillGraphId"]].append(definition)
    for graph_id in graph_ids:
        if len(by_graph[graph_id]) != 1:
            raise ValueError(f"PSG {graph_id}: expected exactly one passive definition")
    instances = [
        {**node, "group": group["group"], "definition": by_graph[node["graph_id"]][0]["definition"]}
        for group in graph["groups"]
        for node in group["nodes"]
    ]
    overrides = []
    for row in rows("ClassPassiveSkillOverrides"):
        value = row["values"]
        base = _resolve(tables, "PassiveSkills", value["SkillToOverride"], "override base")
        replacement = _resolve(tables, "PassiveSkills", value["Override"], "override replacement")
        base_id = rows("PassiveSkills")[base["row"]]["values"]["PassiveSkillGraphId"]
        replacement_id = rows("PassiveSkills")[replacement["row"]]["values"]["PassiveSkillGraphId"]
        overrides.append(
            {
                "row": row["_row"],
                "character": _resolve(tables, "Characters", value["CharacterToOverrideFor"], "override character"),
                "base": base,
                "replacement": replacement,
                "base_graph_id": base_id,
                "replacement_graph_id": replacement_id,
                "base_in_default_graph": base_id in members,
                "replacement_in_default_graph": replacement_id in members,
            }
        )
        if base_id not in members:
            diagnostics.append({"code": "override_base_absent_from_default_graph", **overrides[-1]})

    effects = []
    for row in rows("GrantedEffects"):
        value = row["values"]
        ordered = []
        refs = [("StatSet", None, value["StatSet"])] + [
            ("AdditionalStatSets", i, ref) for i, ref in enumerate(value["AdditionalStatSets"])
        ]
        for field, slot, ref in refs:
            if ref is not None:
                ordered.append(
                    {
                        "local_index_hypothesis": len(ordered),
                        "source_field": field,
                        "source_slot": slot,
                        "stat_set": _resolve(tables, "GrantedEffectStatSets", ref, "effect stat set"),
                    }
                )
            elif field == "AdditionalStatSets":
                diagnostics.append({"code": "null_additional_stat_set", "effect_row": row["_row"], "source_slot": slot})
        effects.append(
            {"effect": _resolve(tables, "GrantedEffects", row["_row"], "effect"), "ordered_stat_sets": ordered}
        )
    qualities = []
    for row in rows("GrantedEffectQualityStats"):
        value = row["values"]
        effect = _resolve(tables, "GrantedEffects", value["GrantedEffect"], "quality effect")
        quality = {
            "row": row["_row"],
            "effect": effect,
            "ordered_stat_sets": effects[effect["row"]]["ordered_stat_sets"],
        }
        for channel, stats_field, values_field, scope_field in (
            ("main", "Stats", "StatsValuesPermille", "ApplyToStatSets"),
            ("alternate", "AltStats", "AltStatValuesPermille", "AltApplyToStatSets"),
        ):
            if len(value[stats_field]) != len(value[values_field]):
                raise ValueError(f"Quality[{row['_row']}]: unequal {stats_field}/{values_field}")
            quality[channel] = {
                "stats": [
                    {"slot": i, "stat": _resolve(tables, "Stats", stat, "quality stat"), "value_permille": amount}
                    for i, (stat, amount) in enumerate(zip(value[stats_field], value[values_field], strict=True))
                ],
                "scope_raw": value[scope_field],
            }
            for scope in value[scope_field]:
                if not 0 <= scope < len(quality["ordered_stat_sets"]):
                    diagnostics.append(
                        {
                            "code": "quality_scope_out_of_range_under_local_index_hypothesis",
                            "quality_row": row["_row"],
                            "effect": effect,
                            "field": scope_field,
                            "scope_raw": value[scope_field],
                            "value": scope,
                            "ordered_stat_sets": quality["ordered_stat_sets"],
                        }
                    )
        qualities.append(quality)
    for row in rows("GrantedEffectStatSets"):
        value = row["values"]
        if len(value["ConstantStats"]) != len(value["ConstantStatsValues"]):
            raise ValueError(f"GrantedEffectStatSets[{row['_row']}]: unequal constant stat/value arrays")
    summary = {
        "passive_definitions": len(definitions),
        "graph_instances": len(instances),
        "class_overrides": len(overrides),
        "graph_stat_entries": sum(len(by_graph[i][0]["stats"]) for i in graph_ids),
        "effects": len(effects),
        "qualities": len(qualities),
    }
    return {
        "passives.json": {
            "definitions": definitions,
            "default_graph_instances": instances,
            "class_overrides": overrides,
        },
        "skills.json": {"effects": effects, "qualities": qualities},
        "diagnostics.json": {"scope": LIMITS, "diagnostics": diagnostics},
    }, summary


def _candidate_payloads(verified, source_identity, tool_identity, *, profile=BASE_PROFILE, source_lock_bytes=None):
    selected_tables = profile_tables(profile)
    if profile == SKILLS_PROFILE and (
        not isinstance(source_lock_bytes, bytes)
        or schema_candidate._sha(source_lock_bytes) != source_identity["source_lock_sha256"]
    ):
        raise ValueError("Core skills source-lock snapshot differs from verified identity")
    # Regenerate only from trusted locked inputs; never execute a caller's specification.
    inputs, schema = schema_candidate._inputs(schema_candidate.ROOT)
    if (
        inputs["pypoe_revision"] != PYPOE
        or inputs["schema_sha256"] != SCHEMA_SHA
        or inputs["source"]["revision"] != SCHEMA
    ):
        raise ValueError("Prepared native decoder/schema identity mismatch")
    spec_raw, specification = schema_candidate._native_specification(schema)
    schema_tables = {t["name"]: t for t in json.loads(schema)["tables"]}
    tables = {
        name: _decode_dat(name, verified[f"Data/Balance/{name}.datc64"], specification, schema_tables[name])
        for name in selected_tables
    }
    graph = _decode_psg(verified[PSG])
    documents, summary = _projections(tables, graph)
    scope = LIMITS
    if profile == SKILLS_PROFILE:
        from RePoE import native_skills

        core, core_summary, diagnostics = native_skills.project(tables, _resolve)
        documents["skill_core.json"] = core
        summary.update(core_summary)
        scope = native_skills.LIMITS
        documents["diagnostics.json"]["scope"] = scope
        documents["diagnostics.json"]["diagnostics"].extend(diagnostics)
    documents.update({f"tables/{name}.json": table for name, table in tables.items()})
    documents["graph.json"] = graph
    if inputs["pypoe_sources"] != {
        name: digest
        for name, digest in tool_identity["sources"].items()
        if not name.startswith("poe/file/specification/data/")
    }:
        raise ValueError("Imported PyPoE source inventory differs from verified tools")
    producer = {
        **inputs["producer"],
        **{
            name: schema_candidate._sha((schema_candidate.ROOT / name).read_bytes())
            for name in (
                "RePoE/native_facts.py",
                "RePoE/native_dat.py",
                "RePoE/native_tools.py",
                "schema/pypoe-sources.json",
            )
        },
    }
    if profile == SKILLS_PROFILE:
        producer["RePoE/native_skills.py"] = schema_candidate._sha(
            (schema_candidate.ROOT / "RePoE/native_skills.py").read_bytes()
        )
    manifest = {
        "format": FORMAT if profile == BASE_PROFILE else "repoe-native-facts/v2",
        "status": "partial-candidate",
        "production_ready": False,
        "source_identity": source_identity,
        "row_key": ROW_KEY,
        "scope": scope,
        "summary": summary,
        "decoder": {
            "pypoe_revision": inputs["pypoe_revision"],
            "python": inputs["python"],
            "sources": tool_identity["sources"],
            "trusted_source_pin_sha256": tool_identity["pin_sha256"],
        },
        "schema": {
            "revision": SCHEMA,
            "sha256": inputs["schema_sha256"],
            "native_specification_sha256": schema_candidate._sha(spec_raw),
            "compatibility_views": 0,
        },
        "producer": producer,
        "files": {},
    }
    if profile == SKILLS_PROFILE:
        manifest["profile"] = profile
    # Materialize only after every input, decoder and required join has passed.
    payloads = {name: _json(document) for name, document in documents.items()}
    if profile == SKILLS_PROFILE:
        payloads["source-lock.json"] = source_lock_bytes
    manifest["files"] = {
        name: {"sha256": schema_candidate._sha(data), "bytes": len(data)} for name, data in sorted(payloads.items())
    }
    payloads["manifest.json"] = _json(manifest)
    if schema_candidate._inputs(schema_candidate.ROOT)[0] != inputs:
        raise ValueError("Producer/schema inputs changed during generation")
    if any(schema_candidate._sha((schema_candidate.ROOT / name).read_bytes()) != sha for name, sha in producer.items()):
        raise ValueError("Facts producer changed during generation")
    return manifest, payloads


def create_candidate(*, source_lock, source, raw, out, profile=BASE_PROFILE):
    sys.dont_write_bytecode = True
    output = Path(out).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Refusing to replace existing output: {output}")
    source_lock_bytes = Path(source_lock).read_bytes() if profile == SKILLS_PROFILE else None
    verified, source_identity = _verified_raw(source_lock, source, raw, profile=profile)
    with pinned_pypoe() as tool_identity:
        manifest, payloads = _candidate_payloads(
            verified, source_identity, tool_identity, profile=profile, source_lock_bytes=source_lock_bytes
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".native-facts-", dir=output.parent) as temporary:
        staging = Path(temporary)
        for name, data in payloads.items():
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        # mkdir reserves without replacing a concurrent empty directory or symlink.
        # Manifest is linked last: interrupted publication has no completion receipt.
        output.mkdir()
        for name in payloads:
            target = output / name
            target.parent.mkdir(parents=True, exist_ok=True)
            os.link(staging / name, target)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-lock", required=True, type=Path)
    parser.add_argument("--source", required=True)
    parser.add_argument("--raw", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--profile", choices=[BASE_PROFILE, SKILLS_PROFILE], default=BASE_PROFILE)
    args = parser.parse_args()
    try:
        manifest = create_candidate(
            source_lock=args.source_lock, source=args.source, raw=args.raw, out=args.out, profile=args.profile
        )
    except (ValueError, OSError, KeyError, TypeError, struct.error) as error:
        parser.exit(1, f"Native facts rejected: {error}\n")
    print(f"{manifest['format']}: {args.out}; {manifest['summary']}; partial candidate, not production")


if __name__ == "__main__":
    main()
