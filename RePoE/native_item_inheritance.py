"""Pinned item metadata literals and a separately named community tag interpretation."""

import argparse
from pathlib import Path
import re
import sys

from RePoE import native_descriptions as envelope


ROOT = Path(__file__).resolve().parents[1]
FORMAT = "repoe-item-inheritance/v1"
POLICY = "pypoe-66d1d744-base-tag-child-first-ordered-union/v1"
PYPOE = "66d1d7442c5718260e1a8efd24989d22987e91af"
MAX_FILES = 128
MAX_FILE_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_DEPTH = 12


def resource_path(name):
    if not isinstance(name, str) or not re.fullmatch(r"Metadata/Items/(?:[A-Za-z0-9_]+/)*[A-Za-z0-9_]+\.it", name):
        raise ValueError("Expected canonical item .it resource path")
    return name


def parse_item(name, raw):
    """Retain every physical line and field; never evaluate arbitrary key/value code."""
    resource_path(name)
    if not raw.startswith(b"\xff\xfe") or len(raw) > MAX_FILE_BYTES:
        raise ValueError("Expected bounded BOM-marked UTF-16LE metadata")
    text = raw[2:].decode("utf-16le", errors="strict")
    result = {"lines": [], "blocks": [], "fields": [], "directives": []}
    stack, pending, offset = [], None, 2
    parent = None
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        end = offset + len(line.encode("utf-16le"))
        location = {"line": number, "byte_span": [offset, end], "raw_text": line}
        result["lines"].append(location)
        offset = end
        token = line.strip()
        if not token or token.startswith(("//", "#")):
            continue
        if pending and token != "{":
            raise ValueError(f"Block label without opening brace: {name}:{number}")
        if token == "{":
            if pending is None or len(stack) >= 32:
                raise ValueError(f"Unexpected/deep block: {name}:{number}")
            label, start = pending
            block = {
                "ordinal": len(result["blocks"]),
                "name": label,
                "parent_ordinal": stack[-1] if stack else None,
                "scope": [result["blocks"][i]["name"] for i in stack] + [label],
                "byte_span": [start, None],
                "field_ordinals": [],
            }
            result["blocks"].append(block)
            stack.append(block["ordinal"])
            pending = None
            continue
        if token == "}":
            if not stack:
                raise ValueError(f"Unexpected closing brace: {name}:{number}")
            result["blocks"][stack.pop()]["byte_span"][1] = end
            continue
        empty = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\s*\{\s*\}", token)
        if empty:
            result["blocks"].append(
                {
                    "ordinal": len(result["blocks"]),
                    "name": empty[1],
                    "parent_ordinal": stack[-1] if stack else None,
                    "scope": [result["blocks"][i]["name"] for i in stack] + [empty[1]],
                    "byte_span": location["byte_span"],
                    "field_ordinals": [],
                }
            )
            continue
        extend = re.fullmatch(r'extends\s+"([^"\r\n]+)"', token)
        if extend and not stack:
            if parent is not None:
                raise ValueError(f"Multiple extends directives: {name}")
            literal = extend[1]
            target = None if literal == "nothing" else resource_path(literal + ".it")
            parent = {"literal": literal, "target": target, **location}
            result["directives"].append({"kind": "extends", **parent})
            continue
        if not stack and (re.fullmatch(r"version\s+\d+", token) or token == "abstract"):
            result["directives"].append({"kind": token.split()[0], **location})
            continue
        field = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)", token)
        if field and stack:
            value = {
                "ordinal": len(result["fields"]),
                "block_ordinal": stack[-1],
                "scope": [result["blocks"][i]["name"] for i in stack],
                "key": field[1],
                "rhs_literal": field[2],
                **location,
            }
            quoted = re.fullmatch(r'"([^"\\]*)"', field[2])
            if quoted:
                value["quoted_literal"] = quoted[1]
            result["blocks"][stack[-1]]["field_ordinals"].append(value["ordinal"])
            result["fields"].append(value)
            continue
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token):
            pending = (token, location["byte_span"][0])
            continue
        raise ValueError(f"Unrecognized metadata syntax: {name}:{number}")
    if parent is None or stack or pending or offset != len(raw):
        raise ValueError(f"Incomplete item metadata: {name}")
    for block in result["blocks"]:
        start, end = block["byte_span"]
        block["raw_slice_sha256"] = envelope._sha(raw[start:end])
    result["extends"] = parent
    return result


