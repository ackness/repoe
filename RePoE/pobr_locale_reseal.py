"""Reseal a retained game part against an explicitly pinned language publication.

Only declared i18n hashes in the schema-3 full snapshot may change. Language
bytes remain with their owner; this operation produces no game facts.
"""

import argparse
import copy
import io
from pathlib import Path
import stat
import tempfile
import zipfile

from RePoE import publication_index as pub
from RePoE.data_publication import ROOT, archive_manifest, decode, encoded, pin, pinned, relative, require, safe_path
from RePoE.pobr_historical_trees import runtime_encoded

SCHEMA = "repoe-locale-reseal-plan/v1"
LANGUAGE_OWNER = "ackness/poe2-zh-cn-stats"
PRODUCERS = (
    "RePoE/__init__.py",
    "RePoE/pobr_locale_reseal.py",
    "RePoE/pobr_historical_trees.py",
    "RePoE/data_publication.py",
    "RePoE/publication_index.py",
)


def rebind_snapshot(raw, target, locale, changes):
    """Require the complete locale inventory and exactly the declared hash delta."""
    snapshot = decode(raw)
    require(
        snapshot.get("schema_version") == 3 and snapshot.get("poe_version") == target["game_patch"],
        "Snapshot version/schema mismatch",
    )
    require(
        locale.get("schema") == "poe2-retained-locale-publication/v1" and locale.get("target") == target,
        "Language target/schema mismatch",
    )
    before = {name: digest for name, digest in snapshot["files"].items() if name.startswith("i18n/")}
    after = {name: expected["sha256"] for name, expected in locale["files"].items() if name.startswith("i18n/")}
    require(before and before.keys() == after.keys(), "Full snapshot locale inventory mismatch")
    require(isinstance(changes, dict) and changes, "Explicit locale changes required")
    actual = {name: {"before": before[name], "after": after[name]} for name in before if before[name] != after[name]}
    require(actual == changes, "Undeclared or incorrect locale hash changes")
    for name, change in changes.items():
        relative(name)
        require(name.startswith("i18n/"), "Only locale bindings may change")
        require(all(isinstance(v, str) and pub.SHA.fullmatch(v) for v in change.values()), "Invalid locale digest")
        snapshot["files"][name] = change["after"]
    return runtime_encoded(snapshot)


def assemble(repo, language_repo, plan_path, plan_sha256, name, out):
    """Authenticate both owners' immutable local blobs and write a fresh candidate."""
    repo, language_repo, plan_path, out = map(safe_path, (repo, language_repo, plan_path, out))
    require(out.is_relative_to(ROOT / ".cache") and not out.exists(), "Fresh repository cache output required")
    require(not any(p.is_relative_to(out) for p in (repo, language_repo, plan_path)), "Output overlaps input")
    require(pub.TOKEN.fullmatch(name), "Invalid handoff name")
    plan_raw = pub.read_metadata(plan_path)
    require(pub.SHA.fullmatch(plan_sha256) and pin(plan_raw)["sha256"] == plan_sha256, "Plan SHA-256 mismatch")
    plan = decode(plan_raw)
    require(plan.get("schema") == SCHEMA, "Unsupported locale reseal plan")
    target, game, language = plan["target"], plan["game_input"], plan["language_manifest"]
    pub.target(target)
    require(target["game"] == "poe2", "PoE2 game part required")
    pub.input_declaration("game", game)
    require(language["repository"] == LANGUAGE_OWNER, "Language owner mismatch")
    language_pin = {key: language[key] for key in ("revision", "path", "bytes", "sha256")}
    locale = decode(pub.git_blob(language_repo, language_pin))
    # Authenticate all language/evidence members without importing them into the
    # game part or changing their producer, ownership or applicability metadata.
    language_prefix = str(relative(language["path"]).parent)
    for member, expected in locale["files"].items():
        relative(member)
        pub.byte_pin(expected)
        pub.tree_blob(language_repo, language["revision"], f"{language_prefix}/{member}", expected)
    producer = {path: pin((ROOT / path).read_bytes()) for path in PRODUCERS}
    game_raw = pub.tree_blob(repo, game["revision"], game["path"], game)
    with zipfile.ZipFile(io.BytesIO(game_raw)) as archive:
        _, manifest = archive_manifest(archive, game)
        require(
            manifest.get("schema") == "pobr-build-data-part/v1"
            and manifest.get("kind") == "game"
            and manifest.get("target") == target,
            "Game part target/schema mismatch",
        )
        require(all("/i18n/" not in path for path in manifest["files"]), "Language member in game part")
        members = {member: pinned(archive.read(member), expected) for member, expected in manifest["files"].items()}
    snapshot_path = f"data/{target['game_patch']}/manifest.json"
    old_snapshot = members[snapshot_path]
    members[snapshot_path] = rebind_snapshot(old_snapshot, target, locale, plan["changes"])
    # Keep every historical provenance/limits field intact. The added receipt
    # describes only this reseal and pins its predecessor; it certifies no source.
    manifest = copy.deepcopy(manifest)
    manifest["files"][snapshot_path] = pin(members[snapshot_path])
    receipt = {
        "plan": pin(plan_raw),
        "retained_game_input": game,
        "language_manifest": language,
        "producer": producer,
        "changes": plan["changes"],
        "snapshot": {"path": snapshot_path, "input": pin(old_snapshot), "output": pin(members[snapshot_path])},
        "limits": [
            "Locale hash binding only; no game facts, source ownership or historical acceptance changes.",
            "Language bytes remain owned by ackness/poe2-zh-cn-stats and are not included in this game part.",
            "No current client freshness, remote publication or consumer adoption is established.",
        ],
    }
    manifest.setdefault("locale_reseals", []).append(receipt)
    manifest_raw = encoded(manifest)
    require(pub.read_metadata(plan_path) == plan_raw, "Plan changed during assembly")
    require({path: pin((ROOT / path).read_bytes()) for path in PRODUCERS} == producer, "Producer changed")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".locale-reseal-", dir=out.parent) as temporary:
        stage = Path(temporary) / "result"
        stage.mkdir()
        # Same deterministic archive and package contract as the owner packer.
        with zipfile.ZipFile(stage / "data.zip", "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for member in sorted([*members, "manifest.json"]):
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
            **pin((stage / "data.zip").read_bytes()),
            "manifest": pin(manifest_raw),
            "expanded_bytes": len(manifest_raw) + sum(map(len, members.values())),
            "target": target,
        }
        (stage / "manifest.json").write_bytes(manifest_raw)
        (stage / "package.json").write_bytes(encoded(result))
        stage.rename(out)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--language-repo", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = assemble(args.repo, args.language_repo, args.plan, args.plan_sha256, args.name, args.out)
    print(encoded(result).decode(), end="")


if __name__ == "__main__":
    main()
