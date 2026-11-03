"""Project PoBR's special-currency catalog and add it to a published game part.

The catalog is a category/identified-regular-stat projection of the neutral
crafting facts, not a complete effect packet, crafting simulator or source
admission. `assemble` reads both published inputs from local Git objects only,
adds the projected file to the game part and checks it against the part's own
snapshot manifest. It never fetches, pushes or edits the publication index.
"""

import argparse
import hashlib
import io
import json
from pathlib import Path
import stat
import tempfile
import zipfile

from RePoE import publication_index as pub
from RePoE.data_publication import ROOT, archive_manifest, decode, encoded, pinned, require, safe_path

FORMAT = "repoe-native-crafting-facts/v1"
POLICY = "pobr-trade-crafting-catalog/v1"
PART_SCHEMA = "pobr-build-data-part/v1"
TABLES = ("BaseItemTypes", "ItemClasses", "Mods", "Stats", "Essences", "EssenceTargetItemCategories", "EssenceMods")
PRODUCERS = {"RePoE/native_crafting_facts.py", "RePoE/native_descriptions.py"}
POLICY_PATH = "RePoE/pobr_crafting_catalog.py"


def runtime_encoded(value):
    """PoBR runtime JSON layout; the snapshot manifest pins these exact bytes."""
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


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
    require(
        spec.get("publication") == "published" and spec.get("repository") == pub.OWNER, "Unpublished crafting facts"
    )
    require(
        set(spec.get("producer", {})) == PRODUCERS
        and all(isinstance(value, str) and pub.SHA.fullmatch(value) for value in spec["producer"].values()),
        "Invalid crafting producer closure",
    )
    pub.byte_pin(spec["input_manifest"])
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


def published_inputs(repo, index_path, sequence=None):
    """Return the target, game and crafting declarations of one validated sequence."""
    index = decode(pub.read_metadata(index_path))
    pub.validate_index(index, repo)
    chain = pub.read_chain(repo, index["head"])
    found = [value for _, value in chain if sequence is None or value["sequence"] == sequence]
    require(found, f"No sequence {sequence} in the publication chain")
    value = found[0]
    return value["target"], value["components"]["game"]["input"], value["components"]["crafting"]["input"]


def assemble(repo, target, game, crafting, name, out):
    """Write a game part that adds the projected catalog to `game`; no network or push."""
    repo, out = pub.safe_path(repo), safe_path(out)
    require(out.is_relative_to(ROOT / ".cache") and not out.exists(), "Fresh repository cache output required")
    require(pub.TOKEN.fullmatch(name), "Invalid handoff name")
    policy_raw = Path(__file__).read_bytes()
    version = target["game_patch"]
    destination = f"data/{version}/overlay/trade_crafting_sources.json"
    game_raw = pub.tree_blob(repo, game["revision"], game["path"], game)
    crafting_raw = pub.tree_blob(repo, crafting["revision"], crafting["path"], crafting)
    with zipfile.ZipFile(io.BytesIO(crafting_raw)) as archive:
        facts = facts_document(archive, crafting, target)
    document, decisions = project(
        facts,
        source_manifest_sha256=crafting["manifest"]["sha256"],
        facts_manifest_sha256=crafting["input_manifest"]["sha256"],
        target=target,
    )
    projected = runtime_encoded(document)
    with zipfile.ZipFile(io.BytesIO(game_raw)) as archive:
        _, base = archive_manifest(archive, game)
        require(
            base.get("schema") == PART_SCHEMA and base.get("kind") == "game" and base.get("target") == target,
            "Game part target/schema mismatch",
        )
        require(destination not in base["files"], "Game part already contains the crafting catalog")
        members = {member: pinned(archive.read(member), pin) for member, pin in base["files"].items()}
    snapshot = decode(members[f"data/{version}/manifest.json"])
    require(
        snapshot["files"].get("overlay/trade_crafting_sources.json") == sha(projected),
        "Projected catalog differs from the game part's snapshot manifest",
    )
    members[destination] = projected
    files = {member: pub.pin(raw) for member, raw in sorted(members.items())}
    manifest = {
        "schema": PART_SCHEMA,
        "kind": "game",
        "target": target,
        "production_ready": False,
        "retained_input_package": game,
        "projection": {
            "path": destination,
            "policy": POLICY,
            "producer": {POLICY_PATH: sha(policy_raw)},
            "crafting_input": crafting,
            "output": pub.pin(projected),
            "summary": decisions["summary"],
            "diagnostics": decisions["diagnostics"],
        },
        "limits": [
            "Every other member is copied byte for byte from retained_input_package with its original limits.",
            "The crafting catalog is an identified-regular-stat/category projection, "
            "not complete effects, weights or eligibility.",
            "Assembly does not acquire sources, certify gameplay semantics or publish remotely.",
        ],
        "files": files,
    }
    manifest_raw = encoded(manifest)
    require(Path(__file__).read_bytes() == policy_raw, "Crafting projection changed during assembly")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".crafting-assembly-", dir=out.parent) as temporary:
        stage = Path(temporary) / "result"
        stage.mkdir()
        with zipfile.ZipFile(stage / "data.zip", "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for member in sorted([*files, "manifest.json"]):
                info = zipfile.ZipInfo(member, (1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                raw = manifest_raw if member == "manifest.json" else members[member]
                archive.writestr(info, raw, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        result = {
            "schema": "repoe-data-package/v1",
            "publication": "local-only",
            "repository": pub.OWNER,
            "path": f"handoff/{name}/game-build-part.zip",
            "ref": f"refs/tags/handoff/{name}",
            **pub.pin((stage / "data.zip").read_bytes()),
            "manifest": pub.pin(manifest_raw),
            "expanded_bytes": len(manifest_raw) + sum(value["bytes"] for value in files.values()),
            "target": target,
        }
        (stage / "package.json").write_bytes(encoded(result))
        (stage / "manifest.json").write_bytes(manifest_raw)
        stage.rename(out)
    return result


def game_input(handoff):
    """The publication index `game` input for a staged and pushed handoff."""
    return {
        "bytes": handoff["bytes"],
        "expanded_bytes": handoff["expanded_bytes"],
        "manifest": handoff["manifest"],
        "path": handoff["path"],
        "publication": "published",
        "repository": handoff["repository"],
        "revision": handoff["revision"],
        "sha256": handoff["sha256"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("assemble", help="Add the projected catalog to the game part of one sequence")
    build.add_argument("--repo", type=Path, default=ROOT)
    build.add_argument("--index", type=Path, default=ROOT / "publication/index.json")
    build.add_argument("--sequence", type=int, help="Source sequence (default: the index head)")
    build.add_argument("--name", required=True, help="Handoff name, e.g. game-crafting-20261102")
    build.add_argument("--out", type=Path, required=True)
    declare = sub.add_parser("game-input", help="Print the index game input of a staged handoff")
    declare.add_argument("--package", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "assemble":
        target, game, crafting = published_inputs(args.repo, args.index, args.sequence)
        result = assemble(args.repo, target, game, crafting, args.name, args.out)
    else:
        result = game_input(decode(pub.read_metadata(safe_path(args.package) / "git-handoff.json")))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
