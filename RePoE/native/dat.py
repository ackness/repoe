"""Bounded validation of native DAT64 variable data before upstream decoding."""

import struct


_WIDTHS = {
    "bool": 1,
    "byte": 1,
    "ubyte": 1,
    "short": 2,
    "ushort": 2,
    "int": 4,
    "uint": 4,
    "long": 8,
    "ulong": 8,
    "float": 4,
    "double": 8,
    "ref|generic": 8,
    "ref|self": 8,
    "ref|out": 16,
    "ref|string": 8,
}


def _width(kind):
    if kind.startswith("ref|list|"):
        _width(kind[9:])
        return 16
    if kind not in _WIDTHS:
        raise ValueError(f"Unsupported native DAT type: {kind}")
    return _WIDTHS[kind]


def validate_dat(name, raw, fields):
    """Follow dereferenced pointers only; row references/nulls remain scalar facts.

    Empty lists do not dereference their offset (including sentinel offsets).
    Strings have no pointer-null sentinel in the pinned decoder. Their UTF-16
    termination is aligned relative to the string start, not the file start.
    """
    layout = [(field, spec.type, _width(spec.type)) for field, spec in fields.items()]
    row_width = sum(width for _, _, width in layout)
    if len(raw) < 12:
        raise ValueError(f"{name}: truncated DAT framing")
    count = struct.unpack_from("<I", raw)[0]
    if count and not row_width:
        raise ValueError(f"{name}: nonempty DAT with zero physical row width")
    boundary = 4 + count * row_width
    magic = b"\xbb" * 8
    if raw[boundary : boundary + 8] != magic:
        raise ValueError(f"{name}: exact physical row width/framing mismatch")
    # PyPoE searches for the first row-count-aligned magic. Do not let an
    # earlier marker change its data_offset after we validate the intended one.
    marker = raw.find(magic, 4)
    while marker < boundary:
        if not count or (marker - 4) % count == 0:
            raise ValueError(f"{name}: ambiguous DAT width/framing marker")
        marker = raw.find(magic, marker + 1)

    checked_strings = set()

    def span(start, length, context):
        if start < boundary + 8 or length > len(raw) - start:
            raise ValueError(f"{name}.{context}: variable data span out of bounds")

    def check(kind, at, context):
        if kind == "ref|string":
            start = boundary + struct.unpack_from("<Q", raw, at)[0]
            span(start, 4, context)
            if start in checked_strings:
                return
            end = raw.find(b"\0" * 4, start)
            while end != -1 and (end - start) % 2:
                end = raw.find(b"\0" * 4, end + 1)
            if end == -1:
                raise ValueError(f"{name}.{context}: unterminated UTF-16 string")
            try:
                raw[start:end].decode("utf-16")
            except UnicodeError as error:
                raise ValueError(f"{name}.{context}: invalid UTF-16 string") from error
            checked_strings.add(start)
        elif kind.startswith("ref|list|"):
            length, pointer = struct.unpack_from("<QQ", raw, at)
            if not length:
                return
            item = kind[9:]
            width = _width(item)
            start = boundary + pointer
            span(start, length * width, context)
            if item == "ref|string" or item.startswith("ref|list|"):
                for slot in range(length):
                    check(item, start + slot * width, f"{context}[{slot}]")

    for row in range(count):
        at = 4 + row * row_width
        for field, kind, width in layout:
            check(kind, at, f"row {row}.{field}")
            at += width
    return row_width
