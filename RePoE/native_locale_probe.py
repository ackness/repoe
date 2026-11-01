"""Two-table, standard-library-only memory probe; never a production source export.

Execute this source in an existing process, then call decode_table on already
extracted bytes. No file, network, installation or patch/realm discovery occurs.
"""

import hashlib
import json
import struct


SCHEMA_REVISION = "6034b071846ef61b39046ebdb59e6d5717179509"
SCHEMA_SHA256 = "50e098543345cf8323aeb294e2cfef1b6b44842faccf560ada935cebe22727df"
COLUMN_PINS = {
    "Words": "f2fc1a18d3cff4b6010be454fb66dc473b90a3ddf30e9d3cd069bfb91fee2660",
    "Ascendancy": "ac06ba05b8e7fc3006c91310fc0a697d824fa8a74d209070e7760c9dbf09360a",
}
LAYOUTS = {
    "Words": [
        ("Wordlist", "int"),
        ("Text", "ref|string"),
        ("SpawnWeight_Tags", "ref|list|ref|out"),
        ("SpawnWeight_Values", "ref|list|int"),
        ("HASH32", "uint"),
        ("Text2", "ref|string"),
        ("Inflection", "ref|string"),
    ],
    "Ascendancy": [
        ("Id", "ref|string"),
        ("ClassNo", "int"),
        ("Character", "ref|out"),
        ("CoordinateRect", "ref|string"),
        ("RGBFlavourTextColour", "ref|string"),
        ("Name", "ref|string"),
        ("FlavourText", "ref|string"),
        ("OGGFile", "ref|string"),
        ("PassiveTreeImage", "ref|string"),
        ("TreeRegionVector", "int"),
        ("TreeRegionAngle", "int"),
        ("BackgroundImage", "int"),
        ("Unknown0", "int"),
        ("Disabled", "bool"),
        ("BaseAscendancy", "ref|generic"),
        ("UIArt", "ref|out"),
        ("SelectSound", "ref|out"),
        ("ConfirmDownSound", "ref|out"),
        ("ConfirmUpSound", "ref|out"),
    ],
}
WIDTHS = {"int": 4, "uint": 4, "bool": 1, "ref|string": 8, "ref|out": 16, "ref|generic": 8}
NULLS = {-0x1010102, 0xFEFEFEFE, -0x101010101010102, 0xFEFEFEFEFEFEFEFE, 0xFFFFFFFF}


def encoded(value):
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def width(kind):
    return 16 if kind.startswith("ref|list|") else WIDTHS[kind]