def interpret_tags(chain, files):
    occurrences, tags, diagnostics = [], [], []
    for resource in chain:
        file = files[resource]
        base_blocks = [b for b in file["blocks"] if b["scope"] == ["Base"]]
        if len(base_blocks) > 1:
            diagnostics.append({"resource": resource, "code": "multiple-base-blocks"})
        for field in file["fields"]:
            if field["scope"] != ["Base"] or field["key"] != "tag":
                continue
            occurrence = {"resource": resource, "field_ordinal": field["ordinal"], **field}
            occurrences.append(occurrence)
            if "quoted_literal" not in field or not field["quoted_literal"]:
                diagnostics.append({"resource": resource, "field_ordinal": field["ordinal"], "code": "nonliteral-tag"})
            elif field["quoted_literal"] not in tags:
                tags.append(field["quoted_literal"])
    return {
        "base_tag_occurrences": occurrences,
        "tag_interpretation": {
            "policy_id": POLICY,
            "authority": "community-parser-interpretation",
            "status": "rejected" if diagnostics else "supported",
            "tags": None if diagnostics else tags,
            "diagnostics": diagnostics,
        },
    }


def _inputs(source_lock, source, raw, expected_source_lock_sha256):
    lock_bytes = envelope._read(Path(source_lock), 2 * 1024 * 1024)
    if not envelope._digest(expected_source_lock_sha256) or envelope._sha(lock_bytes) != expected_source_lock_sha256:
        raise ValueError("Source lock differs from external expected byte pin")
    lock = envelope._decode(lock_bytes)
    if type(lock.get("schema_version")) is not int or lock["schema_version"] != 1:
        raise ValueError("Unsupported source lock schema")
    selected = lock["sources"][source]
    acquisition = selected.get("acquisition", {})
    if (
        selected.get("kind") != "official-client-resource-candidate"
        or selected.get("game") != "poe2"
        or not re.fullmatch(r"\d+(?:\.\d+){2,5}", selected.get("game_patch", ""))
        or selected.get("realm") not in {"international", "china"}
        or acquisition.get("status") not in {"unreviewed-acquisition-draft", "reviewed-source-input"}
        or not isinstance(acquisition.get("evidence"), list)
        or not acquisition["evidence"]
    ):
        raise ValueError("Explicit game/patch/realm/acquisition identity required")
    for item in acquisition["evidence"]:
        if (
            not isinstance(item, dict)
            or set(item) != {"kind", "sha256"}
            or not isinstance(item["kind"], str)
            or not item["kind"]
            or not envelope._digest(item["sha256"])
        ):
            raise ValueError("Invalid acquisition evidence")
    resources, roots = selected.get("resources"), selected.get("roots")
    if (
        not isinstance(resources, dict)
        or not 0 < len(resources) <= MAX_FILES
        or not isinstance(roots, list)
        or not roots
        or any(not isinstance(root, str) or root not in resources for root in roots)
        or len(set(roots)) != len(roots)
    ):
        raise ValueError("Explicit bounded resource inventory and roots required")
    raw_root = Path(raw).resolve(strict=True)
    verified, total, names = {}, 0, set()
    for name, pin in resources.items():
        resource_path(name)
        if name.casefold() in names:
            raise ValueError("Case-colliding metadata resources")
        names.add(name.casefold())
        if (
            not isinstance(pin, dict)
            or type(pin.get("bytes")) is not int
            or not 0 < pin["bytes"] <= MAX_FILE_BYTES
            or not envelope._digest(pin.get("sha256"))
        ):
            raise ValueError("Invalid metadata raw pin")
        total += pin["bytes"]
        if total > MAX_TOTAL_BYTES:
            raise ValueError("Metadata inventory exceeds byte bound")
        path = raw_root / name
        if not path.resolve(strict=True).is_relative_to(raw_root) or any(
            parent.is_symlink() for parent in [path, *path.parents] if parent != raw_root.parent
        ):
            raise ValueError("Raw metadata path escapes root or contains symlink")
        data = envelope._read(path, pin["bytes"])
        if len(data) != pin["bytes"] or envelope._sha(data) != pin["sha256"]:
            raise ValueError(f"Raw metadata fingerprint mismatch: {name}")
        verified[name] = data
    return lock_bytes, selected, verified, raw_root


