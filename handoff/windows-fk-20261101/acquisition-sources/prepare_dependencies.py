"""Decode only acquired FK dependencies with the unchanged bounded probe engine."""
import collections
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import types
import zipfile

ROOT = Path(__file__).resolve().parents[2]
CACHE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from RePoE import native_locale_probe as probe
from RePoE import native_facts as facts

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()

commit = "7cb4918e1141f3af3b0e8295054386820cdc9db3"
git = lambda name: subprocess.check_output(["git", "-C", str(ROOT), "show", commit + ":handoff/mac-fk-targets-20261101/" + name])
inventory_raw = git("inventory.json")
assert sha(inventory_raw) == "061e67ae2eb6f7be41382e793af3fce287bb2541c93db1d1b9ec0ea56558e8ce"
inventory = json.loads(inventory_raw)
archive = git("targets.zip")
assert len(archive) == inventory["archive"]["bytes"] and sha(archive) == inventory["archive"]["sha256"]
target_root = CACHE / "targets"
target_root.mkdir(exist_ok=False)
with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
    assert set(bundle.namelist()) == set(inventory["files"])
    for name, pin in inventory["files"].items():
        raw = bundle.read(name)
        assert len(raw) == pin["bytes"] and sha(raw) == pin["sha256"]
        path = (target_root / name).resolve()
        assert path.is_relative_to(target_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
(target_root / "inventory.json").write_bytes(inventory_raw)
schema_raw = (ROOT / "schema/poe2.json").read_bytes()
assert sha(schema_raw) == probe.SCHEMA_SHA256
schemas = {table["name"]: table for table in json.loads(schema_raw)["tables"]}
assert sha((ROOT / "RePoE/native_locale_probe.py").read_bytes()) == "12b751d31bbbc0991e5fceb12df3752e76cebae476e08515b3e1f343410d79cc"
targets = {name: json.loads((target_root / "f77/tables" / (name + ".json")).read_bytes()) for name in ["ModType", "Stats"]}
targets["ItemVisualIdentity"] = json.loads((target_root / "item-visual-identity/tables.json").read_bytes())["ItemVisualIdentity"]
layouts, pins = {}, {}
kind_map = {"string": "ref|string", "foreignrow": "ref|out", "row": "ref|generic", "enumrow": "int", "bool": "bool", "i32": "int", "u32": "uint", "u16": "ushort", "f32": "float"}
for name, target in targets.items():
    assert len(target["physical_fields"]) == len(schemas[name]["columns"])
    assert target["columns"] == facts._columns(schemas[name], target["physical_fields"])
    layouts[name] = []
    for field, column in zip(target["physical_fields"], schemas[name]["columns"]):
        assert not column["interval"]
        kind = "ref|list|byte" if column["type"] == "array" else ("ref|list|" if column["array"] else "") + kind_map[column["type"]]
        layouts[name].append((field, kind))
    pins[name] = sha(encoded(schemas[name]["columns"]))
namespace = dict(vars(probe), LAYOUTS=layouts, COLUMN_PINS=pins)
decode = types.FunctionType(probe.decode_table.__code__, namespace)
validate = types.FunctionType(probe.validate_table.__code__, namespace)
acquisition_raw = (CACHE / "acquisition.json").read_bytes()
acquisition = json.loads(acquisition_raw)
tables, wires, identities, observations = {}, {}, {}, []
for receipt in acquisition["local_preservation"]["resources"]:
    name = receipt["table"]
    raw = (CACHE / receipt["file"]).read_bytes()
    pin = receipt["identity"]
    decoded = decode(name, raw, expected_bytes=pin["bytes"], expected_sha256=pin["sha256"])
    assert validate(decoded) == name
    tables[name] = {"table": name, "raw_resource": receipt["path"], "physical_fields": decoded["physical_fields"], "columns": facts._columns(schemas[name], decoded["physical_fields"]), "rows": decoded["rows"], "validation": decoded["validation"]}
    identities[receipt["path"]] = pin
    wires[name] = [{"context": t["context"], "raw_second_word_decimal": str(t["raw_second_word"])} for t in decoded["foreign_tail_observations"]]
    key = "Name" if name == "ModType" else "Id"
    groups = []
    for table in [tables[name], targets[name]]:
        mapping = collections.defaultdict(list)
        for row in table["rows"]:
            mapping[row["values"][key]].append(row)
        groups.append(mapping)
    counts, samples = collections.Counter(), []
    for identity in sorted(groups[0].keys() | groups[1].keys()):
        left, right = (g.get(identity, []) for g in groups)
        if len(left) != 1 or len(right) != 1:
            counts["missing_or_duplicate_key"] += 1
            continue
        fields = [field for field in decoded["physical_fields"] if left[0]["values"][field] != right[0]["values"][field]]
        counts["full_physical_equal" if not fields else "different:" + ",".join(fields)] += 1
        if len(samples) < 4:
            samples.append({"key": identity, "source_row": left[0]["_row"], "target_row": right[0]["_row"], "differing_fields": fields})
    observations.append({"table": name, "rows": len(decoded["rows"]), "columns": len(layouts[name]), "row_bytes": decoded["validation"]["schema_row_bytes"], "raw_identity": pin, "target_rows": len(targets[name]["rows"]), "counts": dict(counts), "samples": samples})
output = CACHE / "windows-dependencies"
output.mkdir(exist_ok=False)
payloads = {"tables.json": encoded(tables), "wire-observations.json": encoded(wires), "acquisition.json": acquisition_raw, "index-lookup.json": (CACHE / "lookup.json").read_bytes()}
manifest = {"format": "repoe-observed-fk-dependencies/v1", "status": "partial-observation-candidate", "production_ready": False, "observed_client": {"game": "poe2", "game_patch": None, "realm": None, "index_sha256": acquisition["index"]["prior_sha256"]}, "raw_resources": identities, "schema": {"revision": probe.SCHEMA_REVISION, "sha256": probe.SCHEMA_SHA256, "native_specification_sha256": "c9417f03e2205ff649721c3dbf9620ee0c703bf905b3cf53469ce3eda86f1e25"}, "decoder": {"method": "pinned-stdlib-probe-with-exact-target-schema-layout/v1", "original_probe_sha256": sha((ROOT / "RePoE/native_locale_probe.py").read_bytes()), "adapter_sha256": sha(Path(__file__).read_bytes()), "python": sys.version, "target_handoff_commit": commit, "target_inventory_sha256": sha(inventory_raw), "columns_sha256": pins}, "files": {name: {"bytes": len(raw), "sha256": sha(raw)} for name, raw in payloads.items()}}
for name, raw in payloads.items():
    (output / name).write_bytes(raw)
(output / "manifest.json").write_bytes(encoded(manifest))
(CACHE / "dependency-samples.json").write_bytes(encoded(observations))
print(json.dumps({"manifest_sha256": sha(encoded(manifest)), "observations": observations}, ensure_ascii=True))
