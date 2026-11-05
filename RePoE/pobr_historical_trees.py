"""Restore attribute selectors in pinned historical compatibility trees.

The retired extractor selected the first nested options[1].stats instead of
the node's own stats. This bounded projection reads only the byte-pinned trees
of a published RePoE game part, not Lua, current trees, a consumer checkout or
arbitrary snapshots. `release:build` runs it as the `historical-trees` job.
"""

import copy
import json

from RePoE.pins import decode, encoded, pin, pinned, require

POLICY = "pobr-historical-attribute-selectors/v1"


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
