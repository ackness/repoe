"""Selected actor template literals and parent links, without merge or effect rules."""

from pathlib import Path
import re

from RePoE import native_descriptions as envelope


ROOT = Path(__file__).resolve().parents[1]
FORMAT = "repoe-actor-templates/v1"
MAX_FILES = 64
MAX_FILE_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 4 * 1024 * 1024
MAX_DEPTH = 16


def resource_path(name):
    if not isinstance(name, str) or not re.fullmatch(r"Metadata/(?:[A-Za-z0-9_]+/)*[A-Za-z0-9_]+\.otc?", name):
        raise ValueError("Expected a portable Metadata .ot/.otc resource path")
    return name


def _structure(lines):
    """Mask string contents and line comments only for structural brace counting."""
    result, quote, escaped = [], None, False
    for line in lines:
        masked, i = [], 0
        while i < len(line):
            char = line[i]
            if quote:
                masked.append(char if char == quote and not escaped else "\n" if char == "\n" else " ")
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
            elif line[i : i + 2] == "//" or (char == "#" and not line[:i].strip()):
                masked.extend("\n" if c == "\n" else " " for c in line[i:])
                break
            elif line[i : i + 2] == "/*":
                raise ValueError("Unsupported C-style actor block comment")
            elif char in "\"'":
                quote = char
                masked.append(char)
            else:
                masked.append(char)
            i += 1
        result.append("".join(masked))
    if quote:
        raise ValueError("Unterminated quoted actor literal")
    return result


def parse_template(name, raw):
    """Keep physical lines and ordered syntax; event RHS bodies remain opaque."""
    resource_path(name)
    if not raw.startswith(b"\xff\xfe") or len(raw) > MAX_FILE_BYTES:
        raise ValueError("Expected bounded BOM-marked UTF-16LE actor metadata")
    text = raw[2:].decode("utf-16le", errors="strict")
    lines = text.splitlines(keepends=True)
    structure = _structure(lines)
    result = {"lines": [], "blocks": [], "fields": [], "directives": [], "order": []}
    offset = 2
    for number, line in enumerate(lines, 1):
        end = offset + len(line.encode("utf-16le"))
        result["lines"].append({"line": number, "byte_span": [offset, end], "raw_text": line})
        offset = end
    stack, parent, i = [], None, 0

    def location(first, last):
        return {
            "line": first + 1,
            "byte_span": [result["lines"][first]["byte_span"][0], result["lines"][last]["byte_span"][1]],
            "raw_text": "".join(lines[first : last + 1]),
        }

    def append(kind, value):
        value["ordinal"] = len(result[kind + "s"])
        result[kind + "s"].append(value)
        result["order"].append({"kind": kind, "ordinal": value["ordinal"]})
        return value["ordinal"]

    while i < len(lines):
        token, structural = lines[i].strip(), structure[i].strip()
        if not structural:
            if token and not token.startswith(("//", "#")):
                raise ValueError(f"Unrecognized quoted actor syntax: {name}:{i + 1}")
            i += 1
            continue
        if structural == "}":
            if not stack:
                raise ValueError(f"Unexpected actor closing brace: {name}:{i + 1}")
            ordinal = stack.pop()
            result["blocks"][ordinal]["byte_span"][1] = result["lines"][i]["byte_span"][1]
            result["order"].append({"kind": "block-close", "ordinal": ordinal})
            i += 1
            continue
        directive = re.fullmatch(r'extends\s+"([^"\r\n]+)"', token)
        if not stack and directive:
            if parent is not None:
                raise ValueError(f"Multiple actor extends directives: {name}")
            literal = directive[1]
            suffix = Path(name).suffix
            parent = {
                "literal": literal,
                "target": None if literal == "nothing" else resource_path(literal + suffix),
                **location(i, i),
            }
            append("directive", {"kind": "extends", **parent})
            i += 1
            continue
        if not stack and (re.fullmatch(r"version\s+\d+", token) or token == "abstract"):
            append("directive", {"kind": token.split()[0], **location(i, i)})
            i += 1
            continue
        field = re.fullmatch(r"([^\s={}]+)\s*=(.*)", token)
        if field and stack:
            first, end = i, i
            rhs_structure = structure[i].split("=", 1)[1].strip()
            if not field[2].strip() or field[2].lstrip().startswith("//"):
                following = i + 1
                while following < len(lines) and not structure[following].strip():
                    following += 1
                if following < len(lines) and structure[following].strip().startswith("{"):
                    end, rhs_structure = following, structure[following].strip()
            opaque = rhs_structure.startswith("{")
            if opaque:
                body_start = end
                depth, finished = 0, False
                while end < len(lines):
                    part = rhs_structure if end == body_start else structure[end]
                    for column, char in enumerate(part):
                        if char == "{":
                            depth += 1
                            if depth > 128:
                                raise ValueError("Actor RHS nesting exceeds bound")
                        elif char == "}":
                            depth -= 1
                            if depth < 0:
                                raise ValueError(f"Unbalanced actor RHS: {name}:{end + 1}")
                            if depth == 0:
                                if part[column + 1 :].strip():
                                    raise ValueError(f"Trailing actor RHS syntax: {name}:{end + 1}")
                                finished = True
                                break
                    if finished:
                        break
                    end += 1
                if not finished:
                    raise ValueError(f"Unterminated actor RHS: {name}:{first + 1}")
            elif "{" in rhs_structure or "}" in rhs_structure:
                raise ValueError(f"Unsupported actor RHS braces: {name}:{i + 1}")
            loc = location(first, end)
            rhs = loc["raw_text"].split("=", 1)[1].lstrip(" \t").rstrip("\r\n")
            value = {
                "block_ordinal": stack[-1],
                "scope": [result["blocks"][b]["name"] for b in stack],
                "key": field[1],
                "rhs_literal": rhs,
                "rhs_kind": "opaque-braced" if opaque else "literal",
                **loc,
            }
            ordinal = append("field", value)
            result["blocks"][stack[-1]]["field_ordinals"].append(ordinal)
            i = end + 1
            continue
        block = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\s*(\{\s*\}?)?", structural)
        if block:
            first, empty = i, bool(block[2] and "}" in block[2])
            if not block[2]:
                i += 1
                while i < len(lines) and not structure[i].strip():
                    i += 1
                if i == len(lines) or structure[i].strip() != "{":
                    raise ValueError(f"Actor block label without brace: {name}:{first + 1}")
            if len(stack) >= 32:
                raise ValueError("Actor syntax nesting exceeds bound")
            value = {
                "name": block[1],
                "parent_ordinal": stack[-1] if stack else None,
                "scope": [result["blocks"][b]["name"] for b in stack] + [block[1]],
                "byte_span": [
                    result["lines"][first]["byte_span"][0],
                    result["lines"][i]["byte_span"][1] if empty else None,
                ],
                "field_ordinals": [],
            }
            ordinal = append("block", value)
            if empty:
                result["order"].append({"kind": "block-close", "ordinal": ordinal})
            else:
                stack.append(ordinal)
            i += 1
            continue
        raise ValueError(f"Unrecognized actor syntax: {name}:{i + 1}")
    if parent is None or stack or offset != len(raw):
        raise ValueError(f"Incomplete actor metadata: {name}")
    for block in result["blocks"]:
        start, end = block["byte_span"]
        block["raw_slice_sha256"] = envelope._sha(raw[start:end])
    result["extends"] = parent
    return result


