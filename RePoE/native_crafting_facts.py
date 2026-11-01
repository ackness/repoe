"""Project neutral crafting relationships from exactly seven pinned F77 tables."""

import argparse
from collections import Counter
from pathlib import Path
import re
import sys

from RePoE import native_descriptions as env


ROOT = Path(__file__).resolve().parents[1]
FORMAT = "repoe-native-crafting-facts/v1"
TABLES = (
    "BaseItemTypes",
    "ItemClasses",
    "Mods",
    "Stats",
    "Essences",
    "EssenceTargetItemCategories",
    "EssenceMods",
)
SCHEMA = {
    "revision": "6034b071846ef61b39046ebdb59e6d5717179509",
    "sha256": "50e098543345cf8323aeb294e2cfef1b6b44842faccf560ada935cebe22727df",
    "native_specification_sha256": "c9417f03e2205ff649721c3dbf9620ee0c703bf905b3cf53469ce3eda86f1e25",
    "compatibility_views": 0,
}
MAX_TABLE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 96 * 1024 * 1024
PRODUCERS = ("RePoE/native_crafting_facts.py", "RePoE/native_descriptions.py")


def _read(path, limit):
    path = Path(path).absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError(f"Symlink input path: {path}")
    return env._read(path, limit)


def _pin(raw):
    return {"bytes": len(raw), "sha256": env._sha(raw)}


def _inputs(facts, expected_manifest_sha256):
    root = Path(facts).absolute()
    raw = _read(root / "manifest.json", 4 * 1024 * 1024)
    if not env._digest(expected_manifest_sha256) or env._sha(raw) != expected_manifest_sha256:
        raise ValueError("Facts manifest differs from external expected pin")
    manifest = env._decode(raw)
    if (
        manifest.get("format") != "repoe-native-facts/v4"
        or manifest.get("profile") != "items-actors-bc"
        or manifest.get("status") != "partial-candidate"
        or manifest.get("production_ready") is not False
        or manifest.get("schema") != SCHEMA
    ):
        raise ValueError("Expected partial F77 native facts with exact native schema")
    source = manifest["source_identity"]
    acquisition = source.get("acquisition", {})
    if (
        source.get("kind") != "official-client-resource-candidate"
        or source.get("game") != "poe2"
        or not isinstance(source.get("game_patch"), str)
        or not re.fullmatch(r"\d+(?:\.\d+){2,5}", source["game_patch"])
        or source.get("realm") not in {"international", "china"}
        or source.get("language", "English") != "English"
        or not isinstance(source.get("source"), str)
        or not source["source"]
        or not env._digest(source.get("source_lock_sha256"))
        or not env._digest(source.get("selected_source_sha256"))
        or acquisition.get("status") not in {"unreviewed-acquisition-draft", "reviewed-source-input"}
        or not isinstance(acquisition.get("evidence"), list)
        or not acquisition["evidence"]
    ):
        raise ValueError("Explicit inherited English source/patch/realm and acquisition identity required")
    for evidence in acquisition["evidence"]:
        if (
            not isinstance(evidence, dict)
            or set(evidence) != {"kind", "sha256"}
            or not isinstance(evidence["kind"], str)
            or not evidence["kind"]
            or not env._digest(evidence["sha256"])
        ):
            raise ValueError("Invalid inherited acquisition evidence")
    decoder = manifest["decoder"]
    if (
        decoder.get("pypoe_revision") != "66d1d7442c5718260e1a8efd24989d22987e91af"
        or not isinstance(decoder.get("python"), str)
        or not decoder["python"]
        or not env._digest(decoder.get("trusted_source_pin_sha256"))
        or not isinstance(decoder.get("sources"), dict)
        or not decoder["sources"]
        or any(not env._digest(pin) for pin in decoder["sources"].values())
        or not isinstance(manifest.get("producer"), dict)
        or not manifest["producer"]
        or any(not env._digest(pin) for pin in manifest["producer"].values())
    ):
        raise ValueError("Missing/unsupported inherited decoder or producer fingerprints")
    payloads, tables, total = {}, {}, 0
    for name in TABLES:
        path = f"tables/{name}.json"
        pin = manifest["files"][path]
        if (
            set(pin) != {"bytes", "sha256"}
            or type(pin["bytes"]) is not int
            or not 0 < pin["bytes"] <= MAX_TABLE_BYTES
            or not env._digest(pin["sha256"])
        ):
            raise ValueError(f"Invalid selected payload pin: {path}")
        total += pin["bytes"]
        if total > MAX_TOTAL_BYTES:
            raise ValueError("Seven-table inputs exceed byte bound")
        data = _read(root / path, pin["bytes"])
        if _pin(data) != pin:
            raise ValueError(f"Selected payload differs from manifest pin: {path}")
        resource_pin = source["raw_resources"][f"Data/Balance/{name}.datc64"]
        if (
            type(resource_pin.get("bytes")) is not int
            or resource_pin["bytes"] <= 0
            or not env._digest(resource_pin.get("sha256"))
        ):
            raise ValueError(f"Missing declared raw resource identity: {name}")
        payloads[f"{name}.json"] = data
        tables[name] = env._decode(data)
    return raw, manifest, payloads, tables


