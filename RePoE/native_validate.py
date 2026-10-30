"""Accept native facts against caller-pinned raw inputs, including every graph projection."""

import argparse
from collections import defaultdict
from contextlib import redirect_stdout
import json
from pathlib import Path
import struct
import sys

from RePoE import native_facts as facts
from RePoE import schema_candidate
from RePoE.native_tools import PIN, pinned_pypoe


def _equal(actual, expected, context):
    # Preserve order and JSON types: True must not compare equal to integer 1.
    if facts._json(actual) != facts._json(expected):
        raise ValueError(f"Native facts differ from raw replay: {context}")


def validate_graph_instances(raw_psg, passive_table, graph, passives):
    """An acceptance invariant independent of the producer's _projections code.

    passive_table must first be verified against raw DAT. Never use candidate
    definitions or graph.json as the authority for the repeated instance fields.
    """
    framed = facts._frame_psg(raw_psg)
    _equal({key: graph[key] for key in framed}, framed, "graph.json PSG fields")
    by_graph = defaultdict(list)
    definitions = passives["definitions"]
    rows = passive_table["rows"]
    if len(definitions) != len(rows):
        raise ValueError("Passive definition inventory differs from raw DAT")
    members = {node["graph_id"] for group in framed["groups"] for node in group["nodes"]}
    for index, (row, definition) in enumerate(zip(rows, definitions, strict=True)):
        identity = {"row": index, "id": row["values"]["Id"]}
        graph_id = row["values"]["PassiveSkillGraphId"]
        _equal(definition["definition"], identity, f"definition identity at {index}")
        _equal(definition["graph_id"], graph_id, f"definition graph ID at {index}")
        _equal(definition["in_default_graph"], graph_id in members, f"definition membership at {index}")
        by_graph[graph_id].append(identity)
    expected, seen = [], set()
    for group in framed["groups"]:
        for node in group["nodes"]:
            graph_id = node["graph_id"]
            if graph_id in seen or len(by_graph[graph_id]) != 1:
                raise ValueError(f"Nonunique PSG instance or definition join: {graph_id}")
            seen.add(graph_id)
            expected.append({**node, "group": group["group"], "definition": by_graph[graph_id][0]})
    _equal(passives["default_graph_instances"], expected, "default_graph_instances inventory/order/fields")
    return len(expected)


def validate_candidate(*, source_lock, source, raw, candidate, manifest_sha256=None, profile=facts.BASE_PROFILE):
    directory = Path(candidate).resolve(strict=True)
    manifest_raw = (directory / "manifest.json").read_bytes()
    manifest_hash = schema_candidate._sha(manifest_raw)
    if manifest_sha256 is not None and manifest_hash != manifest_sha256:
        raise ValueError("Externally pinned manifest SHA256 mismatch")
    manifest = json.loads(manifest_raw)
    selected_tables = facts.profile_tables(profile)
    names = {f"tables/{name}.json" for name in selected_tables} | {
        "graph.json",
        "passives.json",
        "skills.json",
        "diagnostics.json",
    }
    if profile != facts.BASE_PROFILE:
        names.update({"skill_core.json", "source-lock.json"})
    if profile == facts.GEMS_PROFILE:
        names.update({"gems.json", "constraints.json"})
    if set(manifest["files"]) != names:
        raise ValueError("Unexpected native facts payload inventory")
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file() or p.is_symlink()}
    if actual != names | {"manifest.json"}:
        raise ValueError("Unexpected native facts directory inventory")
    payloads = {}
    for name in sorted(names):
        path = (directory / name).resolve(strict=True)
        if not path.is_relative_to(directory):
            raise ValueError(f"Candidate path escapes root: {name}")
        data = path.read_bytes()
        _equal(manifest["files"][name], {"bytes": len(data), "sha256": schema_candidate._sha(data)}, name + " hash")
        payloads[name] = json.loads(data)

    source_lock_bytes = Path(source_lock).read_bytes() if profile != facts.BASE_PROFILE else None
    verified, identity = facts._verified_raw(source_lock, source, raw, profile=profile)
    if profile != facts.BASE_PROFILE and (directory / "source-lock.json").read_bytes() != source_lock_bytes:
        raise ValueError("Source-lock payload differs from exact input bytes")
    with pinned_pypoe() as tool_identity, redirect_stdout(sys.stderr):
        expected_manifest, replay = facts._candidate_payloads(
            verified, identity, tool_identity, profile=profile, source_lock_bytes=source_lock_bytes
        )
    for key in ("format", "status", "production_ready", "source_identity", "row_key", "scope", "summary", "schema"):
        _equal(manifest[key], expected_manifest[key], "manifest." + key)
    if profile != facts.BASE_PROFILE:
        _equal(manifest.get("profile"), profile, "manifest.profile")
        _equal(manifest["producer"], expected_manifest["producer"], "manifest.producer")
    pin = json.loads(PIN.read_bytes())
    if "trusted_source_pin_sha256" in manifest["decoder"]:
        _equal(manifest["decoder"]["trusted_source_pin_sha256"], tool_identity["pin_sha256"], "decoder source pin")
    # Older v1 receipts omitted legacy specs imported (but not used) by dat.py.
    # The validating replay always verifies the full installed source tree.
    old_inventory = {name for name in pin["sources"] if not name.startswith("poe/file/specification/data/")}
    if manifest["decoder"]["pypoe_revision"] != pin["revision"] or (
        set(manifest["decoder"]["sources"]) not in (set(pin["sources"]), old_inventory)
        or any(digest not in pin["sources"][name] for name, digest in manifest["decoder"]["sources"].items())
    ):
        raise ValueError("Candidate decoder identity differs from trusted Git pin")
    if profile != facts.BASE_PROFILE and (
        set(manifest["decoder"]["sources"]) != set(pin["sources"])
        or manifest["decoder"].get("trusted_source_pin_sha256") != tool_identity["pin_sha256"]
    ):
        raise ValueError("Extended facts require the complete trusted decoder profile")
    # First establish the DAT authority, then independently check both PSG
    # representations. This also catches a future producer projection regression.
    for name in selected_tables:
        file = f"tables/{name}.json"
        _equal(payloads[file], json.loads(replay[file]), file)
    instances = validate_graph_instances(
        verified[facts.PSG], payloads["tables/PassiveSkills.json"], payloads["graph.json"], payloads["passives.json"]
    )
    for name in sorted(names):
        _equal(payloads[name], json.loads(replay[name]), name)
    return {
        "result": "passed",
        "manifest_sha256": manifest_hash,
        "source_identity": identity,
        "summary": manifest["summary"],
        "complete_graph_instances_checked": instances,
        "validator_sha256": schema_candidate._sha(Path(__file__).read_bytes()),
        "replay_producer": expected_manifest["producer"],
        "trusted_source_pin_sha256": tool_identity["pin_sha256"],
        "scope": "Raw replay and complete repeated graph facts; source authenticity remains caller-pinned.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-lock", required=True, type=Path)
    parser.add_argument("--source", required=True)
    parser.add_argument("--raw", required=True, type=Path)
    parser.add_argument("--facts", required=True, type=Path)
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--profile", choices=facts.PROFILES, default=facts.BASE_PROFILE)
    args = parser.parse_args()
    try:
        receipt = validate_candidate(
            source_lock=args.source_lock,
            source=args.source,
            raw=args.raw,
            candidate=args.facts,
            manifest_sha256=args.manifest_sha256,
            profile=args.profile,
        )
    except (ValueError, OSError, KeyError, TypeError, struct.error) as error:
        parser.exit(1, f"Native facts validation rejected: {error}\n")
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
