"""Optional pinned FK structure correspondence; strict v2 is unchanged."""

from collections import defaultdict
import hashlib
import json

from RePoE.native_locale_probe import TEXT_FIELDS


POLICY = "stable-key-pinned-fk-structure/v1"
INTERPRETATION = "community-reader-language-fallback/v1"
EDGES = {
    "BaseItemTypes": {
        "Implicit_Mods": "Mods",
        "ItemVisualIdentity": "ItemVisualIdentity",
        "FragmentBaseItemType": "BaseItemTypes",
    },
    "Mods": {"ModType": "ModType"},
    "Characters": {
        "StartSkillGem": "BaseItemTypes",
        "StartWeapons": "BaseItemTypes",
        "StartingWeapon": "BaseItemTypes",
        "Key3": "ItemVisualIdentity",
    },
    "AlternateQualityTypes": {"Item": "BaseItemTypes"},
    "ModType": {"Stat": "Stats"},
    "ItemVisualIdentity": {
        "UniqueStat1": "Stats",
        "UniqueStat2": "Stats",
        "UniqueStat3": "Stats",
        "UniqueStat4": "Stats",
    },
}
DEPENDENCIES = ("ItemVisualIdentity", "ModType", "Stats")
ROLES = ("source_default", "source_localized", "target")
ORDINALS = {
    "BaseItemTypes": {"Implicit_Mods": 8, "ItemVisualIdentity": 13, "FragmentBaseItemType": 21},
    "Mods": {"ModType": 2},
    "Characters": {"StartSkillGem": 17, "StartWeapons": 23, "StartingWeapon": 60, "Key3": 65},
    "AlternateQualityTypes": {"Item": 2},
    "ModType": {"Stat": 1},
    "ItemVisualIdentity": {"UniqueStat1": 65, "UniqueStat2": 66, "UniqueStat3": 67, "UniqueStat4": 68},
}


def encoded(value):
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def key_field(name):
    return "HASH32" if name == "Words" else "Name" if name == "ModType" else "Id"


