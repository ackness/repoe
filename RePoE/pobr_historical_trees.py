"""Restore attribute selectors in pinned historical compatibility trees.

The retired extractor selected the first nested options[1].stats instead of
the node's own stats. This bounded projection consumes only a published RePoE
game part, not Lua, current trees, a consumer checkout or arbitrary snapshots.
"""

import argparse
import copy
import io
import json
from pathlib import Path
import re
import stat
import tempfile
import zipfile

from RePoE import publication_index as pub
from RePoE.data_publication import ROOT, archive_manifest, decode, encoded, pin, pinned, require, safe_path

POLICY = "pobr-historical-attribute-selectors/v1"
PART_SCHEMA = "pobr-build-data-part/v1"
PRODUCERS = (
    "RePoE/__init__.py",
    "RePoE/pobr_historical_trees.py",
    "RePoE/data_publication.py",
    "RePoE/publication_index.py",
)


def runtime_encoded(value):
    """Retain the historical JSON member/field order and pretty-print convention."""
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()


def project(raw, binding):
    """Repair only the reviewed identity set in one exact retained tree.

    Name is an index into this byte-pinned compatibility input, not a general
    gameplay rule. The independently reviewed selector identity digest prevents
    a fixed Strength node (or a newly added/renamed Attribute) from joining it.
    """
    pinned(raw, binding["input"])
    nodes = decode(raw)
    require(isinstance(nodes, list) and len(nodes) == binding["nodes"], "Historical node inventory changed")
    seen, selectors = set(), []
    for node in nodes:
        require(isinstance(node, dict), "Invalid historical node")
        skill = node.get("skill")
        require(type(skill) is int and 0 <= skill <= 0xFFFFFFFF and skill not in seen, "Invalid/duplicate skill")
        seen.add(skill)
        if node.get("name") != "Attribute":
            continue
        require(
            node.get("id") == str(skill)
            and node.get("kind") == "normal"
            and node.get("stats") == ["+5 to Strength"]
            and node.get("native_stats") is None
            and not node.get("variants")
            and node.get("ascendancy_id") is None
            and not node.get("apply_to_armour", False),
            f"Unreviewed attribute selector shape: {skill}",
        )
        selectors.append(skill)
    selectors.sort()
    require(len(selectors) == binding["selectors"], "Historical selector count changed")
    pinned(encoded(selectors), binding["selector_ids"])
    output = copy.deepcopy(nodes)
    selected = set(selectors)
    for node in output:
        if node["skill"] in selected:
            node["stats"] = ["+5 to any Attribute"]
    projected = runtime_encoded(output)
    return projected, {
        "input": pin(raw),
        "output": pin(projected),
        "nodes": len(nodes),
        "selectors": len(selectors),
        "selector_ids": selectors,
        "unchanged_nodes": len(nodes) - len(selectors),
    }


def load_policy(path, sha256):
    raw = pub.read_metadata(path)
    require(pub.SHA.fullmatch(sha256) and pin(raw)["sha256"] == sha256, "Policy SHA-256 mismatch")
    policy = decode(raw)
    require(policy.get("schema") == POLICY, "Unsupported historical selector policy")
    pub.target(policy["target"])
    require(policy["target"]["game"] == "poe2", "PoE2 historical trees required")
    pub.input_declaration("game", policy["game_input"])
    require(isinstance(policy.get("versions"), dict) and policy["versions"], "Missing historical versions")
    for version, binding in policy["versions"].items():
        require(re.fullmatch(r"[0-9]+_[0-9]+", version), "Invalid historical tree version")
        pub.byte_pin(binding["input"])
        pub.byte_pin(binding["selector_ids"])
        require(
            type(binding.get("nodes")) is int
            and type(binding.get("selectors")) is int
            and 0 < binding["selectors"] <= binding["nodes"],
            "Invalid historical selector inventory",
        )
    require(isinstance(policy.get("evidence"), dict) and policy["evidence"], "Missing historical provenance")
    return raw, policy


