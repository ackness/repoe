"""Derive inputs.lock.json and frozen-inputs.json from a predecessor and a release:inputs stage.

Human review markers are reported, not invented. The new domains.json must
already exist; all three documents are validated before either output is created.
"""

import argparse
import copy
import io
import os
from pathlib import Path
import re
import tempfile
import zipfile

from RePoE.client import source_io
from RePoE.release import assets, build, policy_rebinding, publish
from RePoE.release.pins import (
    HEX,
    archive_manifest,
    byte_pin,
    decode,
    pin,
    pinned,
    regular,
    relative,
    require,
    runtime_encoded,
    safe_path,
)


def previous_tag(lock, directory):
    sequence = build.declared_sequence(directory, lock["target"])
    require(sequence is not None, "invalid-predecessor: directory must name its target patch")
    return publish.tag_name(lock["target"]["game_patch"], sequence)


def validate_transition(lock, frozen, directory, entries, patch, added, carry):
    require(isinstance(patch, str) and re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", patch), "invalid-patch")
    require(patch != lock["target"]["game_patch"], "unchanged-patch: declaration requires a new patch")
    require(frozen["target"] == lock["target"], "target-mismatch: predecessor frozen inputs")
    require(
        frozen["source"] == lock["reference"] == "previous",
        "invalid-predecessor: frozen source and reference must both be previous",
    )
    previous_tag(lock, directory)
    require("package" in lock.get("expect", {}), "missing-expect: predecessor needs expect.package")
    byte_pin(lock["expect"]["package"])
    require(isinstance(entries, dict) and entries, "missing-inputs: empty stage lock")
    require("previous" not in entries, "reference-package: stage cannot replace previous")
    missing = entries.keys() - lock["packages"].keys() - added
    require(not missing, f"unadded-package: use --add-package for {sorted(missing)}")
    unused = added - (entries.keys() - lock["packages"].keys())
    require(not unused, f"invalid-added-package: not new staged packages: {sorted(unused)}")
    for name, spec in entries.items():
        require(name.isidentifier(), f"invalid-package: {name}")
        require("revision" not in spec, f"stage-package: {name} must be a Release asset")
        assets.validate(spec)
        require(
            re.fullmatch(r"inputs/" + re.escape(patch) + r"-[1-9][0-9]*", spec["tag"]),
            f"invalid-input-tag: {name}: expected inputs/{patch}-<sequence>, no placeholder tags",
        )
    require(lock["facts"]["package"] in entries, "missing-counterpart: staged facts package")
    carried = lock["packages"].keys() - entries.keys() - {"previous"}
    unconfirmed = carried - carry
    require(not unconfirmed, f"unconfirmed-carry: use --carry for {sorted(unconfirmed)}")
    unused = carry - carried
    require(not unused, f"invalid-carry: not carried packages: {sorted(unused)}")


def changed_fields(before, after, path=()):
    """Insertion-ordered field changes, including removed and newly introduced fields."""
    if isinstance(before, dict) and isinstance(after, dict):
        changes = []
        for key in dict.fromkeys([*before, *after]):
            if key not in before or key not in after:
                changes.append({"path": [*path, key], "old": before.get(key), "new": after.get(key)})
            else:
                changes.extend(changed_fields(before[key], after[key], (*path, key)))
        return changes
    return [] if before == after else [{"path": list(path), "old": before, "new": after}]


def derive(lock, frozen, directory, entries, facts_identity, previous, patch, added=frozenset(), carry=frozenset()):
    """Pure declaration transform; facts_identity is {root, sha256} from verified staged facts."""
    added, carry = set(added), set(carry)
    validate_transition(lock, frozen, directory, entries, patch, added, carry)
    tag = previous_tag(lock, directory)
    old_patch = lock["target"]["game_patch"]
    require(previous["tag"] == tag and previous["game_patch"] == old_patch, "target-mismatch: previous package")
    byte_pin(previous["manifest"])
    require(type(previous["expanded_bytes"]) is int and previous["expanded_bytes"] >= 0, "invalid-expanded-bytes")
    relative(facts_identity["root"])
    identity = facts_identity["sha256"]
    require(isinstance(identity, str) and HEX.fullmatch(identity), "invalid-facts-identity")
    result = copy.deepcopy(lock)
    result.pop("expect", None)
    target = {**lock["target"], "game_patch": patch}
    result["target"] = target
    packages = result["packages"]
    for name, spec in entries.items():
        packages[name] = copy.deepcopy(spec)
    require(
        packages.get("crafting", {}).get("input_manifest", {}).get("sha256") == identity,
        "crafting-input-mismatch: crafting.input_manifest must equal the fresh facts identity",
    )
    packages["previous"] = {
        "repository": publish.REPOSITORY,
        "tag": tag,
        "asset": publish.asset_name(old_patch),
        **lock["expect"]["package"],
        "manifest": copy.deepcopy(previous["manifest"]),
        "expanded_bytes": previous["expanded_bytes"],
    }
    result["facts"] = {
        "package": lock["facts"]["package"],
        "root": facts_identity["root"],
        "identities": {"original": identity, "rebound": identity},
    }
    carried = [name for name in lock["packages"] if name not in entries and name != "previous"]
    new_frozen = copy.deepcopy(frozen)
    new_frozen["target"] = copy.deepcopy(target)
    new_frozen["members"] = {}
    prefix = f"data/{old_patch}/"
    for member, entry in frozen["members"].items():
        renamed = f"data/{patch}/" + member[len(prefix) :] if member.startswith(prefix) else member
        require(renamed not in new_frozen["members"], f"frozen-member-conflict: {renamed}")
        carried_entry = copy.deepcopy(entry)
        carried_entry["carried_from"] = {
            "package": frozen["source"],
            "member": member,
            "game_patch": old_patch,
            "tag": tag,
        }
        new_frozen["members"][renamed] = carried_entry
    review = [
        {
            "path": ["inputs.lock.json", "packages", name, field],
            "action": "review publication; no pending marker added",
            "kind": "staged-marker",
        }
        for name, spec in entries.items()
        for field in (["publication_status"] if name == "crafting" else ["publication"])
        if field not in spec
    ]
    review.extend(
        {
            "path": ["inputs.lock.json", "packages", name, field],
            "action": "review carried publication",
            "kind": "carried-publication",
            "value": copy.deepcopy(packages[name][field]),
        }
        for name in carried
        for field in ("publication", "publication_status")
        if field in packages[name]
    )
    review.extend(
        {"path": ["inputs.lock.json", "packages", name], "action": "review added package"}
        for name in entries
        if name in added
    )
    review.extend(
        {
            "path": ["frozen-inputs.json", "members", "*", field],
            "action": "review carried metadata",
            "count": sum(field in entry for entry in frozen["members"].values()),
        }
        for field in ("category", "origin", "reason", "exit", "unchanged_since_0.5.5.4.2")
    )
    report = {
        "changes": changed_fields(lock, result, ("inputs.lock.json",))
        + changed_fields(frozen, new_frozen, ("frozen-inputs.json",)),
        "carried_packages": carried,
        "review": review,
        "expect_absent": True,
    }
    return result, new_frozen, report


def published_previous(lock, directory, cache, repo, fetch):
    """Resolve the local publication tag and verify the cached/downloaded zip against expect."""
    tag = previous_tag(lock, directory)
    require(build.tag_commit(repo, tag) is not None, f"missing-tag: local {tag} required")
    spec = {
        "repository": publish.REPOSITORY,
        "tag": tag,
        "asset": publish.asset_name(lock["target"]["game_patch"]),
        **lock["expect"]["package"],
    }
    raw = assets.fetch(spec, cache, fetch)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        manifest_raw = archive.read("manifest.json")
        spec.update(manifest=pin(manifest_raw), expanded_bytes=sum(info.file_size for info in archive.infolist()))
        _, manifest = archive_manifest(archive, spec)
        require(manifest["target"] == lock["target"], "target-mismatch: previous package manifest")
        for member, expected in manifest["files"].items():
            pinned(archive.read(member), expected)
    return {
        "tag": tag,
        "manifest": spec["manifest"],
        "expanded_bytes": spec["expanded_bytes"],
        "game_patch": manifest["target"]["game_patch"],
    }


def declare(
    *, config, staged, patch, out, add_package=(), carry=(), cache=build.CACHE / "inputs", fetch=False, repo=build.ROOT
):
    """Validate in a temporary directory, then exclusively create both files with rollback."""
    config, staged, out, cache = map(safe_path, (config, staged, out, cache))
    releases = safe_path(build.RELEASES)
    require(out.parent == releases, "invalid-output: new declaration must be a direct child of release/")
    require(not cache.is_relative_to(releases), "invalid-cache: cache must not be inside release/")
    for name, directory in (("config", config), ("staged", staged), ("out", out)):
        require(
            not (cache.is_relative_to(directory) or directory.is_relative_to(cache)),
            f"invalid-cache: cache overlaps {name}: {directory}",
        )
    outputs = [out / name for name in ("inputs.lock.json", "frozen-inputs.json")]
    for path in outputs:
        safe_path(path)
        require(not path.exists(), f"existing-output: {path}")
    domains_path = safe_path(out / "domains.json")
    require(domains_path.exists(), "missing-domains: run policy:rebind first")
    domains_raw = regular(domains_path).read_bytes()
    domains = decode(domains_raw)
    lock = decode(regular(config / "inputs.lock.json").read_bytes())
    frozen = decode(regular(config / "frozen-inputs.json").read_bytes())
    entries = decode(regular(staged / "lock.json").read_bytes())
    validate_transition(lock, frozen, config.name, entries, patch, set(add_package), set(carry))
    target = {**lock["target"], "game_patch": patch}
    require(domains["target"] == target, "target-mismatch: new domains.json")
    match = build.CONFIG_NAME.fullmatch(out.name)
    require(match and match["patch"] == patch, "invalid-output: directory must name the new patch")
    digests = [spec["sha256"] for spec in entries.values()] + [lock["expect"]["package"]["sha256"]]
    for directory in ("downloads", "packages"):
        safe_path(cache / directory)
    for digest in digests:
        for path in (
            cache / "downloads" / digest,
            cache / "downloads" / f".{digest}.{os.getpid()}.partial",
            cache / "packages" / digest,
            cache / "packages" / f"{digest}.partial",
        ):
            safe_path(path)
    for spec in entries.values():
        regular(staged / "assets" / spec["asset"])
    packages = policy_rebinding.staged_packages(staged, set(entries), cache, repo)
    for name, package in packages.items():
        manifest = decode(package.read("manifest.json"))
        identity = manifest.get("target", manifest.get("source_identity", {}))
        require(all(identity.get(key) == value for key, value in target.items()), f"target-mismatch: staged {name}")
    facts_package = packages[lock["facts"]["package"]]
    facts = policy_rebinding.fresh_facts(facts_package, target, cache)
    facts_root, manifest_pin = facts["roots"]["original"]
    facts_identity = {"root": facts_root.relative_to(facts_package.root).as_posix(), "sha256": manifest_pin["sha256"]}
    previous = published_previous(lock, config.name, cache, repo, fetch)
    result, new_frozen, report = derive(
        lock, frozen, config.name, entries, facts_identity, previous, patch, set(add_package), set(carry)
    )
    encoded = [runtime_encoded(document) for document in (result, new_frozen)]
    with tempfile.TemporaryDirectory(prefix="release-declare-") as temporary:
        work = Path(temporary) / out.name
        build.write_new(work / "domains.json", domains_raw)
        for path, raw in zip(outputs, encoded):
            build.write_new(work / path.name, raw)
        build.load_config(work)
    created = []
    try:
        for path, raw in zip(outputs, encoded):
            source_io.write_new(path, raw)
            created.append(path)
    except BaseException:
        for path in created:
            path.unlink()
        raise
    return report


def display_value(value):
    """Bounded, single-line values for humans; the change report retains the full data."""
    if isinstance(value, dict):
        keys = ("category", "bytes") if "category" in value else ("tag", "sha256")
        parts = [f"{key}={value[key]}" for key in keys if key in value and not isinstance(value[key], (dict, list))]
        text = ", ".join(parts) if parts else "object keys: " + ", ".join(value)
    elif isinstance(value, list):
        text = f"list ({len(value)} items)"
    else:
        text = str(value)
    text = " ".join(text.splitlines())
    return text if len(text) <= 120 else text[:117] + "..."


def change_lines(changes):
    """Present changes by document, collapsing only proven frozen provenance carries."""
    lines = []
    for document in dict.fromkeys(change["path"][0] for change in changes):
        group = [change for change in changes if change["path"][0] == document]
        consumed, carried = set(), []
        if document == "frozen-inputs.json":
            patch = next((change for change in group if change["path"][1:] == ["target", "game_patch"]), None)
            members = {
                change["path"][2]: index
                for index, change in enumerate(group)
                if len(change["path"]) == 3 and change["path"][1] == "members"
            }
            if patch:
                prefix = f"data/{patch['old']}/"
                for member, index in members.items():
                    before = group[index]
                    if (
                        not member.startswith(prefix)
                        or before["new"] is not None
                        or not isinstance(before["old"], dict)
                    ):
                        continue
                    renamed = f"data/{patch['new']}/" + member[len(prefix) :]
                    other = members.get(renamed)
                    if other is None:
                        continue
                    after = group[other]
                    if after["old"] is not None or not isinstance(after["new"], dict):
                        continue
                    old_content = {k: v for k, v in before["old"].items() if k != "carried_from"}
                    new_content = {k: v for k, v in after["new"].items() if k != "carried_from"}
                    if old_content == new_content:
                        consumed.update((index, other))
                        carried.append(f"frozen member {member} -> {renamed} (carried)")
            # Shared overlay members keep their keys but acquire the latest provenance hop.
            unchanged = {}
            for index, change in enumerate(group):
                path = change["path"]
                if len(path) >= 4 and path[1] == "members":
                    unchanged.setdefault(path[2], []).append(index)
            for member, indices in unchanged.items():
                if all(group[index]["path"][3] == "carried_from" for index in indices):
                    consumed.update(indices)
                    carried.append(f"frozen member {member} (carried)")
        additions = removals = fields = 0
        detail = []
        for index, change in enumerate(group):
            if index in consumed:
                continue
            path = change["path"]
            member = document == "frozen-inputs.json" and len(path) == 3 and path[1] == "members"
            if member and change["old"] is None:
                additions += 1
            elif member and change["new"] is None:
                removals += 1
            else:
                fields += 1
            pointer = "/" + "/".join(str(k).replace("~", "~0").replace("/", "~1") for k in path)
            detail.append(f"  {pointer}: {display_value(change['old'])} -> {display_value(change['new'])}")
        if document == "frozen-inputs.json":
            lines.append(
                f"{document}: {fields} field changes, {len(carried)} carried members, {additions} additions, {removals} removals"
            )
        else:
            lines.append(f"{document}: {fields} field changes")
        lines.extend(detail)
        lines.extend(carried)
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path, help="Published predecessor declaration directory")
    parser.add_argument(
        "--staged", required=True, type=Path, help="release:inputs directory with lock.json and assets/"
    )
    parser.add_argument("--patch", required=True)
    parser.add_argument("--out", required=True, type=Path, help="New declaration directory containing domains.json")
    parser.add_argument(
        "--add-package", action="append", default=[], metavar="NAME", help="Explicitly include a new package"
    )
    parser.add_argument(
        "--carry",
        action="append",
        default=[],
        metavar="NAME",
        help="Explicitly carry a predecessor package absent from the stage",
    )
    parser.add_argument("--cache", type=Path, default=build.CACHE / "inputs")
    parser.add_argument("--fetch", action="store_true", help="Allow downloading the pinned predecessor Release asset")
    args = parser.parse_args(argv)
    try:
        report = declare(**vars(args))
    except build.BUILD_ERRORS as error:
        parser.exit(1, f"release:declare: {error}\n")
    for line in change_lines(report["changes"]):
        print(line)
    print("Carried packages: " + ", ".join(report["carried_packages"]))
    for item in report["review"]:
        count = f" ({item['count']} members)" if "count" in item else ""
        value = f"; carried value: {display_value(item['value'])}" if "value" in item else ""
        print(f"H /{'/'.join(item['path'])}: {item['action']}{count}{value}")
    print("expect absent: pin it after the first release:build")
    print(f"Wrote {args.out / 'inputs.lock.json'} and {args.out / 'frozen-inputs.json'}")


if __name__ == "__main__":
    main()
