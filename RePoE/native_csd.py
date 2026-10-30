"""Read explicit PoE2 CSD lexical facts without selecting or rendering branches.

This parser is written from the acquired UTF-16 resources. It does not import
or copy PyPoE's translation parser/handler implementation.
"""

import hashlib
from pathlib import PurePosixPath
import re


BRANCH = re.compile(
    r"\s*(?P<conditions>(?:[0-9\-\|#!]+[ \t]+)+)"
    r'(?P<restrictions>(?:\w+[ \t]+)*)"(?P<template>[^"\r\n]*)"'
    r"(?P<handlers>(?:[ \t]+[\w%]+)*)[ \t]*"
)
LANGUAGE = re.compile(r'lang[ \t]+"([^"\r\n]+)"')
INCLUDE = re.compile(r'include[ \t]+"([^"\r\n]+)"')
PLACEHOLDER = re.compile(r"\{([^{}]*)\}")


def resource_path(value):
    """Require a canonical explicit resource name, never a host filesystem path."""
    if not isinstance(value, str) or "\\" in value or ":" in value:
        raise ValueError(f"Invalid CSD resource path: {value!r}")
    parts = value.split("/")
    if (
        len(parts) < 3
        or parts[:2] != ["Data", "StatDescriptions"]
        or any(not part or part in {".", ".."} for part in parts)
        or PurePosixPath(value).suffix != ".csd"
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError(f"Invalid CSD resource path: {value!r}")
    return value


class _Lines:
    def __init__(self, path, raw):
        if not raw.startswith(b"\xff\xfe") or len(raw) % 2:
            raise ValueError(f"{path}: expected BOM UTF-16LE resource")
        self.path, self.raw = path, raw
        text = raw[2:].decode("utf-16-le", errors="strict")
        self.lines = text.split("\n")
        if self.lines[-1] == "":
            self.lines.pop()
        self.offsets = [2]
        for index, line in enumerate(self.lines):
            suffix = "\n" if index + 1 < len(self.lines) or text.endswith("\n") else ""
            self.offsets.append(self.offsets[-1] + len((line + suffix).encode("utf-16-le")))
        if self.offsets[-1] != len(raw):
            raise ValueError(f"{path}: incomplete UTF-16 line accounting")
        self.position = 0

    def line(self):
        return self.lines[self.position].strip()

    def skip_blank(self):
        while self.position < len(self.lines) and not self.line():
            self.position += 1

    def span(self, start, end):
        return {
            "byte_start": self.offsets[start],
            "byte_end": self.offsets[end],
            "line_start": start + 1,
            "line_end": end,
        }

    def fail(self, message):
        raise ValueError(f"{self.path}:{self.position + 1}: {message}")

    def count(self):
        self.skip_blank()
        if self.position == len(self.lines) or not re.fullmatch(r"[0-9]+", self.line()):
            self.fail("expected branch count")
        count = int(self.line())
        self.position += 1
        if count > len(self.lines) - self.position:
            self.fail("branch count exceeds remaining source lines")
        return count


def _quantifiers(tokens):
    result = []
    for token in tokens:
        if token.isdecimal():
            if not result:
                raise ValueError("CSD quantifier argument without a preceding name")
            result[-1]["argument_tokens_raw"].append(token)
        else:
            result.append({"name_raw": token, "argument_tokens_raw": []})
    return result


def _placeholders(template):
    placeholders = []
    diagnostics = []
    consumed = set()
    for match in PLACEHOLDER.finditer(template):
        syntax = re.fullmatch(r"([0-9]*)(?::([^{}]*))?", match[1])
        span = list(match.span())
        placeholders.append(
            {
                "token_raw": match[0],
                "index_token_raw": syntax[1] if syntax else None,
                "format_raw": syntax[2] if syntax else None,
                "syntax_status": "recognized-lexical" if syntax else "unresolved-placeholder-syntax",
                "template_character_span": span,
            }
        )
        consumed.update(range(*match.span()))
        if syntax is None:
            diagnostics.append({"code": "unresolved_placeholder_syntax", "template_character_span": span})
    for index, character in enumerate(template):
        if character in "{}" and index not in consumed:
            diagnostics.append({"code": "unmatched_template_delimiter", "template_character_span": [index, index + 1]})
    return placeholders, diagnostics


def _branches(source, count, id_count):
    result = []
    for _ in range(count):
        source.skip_blank()
        if source.position == len(source.lines):
            source.fail("truncated branch group")
        start = source.position
        match = BRANCH.fullmatch(source.lines[start].rstrip("\r"))
        if match is None:
            source.fail("unsupported or malformed branch syntax")
        conditions = match["conditions"].split()
        if len(conditions) != id_count:
            source.fail("condition count differs from ordered stat ID count")
        template = match["template"]
        tokens = match["handlers"].split()
        placeholders, diagnostics = _placeholders(template)
        source.position += 1
        result.append(
            {
                "span": source.span(start, source.position),
                "condition_tokens_raw": conditions,
                "restrictions_raw": match["restrictions"].split(),
                "template_raw": template,
                "placeholders": placeholders,
                "template_syntax_diagnostics": diagnostics,
                "quantifier_tokens_raw": tokens,
                "quantifiers_lexical": _quantifiers(tokens),
            }
        )
    return result


def _description(source):
    start = source.position
    header = source.lines[start].rstrip("\r")
    source.position += 1
    source.skip_blank()
    if source.position == len(source.lines):
        source.fail("missing description ID header")
    header_match = re.fullmatch(r"([0-9]+)[ \t]+([^\r\n]+)", source.line())
    if header_match is None:
        source.fail("malformed description ID header")
    ids = header_match[2].split()
    if int(header_match[1]) != len(ids) or not ids:
        source.fail("ordered stat ID count mismatch")
    source.position += 1
    groups = []
    language = None
    language_span = None
    while True:
        group_start = source.position
        count = source.count()
        groups.append(
            {
                "declared_language": language,
                "language_origin": "implicit-default" if language is None else "explicit-lang",
                "language_declaration_span": language_span,
                "declared_branch_count": count,
                "branches": _branches(source, count, len(ids)),
                "span": source.span(group_start, source.position),
            }
        )
        after_group = source.position
        source.skip_blank()
        if source.position == len(source.lines):
            break
        match = LANGUAGE.fullmatch(source.line())
        if match is None:
            source.position = after_group
            break
        language = match[1]
        language_span = source.span(source.position, source.position + 1)
        source.position += 1
    span = source.span(start, source.position)
    return {
        "kind": "description",
        "header_raw": header,
        "ids": ids,
        "groups": groups,
        "span": span,
        "raw_slice_sha256": hashlib.sha256(source.raw[span["byte_start"] : span["byte_end"]]).hexdigest(),
    }


def parse_csd(path, raw):
    """Preserve ordered declarations and exact source spans; reject parse gaps."""
    resource_path(path)
    source = _Lines(path, raw)
    records = []
    while source.position < len(source.lines):
        start = source.position
        line = source.line()
        if not line:
            source.skip_blank()
            record = {"kind": "blank", "span": source.span(start, source.position)}
        elif line == "description" or line.startswith("description ") or line.startswith("description\t"):
            record = _description(source)
        else:
            source.position += 1
            record = {"span": source.span(start, source.position), "line_raw": source.lines[start].rstrip("\r")}
            include = INCLUDE.fullmatch(line)
            if include:
                # Preserve the literal separately; only slash spelling is normalized.
                record.update(
                    kind="include", literal_target=include[1], target=resource_path(include[1].replace("\\", "/"))
                )
            elif line.startswith("no_description ") or line.startswith("no_description\t"):
                record.update(kind="no_description", ids=line.split()[1:])
            elif line == "no_identifiers":
                record["kind"] = "no_identifiers"
            elif re.fullmatch(r'"[^"\r\n]*"', line):
                record["kind"] = "caption"
            else:
                source.position = start
                source.fail("unsupported top-level directive; no partial output")
        records.append(record)
    stat_index = {}
    for index, record in enumerate(records):
        if record["kind"] == "description":
            for identifier in record["ids"]:
                stat_index.setdefault(identifier, []).append(index)
    return {
        "path": path,
        "encoding": "BOM UTF-16LE",
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "records": records,
        "stat_index": stat_index,
    }


def validate_closure(files, roots, *, max_depth=16):
    """Check file reachability/cycles/longest depth without expanding occurrences."""
    heights = {}
    active = set()

    def height(path):
        if len(active) > max_depth:
            raise ValueError(f"Over-depth CSD includes: {path}")
        if path in active:
            raise ValueError(f"Cyclic CSD includes: {path}")
        if path in heights:
            return heights[path]
        if path not in files:
            raise ValueError(f"Missing explicit CSD include: {path}")
        active.add(path)
        result = 0
        for record in files[path]["records"]:
            if record["kind"] == "include":
                result = max(result, 1 + height(record["target"]))
        active.remove(path)
        heights[path] = result
        if result > max_depth:
            raise ValueError(f"Over-depth CSD includes: {path}")
        return result

    for root in roots:
        height(resource_path(root))
    return set(heights)


def iter_records(files, root, *, max_depth=16, max_occurrences=1_000_000):
    """Yield repeated lexical occurrences, failing explicitly at the work budget."""
    if type(max_occurrences) is not int or not 0 < max_occurrences <= 1_000_000:
        raise ValueError("CSD occurrence budget must be between one and one million")
    validate_closure(files, [root], max_depth=max_depth)
    count = 0

    def walk(path, chain):
        nonlocal count
        if len(chain) > max_depth or path in [item["path"] for item in chain]:
            raise ValueError(f"Cyclic or over-depth CSD includes: {path}")
        if path not in files:
            raise ValueError(f"Missing explicit CSD include: {path}")
        for index, record in enumerate(files[path]["records"]):
            count += 1
            if count > max_occurrences:
                raise ValueError("CSD occurrence work budget exceeded")
            reference = {"path": path, "record": index}
            yield {**reference, "include_chain": chain, "fact": record}
            if record["kind"] == "include":
                yield from walk(record["target"], [*chain, reference])

    yield from walk(resource_path(root), [])
