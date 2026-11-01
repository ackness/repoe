"""Explicit opt-in FK candidate from pinned, already decoded observations."""

import argparse
import json
from pathlib import Path
import sys
import types

from RePoE import native_decoded_tables as strict
from RePoE import native_descriptions as env
from RePoE import native_facts as facts
from RePoE import native_locale_probe as probe
from RePoE.native_fk_binding import Correspondence, DEPENDENCIES, EDGES, INTERPRETATION, POLICY, ROLES

ROOT = strict.ROOT
READER = {
    "repository": "https://github.com/repoe-fork/pypoe",
    "revision": "66d1d7442c5718260e1a8efd24989d22987e91af",
    "path": "PyPoE/poe/file/dat.py",
    "sha256": "19f114e1a763a177a2c9a9aa36af9798341ef1a7f496219fdb8fcd54fb823d43",
    "symbol": "RelationalReader.__getitem__",
    "lines": [1173, 1187],
}


def read(path, pin, reads):
    path = Path(path)
    size = path.stat().st_size
    if "bytes" in pin and size != pin["bytes"]:
        raise ValueError(f"Pinned size differs: {path}")
    raw = env._read(path, size)
    if len(raw) != size or env._sha(raw) != pin["sha256"]:
        raise ValueError(f"Pinned bytes differ: {path}")
    reads[path] = {"bytes": len(raw), "sha256": env._sha(raw)}
    return raw


def namespace(role, name, manifest_sha, payload_pin, table, raw_pin):
    return {
        "role": role,
        "table": name,
        "manifest_sha256": manifest_sha,
        "payload_sha256": payload_pin["sha256"],
        "raw_resource": table["raw_resource"],
        "raw_identity": raw_pin,
    }


def validate_dependency(table, schemas, raw_pin):
    name = table["table"]
    fields = table["physical_fields"]
    if len(fields) != len(schemas[name]["columns"]) or table["columns"] != facts._columns(schemas[name], fields):
        raise ValueError("Dependency physical schema differs")
    kinds = {
        "string": "ref|string",
        "foreignrow": "ref|out",
        "row": "ref|generic",
        "enumrow": "int",
        "bool": "bool",
        "i32": "int",
        "u32": "uint",
        "u16": "ushort",
        "f32": "float",
    }
    layout = []
    for field, column in zip(fields, schemas[name]["columns"]):
        if column["interval"]:
            raise ValueError("Unexpected interval dependency column")
        kind = (
            "ref|list|byte"
            if column["type"] == "array"
            else ("ref|list|" if column["array"] else "") + kinds[column["type"]]
        )
        layout.append((field, kind))
    pin = env._sha(env._json(schemas[name]["columns"]))
    scope = dict(vars(probe), LAYOUTS={name: layout}, COLUMN_PINS={name: pin})
    validator = types.FunctionType(probe.validate_table.__code__, scope)
    validator(
        {
            **table,
            "wire_layout": layout,
            "schema": {"revision": probe.SCHEMA_REVISION, "sha256": probe.SCHEMA_SHA256, "columns_sha256": pin},
            "raw_identity": raw_pin,
            "validation": {k: table["validation"][k] for k in ["rows", "schema_row_bytes", "actual_row_bytes"]},
            "decoder_method": probe.METHOD,
            "foreign_tail_observations": [],
        }
    )