def _validate_tables(tables):
    if set(tables) != set(TABLES):
        raise ValueError("Exactly seven selected physical tables required")
    for name, table in tables.items():
        fields, rows, columns = table["physical_fields"], table["rows"], table["columns"]
        if (
            table.get("table") != name
            or table.get("raw_resource") != f"Data/Balance/{name}.datc64"
            or not isinstance(table.get("row_key"), str)
            or not table["row_key"]
            or not isinstance(fields, list)
            or not fields
            or any(not isinstance(field, str) or not field for field in fields)
            or len(set(fields)) != len(fields)
            or not isinstance(columns, list)
            or not isinstance(rows, list)
            or len(rows) > 100000
            or [column["source_column"] for column in columns] != list(range(len(columns)))
            or [field for column in columns for field in column["physical_fields"]] != fields
            or table["validation"]["rows"] != len(rows)
            or table["validation"]["actual_row_bytes"] != table["validation"]["schema_row_bytes"]
        ):
            raise ValueError(f"Invalid physical table layout: {name}")
        for index, row in enumerate(rows):
            if (
                set(row) != {"_row", "values"}
                or type(row["_row"]) is not int
                or row["_row"] != index
                or not isinstance(row["values"], dict)
                or set(row["values"]) != set(fields)
            ):
                raise ValueError(f"Invalid physical row identity/fields: {name}/{index}")
        if name not in {"Essences", "EssenceMods"}:
            ids = [row["values"]["Id"] for row in rows]
            if any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
                raise ValueError(f"Missing or duplicate stable string identity: {name}")


def _reference(tables, name, row, context):
    if row is None:
        return None
    if type(row) is not int or not 0 <= row < len(tables[name]["rows"]):
        raise ValueError(f"Unresolved selected reference: {context} -> {name}/{row}")
    result = {"table": name, "row": row}
    value = tables[name]["rows"][row]["values"]
    if isinstance(value.get("Id"), str):
        result["id"] = value["Id"]
    return result


def _relations(tables):
    checked, nulls, external = 0, Counter(), []
    for name, table in tables.items():
        for column in table["columns"]:
            schema = column["schema"]
            target = (schema.get("references") or {}).get("table")
            if not target or schema["type"] not in {"row", "foreignrow"}:
                continue
            if len(column["physical_fields"]) != 1:
                raise ValueError(f"Unsupported reference layout: {name}")
            field = column["physical_fields"][0]
            if target not in tables:
                external.append({"table": name, "field": field, "target": target})
                continue
            for row in table["rows"]:
                value = row["values"][field]
                if schema["array"] and not isinstance(value, list):
                    raise ValueError(f"Expected physical reference array: {name}/{row['_row']}/{field}")
                for entry in value if schema["array"] else [value]:
                    _reference(tables, target, entry, f"{name}/{row['_row']}/{field}")
                    if entry is None:
                        nulls[f"{name}.{field}"] += 1
                    else:
                        checked += 1
    return {
        "checked_internal_references": checked,
        "null_references": dict(nulls),
        "external_reference_fields": external,
    }


