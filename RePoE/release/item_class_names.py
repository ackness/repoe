"""Project native ItemClasses Id/Name into an optional English display member."""

from RePoE.release.pins import require

SCHEMA = "repoe-item-class-names/v1"
MEMBER = "overlay/item_class_names.json"
TABLE = "ItemClasses"
SCOPE = "ItemClasses.Name"


def project(table, target):
    """Keep exact strings by stable Id; empty names are counted and omitted."""
    require(isinstance(table, dict) and table.get("table") == TABLE, "Expected the ItemClasses table")
    require(isinstance(table.get("rows"), list), "ItemClasses: rows must be an array")
    values, ids = [], set()
    for row in table["rows"]:
        value = row.get("values") if isinstance(row, dict) else None
        require(isinstance(value, dict), "ItemClasses: row needs values")
        key = value.get("Id")
        require(isinstance(key, str) and key.strip(), "ItemClasses: Id must be a nonblank string")
        require(key not in ids, f"ItemClasses: duplicate Id {key!r}")
        ids.add(key)
        values.append(value)

    names = {}
    summary = {"rows": len(values), "emitted": 0, "empty": 0, "whitespace": 0}
    for value in values:
        name = value.get("Name")
        require(isinstance(name, str), "ItemClasses: Name must be a string")
        if name == "":
            summary["empty"] += 1
        elif not name.strip():
            summary["whitespace"] += 1
        else:
            names[value["Id"]] = name
    summary["emitted"] = len(names)
    return {
        "_meta": {"schema": SCHEMA, **target},
        "scopes": {SCOPE: dict(sorted(names.items()))},
    }, summary