def parent_chains(roots, files):
    """Report literal links and failures independently from syntax or field merging."""
    result, reached = {}, set()
    for root in roots:
        chain, cursor, diagnostic = [], root, None
        while cursor is not None:
            if cursor in chain:
                diagnostic = {"code": "cycle", "resource": cursor}
                break
            if cursor not in files:
                diagnostic = {"code": "missing-resource", "resource": cursor}
                break
            if len(chain) == MAX_DEPTH:
                diagnostic = {"code": "depth-limit", "resource": cursor}
                break
            chain.append(cursor)
            reached.add(cursor)
            cursor = files[cursor]["extends"]["target"]
        result[root] = {
            "chain_child_to_parent": chain,
            "status": "unresolved" if diagnostic else "literal-nothing-terminated",
            "diagnostic": diagnostic,
        }
    return result, reached


def _inputs(source_lock, source, raw, expected_source_lock_sha256):
    lock_bytes = envelope._read(Path(source_lock), 2 * 1024 * 1024)
    if not envelope._digest(expected_source_lock_sha256) or envelope._sha(lock_bytes) != expected_source_lock_sha256:
        raise ValueError("Source lock differs from external expected byte pin")
    lock = envelope._decode(lock_bytes)
    if not isinstance(lock, dict) or type(lock.get("schema_version")) is not int or lock["schema_version"] != 1:
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
    for evidence in acquisition["evidence"]:
        if (
            not isinstance(evidence, dict)
            or set(evidence) != {"kind", "sha256"}
            or not isinstance(evidence["kind"], str)
            or not evidence["kind"]
            or not envelope._digest(evidence["sha256"])
        ):
            raise ValueError("Invalid acquisition evidence")
    resources, roots = selected.get("resources"), selected.get("roots")
    if (
        not isinstance(resources, dict)
        or not 0 < len(resources) <= MAX_FILES
        or not isinstance(roots, list)
        or not roots
        or any(not isinstance(r, str) or r not in resources for r in roots)
        or len(set(roots)) != len(roots)
    ):
        raise ValueError("Explicit bounded resources and unique roots required")
    raw_root = Path(raw).resolve(strict=True)
    verified, total, names = {}, 0, set()
    for name, pin in resources.items():
        resource_path(name)
        if name.casefold() in names:
            raise ValueError("Case-colliding actor resources")
        names.add(name.casefold())
        if (
            not isinstance(pin, dict)
            or type(pin.get("bytes")) is not int
            or not 0 < pin["bytes"] <= MAX_FILE_BYTES
            or not envelope._digest(pin.get("sha256"))
        ):
            raise ValueError("Invalid actor raw pin")
        total += pin["bytes"]
        if total > MAX_TOTAL_BYTES:
            raise ValueError("Actor raw inventory exceeds byte bound")
        path = raw_root / name
        if not path.resolve(strict=True).is_relative_to(raw_root) or any(p.is_symlink() for p in [path, *path.parents]):
            raise ValueError("Actor raw path escapes root or contains symlink")
        data = envelope._read(path, pin["bytes"])
        if len(data) != pin["bytes"] or envelope._sha(data) != pin["sha256"]:
            raise ValueError(f"Actor raw fingerprint mismatch: {name}")
        verified[name] = data
    return lock_bytes, selected, verified, raw_root