def _payloads(lock_bytes, selected, verified, source):
    files = {name: parse_item(name, raw) for name, raw in sorted(verified.items())}
    roots, reached = {}, set()
    for name in selected["roots"]:
        chain, cursor = [], name
        while cursor is not None:
            if cursor not in files or cursor in chain or len(chain) > MAX_DEPTH:
                raise ValueError(f"Missing/cyclic/deep inheritance: {name} -> {cursor}")
            chain.append(cursor)
            reached.add(cursor)
            cursor = files[cursor]["extends"]["target"]
        roots[name] = {"chain_child_to_parent": chain, **interpret_tags(chain, files)}
    if reached != files.keys():
        raise ValueError("Metadata inventory contains resources outside root closure")
    pin = envelope._decode((ROOT / "schema/pypoe-sources.json").read_bytes())
    if pin["revision"] != PYPOE:
        raise ValueError("Tag interpretation source revision differs from policy ID")
    policy = {
        "id": POLICY,
        "authority": "community-parser-interpretation",
        "repository": "https://github.com/repoe-fork/pypoe",
        "revision": pin["revision"],
        "source_files": {name: pin["sources"][name] for name in ["poe/file/it.py", "poe/file/shared/keyvalues.py"]},
        "rule": "Visit child to parent; Base.tag literals in field order; retain first occurrence of each exact string.",
        "scope": "Base.tag only. Other fields/blocks remain ordered literals without merge, units or applicability rules.",
        "official_merge_semantics_certified": False,
    }
    document = {"format": FORMAT, "files": files, "roots": roots, "interpretation_policy": policy}
    payloads = {"inheritance.json": envelope._json(document), "source-lock.json": lock_bytes}
    manifest = {
        "format": FORMAT,
        "status": "partial-candidate",
        "production_ready": False,
        "source_identity": {
            "source": source,
            "source_lock_sha256": envelope._sha(lock_bytes),
            "selected_source_sha256": envelope._sha(envelope._json(selected)),
            **{key: selected[key] for key in ["kind", "game", "game_patch", "realm", "acquisition"]},
            "raw_resources": {
                name: {"bytes": len(raw), "sha256": envelope._sha(raw)} for name, raw in verified.items()
            },
        },
        "representation": {"payload": "inheritance.json", "format": FORMAT, "tag_policy_id": POLICY},
        "producer": {
            name: envelope._sha((ROOT / name).read_bytes())
            for name in [
                "RePoE/native_item_inheritance.py",
                "RePoE/native_descriptions.py",
                "schema/pypoe-sources.json",
            ]
        },
        "summary": {
            "files": len(files),
            "roots": len(roots),
            "raw_bytes": sum(map(len, verified.values())),
            "fields": sum(len(f["fields"]) for f in files.values()),
            "literal_base_tags": sum(
                field["scope"] == ["Base"] and field["key"] == "tag" for f in files.values() for field in f["fields"]
            ),
            "rejected_tag_roots": sum(r["tag_interpretation"]["status"] == "rejected" for r in roots.values()),
        },
        "limits": ["Selected item .it closure only; no actor .ot or unique catalogue.", policy["scope"]],
        "files": {name: {"bytes": len(raw), "sha256": envelope._sha(raw)} for name, raw in payloads.items()},
    }
    payloads["manifest.json"] = envelope._json(manifest)
    return manifest, payloads


def create_candidate(*, source_lock, source, raw, out, expected_source_lock_sha256):
    sys.dont_write_bytecode = True
    output = Path(out).absolute()
    cache = ROOT.resolve(strict=True) / ".cache"
    if output.exists() or output.is_symlink():
        raise FileExistsError("Refusing to replace inheritance candidate")
    if output.resolve() == cache or not output.resolve().is_relative_to(cache):
        raise ValueError("Inheritance output must be beneath this checkout's .cache/")
    args = (source_lock, source, raw, expected_source_lock_sha256)
    lock_bytes, selected, verified, raw_root = _inputs(*args)
    if output.resolve().is_relative_to(raw_root):
        raise ValueError("Output cannot enter raw input")
    manifest, payloads = _payloads(lock_bytes, selected, verified, source)
    if _inputs(*args)[:3] != (lock_bytes, selected, verified):
        raise ValueError("Inheritance raw inputs changed during parsing")
    for name, digest in manifest["producer"].items():
        if envelope._sha((ROOT / name).read_bytes()) != digest:
            raise ValueError("Inheritance producer changed during parsing")
    envelope._publish(output, raw_root, payloads)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["source-lock", "raw", "out"]:
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--source", required=True)
    parser.add_argument("--expected-source-lock-sha256", required=True)
    args = parser.parse_args()
    try:
        manifest = create_candidate(**vars(args))
    except (ValueError, KeyError, OSError, TypeError, UnicodeError) as error:
        parser.exit(1, f"item-inheritance: {error}\n")
    print(envelope._json(manifest["summary"]).decode(), end="")


if __name__ == "__main__":
    main()
