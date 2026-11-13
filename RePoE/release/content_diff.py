"""Informational package comparison; never changes runtime bytes or publication gates.

Rules apply to exact member families and paired, compatible JSON leaves.
Unknown fields, ordered occurrences and policy/compatibility evidence remain
content. See docs/release/content-diff.md for the interpretation and limits.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
import re

from RePoE.release.pins import decode, encoded

FORMAT = "repoe-release-content-diff/v1"
RECEIPT_LIMIT = 4 * 1024 * 1024
SAMPLES = 5
TEXT_LIMIT = 160
HEX = re.compile(r"[0-9a-f]{64}")
# Published row coordinates are u32; bound parsing before converting text.
POINTER = re.compile(r"/rows/([0-9]{1,10})/values/(.+)")
STATUSES = ("identity-only", "content-changed", "unresolved")

# Exact metadata leaves shared by the named source-identity wrappers. In
# particular, evidence kinds/status/unknown fields and resource keys survive.
SOURCE_IDENTITY = {
    ("game_patch",): "text",
    ("source",): "text",
    ("source_lock_sha256",): "digest",
    ("selected_source_sha256",): "digest",
    ("acquisition", "evidence", "[]", "sha256"): "digest",
    ("raw_resources", "*", "bytes"): "bytes",
    ("raw_resources", "*", "sha256"): "digest",
}
INPUTS = {
    ("inputs", "*"): "digest",
    ("inputs", "*", "bytes"): "bytes",
    ("inputs", "*", "sha256"): "digest",
}


def metadata(*names, source=None, inputs=False):
    rules = {(name,): "text" if name in ("game_patch", "poe_version") else "digest" for name in names}
    if source:
        prefix = tuple(source.split("."))
        rules.update({prefix + path: kind for path, kind in SOURCE_IDENTITY.items()})
    if inputs:
        rules.update(INPUTS)
    return {("_meta",) + path: kind for path, kind in rules.items()}


# Policy, codec, compatibility and legacy-source pins are deliberately absent.
IDENTITY_RULES = {
    "base/monster_resistances.json": metadata(
        "facts_manifest_sha256", "poe_version", source="source_identity", inputs=True
    ),
    "base/monster_scaling.json": metadata(
        "facts_manifest_sha256", "poe_version", source="source_identity", inputs=True
    ),
    "overlay/totem_varieties.json": metadata(
        "facts_manifest_sha256", "poe_version", source="source_identity", inputs=True
    ),
    "overlay/boss_poise_thresholds.json": metadata("facts_manifest_sha256"),
    "overlay/gem_descriptions.json": metadata("facts_manifest_sha256", "game_patch"),
    "overlay/gem_effects.json": metadata("facts_manifest_sha256", "game_patch", source="source_identity"),
    "overlay/gem_quality_stats.json": metadata(
        "source_manifest_sha256", "poe_version", source="target_source", inputs=True
    ),
    "overlay/granted_effect_minions.json": metadata(source="target_fields.source_identity"),
    "overlay/minions.json": metadata(source="target_fields.source_identity"),
    "overlay/spectres.json": metadata(source="target_fields.source_identity"),
    "overlay/skill_overrides.json": metadata(source="target_numeric.source_identity"),
    "overlay/runes.json": metadata("facts_manifest_sha256", source="source_identity"),
    "overlay/stat_descriptions.json": metadata(
        "facts_manifest_sha256",
        "lookup_manifest_sha256",
        "descriptions_manifest_sha256",
        "descriptions_sha256",
        source="source_identity",
    ),
    "overlay/trade_crafting_sources.json": {
        **metadata("source_manifest_sha256", "input_manifest_sha256"),
        ("_meta", "declared_target", "game_patch"): "text",
    },
    "base/passive_tree.json": {
        ("[]", "native_stats", "data_version"): "text",
        ("[]", "native_stats", "stats", "[]", "provenance", "game_patch"): "text",
        ("[]", "native_stats", "stats", "[]", "provenance", "source_manifest_sha256"): "digest",
        ("[]", "native_stats", "stats", "[]", "provenance", "references", "[]", "sha256"): "digest",
    },
    "manifest.json": {("poe_version",): "text", ("files", "*"): "digest"},
}
for _member in ("overlay/granted_effect_minions.json", "overlay/minions.json", "overlay/spectres.json"):
    IDENTITY_RULES[_member][("_meta", "target_fields", "facts_manifest_sha256")] = "digest"
IDENTITY_RULES["overlay/skill_overrides.json"][("_meta", "target_numeric", "facts_manifest_sha256")] = "digest"

# Only these non-id keys have a package/producer-defined entity interpretation.
ENTITY_KEYS = {
    ("base/granted_effect_stat_sets.json", ()): "effect_id",
    ("base/granted_effect_stat_sets.json", ("*", "sets")): "set_id",
    ("base/granted_effect_stat_sets.json", ("*", "sets", "*", "levels")): "gem_level",
    ("base/granted_effect_levels.json", ("*",)): "level",
    ("overlay/gem_effects.json", ("gems",)): "gem_id",
    ("overlay/gem_quality_stats.json", ("effects",)): "effect_id",
    ("overlay/granted_effect_minions.json", ("entries",)): "effect_id",
}
DICT_ENTITIES = {
    "base/granted_effect_levels.json": ((),),
    "base/character_constants.json": ((),),
    "base/game_constants.json": (("character",), ("game",), ("monster",)),
    "base/monster_resistances.json": (("monsters",),),
    "base/non_damaging_ailments.json": (("ailments",), ("buildup_types",), ("default_ailment_damage_types",)),
    "base/jewel_radii.json": (("tree_versions",),),
    "overlay/gem_descriptions.json": (("scopes", "*"),),
    "overlay/stat_descriptions.json": (("scopes",),),
    "overlay/skill_stat_map.json": (("global",), ("per_stat_set",)),
}
REFERENCE_MEMBERS = {
    "base/granted_effects.json",
    "base/mods.json",
    "base/stats.json",
    "base/active_skill_types.json",
    "base/passive_tree.json",
}
COUNT_FIELDS = (
    "identity_fields",
    "payload_fields",
    "metadata_fields",
    "added_entities",
    "removed_entities",
    "changed_entities",
    "unresolved_entities",
    "row_reference_shifts",
    "retargeted_references",
    "unresolved_references",
    "unresolved_raw_changes",
    "alignment_issues",
    "order_changes",
    "interpretation_failures",
)


def matches(pattern, path):
    return len(pattern) == len(path) and all(a in ("*", "[]") or a == b for a, b in zip(pattern, path))


def compatible(kind, before, after):
    if type(before) is not type(after):
        return False
    if kind == "digest":
        return isinstance(before, str) and HEX.fullmatch(before) and HEX.fullmatch(after)
    if kind == "bytes":
        return type(before) is int and before >= 0 and after >= 0
    return isinstance(before, str) and bool(before) and bool(after)


def short(value):
    # JSON permits escaped lone surrogates; keep them visible without making
    # this optional display fail the receipt's existing UTF-8 encoder.
    text = str(value).encode("utf-8", "backslashreplace").decode("utf-8")
    return text if len(text) <= TEXT_LIMIT else text[:TEXT_LIMIT] + f"…[{len(text) - TEXT_LIMIT} chars omitted]"


def preview(value, depth=2):
    """A bounded display, with the full JSON type/size visible for large values."""
    if isinstance(value, (list, dict)):
        result = {"type": type(value).__name__, "items": len(value)}
        if depth:
            result["sample"] = (
                [{"key": short(key), "value": preview(value[key], depth - 1)} for key in sorted(value)[:3]]
                if isinstance(value, dict)
                else [preview(child, depth - 1) for child in value[:3]]
            )
            result["omitted_items"] = max(0, len(value) - 3)
        return result
    return short(value) if isinstance(value, str) else value


def index_rows(rows, key):
    if not isinstance(rows, list):
        return None
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            return None
        value = row.get(key)
        if not ((type(value) is int) or (isinstance(value, str) and value.strip())):
            return None
        identity = (type(value).__name__, value)
        if identity in result:
            return None
        result[identity] = row
    return result


class PackageView:
    """Already authenticated bytes; strict JSON decoding remains owned by pins."""

    def __init__(self, members):
        self.members, self.documents, self.errors, self.lookups = members, {}, {}, {}

    def document(self, name):
        if name not in self.documents:
            try:
                self.documents[name] = decode(self.members[name])
            except (ValueError, UnicodeError, RecursionError) as error:
                self.errors[name] = str(error)
                self.documents[name] = None
        return self.documents[name]

    def lookup(self, kind):
        if kind in self.lookups:
            return self.lookups[kind]
        pairs = []
        dependency = {
            "stat_set": "base/granted_effect_stat_sets.json",
            "cost": "base/cost_types.json",
            "mod_type": "base/mods.json",
            "active_type": "base/active_skill_types.json",
            "passive": "base/passive_tree.json",
            "stat": "base/passive_tree.json",
        }[kind]
        document = self.document(dependency) if dependency in self.members else None
        if kind == "stat_set":
            effects = (
                self.document("base/granted_effects.json") if "base/granted_effects.json" in self.members else None
            )
            definitions = index_rows(document, "effect_id")
            effects = index_rows(effects, "id")
            if definitions is not None and effects is not None:
                for identity, effect in effects.items():
                    definition = definitions.get(identity, {})
                    sets = definition.get("sets")
                    if isinstance(sets, list) and sets and index_rows(sets, "set_id") is not None:
                        pairs.append((effect.get("stat_set"), sets[0].get("set_id")))
        elif kind == "cost":
            if index_rows(document, "id") is not None:
                pairs = [(row, value["id"]) for row, value in enumerate(document)]
        elif kind in ("mod_type", "active_type"):
            if index_rows(document, "id") is not None:
                coordinate, stable = ("mod_type", "group") if kind == "mod_type" else ("index", "id")
                pairs = [(row.get(coordinate), row.get(stable)) for row in document]
        elif index_rows(document, "id") is not None:
            for node in document:
                packet = node.get("native_stats")
                if not isinstance(packet, dict) or not isinstance(packet.get("stats"), list):
                    continue
                for stat in packet["stats"]:
                    if not isinstance(stat, dict) or not isinstance(stat.get("provenance"), dict):
                        continue
                    provenance = stat["provenance"]
                    pairs.append(
                        (provenance.get("passive_row"), provenance.get("passive_id"))
                        if kind == "passive"
                        else (provenance.get("stat_row"), stat.get("id"))
                    )
        forward, reverse = defaultdict(set), defaultdict(set)
        for row, identity in pairs:
            if type(row) is int and row >= 0 and isinstance(identity, str) and identity.strip():
                forward[row].add(identity)
                reverse[identity].add(row)
        result = {
            row: next(iter(ids)) for row, ids in forward.items() if len(ids) == 1 and len(reverse[next(iter(ids))]) == 1
        }
        self.lookups[kind] = (result, dependency)
        return self.lookups[kind]


@dataclass
class MemberDiff:
    family: str
    before: PackageView
    after: PackageView
    counts: Counter = field(default_factory=Counter)
    samples: dict = field(default_factory=dict)
    changed: set = field(default_factory=set)
    unresolved: set = field(default_factory=set)
    entities: set = field(default_factory=set)
    entity_counts_available: bool = True

    def event(self, kind, path, entity, before=None, after=None, reason=None):
        self.counts[kind] += 1
        if entity is not None:
            self.entities.add(entity)
            if kind in ("payload_fields", "metadata_fields", "retargeted_references", "order_changes"):
                self.changed.add(entity)
            elif kind == "unresolved_references":
                self.unresolved.add(entity)
        examples = self.samples.setdefault(kind, [])
        if len(examples) < SAMPLES:
            example = {"path": short("/" + "/".join(map(str, path))), "entity": short(entity or "/")}
            if reason is not None:
                example["reason"] = short(reason)
            example.update(before=preview(before), after=preview(after))
            examples.append(example)

    def content(self, path, entity, before, after, reason=None):
        kind = "metadata_fields" if path[:1] == ("_meta",) else "payload_fields"
        if kind == "payload_fields" and entity is None:
            self.entity_counts_available = False
        self.event(kind, path, entity, before, after, reason)

    def reference(self, path, before, after, parents, entity):
        kind = None
        if self.family == "base/granted_effects.json":
            kind = {("*", "stat_set"): "stat_set", ("*", "cost_types", "*"): "cost"}.get(path)
        elif self.family == "base/mods.json" and path == ("*", "mod_type"):
            kind = "mod_type"
        elif self.family == "base/active_skill_types.json" and path == ("*", "index"):
            kind = "active_type"
        elif self.family == "base/stats.json" and path in (("*", "semantic"), ("*", "category")):
            if before != after:
                self.event("unresolved_references", path, entity, before, after, "target table absent from package")
                self.counts["unresolved_raw_changes"] += 1
            return True
        elif self.family == "base/passive_tree.json":
            provenance = ("*", "native_stats", "stats", "*", "provenance")
            if path == provenance + ("passive_row",):
                kind = "passive"
            elif path == provenance + ("stat_row",):
                kind = "stat"
            elif path == provenance + ("references", "*", "pointer"):
                first = POINTER.fullmatch(before) if isinstance(before, str) else None
                second = POINTER.fullmatch(after) if isinstance(after, str) else None
                resources = tuple(parent.get("resource") for parent in parents)
                kinds = {"tables/PassiveSkills.json": "passive", "tables/Stats.json": "stat"}
                if first and second and resources[0] == resources[1] and resources[0] in kinds:
                    if first[2] != second[2]:
                        self.content(path, entity, before, after, "reference field changed")
                        return True
                    return self.resolved_reference(kinds[resources[0]], int(first[1]), int(second[1]), path, entity)
                if before != after:
                    self.event("unresolved_references", path, entity, before, after, "unknown pointer/resource")
                    self.counts["unresolved_raw_changes"] += 1
                return True
        if kind is None:
            return False
        if before is None and after is None:
            return True
        return self.resolved_reference(kind, before, after, path, entity)

    def resolved_reference(self, kind, before, after, path, entity):
        old, dependency = self.before.lookup(kind)
        new, _ = self.after.lookup(kind)
        old_id = old.get(before) if type(before) is int else None
        new_id = new.get(after) if type(after) is int else None
        if old_id is None or new_id is None:
            if before != after or self.before.members.get(dependency) != self.after.members.get(dependency):
                self.event(
                    "unresolved_references", path, entity, before, after, "missing/ambiguous package target identity"
                )
                self.counts["unresolved_raw_changes"] += before != after
        elif old_id != new_id:
            self.event("retargeted_references", path, entity, old_id, new_id, "resolved target changed")
        elif before != after:
            self.event("row_reference_shifts", path, entity, before, after, f"same stable target: {old_id}")
        return True

    def walk(self, before, after, path=(), entity=None, parents=({}, {}), containers=()):
        if type(before) is not type(after):
            self.content(path, entity, before, after, "JSON type changed")
            return
        if isinstance(before, dict):
            for key in sorted(before.keys() | after.keys()):
                child = path + (key,)
                keyed = any(matches(pattern, path) for pattern in DICT_ENTITIES.get(self.family, ()))
                owner = "/".join(str(part).replace("~", "~0").replace("/", "~1") for part in child) if keyed else entity
                if key not in before or key not in after:
                    if owner != entity:
                        self.event(
                            "added_entities" if key in after else "removed_entities",
                            child,
                            owner,
                            before.get(key),
                            after.get(key),
                        )
                    else:
                        self.content(child, owner, before.get(key), after.get(key), "field added/removed")
                else:
                    self.walk(before[key], after[key], child, owner, (before, after), containers + (dict,))
            return
        if isinstance(before, list):
            key = next(
                (
                    value
                    for (family, pattern), value in ENTITY_KEYS.items()
                    if family == self.family and matches(pattern, path)
                ),
                None,
            )
            if key is None:
                for candidate in ("id", "Id"):
                    if any(isinstance(row, dict) and candidate in row for row in before + after):
                        key = candidate
                        break
            old, new = (index_rows(rows, key) for rows in (before, after)) if key else (None, None)
            if key and old is not None and new is not None:
                common = old.keys() & new.keys()
                if [k for k in old if k in common] != [k for k in new if k in common]:
                    self.event("order_changes", path, entity, list(old), list(new), "surviving entity order changed")
                if self.family == "base/granted_effect_stat_sets.json" and path == ("*", "sets"):
                    if before and after and before[0][key] != after[0][key]:
                        self.content(path, entity, before[0][key], after[0][key], "main stat-set selection changed")
                for identity in sorted(old.keys() | new.keys(), key=lambda item: (item[0], str(item[1]))):
                    owner = entity or f"{identity[0]}:{identity[1]}"
                    if identity not in old or identity not in new:
                        self.event(
                            "added_entities" if identity in new else "removed_entities",
                            path,
                            owner,
                            old.get(identity),
                            new.get(identity),
                        )
                    else:
                        self.walk(old[identity], new[identity], path + ("*",), owner, containers=containers + (list,))
                return
            if key:
                self.entity_counts_available = False
                self.event(
                    "alignment_issues", path, entity, len(before), len(after), f"missing/invalid/duplicate {key}"
                )
            elif before != after:
                self.entity_counts_available = False
            # No guessed identity: retain complete order and duplicates. Length
            # changes are one collection delta, not a cascade of shifted rows.
            if len(before) != len(after):
                self.entity_counts_available = False
                self.content(path, entity, before, after, "unkeyed ordered collection length changed")
                return
            for left, right in zip(before, after):
                self.walk(left, right, path + ("*",), entity, containers=containers + (list,))
            return
        if self.reference(path, before, after, parents, entity):
            return
        if before == after:
            return
        for pattern, kind in IDENTITY_RULES.get(self.family, {}).items():
            # [] is an array step; * is an object member. Every ancestor has
            # already passed the paired type check above, so malformed shapes
            # cannot borrow a leaf exclusion from a valid producer shape.
            shape = tuple(list if step == "[]" else dict for step in pattern)
            if matches(pattern, path) and shape == containers and compatible(kind, before, after):
                self.event("identity_fields", path, entity, before, after)
                return
        self.content(path, entity, before, after)

    def result(self):
        self.counts["changed_entities"] = len(self.changed)
        self.counts["unresolved_entities"] = len(self.unresolved)
        payload = any(
            self.counts[k]
            for k in (
                "payload_fields",
                "added_entities",
                "removed_entities",
                "retargeted_references",
                "order_changes",
            )
        )
        content = payload or self.counts["metadata_fields"]
        uncertain = self.counts["unresolved_references"] or self.counts["interpretation_failures"]
        status = "content-changed" if content else "unresolved" if uncertain else "identity-only"
        if status == "content-changed":
            reason = (
                "payload, entities, ordering or stable targets changed; metadata/unresolved counts are separate"
                if payload
                else "preserved metadata changed; no payload change proved"
            )
        elif status == "unresolved":
            reason = "JSON interpretation or changed package reference/dependency is unresolved"
        else:
            reason = "only typed identity, formatting or proven same-target row changes"
        result = {
            "status": status,
            "reason": reason,
            "counts": {key: self.counts[key] for key in COUNT_FIELDS},
            "entity_counts_available": self.entity_counts_available,
            "samples": self.samples,
            "omitted_samples": {key: self.counts[key] - len(value) for key, value in self.samples.items()},
            "entity_details": {
                "total": len(self.entities),
                "sample": [short(value) for value in sorted(self.entities)[:SAMPLES]],
                "omitted": max(0, len(self.entities) - SAMPLES),
            },
        }
        if self.family == "manifest.json":
            result["reason"] = (
                "compares dependency stamps only; consult referenced member results and raw classes"
                if status == "identity-only"
                else f"snapshot {reason}; patch/dependency stamps are excluded"
            )
        return result


def compare(current, reference, classes, prefix, reference_paths):
    """Compare authenticated bytes in a mapped view; raw class entries are read-only."""
    before = PackageView({name.removeprefix(prefix): raw for name, raw in reference.items()})
    after = PackageView({name.removeprefix(prefix): raw for name, raw in current.items()})
    members, statuses, totals = {}, Counter(), Counter()
    inspected = 0
    for name, raw in sorted(current.items()):
        raw_class = classes[name]["class"]
        family = name.removeprefix(prefix)
        if raw_class == "frozen" and family not in REFERENCE_MEMBERS:
            continue
        inspected += 1
        diff = MemberDiff(family, before, after)
        right = after.document(family)
        if name not in reference:
            diff.content((), None, None, right, "new member")
        else:
            left = before.document(family)
            errors = [view.errors[family] for view in (before, after) if family in view.errors]
            if errors:
                diff.event("interpretation_failures", (), None, reason="; ".join(errors))
                diff.entity_counts_available = False
            elif raw != reference[name] or family in REFERENCE_MEMBERS:
                diff.walk(left, right)
            if raw == reference[name] and not any(diff.counts.values()):
                continue
        if name not in reference and family in after.errors:
            diff.event("interpretation_failures", (), None, reason=after.errors[family])
        result = diff.result()
        result.update(
            member=short(name),
            reference_member=short(reference_paths.get(name, "")),
            raw_class=raw_class,
        )
        members[name] = result
        statuses[result["status"]] += 1
        totals.update(result["counts"])
    return {
        "format": FORMAT,
        "summary": {
            "inspected_members": inspected,
            "reported_members": len(members),
            "statuses": {status: statuses[status] for status in STATUSES},
            "counts": {key: totals[key] for key in COUNT_FIELDS},
            "entity_details": sum(member["entity_details"]["total"] for member in members.values()),
        },
        "members": list(members.values()),
        "omitted_members": 0,
        "omitted_field_samples": sum(sum(member["omitted_samples"].values()) for member in members.values()),
        "omitted_entity_details": sum(member["entity_details"]["omitted"] for member in members.values()),
        "detail": "bounded samples",
    }


def summary(report):
    counts, statuses = report["summary"]["counts"], report["summary"]["statuses"]
    return (
        f"content diff: members={report['summary']['reported_members']}/{report['summary']['inspected_members']}, "
        f"entity_details={report['summary']['entity_details']}; "
        + ", ".join(f"{status}={statuses[status]}" for status in STATUSES)
        + "; "
        + ", ".join(f"{key}={value}" for key, value in counts.items())
    )


def attach(receipt, report, limit=RECEIPT_LIMIT):
    """Fit only optional evidence, using the actual final canonical UTF-8 receipt."""
    base = len(encoded(receipt))
    omitted = report["summary"]["reported_members"]
    without_values, without_samples = [], []
    for member in report["members"]:
        without_values.append(
            {
                **member,
                "samples": {
                    kind: [
                        {key: value for key, value in sample.items() if key not in ("before", "after")}
                        for sample in values
                    ]
                    for kind, values in member["samples"].items()
                },
            }
        )
        without_samples.append(
            {
                **{key: value for key, value in member.items() if key != "samples"},
                "omitted_samples": {kind: member["counts"][kind] for kind in member["samples"]},
                "entity_details": {
                    **member["entity_details"],
                    "sample": [],
                    "omitted": member["entity_details"]["total"],
                },
            }
        )
    sample_total = sum(sum(member["counts"][kind] for kind in member["samples"]) for member in report["members"])
    compact = {
        **report,
        "omitted_field_samples": sample_total,
        "omitted_entity_details": report["summary"]["entity_details"],
    }
    candidates = [
        report,
        {**report, "members": without_values, "detail": "sample values omitted for size"},
        {**compact, "members": without_samples, "detail": "samples omitted for size"},
        {**compact, "members": [], "omitted_members": omitted, "detail": "member details omitted for size"},
    ]
    for candidate in candidates:
        if len(encoded({**receipt, "content_diff": candidate})) <= limit:
            receipt["content_diff"] = candidate
            return None if candidate is report else summary(report) + f"; {candidate['detail']}"
    reason = "existing receipt already exceeds cap" if base > limit else "insufficient receipt budget"
    return summary(report) + f"; content_diff omitted for size: {reason} ({base} base bytes, cap {limit})"