def create_candidate(*, source_lock, source, raw, out, expected_source_lock_sha256):
    """Publish one explicit offline candidate with a completion-last manifest."""
    output = Path(out).absolute()
    cache = ROOT.resolve(strict=True) / ".cache"
    if output.exists() or output.is_symlink():
        raise FileExistsError("Refusing to replace actor template candidate")
    if output.resolve() == cache or not output.resolve().is_relative_to(cache):
        raise ValueError("Actor output must be beneath this checkout's .cache/")
    args = (source_lock, source, raw, expected_source_lock_sha256)
    lock_bytes, selected, verified, raw_root = _inputs(*args)
    if output.resolve().is_relative_to(raw_root):
        raise ValueError("Actor output cannot enter raw input")
    producer = {
        name: envelope._sha((ROOT / name).read_bytes())
        for name in ["RePoE/native_actor_templates.py", "RePoE/native_descriptions.py"]
    }
    files = {name: parse_template(name, data) for name, data in sorted(verified.items())}
    roots, reached = parent_chains(selected["roots"], files)
    if reached != files.keys():
        raise ValueError("Actor resources outside bounded root traversal")
    document = {
        "format": FORMAT,
        "files": files,
        "roots": roots,
        "parent_path_convention": "Literal nothing terminates; otherwise append the child's .ot/.otc suffix to the literal stem. Candidate path identity requires separate index evidence.",
        "interpretation": {
            "merge_law": None,
            "mod_list": None,
            "effect_evaluation": None,
            "event_rhs": "opaque literal; never executed",
        },
    }
    payloads = {"templates.json": envelope._json(document), "source-lock.json": lock_bytes}
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
                name: {"bytes": len(data), "sha256": envelope._sha(data)} for name, data in verified.items()
            },
        },
        "representation": {"payload": "templates.json", "format": FORMAT},
        "producer": producer,
        "summary": {
            "files": len(files),
            "roots": len(roots),
            "raw_bytes": sum(map(len, verified.values())),
            "blocks": sum(len(f["blocks"]) for f in files.values()),
            "fields": sum(len(f["fields"]) for f in files.values()),
            "opaque_rhs_fields": sum(f["rhs_kind"] == "opaque-braced" for v in files.values() for f in v["fields"]),
            "unresolved_roots": sum(r["status"] == "unresolved" for r in roots.values()),
        },
        "limits": [
            "Selected literal syntax and parent links only; no field merge, units, numerical effects or runtime adoption.",
            "Caller-declared patch/realm/acquisition and raw pins are not source authentication or authoritative path spelling.",
            "Language identity is not established by default resource paths or English-looking literals.",
            "Missing/cyclic/deep parents remain diagnosed; successful syntax parsing does not imply complete client metadata.",
        ],
        "files": {name: {"bytes": len(data), "sha256": envelope._sha(data)} for name, data in payloads.items()},
    }
    payloads["manifest.json"] = envelope._json(manifest)
    if _inputs(*args)[:3] != (lock_bytes, selected, verified):
        raise ValueError("Actor inputs changed during parsing")
    if any(envelope._sha((ROOT / name).read_bytes()) != digest for name, digest in producer.items()):
        raise ValueError("Actor producer changed during parsing")
    envelope._publish(output, raw_root, payloads)
    return manifest