class Correspondence:
    def __init__(self, sides, namespaces):
        if set(sides) != set(ROLES):
            raise ValueError("Explicit three-sided table namespace required")
        if set(namespaces) != set(ROLES) or any(set(namespaces[r]) != set(sides[r]) for r in ROLES):
            raise ValueError("Explicit per-role package namespace required")
        self.sides, self.groups, self.namespaces, self.closures = sides, {}, namespaces, {}
        for role, tables in sides.items():
            self.groups[role] = {}
            for name, table in tables.items():
                pin = namespaces[role][name]
                if (
                    pin.get("role") != role
                    or pin.get("table") != name
                    or not all(
                        isinstance(pin.get(k), str)
                        and len(pin[k]) == 64
                        and all(c in "0123456789abcdef" for c in pin[k])
                        for k in ["manifest_sha256", "payload_sha256"]
                    )
                ):
                    raise ValueError("Invalid FK package namespace")
                original = sides["source_default"].get(name)
                if (
                    original is None
                    or table["columns"] != original["columns"]
                    or table["physical_fields"] != original["physical_fields"]
                ):
                    raise ValueError("FK physical schema differs between roles")
                grouped = defaultdict(list)
                for i, row in enumerate(table["rows"]):
                    if row["_row"] != i:
                        raise ValueError("Noncontiguous FK table rows")
                    grouped[row["values"][key_field(name)]].append(row)
                self.groups[role][name] = grouped
                columns = {field: c["schema"] for c in table["columns"] for field in c["physical_fields"]}
                for field, target in EDGES.get(name, {}).items():
                    column = columns.get(field, {})
                    if (
                        (column.get("references") or {}).get("table") != target
                        or column.get("type") not in {"row", "foreignrow"}
                        or table["physical_fields"][ORDINALS[name][field]] != field
                    ):
                        raise ValueError(f"FK policy differs from pinned schema: {name}.{field}")

    def resolve(self, role, table, pointer):
        if pointer is None:
            return None, None
        document = self.sides[role].get(table)
        if document is None:
            return None, "fk-missing-table"
        if type(pointer) is not int or not 0 <= pointer < len(document["rows"]):
            return None, "fk-row-out-of-range"
        row = document["rows"][pointer]
        key = row["values"][key_field(table)]
        if key is None or key == "" or len(self.groups[role][table].get(key, [])) != 1:
            return None, "fk-invalid-or-duplicate-key"
        return row, None

    def edge(self, table, field, left, right, right_role):
        if right_role not in {"source_localized", "target"}:
            raise ValueError("Invalid comparison role")
        target = EDGES[table][field]
        array = next(
            c["schema"]["array"]
            for c in self.sides["source_default"][table]["columns"]
            if field in c["physical_fields"]
        )
        aa, bb = (left, right) if array else ([left], [right])
        witness = {
            "field": field,
            "target_table": target,
            "right_role": right_role,
            "left_rows": aa,
            "right_rows": bb,
            "left_keys": [],
            "right_keys": [],
            "reason_codes": [],
        }
        if not isinstance(aa, list) or not isinstance(bb, list) or len(aa) != len(bb):
            witness["reason_codes"] = ["fk-array-shape-mismatch"]
            witness.update(closure_nodes=0, closure_sha256=None)
            return witness
        queue, nodes, visited, reasons = [], [], set(), []

        def enqueue(name, x, y):
            if x is None or y is None:
                if x != y:
                    reasons.append("fk-null-mismatch")
                return None, None
            a, ae = self.resolve("source_default", name, x)
            b, be = self.resolve(right_role, name, y)
            if ae or be:
                reasons.extend(e for e in [ae, be] if e)
                return None, None
            ak, bk = a["values"][key_field(name)], b["values"][key_field(name)]
            if ak != bk:
                reasons.append("fk-key-mismatch")
            else:
                queue.append((name, x, y))
            return ak, bk

        for x, y in zip(aa, bb):
            ak, bk = enqueue(target, x, y)
            witness["left_keys"].append(ak)
            witness["right_keys"].append(bk)
        while queue:
            name, x, y = queue.pop()
            if (name, x, y) in visited:
                continue
            visited.add((name, x, y))
            if len(visited) > 100000:
                raise ValueError("FK closure exceeds bounded table scope")
            a = self.sides["source_default"][name]["rows"][x]["values"]
            b = self.sides[right_role][name]["rows"][y]["values"]
            fields = self.sides["source_default"][name]["physical_fields"]
            ignored = TEXT_FIELDS.get(name, []) if right_role == "source_localized" else []
            differences, edges = [], []
            for column in fields:
                if column in ignored:
                    continue
                if column not in EDGES.get(name, {}):
                    if a[column] != b[column]:
                        differences.append(column)
                    continue
                dest = EDGES[name][column]
                is_array = next(
                    c["schema"]["array"]
                    for c in self.sides["source_default"][name]["columns"]
                    if column in c["physical_fields"]
                )
                av, bv = (a[column], b[column]) if is_array else ([a[column]], [b[column]])
                detail = {
                    "field": column,
                    "target_table": dest,
                    "left_rows": av,
                    "right_rows": bv,
                    "left_keys": [],
                    "right_keys": [],
                }
                if not isinstance(av, list) or not isinstance(bv, list) or len(av) != len(bv):
                    reasons.append("fk-array-shape-mismatch")
                else:
                    for xx, yy in zip(av, bv):
                        ak, bk = enqueue(dest, xx, yy)
                        detail["left_keys"].append(ak)
                        detail["right_keys"].append(bk)
                edges.append(detail)
            if differences:
                reasons.append("fk-required-structure-mismatch")
            nodes.append(
                {
                    "table": name,
                    "key": a[key_field(name)],
                    "left_row": x,
                    "right_row": y,
                    "left_namespace": self.namespaces["source_default"][name],
                    "right_namespace": self.namespaces[right_role][name],
                    "differing_fields": differences,
                    "edges": edges,
                }
            )
        nodes.sort(key=lambda n: (n["table"], n["left_row"], n["right_row"]))
        closure = {"right_role": right_role, "nodes": nodes}
        closure_sha = hashlib.sha256(encoded(closure)).hexdigest()
        # Store only completed closures. A visited back-edge never commits success.
        self.closures[closure_sha] = closure
        witness.update(reason_codes=sorted(set(reasons)), closure_nodes=len(nodes), closure_sha256=closure_sha)
        return witness

    def compare(self, name, left, right, right_role):
        differing, witnesses = [], []
        for field in self.sides["source_default"][name]["physical_fields"]:
            if field in TEXT_FIELDS[name]:
                continue
            if field in EDGES.get(name, {}):
                witness = self.edge(name, field, left[field], right[field], right_role)
                witnesses.append(witness)
                if witness["reason_codes"]:
                    differing.append(field)
            elif left[field] != right[field]:
                differing.append(field)
        return differing, witnesses

    def bind(self, strict_binding):
        result = json.loads(encoded(strict_binding))
        result["policy_id"] = POLICY
        result["reference_policy"] = (
            "Only declared pinned FK edges use ordered stable-key full reachable structure; all other physical values remain strict."
        )
        result["interpretation"] = {
            "id": INTERPRETATION,
            "authority": "community-interpretation",
            "official_client_semantics_verified": False,
        }
        for name, table in result["tables"].items():
            for record in table["records"]:
                record["strict_v2"] = {
                    key: record[key] for key in ["decision", "reason_codes", "comparison", "differing_fields"]
                }
                record["fk_witnesses"] = {"source": [], "target": []}
                row_lists = [record["source_default_rows"], record["source_localized_rows"], record["target_rows"]]
                if not all(len(rows) == 1 for rows in row_lists):
                    continue
                a, b, c = [self.sides[role][name]["rows"][rows[0]]["values"] for role, rows in zip(ROLES, row_lists)]
                source_diff, sw = self.compare(name, a, b, "source_localized")
                target_diff, tw = self.compare(name, a, c, "target")
                english_diff = record["strict_v2"]["differing_fields"]["target_english"]
                record["fk_witnesses"] = {"source": sw, "target": tw}
                record["differing_fields"] = {
                    "source_nontext": source_diff,
                    "target_nontext": target_diff,
                    "target_english": english_diff,
                }
                record["comparison"] = {
                    "source_nontext_equal": not source_diff,
                    "target_nontext_equal": not target_diff,
                    "target_english_equal": not english_diff,
                }
                reasons = [label + "-mismatch" for label, fields in record["differing_fields"].items() if fields]
                reasons += sorted({reason for w in sw + tw for reason in w["reason_codes"]})
                if record["id"] is None or record["id"] == "":
                    reasons.append("invalid-stable-key")
                record["reason_codes"] = reasons
                record["decision"] = "rejected" if reasons else "accepted"
                if record["decision"] == "accepted" and record["strict_v2"]["decision"] == "rejected":
                    record["binding_kind"] = "fk-structure-bound"
        result["closures"] = dict(sorted(self.closures.items()))
        result["namespaces"] = self.namespaces
        return result