def project(tables):
    """Retain physical rows and ordered joins; no consumer selection or fallback."""
    _validate_tables(tables)
    relations = _relations(tables)
    required = {
        "Essences": {"BaseItemType": ("BaseItemTypes", False)},
        "EssenceTargetItemCategories": {"ItemClasses": ("ItemClasses", True)},
        "EssenceMods": {
            "Essence": ("Essences", False),
            "TargetItemCategory": ("EssenceTargetItemCategories", False),
            "Mod": ("Mods", False),
            "DisplayMod": ("Mods", False),
            "OutcomeMods": ("Mods", True),
        },
        "Mods": {f"Stat{slot}": ("Stats", False) for slot in range(1, 9)},
    }
    for name, fields in required.items():
        columns = {c["physical_fields"][0]: c["schema"] for c in tables[name]["columns"]}
        for field, (target, array) in fields.items():
            column = columns[field]
            if (
                column["type"] != "foreignrow"
                or column["array"] is not array
                or column.get("references") != {"table": target}
            ):
                raise ValueError(f"Required physical relationship schema differs: {name}.{field}")

    def ref(name, row):
        return _reference(tables, name, row, "projection")

    def raw(name, row):
        return {"payload": f"{name}.json", "pointer": f"/rows/{row}/values"}

    def ordered(name, values):
        if not isinstance(values, list):
            raise ValueError(f"Expected ordered physical reference array: {name}")
        return [{"source_slot": slot, "target": ref(name, row)} for slot, row in enumerate(values)]

    diagnostics, essences, categories, mods, essence_mods = [], [], [], [], []
    for row in tables["Essences"]["rows"]:
        index, value = row["_row"], row["values"]
        essences.append(
            {
                "essence": ref("Essences", index),
                "raw": raw("Essences", index),
                "currency": ref("BaseItemTypes", value["BaseItemType"]),
            }
        )
        if value["BaseItemType"] is None:
            diagnostics.append({"code": "null_currency_reference", "source": ref("Essences", index)})
    for row in tables["EssenceTargetItemCategories"]["rows"]:
        index, value = row["_row"], row["values"]
        categories.append(
            {
                "category": ref("EssenceTargetItemCategories", index),
                "raw": raw("EssenceTargetItemCategories", index),
                "item_classes": ordered("ItemClasses", value["ItemClasses"]),
            }
        )
    for row in tables["Mods"]["rows"]:
        index, value, slots = row["_row"], row["values"], []
        for slot in range(1, 9):
            endpoints = {
                key: value[f"Stat{slot}{suffix}"]
                for key, suffix in [
                    ("min_raw", "Min"),
                    ("max_raw", "Max"),
                    ("min_hardmode_raw", "MinHardmode"),
                    ("max_hardmode_raw", "MaxHardmode"),
                ]
            }
            if any(endpoint is not None and type(endpoint) is not int for endpoint in endpoints.values()):
                raise ValueError(f"Expected raw integer/null stat endpoints: Mods/{index}/Stat{slot}")
            slots.append({"slot": slot, "stat": ref("Stats", value[f"Stat{slot}"]), **endpoints})
            for channel in ("", "_hardmode"):
                low, high = endpoints[f"min{channel}_raw"], endpoints[f"max{channel}_raw"]
                if low is not None and high is not None and low > high:
                    diagnostics.append(
                        {
                            "code": "inverted_raw_interval",
                            "source": ref("Mods", index),
                            "slot": slot,
                            "channel": channel or "regular",
                        }
                    )
        mods.append(
            {
                "mod": ref("Mods", index),
                "raw": raw("Mods", index),
                "slots": slots,
                "level_raw": value["Level"],
                "has_hardmode_values_raw": value["HasHardmodeStatValues"],
            }
        )
    for row in tables["EssenceMods"]["rows"]:
        index, value = row["_row"], row["values"]
        essence, category = value["Essence"], value["TargetItemCategory"]
        outcomes, weights = ordered("Mods", value["OutcomeMods"]), value["OutcomeModWeights"]
        if not isinstance(weights, list) or any(weight is not None and type(weight) is not int for weight in weights):
            raise ValueError(f"Expected raw integer/null weight array: EssenceMods/{index}")
        essence_mods.append(
            {
                "source": ref("EssenceMods", index),
                "raw": raw("EssenceMods", index),
                "essence": ref("Essences", essence),
                "currency": None if essence is None else essences[essence]["currency"],
                "target_category": ref("EssenceTargetItemCategories", category),
                "item_classes": None if category is None else categories[category]["item_classes"],
                "mod": ref("Mods", value["Mod"]),
                "display_mod": ref("Mods", value["DisplayMod"]),
                "outcome_mods": outcomes,
                "outcome_mod_weights_raw": weights,
            }
        )
        if essence is None or category is None:
            diagnostics.append({"code": "null_join_reference", "source": ref("EssenceMods", index)})
        if len(outcomes) != len(weights):
            diagnostics.append(
                {
                    "code": "outcome_weight_alignment_unresolved",
                    "source": ref("EssenceMods", index),
                    "outcome_count": len(outcomes),
                    "weight_count": len(weights),
                }
            )
    return {
        "format": FORMAT,
        "essences": essences,
        "categories": categories,
        "mods": mods,
        "essence_mods": essence_mods,
        "diagnostics": diagnostics,
        "summary": {
            "tables": {name: len(tables[name]["rows"]) for name in TABLES},
            **relations,
            "diagnostics": dict(Counter(entry["code"] for entry in diagnostics)),
            "unresolved_selected_references": 0,
        },
    }


