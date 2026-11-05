"""Project PoBR's special-currency catalog from the pinned crafting facts package.

The catalog is a category/identified-regular-stat projection of the neutral
crafting facts, not a complete effect packet, crafting simulator or source
admission. `release:build` runs it as the `crafting-catalog` job.
"""

import json

from RePoE.pins import HEX, archive_manifest, byte_pin, decode, pinned, require

FORMAT = "repoe-native-crafting-facts/v1"
POLICY = "pobr-trade-crafting-catalog/v1"
TABLES = ("BaseItemTypes", "ItemClasses", "Mods", "Stats", "Essences", "EssenceTargetItemCategories", "EssenceMods")
PRODUCERS = {"RePoE/native_crafting_facts.py", "RePoE/native_descriptions.py"}
OWNER = "ackness/repoe"


def runtime_encoded(value):
    """PoBR runtime JSON layout; the snapshot manifest pins these exact bytes."""
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()


def project(facts, *, source_manifest_sha256, facts_manifest_sha256, target):
    """Apply PoBR's catalog selection policy without inferring probabilities."""
    require(facts.get("format") == FORMAT, "Unknown crafting facts format")
    counts = facts["summary"]["tables"]
    require(
        set(counts) == set(TABLES) and all(type(n) is int and n >= 0 for n in counts.values()),
        "Invalid crafting table inventory",
    )

    def ref(value, table, *, nullable=True):
        if value is None:
            require(nullable, f"Selected {table} reference is null")
            return None
        require(
            isinstance(value, dict)
            and value.get("table") == table
            and type(value.get("row")) is int
            and 0 <= value["row"] < counts[table],
            f"Invalid {table} reference",
        )
        if table not in ("Essences", "EssenceMods"):
            require(isinstance(value.get("id"), str) and bool(value["id"]), f"Missing {table} string ID")
        return value

    def ordered(values, table):
        require(isinstance(values, list), f"Expected ordered {table} references")
        for index, value in enumerate(values):
            require(
                type(value.get("source_slot")) is int and value["source_slot"] == index, "Changed reference array order"
            )
            ref(value["target"], table)
        return [value["target"] for value in values]

    mods, ids = facts["mods"], set()
    require(len(mods) == counts["Mods"], "Incomplete Mods collection")
    for index, mod in enumerate(mods):
        identity = ref(mod["mod"], "Mods", nullable=False)
        require(identity["row"] == index and identity["id"] not in ids, "Duplicate/changed Mods identity")
        ids.add(identity["id"])
        require(
            type(mod["level_raw"]) is int and type(mod["has_hardmode_values_raw"]) is bool,
            "Invalid raw mod level/hardmode flag",
        )
        slots = mod["slots"]
        require(
            len(slots) == 8 and all(type(s["slot"]) is int and s["slot"] == i for i, s in enumerate(slots, 1)),
            "Eight ordered stat slots required",
        )
        for slot in slots:
            ref(slot["stat"], "Stats")
            require(
                all(
                    slot[key] is None or type(slot[key]) is int
                    for key in ("min_raw", "max_raw", "min_hardmode_raw", "max_hardmode_raw")
                ),
                "Invalid raw stat endpoints",
            )
    essences, categories = facts["essences"], facts["categories"]
    require(
        len(essences) == counts["Essences"] and len(categories) == counts["EssenceTargetItemCategories"],
        "Incomplete crafting join owners",
    )
    for index, row in enumerate(essences):
        require(ref(row["essence"], "Essences", nullable=False)["row"] == index, "Changed essence identity")
        ref(row["currency"], "BaseItemTypes")
    for index, row in enumerate(categories):
        require(
            ref(row["category"], "EssenceTargetItemCategories", nullable=False)["row"] == index,
            "Changed category identity",
        )
        ordered(row["item_classes"], "ItemClasses")

    selected, diagnostics, result, provenance = [], [], {}, {}
    rows = facts["essence_mods"]
    require(len(rows) == counts["EssenceMods"], "Incomplete EssenceMods collection")
    for index, row in enumerate(rows):
        require(ref(row["source"], "EssenceMods", nullable=False)["row"] == index, "Changed recipe row identity")
        essence = ref(row["essence"], "Essences")
        category = ref(row["target_category"], "EssenceTargetItemCategories")
        currency = ref(row["currency"], "BaseItemTypes")
        require(
            currency == (None if essence is None else essences[essence["row"]]["currency"]),
            "Recipe currency differs from essence owner",
        )
        require(
            row["item_classes"] == (None if category is None else categories[category["row"]]["item_classes"]),
            "Recipe classes differ from category owner",
        )
        direct, display = ref(row["mod"], "Mods"), ref(row["display_mod"], "Mods")
        outcomes = ordered(row["outcome_mods"], "Mods")
        for value in (direct, display, *outcomes):
            require(value is None or value == mods[value["row"]]["mod"], "Changed joined Mods identity")
        weights = row["outcome_mod_weights_raw"]
        require(
            isinstance(weights, list) and all(w is None or type(w) is int for w in weights),
            "Invalid raw outcome weights",
        )
        currency_name = "" if currency is None else currency["id"].rsplit("/", 1)[-1]
        source = "alloy" if currency_name.startswith("CurrencyVerisiumAlloy") else "essence"
        if source != "alloy" and not currency_name.startswith(("CurrencyPerfectEssence", "CurrencyCorruptedEssence")):
            if currency is None:
                diagnostics.append({"code": "unidentified_currency_not_selected", "source": row["source"]})
            continue
        require(category is not None, "Selected category owner is null")
        classes = ordered(row["item_classes"], "ItemClasses")
        require(all(value is not None for value in classes), "Selected item class is null")
        # PoBR's catalog policy, not proof of crafting eligibility.
        # DisplayMod is never substituted for a Mod.
        choices = outcomes if outcomes else ([direct] if direct is not None else [])
        require(choices and all(value is not None for value in choices), "Selected recipe has no identified outcome")
        selected.append(
            {
                "source": row["source"],
                "currency": currency,
                "category": category,
                "relationship": "OutcomeMods" if outcomes else "Mod",
                "mods": choices,
                "weights_raw": weights,
            }
        )
        if len(outcomes) != len(weights):
            diagnostics.append(
                {
                    "code": "selected_outcome_weights_unresolved",
                    "source": row["source"],
                    "outcomes": row["outcome_mods"],
                    "weights_raw": weights,
                }
            )
        for choice in choices:
            key = (source, choice["id"])
            result.setdefault(key, {"row": mods[choice["row"]], "types": set()})["types"].update(
                value["id"] for value in classes
            )
            provenance.setdefault(key, []).append(row["source"])

    recipes = []
    for (source, identity), entry in sorted(result.items()):
        mod, stats = entry["row"], []
        for slot in mod["slots"]:
            if slot["stat"] is None:
                if any(
                    slot[key] not in (None, 0) for key in ("min_raw", "max_raw", "min_hardmode_raw", "max_hardmode_raw")
                ):
                    diagnostics.append(
                        {
                            "code": "unidentified_stat_interval",
                            "mod": mod["mod"],
                            "sources": provenance[(source, identity)],
                            **slot,
                        }
                    )
                continue
            low, high = slot["min_raw"], slot["max_raw"]
            require(
                type(low) is int and type(high) is int and low <= high,
                "Selected identified stat lacks a regular interval",
            )
            stats.append({"id": slot["stat"]["id"], "min": low, "max": high})
        if mod["has_hardmode_values_raw"]:
            diagnostics.append({"code": "hardmode_channel_not_projected", "mod": mod["mod"]})
        recipes.append(
            {
                "source": source,
                "id": identity,
                "item_types": sorted(entry["types"]),
                "level": mod["level_raw"],
                "stats": stats,
            }
        )
    document = {
        "_meta": {
            "schema": POLICY,
            "source": FORMAT,
            "source_manifest_sha256": source_manifest_sha256,
            "input_manifest_sha256": facts_manifest_sha256,
            "declared_target": target,
            "scope": "Selected special-currency categories and identified regular-stat ranges; "
            "not complete effects, eligibility or probabilities.",
            "client_identity_independently_observed": False,
        },
        "mods": recipes,
    }
    return document, {
        "selected": selected,
        "diagnostics": diagnostics,
        "source_diagnostics": facts["diagnostics"],
        "summary": {"selected_rows": len(selected), "catalog_mods": len(recipes)},
    }


