"""Lossless metadata lines and bounded literal inheritance, without stat merging.

AO and OT are distinct file formats. Sharing a stem never creates an inheritance
edge. Only the literal extends declaration selects a parent of the same format
(or an explicitly supplied extension). Assignment values remain raw tokens.
"""

from pathlib import PurePosixPath
import re


TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|//.*|[{}]|[^\s{}"]+')
NAME = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
ASSIGNMENT = re.compile(r"\s*([A-Za-z_][A-Za-z_0-9.%+\-]*)\s*=\s*(.*?)\s*\Z")


def resource_path(value):
    if (
        not isinstance(value, str)
        or len(value) > 512
        or not value.startswith("Metadata/")
        or PurePosixPath(value).suffix not in {".ao", ".ot"}
        or any(char in value for char in "\\:\x00")
        or any(ord(char) < 32 for char in value)
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ValueError(f"Unsafe native metadata resource: {value!r}")


def _tokens(line):
    tokens = []
    end = 0
    code_end = len(line)
    for match in TOKEN.finditer(line):
        if line[end : match.start()].strip():
            raise ValueError("Unterminated or unsupported metadata string")
        token = match.group()
        if token.startswith("//"):
            code_end = match.start()
            break
        if token.startswith("/*") or token.endswith("*/"):
            raise ValueError("Block comments require a separate lexical profile")
        tokens.append((token, match.start(), match.end()))
        end = match.end()
    else:
        if line[end:].strip():
            raise ValueError("Unterminated metadata string")
    return tokens, line[:code_end].rstrip()


def parse_metadata(path, raw):
    """Preserve every source line, scope and standalone assignment in order.

    This is lexical extraction only. Repeated blocks/keys and conditional scopes
    remain separate. Inline statements stay in their original line rather than
    being interpreted as effective Stats. Numeric tokens are never normalized.
    """
    resource_path(path)
    if not isinstance(raw, bytes) or not raw.startswith(b"\xff\xfe"):
        raise ValueError("Native metadata requires BOM UTF-16LE bytes")
    text = raw[2:].decode("utf-16-le", errors="strict")
    lines = text.splitlines(keepends=True)
    if len(lines) > 100000:
        raise ValueError("Metadata line limit exceeded")
    records, assignments, extends, diagnostics = [], [], [], []
    stack = []
    pending = None
    next_block = 0
    byte_start = 2
    for line_number, full_line in enumerate(lines, 1):
        literal = full_line.rstrip("\r\n")
        tokens, code = _tokens(literal)
        byte_end = byte_start + len(full_line.encode("utf-16-le"))
        record = {
            "line": line_number,
            "byte_start": byte_start,
            "byte_end": byte_end,
            "literal": literal,
            "scope": [dict(block) for block in stack],
        }
        if tokens and tokens[0][0] == "extends":
            if stack or len(tokens) != 2 or not tokens[1][0].startswith('"'):
                raise ValueError("Metadata extends must be an unambiguous top-level literal")
            parent = tokens[1][0][1:-1]
            target = None
            if parent != "nothing":
                target = parent if PurePosixPath(parent).suffix else parent + PurePosixPath(path).suffix
                resource_path(target)
            extends.append({"line": line_number, "literal": parent, "target": target})
        match = ASSIGNMENT.fullmatch(code) if not any(token[0] in {"{", "}"} for token in tokens) else None
        if match:
            value_start, value_end = match.span(2)
            assignments.append(
                {
                    "line": line_number,
                    "key_raw": match[1],
                    "value_raw": match[2],
                    "value_byte_start": byte_start + len(literal[:value_start].encode("utf-16-le")),
                    "value_byte_end": byte_start + len(literal[:value_end].encode("utf-16-le")),
                    "scope": [dict(block) for block in stack],
                    "plain_stats_scope": len(stack) == 1 and stack[0]["name_raw"] == "Stats",
                }
            )
        prefix = []
        for token, start, _ in tokens:
            if token == "{":
                name = prefix[0] if len(prefix) == 1 and NAME.fullmatch(prefix[0]) else pending
                if name is None:
                    name = f"opaque@{line_number}:{start}"
                    diagnostics.append({"code": "opaque_block_name", "line": line_number, "column": start})
                next_block += 1
                stack.append({"id": next_block, "name_raw": name, "open_line": line_number})
                if len(stack) > 32:
                    raise ValueError("Metadata block depth exceeded")
                pending, prefix = None, []
            elif token == "}":
                if not stack:
                    raise ValueError("Unmatched metadata closing brace")
                stack.pop()
                pending, prefix = None, []
            else:
                prefix.append(token)
        if tokens:
            pending = tokens[0][0] if len(tokens) == 1 and NAME.fullmatch(tokens[0][0]) else None
        records.append(record)
        byte_start = byte_end
    if stack:
        raise ValueError("Unclosed metadata block")
    if len(extends) != 1:
        raise ValueError("Exactly one literal metadata parent declaration is required")
    return {
        "format": "repoe-native-metadata-lines/v1",
        "path": path,
        "bytes": len(raw),
        "encoding": "BOM UTF-16LE",
        "records": records,
        "assignments": assignments,
        "extends": extends,
        "diagnostics": diagnostics,
        "merge_policy": "none; ordered lexical records only",
    }


def validate_closure(files, roots):
    """Validate exact literal closure in linear time, without actor binding."""
    reached, active, heights = set(), set(), {}

    def visit(path):
        if path in active:
            raise ValueError("Cyclic metadata inheritance")
        if path in heights:
            return heights[path]
        if path not in files:
            raise ValueError(f"Missing literal metadata parent: {path}")
        active.add(path)
        reached.add(path)
        target = files[path]["extends"][0]["target"]
        height = 0 if target is None else 1 + visit(target)
        if height > 16:
            raise ValueError("Metadata inheritance depth exceeded")
        active.remove(path)
        heights[path] = height
        return height

    for root in roots:
        visit(root)
    if reached != files.keys():
        raise ValueError("Metadata inventory has files outside the selected literal closure")
    return {root: heights[root] for root in roots}