def create_candidate(*, facts, expected_manifest_sha256, out):
    """Write a fresh completion-last package from authenticated exported bytes."""
    output, source_root = Path(out).absolute(), Path(facts).absolute()
    cache = ROOT.resolve(strict=True) / ".cache"
    if output.exists() or output.is_symlink():
        raise FileExistsError("Refusing to replace crafting candidate")
    if output.resolve() == cache or not output.resolve().is_relative_to(cache):
        raise ValueError("Crafting candidate must be beneath this checkout's .cache")
    if output.resolve().is_relative_to(source_root.resolve()):
        raise ValueError("Crafting output cannot be inside facts input")
    producer = {name: env._sha(_read(ROOT / name, 1024 * 1024)) for name in PRODUCERS}
    raw, source_manifest, payloads, tables = _inputs(facts, expected_manifest_sha256)
    projection = project(tables)
    payloads["crafting.json"] = env._json(projection)
    payloads["input-manifest.json"] = raw
    source = source_manifest["source_identity"]
    manifest = {
        "format": FORMAT,
        "status": "partial-candidate",
        "production_ready": False,
        "source_identity": {
            **source,
            "raw_resources": {
                f"Data/Balance/{name}.datc64": source["raw_resources"][f"Data/Balance/{name}.datc64"] for name in TABLES
            },
        },
        "input_package": {
            "manifest": _pin(raw),
            "format": source_manifest["format"],
            "profile": source_manifest["profile"],
            "schema": source_manifest["schema"],
            "decoder": source_manifest["decoder"],
            "producer": source_manifest["producer"],
        },
        "input_files": {f"tables/{name}.json": source_manifest["files"][f"tables/{name}.json"] for name in TABLES},
        "observation": {
            "method": "pinned-export-projection",
            "raw_decoding_performed": False,
            "client_identity_independently_observed": False,
        },
        "producer": producer,
        "python": sys.version.split()[0],
        "summary": projection["summary"],
        "scope": [
            "Only the seven selected exported tables are read and verified; other input-manifest declarations are retained without verification.",
            "Source identity/acquisition is inherited unchanged as a declaration, not independently authenticated or promoted.",
            "All physical rows, eight Mods slots, endpoints, nulls, duplicates and array order are retained; unconsumed fields bind to exact copied tables.",
            "Mod, DisplayMod and OutcomeMods are independent physical relations; no fallback, weight probabilities or complete crafting semantics are inferred.",
            "External foreign references remain outside this selected closure. No consumer filtering, aggregation, text/calc interpretation or runtime adoption.",
        ],
        "files": {name: _pin(data) for name, data in payloads.items()},
    }
    # Re-read just these seven files, with no second decode or broader closure.
    for name in TABLES:
        if _read(source_root / f"tables/{name}.json", MAX_TABLE_BYTES) != payloads[f"{name}.json"]:
            raise ValueError(f"Selected crafting input changed during projection: {name}")
    if _read(source_root / "manifest.json", 4 * 1024 * 1024) != raw:
        raise ValueError("Facts manifest changed during projection")
    if producer != {name: env._sha(_read(ROOT / name, 1024 * 1024)) for name in PRODUCERS}:
        raise ValueError("Crafting producer changed during projection")
    payloads["manifest.json"] = env._json(manifest)
    env._publish(output, source_root, payloads)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("facts", "expected-manifest-sha256", "out"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    try:
        manifest = create_candidate(**vars(args))
    except (ValueError, OSError, KeyError, TypeError, UnicodeError, AttributeError) as error:
        parser.exit(1, f"Native crafting facts rejected: {error}\n")
    print(env._json({"format": FORMAT, "summary": manifest["summary"], "production_ready": False}).decode(), end="")


if __name__ == "__main__":
    main()