def decode_table(name, raw, *, expected_bytes, expected_sha256):
    """Verify externally supplied raw observation before parsing all physical rows.

    Pins may be acquisition observations. They do not authenticate source/build.
    Scalar null handling matches the fixed native reader, including numeric null
    sentinels. Foreign-reference second words remain separate wire observations.
    """
    if name not in LAYOUTS or type(raw) is not bytes or not 12 <= len(raw) <= 32 * 1024 * 1024:
        raise ValueError("Expected bounded Words/Ascendancy DAT64 byte buffer")
    digest = hashlib.sha256(raw).hexdigest()
    if type(expected_bytes) is not int or len(raw) != expected_bytes or digest != expected_sha256:
        raise ValueError("Raw buffer differs from external byte pin")
    layout = LAYOUTS[name]
    row_bytes = sum(width(kind) for _, kind in layout)
    count = struct.unpack_from("<I", raw)[0]
    boundary = 4 + count * row_bytes
    if count > 100000 or raw[boundary : boundary + 8] != b"\xbb" * 8:
        raise ValueError("Exact schema row width/framing mismatch")
    marker = raw.find(b"\xbb" * 8, 4)
    while marker < boundary:
        if not count or (marker - 4) % count == 0:
            raise ValueError("Ambiguous physical framing")
        marker = raw.find(b"\xbb" * 8, marker + 1)
    strings, foreign_tails, rows = {}, [], []

    def variable(start, length):
        if start < boundary + 8 or start > len(raw) or length < 0 or length > len(raw) - start:
            raise ValueError("Variable-data pointer/span outside raw buffer")

    def value(kind, at, context):
        if kind.startswith("ref|list|"):
            length, pointer = struct.unpack_from("<QQ", raw, at)
            if not length:
                return []
            if length > 100000:
                raise ValueError("Array count exceeds probe bound")
            element = kind[9:]
            start = boundary + pointer
            variable(start, length * width(element))
            return [value(element, start + i * width(element), context + [i]) for i in range(length)]
        if kind == "ref|string":
            start = boundary + struct.unpack_from("<Q", raw, at)[0]
            variable(start, 4)
            if start not in strings:
                end = raw.find(b"\0" * 4, start)
                while end != -1 and (end - start) % 2:
                    end = raw.find(b"\0" * 4, end + 1)
                if end == -1:
                    raise ValueError("Unterminated UTF-16 string")
                strings[start] = raw[start:end].decode("utf-16-le")
            return strings[start]
        if kind == "bool":
            number = raw[at]
            if number not in {0, 1}:
                raise ValueError("Noncanonical boolean")
            return bool(number)
        number = struct.unpack_from("<" + {"int": "i", "uint": "I"}.get(kind, "Q"), raw, at)[0]
        if kind == "ref|out":
            tail = struct.unpack_from("<Q", raw, at + 8)[0]
            if tail:
                foreign_tails.append({"context": context, "raw_second_word": tail})
        return None if number in NULLS else number

    for ordinal in range(count):
        at, fields = 4 + ordinal * row_bytes, {}
        for field, kind in layout:
            fields[field] = value(kind, at, [ordinal, field])
            at += width(kind)
        rows.append({"_row": ordinal, "values": fields})
    return {
        "table": name,
        "physical_fields": [field for field, _ in layout],
        "wire_layout": layout,
        "rows": rows,
        "validation": {"rows": count, "schema_row_bytes": row_bytes, "actual_row_bytes": row_bytes},
        "raw_identity": {"bytes": len(raw), "sha256": digest},
        "schema": {"revision": SCHEMA_REVISION, "sha256": SCHEMA_SHA256, "columns_sha256": COLUMN_PINS[name]},
        "foreign_tail_observations": foreign_tails,
        "status": "memory-decode-probe-only",
        "patch_certified": False,
        "realm_certified": False,
    }


def compare_pair(default, localized):
    """Report structural correspondence without claiming same patch or realm."""
    name = default["table"]
    if localized["table"] != name:
        raise ValueError("Cannot compare different tables")
    key = "HASH32" if name == "Words" else "Id"
    ignored = {"Text", "Text2", "Inflection"} if name == "Words" else {"Name", "FlavourText"}
    maps, duplicates = [], []
    for table in [default, localized]:
        mapping, repeated = {}, []
        for row in table["rows"]:
            identity = row["values"][key]
            if identity is None or identity in mapping:
                repeated.append({"row": row["_row"], "key": identity})
            mapping[identity] = row
        maps.append(mapping)
        duplicates.append(repeated)
    left, right = maps
    differences = []

    def order(identity):
        return type(identity).__name__, str(identity)

    for identity in sorted(left.keys() & right.keys(), key=order):
        for field in default["physical_fields"]:
            if field not in ignored and left[identity]["values"][field] != right[identity]["values"][field]:
                differences.append(
                    {
                        "key": identity,
                        "field": field,
                        "default": left[identity]["values"][field],
                        "localized": right[identity]["values"][field],
                    }
                )
    return {
        "key": key,
        "duplicate_or_null_keys": duplicates,
        "default_only": sorted(left.keys() - right.keys(), key=order),
        "localized_only": sorted(right.keys() - left.keys(), key=order),
        "nontext_differences": differences,
        "default_rows": len(default["rows"]),
        "localized_rows": len(localized["rows"]),
        "patch_certified": False,
        "realm_certified": False,
    }
