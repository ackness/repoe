"""Create new policies and domains.json from verified old inputs and a release:inputs stage.

Only whole JSON identity values are rebound. Historical evidence that does not
name an input member stays as recorded; this command does not review policy rules.
"""

import argparse
import copy
from pathlib import Path
import tempfile

from RePoE.client import source_io
from RePoE.release import build
from RePoE.release.pins import HEX, decode, pin, pinned, relative, require, safe_path


def input_references(job):
    return [
        ref
        for option in job.get("options", {}).values()
        for ref in (option.values() if isinstance(option, dict) else [option])
        if isinstance(ref, str) and ":" in ref and not ref.startswith("policy:")
    ]


def staged_packages(stage, names, cache, repo):
    entries = decode((stage / "lock.json").read_bytes())
    packages = {}
    for name in sorted(names & entries.keys()):
        spec = entries[name]
        asset = stage / "assets" / relative(spec["asset"])
        raw = pinned(asset.read_bytes(), spec)
        download = cache / "downloads" / spec["sha256"]
        if not download.exists():
            build.write_new(download, raw)
        packages[name] = build.open_package(repo, name, spec, cache, False)
    return packages


def fresh_facts(package, target, cache):
    candidates = []
    for member in package.members:
        if member.endswith("/manifest.json"):
            document = decode(package.read(member))
            if document.get("format") == "repoe-native-facts/v4":
                candidates.append(member.removesuffix("/manifest.json"))
    require(len(candidates) == 1, "facts-root: staged package needs exactly one fresh facts candidate")
    root = candidates[0]
    manifest = package.read(root + "/manifest.json")
    identity = decode(manifest)["source_identity"]
    require(all(identity.get(k) == v for k, v in target.items()), "target-mismatch: staged facts target")
    return build.prepare_facts(
        package,
        {"root": root, "identities": dict.fromkeys(build.FACTS_IDENTITIES, pin(manifest)["sha256"])},
        cache,
    )


class Identities:
    """Match byte identities only when every old member has the same counterpart."""

    def __init__(self, old, new, old_facts, new_facts):
        self.members = {}
        for name, package in old.items():
            replacement = new[name]
            for member, before in package.members.items():
                self.members.setdefault(before["sha256"], []).append(
                    (f"{name}:{member}", replacement.members.get(member))
                )
        for identity, (root, manifest_pin) in old_facts["roots"].items():
            new_root, new_manifest_pin = new_facts["roots"][identity]
            self.members.setdefault(manifest_pin["sha256"], []).append(
                (f"facts:{identity}/manifest.json", new_manifest_pin)
            )
            before = decode((root / "manifest.json").read_bytes())["files"]
            after = decode((new_root / "manifest.json").read_bytes())["files"]
            for member, expected in before.items():
                self.members.setdefault(expected["sha256"], []).append(
                    (f"facts:{identity}/{member}", after.get(member))
                )

    def counterpart(self, digest, location):
        candidates = self.members.get(digest)
        if not candidates:
            return None, []
        # A job reference does not identify which policy field owns duplicate bytes.
        # Checking every occurrence also prevents a removed member being hidden.
        missing = [name for name, after in candidates if after is None]
        require(not missing, f"missing-counterpart: {location}: {', '.join(missing)} ({digest})")
        replacements = {(after["bytes"], after["sha256"]) for _, after in candidates}
        require(len(replacements) == 1, f"ambiguous-counterpart: {location}: {[c[0] for c in candidates]}")
        return candidates[0][1], [name for name, _ in candidates]


def rebind_document(document, identities, old_patch, patch, policy):
    changes = []
    tree_context_paths = (
        {("context_baseline",), ("context_columns",)}
        if document.get("schema") in {f"pobr-ordinary-target-tree-policy/v{version}" for version in range(1, 5)}
        else set()
    )

    def visit(value, path=()):
        # These tree-policy subtrees deliberately bind historical evidence.
        # Rebinding carries review markers verbatim; the adapter validates them.
        if path in tree_context_paths:
            return copy.deepcopy(value)
        if isinstance(value, dict):
            result = {key: visit(child, (*path, key)) for key, child in value.items()}
            # Pins containing a byte count must move both fields together.
            if "sha256" in value and "bytes" in value:
                after, _ = identities.counterpart(value["sha256"], f"{policy}:{'/'.join(map(str, path))}")
                if after is not None and value["bytes"] != after["bytes"]:
                    result["bytes"] = after["bytes"]
                    changes.append({"path": [*path, "bytes"], "old": value["bytes"], "new": after["bytes"]})
            return result
        if isinstance(value, list):
            return [visit(child, (*path, index)) for index, child in enumerate(value)]
        after, members = None, []
        required_identity = path and (
            str(path[-1]).endswith("manifest_sha256")
            or path[-1] in {"descriptions_sha256", "source_sha256", "source_lock_sha256"}
        )
        if required_identity:
            require(
                isinstance(value, str) and HEX.fullmatch(value),
                f"unknown-identity: {policy}: {'/'.join(map(str, path))}: {value}",
            )
        if isinstance(value, str) and HEX.fullmatch(value):
            replacement, members = identities.counterpart(value, f"{policy}:{'/'.join(map(str, path))}")
            if replacement is not None:
                after = replacement["sha256"]
            elif required_identity:
                raise ValueError(f"unknown-identity: {policy}: {'/'.join(map(str, path))}: {value}")
        elif value == old_patch and (
            path == ("version",) or (len(path) >= 2 and path[-2:] == ("target", "game_patch"))
        ):
            after = patch
        if after is not None and after != value:
            changes.append({"path": list(path), "old": value, "new": after, "members": members})
            return after
        return value

    return visit(document), changes