def assemble(repo, policy_path, policy_sha256, name, out):
    """Write a fresh local game candidate using the existing package/handoff contract."""
    repo, policy_path, out = map(safe_path, (repo, policy_path, out))
    require(out.is_relative_to(ROOT / ".cache") and not out.exists(), "Fresh repository cache output required")
    require(not policy_path.is_relative_to(out), "Output overlaps policy")
    require(pub.TOKEN.fullmatch(name), "Invalid handoff name")
    policy_raw, policy = load_policy(policy_path, policy_sha256)
    producer = {path: pin((ROOT / path).read_bytes()) for path in PRODUCERS}
    game, target = policy["game_input"], policy["target"]
    game_raw = pub.tree_blob(repo, game["revision"], game["path"], game)
    with zipfile.ZipFile(io.BytesIO(game_raw)) as archive:
        original_manifest, base = archive_manifest(archive, game)
        require(
            base.get("schema") == PART_SCHEMA and base.get("kind") == "game" and base.get("target") == target,
            "Game part target/schema mismatch",
        )
        members = {member: pinned(archive.read(member), expected) for member, expected in base["files"].items()}
    version = target["game_patch"]
    prefix = f"data/{version}/base/passive_trees/"
    expected_paths = {f"{prefix}{v}.json" for v in policy["versions"]}
    require(
        {path for path in members if path.startswith(prefix)} == expected_paths,
        "Unreviewed/missing historical tree version",
    )
    snapshot_path = f"data/{version}/manifest.json"
    original_snapshot = members[snapshot_path]
    snapshot = decode(original_snapshot)
    require(
        snapshot.get("schema_version") == 3 and snapshot.get("poe_version") == version,
        "Snapshot version/schema mismatch",
    )
    require(
        {f"data/{version}/{path}" for path in snapshot["files"] if path.startswith("base/passive_trees/")}
        == expected_paths,
        "Snapshot historical inventory mismatch",
    )
    records = {}
    for tree_version, binding in sorted(policy["versions"].items()):
        path = f"{prefix}{tree_version}.json"
        relative_path = f"base/passive_trees/{tree_version}.json"
        require(snapshot["files"][relative_path] == pin(members[path])["sha256"], "Snapshot tree pin mismatch")
        members[path], records[tree_version] = project(members[path], binding)
        snapshot["files"][relative_path] = pin(members[path])["sha256"]
    # Only four tree digests change. All other snapshot metadata and file pins
    # remain historical, including files supplied separately by other owners.
    members[snapshot_path] = runtime_encoded(snapshot)
    manifest = {
        "schema": PART_SCHEMA,
        "kind": "game",
        "target": target,
        "production_ready": False,
        "retained_input_package": game,
        # Preserve the complete old composition/limits, not just a newer label.
        "retained_input_manifest": base,
        "projection": {
            "policy": policy,
            "policy_pin": pin(policy_raw),
            "producer": producer,
            "trees": records,
            "snapshot": {
                "path": snapshot_path,
                "input": pin(original_snapshot),
                "output": pin(members[snapshot_path]),
            },
        },
        "limits": [
            "Bounded historical compatibility repair; not current client facts or full historical tree parity.",
            "Only reviewed attribute-selector stats and their snapshot digests change.",
            "All other package members retain their exact bytes and original provenance/limits.",
            "No Lua/vendor, current-tree substitution, client acquisition, remote publication or consumer adoption.",
        ],
        "files": {member: pin(raw) for member, raw in sorted(members.items())},
    }
    manifest_raw = encoded(manifest)
    require(pub.read_metadata(policy_path) == policy_raw, "Policy changed during assembly")
    require({path: pin((ROOT / path).read_bytes()) for path in PRODUCERS} == producer, "Producer changed")
    require(pin(original_manifest) == game["manifest"], "Retained manifest identity changed")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".historical-tree-assembly-", dir=out.parent) as temporary:
        stage = Path(temporary) / "result"
        stage.mkdir()
        # Match data_publication and the crafting game-part assembler's archive
        # convention. package.json is written last; no partial output is accepted.
        with zipfile.ZipFile(stage / "data.zip", "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for member in sorted([*members, "manifest.json"]):
                info = zipfile.ZipInfo(member, (1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                raw = manifest_raw if member == "manifest.json" else members[member]
                archive.writestr(info, raw, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        result = {
            "schema": "repoe-data-package/v1",
            "publication": "local-only",
            "repository": pub.OWNER,
            "path": f"handoff/{name}/game-build-part.zip",
            "ref": f"refs/tags/handoff/{name}",
            **pin((stage / "data.zip").read_bytes()),
            "manifest": pin(manifest_raw),
            "expanded_bytes": len(manifest_raw) + sum(map(len, members.values())),
            "target": target,
        }
        (stage / "manifest.json").write_bytes(manifest_raw)
        (stage / "package.json").write_bytes(encoded(result))
        stage.rename(out)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT, help="Read-only local RePoE Git objects")
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--policy-sha256", required=True)
    parser.add_argument("--name", required=True, help="Proposed handoff name; no tag is created")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = assemble(args.repo, args.policy, args.policy_sha256, args.name, args.out)
    print(encoded(result).decode(), end="")


if __name__ == "__main__":
    main()