def facts_document(archive, spec, target):
    """Authenticate the whole crafting package before reading `crafting.json`."""
    require(spec.get("publication") == "published" and spec.get("repository") == OWNER, "Unpublished crafting facts")
    require(
        set(spec.get("producer", {})) == PRODUCERS
        and all(isinstance(value, str) and HEX.fullmatch(value) for value in spec["producer"].values()),
        "Invalid crafting producer closure",
    )
    byte_pin(spec["input_manifest"])
    _, manifest = archive_manifest(archive, spec)
    source = manifest["source_identity"]
    require(
        manifest.get("format") == FORMAT
        and manifest.get("status") == "partial-candidate"
        and manifest.get("production_ready") is False
        and all(source.get(key) == value for key, value in target.items()),
        "Crafting target/format mismatch",
    )
    require(
        manifest["input_package"]["manifest"] == spec["input_manifest"] and manifest["producer"] == spec["producer"],
        "Crafting producer/input identity mismatch",
    )
    expected = {"crafting.json", "input-manifest.json", *(f"{name}.json" for name in TABLES)}
    require(set(manifest["files"]) == expected, "Unexpected crafting package inventory")
    require(manifest["files"]["input-manifest.json"] == spec["input_manifest"], "Crafting input manifest pin differs")
    for name, expected_pin in manifest["files"].items():
        pinned(archive.read(name), expected_pin)
    return decode(archive.read("crafting.json"))