def rebind(
    *, config, staged, patch, domains_out, policies=build.POLICIES, cache=build.CACHE / "inputs", repo=build.ROOT
):
    """Preflight everything, then exclusively create the new policies and domains file."""
    config, staged, policies, cache = map(Path, (config, staged, policies, cache))
    require(len(relative(patch).parts) == 1, "invalid-patch: expected a single path component")
    lock = decode((config / "inputs.lock.json").read_bytes())
    domains = decode((config / "domains.json").read_bytes())
    require(domains["target"] == lock["target"], "target-mismatch: old declaration")
    old_patch = lock["target"]["game_patch"]
    require(patch != old_patch, "unchanged-patch: new policies require a new patch")
    target = {**lock["target"], "game_patch": patch}
    references = {ref for job in domains["jobs"] for ref in input_references(job)}
    names = {ref.partition(":")[0] for ref in references} | {lock["facts"]["package"]}
    old = {name: build.open_package(repo, name, lock["packages"][name], cache, False) for name in sorted(names)}
    staged_inputs = staged_packages(staged, names, cache, repo)
    facts_name = lock["facts"]["package"]
    require(facts_name in staged_inputs, f"missing-counterpart: staged {facts_name} facts package")
    # Packages absent from the new stage are explicitly carried from the declaration (e.g. legacy codec).
    new = {**old, **staged_inputs}
    for name, package in staged_inputs.items():
        require(decode(package.read("manifest.json")).get("target") == target, f"target-mismatch: staged {name}")
    old_facts = build.prepare_facts(old[facts_name], lock["facts"], cache)
    new_facts = fresh_facts(new[facts_name], target, cache)
    identities = Identities(old, new, old_facts, new_facts)
    result = copy.deepcopy(domains)
    result["target"] = target
    outputs, reports = {}, {}
    with tempfile.TemporaryDirectory(prefix="policy-rebind-") as temporary:
        work = Path(temporary)
        ctx = build.Context(target, new, new_facts, work, build.ADAPTER, work / "policies-source")
        for job in result["jobs"]:
            for flag, option in job.get("options", {}).items():
                ref = option["policy"] if isinstance(option, dict) else option
                if not ref.startswith("policy:"):
                    continue
                member = relative(ref.removeprefix("policy:"))
                require(member.name.startswith(old_patch + "-"), f"policy-name: {ref} does not name {old_patch}")
                renamed = member.with_name(patch + member.name[len(old_patch) :]).as_posix()
                source = decode((policies / member).read_bytes())
                policy, changes = rebind_document(source, identities, old_patch, patch, ref)
                raw = build.runtime_encoded(policy)
                destination = policies / renamed
                require(destination not in outputs or outputs[destination] == raw, f"policy-conflict: {destination}")
                outputs[destination] = raw
                reports[renamed] = changes
                new_ref = "policy:" + renamed
                if isinstance(option, dict):
                    option["policy"] = new_ref
                    option.pop("expect", None)
                    if not (ctx.policies / renamed).exists():
                        build.write_new(ctx.policies / renamed, raw)
                    materialized = build.materialize_policy(ctx, option, job)
                    option["expect"] = build.file_pin(materialized)
                else:
                    job["options"][flag] = new_ref
            job["outputs"] = {
                name: member.replace(f"data/{old_patch}/", f"data/{patch}/", 1)
                for name, member in job.get("outputs", {}).items()
            }
            if job.get("kind") == "snapshot-manifest":
                job["member"] = f"data/{patch}/manifest.json"
    destination = safe_path(domains_out)
    require(destination not in outputs, f"output-conflict: {destination}")
    outputs[destination] = build.runtime_encoded(result)
    for path in outputs:
        safe_path(path)
        require(not path.exists(), f"existing-output: {path}")
    created = []
    try:
        for path, raw in outputs.items():
            source_io.write_new(path, raw)
            created.append(path)
    except BaseException:
        for path in created:
            path.unlink()
        raise
    return reports


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path, help="Old declaration directory")
    parser.add_argument(
        "--staged", required=True, type=Path, help="release:inputs directory with lock.json and assets/"
    )
    parser.add_argument("--patch", required=True)
    parser.add_argument("--domains-out", required=True, type=Path, help="New domains.json (must not exist)")
    parser.add_argument("--policies", type=Path, default=build.POLICIES)
    parser.add_argument("--cache", type=Path, default=build.CACHE / "inputs")
    args = parser.parse_args(argv)
    try:
        reports = rebind(**vars(args))
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, f"policy-rebind: {error}\n")
    for policy, changes in reports.items():
        print(f"policy:{policy}")
        for change in changes:
            path = "/" + "/".join(str(k).replace("~", "~0").replace("/", "~1") for k in change["path"])
            members = ", ".join(change.get("members", []))
            print(f"  {path}: {change['old']} -> {change['new']}" + (f" [{members}]" if members else ""))
    print(f"Wrote {len(reports)} policies and {args.domains_out}")


if __name__ == "__main__":
    main()