def create_candidate(*, base, expected_base_manifest_sha256, policy_lock, expected_policy_lock_sha256, out):
    output = Path(out).absolute()
    if output.exists() or output.is_symlink() or not output.resolve().is_relative_to(ROOT / ".cache"):
        raise ValueError("Fresh checkout .cache candidate required")
    reads, payloads = {}, {}
    base = Path(base)
    base_raw = read(base / "manifest.json", {"sha256": expected_base_manifest_sha256}, reads)
    manifest = env._decode(base_raw)
    if manifest["format"] != strict.FORMAT or manifest["target_binding"]["policy_id"] != strict.POLICY:
        raise ValueError("Frozen strict v2 parent required")
    for file, pin in manifest["files"].items():
        if Path(file).name != file:
            raise ValueError("Invalid base payload name")
        payloads[file] = read(base / file, pin, reads)
    lock_raw = read(policy_lock, {"sha256": expected_policy_lock_sha256}, reads)
    lock = env._decode(lock_raw)
    if (
        lock.get("format") != "repoe-fk-policy-lock/v1"
        or lock.get("policy_id") != POLICY
        or lock.get("base_manifest_sha256") != expected_base_manifest_sha256
    ):
        raise ValueError("Wrong explicit FK policy lock")
    if lock.get("edges") != EDGES or lock.get("interpretation") != {
        "id": INTERPRETATION,
        "authority": "community-interpretation",
        "official_client_semantics_verified": False,
        "reader": READER,
    }:
        raise ValueError("Wrong scoped FK/community interpretation")
    reader_pins = env._decode((ROOT / "schema/pypoe-sources.json").read_bytes())
    if (
        reader_pins["revision"] != READER["revision"]
        or READER["sha256"] not in reader_pins["sources"]["poe/file/dat.py"]
    ):
        raise ValueError("Reader interpretation pin outside fixed source inventory")
    schemas = strict.schema_tables()
    defaults, localized = (env._decode(payloads[f]) for f in ["default-tables.json", "tables.json"])
    receipt = env._decode(payloads["transfer-receipt.json"])
    _, targets, target_pins, identity, verified = strict._targets(
        base / "target-lock.json", manifest["files"]["target-lock.json"]["sha256"], defaults, schemas
    )
    for path, expected, _ in verified:
        read(path, {"sha256": expected}, reads)
    original_binding = env._decode(payloads["target_binding.json"])
    for name in defaults:
        entry = strict.bind_table(
            name,
            {**defaults[name], "raw_identity": receipt["tables"][name]["default"]["raw_identity"]},
            localized[name],
            targets[name],
            target_pins[name],
        )
        if original_binding["tables"][name] != entry:
            raise ValueError("Frozen strict binding does not reproduce from original rows")
    sides = dict(zip(ROLES, [dict(defaults), dict(localized), dict(targets)]))
    namespaces = {role: {} for role in ROLES}
    for role in ROLES:
        for name, table in sides[role].items():
            if role == "target":
                p = target_pins[name]
                namespaces[role][name] = namespace(
                    role, name, p["manifest_sha256"], {"sha256": p["payload_sha256"]}, table, p["raw_identity"]
                )
            else:
                file = "default-tables.json" if role == "source_default" else "tables.json"
                raw_pin = manifest["observed_client"]["resources"][table["raw_resource"]]
                namespaces[role][name] = namespace(
                    role, name, expected_base_manifest_sha256, manifest["files"][file], table, raw_pin
                )
    dependency_meta = {
        "format": "repoe-fk-dependencies/v1",
        "interpretation": lock["interpretation"],
        "packages": {},
        "roles": {role: {} for role in ROLES},
    }
    source_select = lock["source_dependency"]
    root = Path(source_select["package"])
    source_raw = read(root / "manifest.json", {"sha256": source_select["manifest_sha256"]}, reads)
    source = env._decode(source_raw)
    if (
        source["format"] != "repoe-observed-fk-dependencies/v1"
        or source["observed_client"] != receipt["observed_client"]
        or source["schema"] != strict.schemas()
    ):
        raise ValueError("Dependency observation/index/schema differs from source")
    payloads["fk-source-manifest.json"] = source_raw
    mapping = {}
    for file, pin in source["files"].items():
        if Path(file).name != file:
            raise ValueError("Unsafe dependency file")
        mapping[file] = "fk-source-" + file
        payloads[mapping[file]] = read(root / file, pin, reads)
    dependency_meta["packages"]["source"] = {"manifest": "fk-source-manifest.json", "files": mapping}
    source_tables = env._decode(payloads[mapping["tables.json"]])
    lookup = env._decode(payloads[mapping["index-lookup.json"]])
    acquisition = env._decode(payloads[mapping["acquisition.json"]])
    index_sha = receipt["observed_client"]["index_sha256"]
    if (
        set(source_tables) != set(DEPENDENCIES)
        or lookup["index"]["sha256"] != index_sha
        or not lookup["index"]["stable"]
        or acquisition["index"]["prior_sha256"] != index_sha
        or acquisition["index"]["stable"] is not True
        or acquisition["index"]["before"] != acquisition["index"]["after"]
        or acquisition["lookup_receipt_sha256"] != source["files"]["index-lookup.json"]["sha256"]
    ):
        raise ValueError("Dependency lookup/acquisition identity differs")
    if set(lock["targets"]) != set(DEPENDENCIES):
        raise ValueError("Exact three dependency target scope required")
    for name in DEPENDENCIES:
        table = source_tables[name]
        expected_path = "data/balance/" + name.lower() + ".datc64"
        if table["raw_resource"] != expected_path:
            raise ValueError("Wrong source dependency namespace")
        raw_pin = source["raw_resources"][expected_path]
        validate_dependency(table, schemas, raw_pin)
        found = [entry for entry in lookup["tables"] if entry["table"] == name]
        if (
            len(found) != 1
            or found[0]["default"]["status"] != "present"
            or found[0]["default"]["observed_exact_path"] != expected_path
        ):
            raise ValueError("Dependency exact default lookup missing")
        absent = found[0]["simplified_chinese"]
        sc_path = "data/balance/simplified chinese/" + name.lower() + ".datc64"
        if len(absent) != 1 or absent[0]["status"] != "absent" or absent[0]["query_path"].lower() != sc_path:
            raise ValueError("Community fallback lacks exact SC absence evidence")
        observed = [r for r in acquisition["local_preservation"]["resources"] if r["table"] == name]
        if len(observed) != 1 or observed[0]["identity"] != raw_pin or observed[0]["path"] != expected_path:
            raise ValueError("Dependency raw acquisition differs")
        for role in ROLES[:2]:
            sides[role][name] = table
            namespaces[role][name] = namespace(
                role, name, source_select["manifest_sha256"], source["files"]["tables.json"], table, raw_pin
            )
            dependency_meta["roles"][role][name] = {
                "package": "source",
                "payload": "tables.json",
                "table_pointer": "/" + name,
                "namespace": namespaces[role][name],
                "resolution": "exact-default" if role == "source_default" else INTERPRETATION,
                "absent_exact_path": None if role == "source_default" else sc_path,
                "index_sha256": index_sha,
            }
        selection = lock["targets"][name]
        package = Path(selection["package"])
        target_raw = read(package / "manifest.json", {"sha256": selection["manifest_sha256"]}, reads)
        target_manifest = env._decode(target_raw)
        if (
            any(target_manifest["source_identity"][k] != identity[k] for k in identity)
            or target_manifest["source_identity"].get("language", "English") != "English"
            or any(target_manifest["schema"].get(k) != v for k, v in strict.schemas().items())
        ):
            raise ValueError("Dependency target identity/schema mismatch")
        file = "tables.json" if "tables.json" in target_manifest["files"] else f"tables/{name}.json"
        target_payload = read(package / file, target_manifest["files"][file], reads)
        target_table = env._decode(target_payload)
        if file == "tables.json":
            target_table = target_table[name]
        raw_resource = target_table["raw_resource"]
        if raw_resource.lower() != expected_path:
            raise ValueError("Wrong dependency target namespace")
        target_raw_pin = target_manifest["source_identity"]["raw_resources"][raw_resource]
        validate_dependency(target_table, schemas, target_raw_pin)
        key = "target-" + name
        payloads["fk-" + key + "-manifest.json"] = target_raw
        payloads["fk-" + key + ".json"] = target_payload
        dependency_meta["packages"][key] = {
            "manifest": "fk-" + key + "-manifest.json",
            "files": {file: "fk-" + key + ".json"},
        }
        sides["target"][name] = target_table
        namespaces["target"][name] = namespace(
            "target", name, selection["manifest_sha256"], target_manifest["files"][file], target_table, target_raw_pin
        )
        dependency_meta["roles"]["target"][name] = {
            "package": key,
            "payload": file,
            "table_pointer": "/" + name if file == "tables.json" else "",
            "namespace": namespaces["target"][name],
            "resolution": "exact-English-target",
        }
    engine = Correspondence(sides, namespaces)
    binding = engine.bind(original_binding)
    payloads["strict-manifest.json"] = base_raw
    payloads["strict-binding.json"] = payloads["target_binding.json"]
    payloads["target_binding.json"] = env._json(binding)
    payloads["fk-policy-lock.json"] = lock_raw
    payloads["fk-dependencies.json"] = env._json(dependency_meta)
    manifest["format"] = "repoe-localized-tables/v3"
    manifest["parent_manifest_sha256"] = expected_base_manifest_sha256
    manifest["target_binding"]["policy_id"] = POLICY
    manifest["fk"] = {
        "policy_lock_sha256": expected_policy_lock_sha256,
        "dependencies": "fk-dependencies.json",
        "interpretation": lock["interpretation"],
    }
    manifest["summary"]["bindings"] = {
        name: {
            "accepted": sum(r["decision"] == "accepted" for r in table["records"]),
            "rejected": sum(r["decision"] == "rejected" for r in table["records"]),
        }
        for name, table in binding["tables"].items()
    }
    manifest["producer"].update(
        {
            file: env._sha((ROOT / file).read_bytes())
            for file in ["RePoE/native_fk_binding.py", "RePoE/native_fk_tables.py", "schema/pypoe-sources.json"]
        }
    )
    manifest["files"] = {file: {"bytes": len(raw), "sha256": env._sha(raw)} for file, raw in payloads.items()}
    payloads["manifest.json"] = env._json(manifest)
    for path, pin in list(reads.items()):
        read(path, pin, {})
    env._publish(output, base, payloads)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["base", "expected-base-manifest-sha256", "policy-lock", "expected-policy-lock-sha256", "out"]:
        parser.add_argument("--" + name, required=True)
    result = create_candidate(**vars(parser.parse_args()))
    print(json.dumps(result["summary"], ensure_ascii=False))


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    main()
