"""Publish explicitly selected, byte-pinned exports without decoding or networking.

Historical compatibility bytes stay opaque: their schema, patch and provenance
are never promoted to native facts by moving their storage to RePoE.
"""

import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
HEX = re.compile(r"[0-9a-f]{64}")
KINDS = {"native-facts", "native-facts-archive", "retained-compatibility", "source-metadata"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def constant(value):
        raise ValueError(f"Invalid JSON constant: {value}")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def validate_pin(expected):
    require(
        isinstance(expected, dict)
        and type(expected.get("bytes")) is int
        and expected["bytes"] >= 0
        and isinstance(expected.get("sha256"), str)
        and HEX.fullmatch(expected["sha256"]),
        "Invalid byte pin",
    )


def pinned(raw, expected):
    validate_pin(expected)
    require(pin(raw) == {key: expected[key] for key in ("bytes", "sha256")}, "Byte pin mismatch")
    return raw


def relative(name):
    require(
        isinstance(name, str)
        and name
        and "\\" not in name
        and ":" not in name
        and all(ord(c) >= 32 and ord(c) != 127 for c in name),
        "Unsafe member path",
    )
    path = PurePosixPath(name)
    require(
        bool(path.parts)
        and not path.is_absolute()
        and path.as_posix() == name
        and ".." not in path.parts
        and "." not in path.parts,
        "Unsafe member path",
    )
    return path


def safe_path(path):
    path = Path(path).absolute()
    require(".." not in path.parts and all(not p.is_symlink() for p in (path, *path.parents)), "Symlink/unsafe path")
    return path


def regular(path):
    path = safe_path(path)
    require(stat.S_ISREG(path.stat().st_mode), "Regular file required")
    return path


def archive_manifest(archive, spec):
    entries = archive.infolist()
    names = [entry.filename for entry in entries]
    require(len(names) == len(set(names)) and "manifest.json" in names, "Duplicate/missing archive member")
    for entry in entries:
        relative(entry.filename)
        require(
            not entry.is_dir() and stat.S_IFMT(entry.external_attr >> 16) in (0, stat.S_IFREG),
            "Non-regular archive member",
        )
    require(
        type(spec.get("expanded_bytes")) is int and sum(e.file_size for e in entries) == spec["expanded_bytes"],
        "Expanded size mismatch",
    )
    raw = pinned(archive.read("manifest.json"), spec["manifest"])
    manifest = decode(raw)
    require(set(names) == {"manifest.json", *manifest["files"]}, "Archive inventory mismatch")
    for name, expected in manifest["files"].items():
        relative(name)
        validate_pin(expected)
        require(archive.getinfo(name).file_size == expected["bytes"], "Member size mismatch")
    return raw, manifest


class GitTree:
    """Read only immutable tracked blobs, never the checkout's data files."""

    def __init__(self, root, spec):
        self.root, self.spec = safe_path(root), spec
        paths = [str(relative(path)) for path in spec["inventory_paths"]]
        listing = subprocess.check_output(
            ["git", "-C", str(self.root), "ls-tree", "-rz", spec["revision"], "--", *paths]
        )
        files = {}
        for item in listing.split(b"\0"):
            if not item:
                continue
            metadata, name = item.decode().split("\t", 1)
            mode, kind, _ = metadata.split()
            require(mode == "100644" and kind == "blob", "Non-regular Git member")
            name = PurePosixPath(name).relative_to(spec["path"]).as_posix()
            relative(name)
            files[name] = spec["files"].get(name)
        require(files.keys() == spec["files"].keys(), "Git inventory mismatch")
        for expected in files.values():
            validate_pin(expected)

    def read(self, name):
        relative(name)
        raw = subprocess.check_output(
            ["git", "-C", str(self.root), "cat-file", "blob", f"{self.spec['revision']}:{self.spec['path']}/{name}"]
        )
        return pinned(raw, self.spec["files"][name])


def selected(raw, member):
    """Extract declared data objects; no rules, hash rebinding or value rewriting."""
    if "fields" not in member:
        return raw
    source, result = decode(raw), {}
    for pointer in member["fields"]:
        require(
            isinstance(pointer, list) and pointer and all(isinstance(k, str) for k in pointer),
            "Invalid data field selection",
        )
        value, destination = source, result
        for key in pointer[:-1]:
            value = value[key]
            destination = destination.setdefault(key, {})
        require(pointer[-1] not in destination, "Overlapping data field selection")
        destination[pointer[-1]] = value[pointer[-1]]
    # The consumer reconstructs the original policy bytes, including insertion
    # order inside every retained mapping object. Canonical sorting loses that.
    return (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode()


def validate_plan(plan):
    require(plan.get("schema") == "repoe-data-publication-plan/v1", "Unsupported publication plan")
    target = plan["target"]
    require(
        set(target) == {"game", "game_patch", "realm"}
        and all(isinstance(value, str) and value for value in target.values()),
        "Explicit target required",
    )
    require(plan.get("repository") == "ackness/repoe", "RePoE publication repository required")
    relative(plan["path"])
    require(
        re.fullmatch(r"refs/heads/handoff/[A-Za-z0-9._/-]+", plan["ref"])
        and ".." not in plan["ref"]
        and not plan["ref"].endswith("/"),
        "Invalid handoff ref",
    )
    require(plan["sources"] and plan["members"], "Empty publication")
    for key, source in plan["sources"].items():
        require(re.fullmatch(r"[A-Za-z0-9_-]+", key), "Invalid source key")
        require(
            re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", source["repository"])
            and re.fullmatch(r"[0-9a-f]{40}", source["revision"]),
            "Immutable Git source required",
        )
        relative(source["path"])
        if source.get("type", "zip") == "zip":
            validate_pin(source)
            validate_pin(source["manifest"])
        else:
            require(
                source["type"] == "git-tree" and source["files"] and source["inventory_paths"], "Invalid Git source"
            )
            for name, expected in source["files"].items():
                relative(name)
                validate_pin(expected)
    for name, member in plan["members"].items():
        relative(name)
        require(name != "manifest.json" and not name.startswith("publication-provenance/"), "Reserved output path")
        require(member["source"] in plan["sources"] and member["kind"] in KINDS, "Invalid member ownership")
        relative(member["member"])
        require(member.get("note") and "observed_identity" in member, "Member scope/provenance required")
        validate_pin(member)
        if "fields" in member:
            require(member["kind"] == "retained-compatibility", "Only retained data supports field selection")
            validate_pin(member["source_pin"])


def package(plan_path, plan_sha256, inputs, output):
    """Validate the entire selection before atomically exposing a new package."""
    plan_raw = regular(plan_path).read_bytes()
    require(HEX.fullmatch(plan_sha256 or "") and pin(plan_raw)["sha256"] == plan_sha256, "Plan SHA-256 mismatch")
    plan = decode(plan_raw)
    validate_plan(plan)
    require(set(inputs) == set(plan["sources"]), "Explicit source paths required; no fallback")
    output = safe_path(output)
    require(output.is_relative_to(ROOT / ".cache") and not output.exists(), "Fresh repository cache output required")
    input_paths = {
        key: (regular(path) if plan["sources"][key].get("type", "zip") == "zip" else safe_path(path))
        for key, path in inputs.items()
    }
    require(
        not any(p.is_relative_to(output) for p in [*input_paths.values(), Path(plan_path).absolute()]),
        "Output overlaps input",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with ExitStack() as stack, tempfile.TemporaryDirectory(prefix=".publication-", dir=output.parent) as temporary:
        sources, manifests, provenance = {}, {}, {}
        for key, spec in plan["sources"].items():
            if spec.get("type", "zip") == "zip":
                # Authenticate the original compressed archive once, without expanded copies.
                with input_paths[key].open("rb") as handle:
                    actual = {
                        "bytes": os.fstat(handle.fileno()).st_size,
                        "sha256": hashlib.file_digest(handle, "sha256").hexdigest(),
                    }
                require(actual == {field: spec[field] for field in actual}, "Source archive pin mismatch")
                sources[key] = stack.enter_context(zipfile.ZipFile(input_paths[key]))
                raw, manifests[key] = archive_manifest(sources[key], spec)
                provenance[f"publication-provenance/{key}-manifest.json"] = raw
            else:
                sources[key] = GitTree(input_paths[key], spec)
                manifests[key] = {"files": spec["files"]}
            accounted = [m["member"] for m in plan["members"].values() if m["source"] == key and "fields" not in m]
            excluded = plan["excluded"].get(key, {})
            require(
                len(accounted) == len(set(accounted))
                and not set(accounted) & set(excluded)
                and set(accounted) | set(excluded) == set(manifests[key]["files"]),
                "Unaccounted source member",
            )
            require(
                all(isinstance(reason, str) and reason for reason in excluded.values()), "Exclusion reason required"
            )
        files = {name: {k: entry[k] for k in ("bytes", "sha256")} for name, entry in plan["members"].items()}
        files.update({name: pin(raw) for name, raw in provenance.items()})
        for name, entry in plan["members"].items():
            expected = entry.get("source_pin", files[name])
            require(manifests[entry["source"]]["files"].get(entry["member"]) == expected, "Selection pin mismatch")
        schema = plan.get("output_schema", "repoe-data-publication/v1")
        require(schema in {"repoe-data-publication/v1", "pobr-build-data-part/v1"}, "Unsupported output schema")
        if schema == "pobr-build-data-part/v1":
            require(
                plan.get("kind") == "game"
                and not provenance
                and all(
                    name.startswith((f"data/{plan['target']['game_patch']}/", "data/overlay-common/"))
                    and "/i18n/" not in name
                    for name in files
                ),
                "Invalid game build part",
            )
        manifest = {
            "schema": schema,
            "target": plan["target"],
            "production_ready": False,
            "plan": pin(plan_raw),
            "sources": plan["sources"],
            "members": plan["members"],
            "excluded": plan["excluded"],
            "limits": plan["limits"],
            "files": files,
        }
        if schema == "pobr-build-data-part/v1":
            manifest["kind"] = "game"
        manifest_raw = encoded(manifest)
        stage = Path(temporary) / "result"
        stage.mkdir()
        path = stage / "data.zip"
        with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in sorted([*files, "manifest.json"]):
                if name == "manifest.json":
                    raw = manifest_raw
                elif name in provenance:
                    raw = provenance[name]
                else:
                    entry = plan["members"][name]
                    raw = sources[entry["source"]].read(entry["member"])
                    if "fields" in entry:
                        pinned(raw, entry["source_pin"])
                    raw = pinned(selected(raw, entry), files[name])
                info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                archive.writestr(info, raw, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        result = {
            "schema": "repoe-data-package/v1",
            "publication": "local-only",
            "repository": plan["repository"],
            "path": plan["path"],
            "ref": plan["ref"],
            **pin(path.read_bytes()),
            "manifest": pin(manifest_raw),
            "expanded_bytes": len(manifest_raw) + sum(value["bytes"] for value in files.values()),
            "plan": pin(plan_raw),
            "target": plan["target"],
        }
        (stage / "package.json").write_bytes(encoded(result))
        (stage / "manifest.json").write_bytes(manifest_raw)
        stage.rename(output)
    return result


def git_handoff(package_dir):
    """Stage an orphan artifact for ackness/repoe; never create a checkout or push."""
    package_dir = safe_path(package_dir)
    require(package_dir.is_relative_to(ROOT / ".cache"), "Repository cache required")
    spec = decode(regular(package_dir / "package.json").read_bytes())
    require(spec.get("schema") == "repoe-data-package/v1" and spec["repository"] == "ackness/repoe", "Invalid package")
    relative(spec["path"])
    raw = pinned(regular(package_dir / "data.zip").read_bytes(), spec)
    with zipfile.ZipFile(regular(package_dir / "data.zip")) as archive:
        archive_manifest(archive, spec)
    bare = package_dir / "handoff.git"
    require(not bare.exists(), "Fresh Git handoff required")
    subprocess.run(["git", "init", "--bare", "--quiet", str(bare)], check=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "RePoE data publication",
        "GIT_AUTHOR_EMAIL": "data@repoe.invalid",
        "GIT_COMMITTER_NAME": "RePoE data publication",
        "GIT_COMMITTER_EMAIL": "data@repoe.invalid",
        "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
        "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
    }

    def git(*args, data=None):
        return subprocess.check_output(["git", "--git-dir", str(bare), *args], input=data, env=env).decode().strip()

    git("check-ref-format", spec["ref"])
    blob = git("hash-object", "-w", "--stdin", data=raw)
    parts = list(relative(spec["path"]).parts)
    tree = git("mktree", data=f"100644 blob {blob}\t{parts.pop()}\n".encode())
    for part in reversed(parts):
        tree = git("mktree", data=f"040000 tree {tree}\t{part}\n".encode())
    revision = git("commit-tree", tree, data=b"Retain pinned independent RePoE data inputs\n")
    git("update-ref", spec["ref"], revision)
    result = {**spec, "revision": revision, "tree": tree, "blob": blob, "bare": str(bare)}
    (package_dir / "git-handoff.json").write_bytes(encoded(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("package")
    build.add_argument("--plan", type=Path, required=True)
    build.add_argument("--plan-sha256", required=True)
    build.add_argument("--input", action="append", default=[], metavar="SOURCE=PATH")
    build.add_argument("--out", type=Path, required=True)
    handoff = sub.add_parser("git-handoff")
    handoff.add_argument("--package", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "git-handoff":
        result = git_handoff(args.package)
    else:
        inputs = {}
        for item in args.input:
            key, separator, path = item.partition("=")
            require(separator and key not in inputs and path, "Use unique SOURCE=PATH inputs")
            inputs[key] = path
        result = package(args.plan, args.plan_sha256, inputs, args.out)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
