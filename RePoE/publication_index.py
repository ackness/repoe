"""Register and validate small, completed RePoE publication declarations offline.

This module neither produces data nor verifies a new remote publication. Explicitly
pinned coordinator-accepted locks are the bootstrap/completion trust boundary.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile

OWNER = "ackness/repoe"
ROLES = frozenset({"game", "crafting", "ordinary", "display_source", "source_verifier", "test_fixtures"})
SCOPE = {
    "complete": True,
    "meaning": "declared-role-dependencies-only",
    "official_semantics_certified": False,
    "client_identity_certified": False,
}
LIMIT = 256 * 1024
SHA = re.compile(r"[0-9a-f]{64}")
REV = re.compile(r"[0-9a-f]{40}")
TOKEN = re.compile(r"[a-z0-9][a-z0-9_-]*")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def decode(raw):
    require(len(raw) <= LIMIT, "Metadata size limit exceeded")

    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def constant(value):
        raise ValueError(f"Invalid JSON constant: {value}")

    def finite(value):
        number = float(value)
        require(math.isfinite(number), "Invalid nonfinite JSON number")
        return number

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant, parse_float=finite)


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def byte_pin(value):
    require(isinstance(value, dict) and set(value) == {"bytes", "sha256"}, "Invalid byte pin fields")
    require(type(value["bytes"]) is int and value["bytes"] >= 0, "Invalid bytes")
    require(isinstance(value["sha256"], str) and SHA.fullmatch(value["sha256"]), "Invalid sha256")


def revision(value):
    require(isinstance(value, str) and REV.fullmatch(value) and value != "0" * 40, "Invalid full revision")


def relative(value):
    require(isinstance(value, str) and value and "\\" not in value and ":" not in value, "Invalid path")
    require(all(ord(c) >= 32 and ord(c) != 127 for c in value), "Invalid path")
    path = PurePosixPath(value)
    require(not path.is_absolute() and path.parts and path.as_posix() == value, "Invalid path")
    require(not {".", ".."}.intersection(path.parts) and value != ".", "Invalid path")
    return value


def safe_path(path):
    path = Path(path).absolute()
    require(".." not in path.parts and all(not p.is_symlink() for p in (path, *path.parents)), "Symlink/unsafe path")
    return path


def read_metadata(path):
    path = safe_path(path)
    require(stat.S_ISREG(path.stat().st_mode), "Regular metadata file required")
    require(path.stat().st_size <= LIMIT, "Metadata size limit exceeded")
    with path.open("rb") as stream:
        raw = stream.read(LIMIT + 1)
    decode(raw)
    return raw


def positive(value):
    require(type(value) is int and value > 0, "Sequence must be a positive integer")


def channel(value):
    require(isinstance(value, dict) and set(value) == {"game", "realm"}, "Invalid channel")
    require(all(isinstance(v, str) and TOKEN.fullmatch(v) for v in value.values()), "Invalid channel identity")


def target(value):
    require(isinstance(value, dict) and set(value) == {"game", "game_patch", "realm"}, "Invalid target")
    channel({k: value[k] for k in ("game", "realm")})
    require(
        isinstance(value["game_patch"], str)
        and value["game_patch"].strip() == value["game_patch"]
        and bool(value["game_patch"]),
        "Invalid target patch",
    )


def descriptor_pin(value):
    require(isinstance(value, dict) and set(value) == {"revision", "path", "bytes", "sha256"}, "Invalid descriptor pin")
    revision(value["revision"])
    relative(value["path"])
    byte_pin({k: value[k] for k in ("bytes", "sha256")})
    require(value["bytes"] <= LIMIT, "Metadata size limit exceeded")


def input_declaration(role, value):
    require(isinstance(value, dict) and value.get("repository") == OWNER, "Wrong input owner")
    revision(value.get("revision"))
    if role == "source_verifier":
        require(value.get("schema") == "pobr-source-verifier/v1", "Invalid source verifier schema")
        require("path" not in value and "publication" not in value, "Source verifier must retain Git-files form")
        require(isinstance(value.get("files"), dict) and value["files"], "Missing verifier file closure")
        for name, expected in value["files"].items():
            relative(name)
            byte_pin(expected)
    else:
        # The accepted display-source lock predates explicit publication fields.
        # Registration still requires exact equality to its pinned accepted record.
        require(
            value.get("publication") == "published" or (role == "display_source" and "publication" not in value),
            "Unpublished package",
        )
        relative(value.get("path"))
        byte_pin({k: value.get(k) for k in ("bytes", "sha256")})
        byte_pin(value.get("manifest"))
        require(
            type(value.get("expanded_bytes")) is int and value["expanded_bytes"] >= value["bytes"],
            "Invalid expanded bytes",
        )
    if "target" in value:
        target(value["target"])

    # Validate additional original pins without changing or reclassifying metadata.
    def nested(item):
        if isinstance(item, dict):
            if "bytes" in item or "sha256" in item:
                byte_pin({k: item.get(k) for k in ("bytes", "sha256")})
            for key, child in item.items():
                if key == "revision":
                    revision(child)
                elif key == "path":
                    relative(child)
                elif key == "files":
                    require(isinstance(child, (dict, list)) and child, "Invalid file closure")
                    for name in child:
                        relative(name)
                    require(len(child) == len(set(child)), "Duplicate file closure entry")
                    if isinstance(child, dict):
                        for expected in child.values():
                            byte_pin(expected)
                elif key == "producer":
                    require(isinstance(child, dict) and child, "Invalid producer pins")
                    for name, digest in child.items():
                        relative(name)
                        require(isinstance(digest, str) and SHA.fullmatch(digest), "Invalid producer sha256")
                nested(child)
        elif isinstance(item, list):
            for child in item:
                nested(child)

    nested(value)


def validate_descriptor(value, accepted=None):
    require(
        isinstance(value, dict)
        and set(value) == {"schema", "owner", "target", "sequence", "previous", "components", "scope"},
        "Invalid descriptor fields",
    )
    require(value["schema"] == "owned-data-publication/v2", "Expected publication v2 (v1 is historical)")
    require(value["owner"] == OWNER, "Wrong descriptor owner")
    target(value["target"])
    positive(value["sequence"])
    require(encoded(value["scope"]) == encoded(SCOPE), "Invalid completeness scope")
    components = value["components"]
    require(isinstance(components, dict) and set(components) == ROLES, "Missing/extra role (crafting is required)")
    for role, component in components.items():
        require(isinstance(component, dict) and set(component) == {"sequence", "input"}, "Invalid component fields")
        positive(component["sequence"])
        input_declaration(role, component["input"])
        if "target" in component["input"]:
            require(component["input"]["target"] == value["target"], "Wrong input target")
    if value["sequence"] == 1:
        require(value["previous"] is None, "Bootstrap must have no predecessor")
        require(all(c["sequence"] == 1 for c in components.values()), "Bootstrap role sequence must be 1")
    else:
        descriptor_pin(value["previous"])
    if accepted is not None:
        validate_accepted(accepted)
        require(value["target"] == accepted["target"], "Wrong accepted target")
        require(
            encoded({r: c["input"] for r, c in components.items()}) == encoded(accepted["inputs"]),
            "Descriptor differs from completed accepted inputs",
        )
    return value


def validate_accepted(value):
    require(isinstance(value, dict) and set(value) == {"target", "inputs"}, "Invalid accepted record")
    target(value["target"])
    require(isinstance(value["inputs"], dict) and set(value["inputs"]) == ROLES, "Missing/extra accepted role")
    for role, declaration in value["inputs"].items():
        input_declaration(role, declaration)
        if "target" in declaration:
            require(declaration["target"] == value["target"], "Wrong accepted input target")


def load_accepted_inputs(build, ordinary, imports, *, sha256s):
    """Extract only existing owner declarations from three explicitly trusted locks.

    Digests must come from the coordinator's acceptance, not mutable discovery.
    This is a local replay of acceptance, never a fresh remote verification.
    """
    locks = []
    require(set(sha256s) == {"build", "ordinary", "imports"}, "Three trusted lock hashes required")
    for name, path, schema in [
        ("build", build, "pobr-build-data-lock/v2"),
        ("ordinary", ordinary, "pobr-ordinary-input-lock/v2"),
        ("imports", imports, "pobr-data-import-lock/v1"),
    ]:
        raw = read_metadata(path)
        require(isinstance(sha256s[name], str) and SHA.fullmatch(sha256s[name]), "Invalid trusted lock sha256")
        require(pin(raw)["sha256"] == sha256s[name], "Accepted lock SHA mismatch")
        lock = decode(raw)
        require(isinstance(lock, dict) and lock.get("schema") == schema, "Wrong accepted lock schema")
        target(lock.get("target"))
        locks.append(lock)
    b, o, i = locks
    require(b["target"] == o["target"] == i["target"], "Accepted lock target mismatch")
    try:
        result = {
            "target": b["target"],
            "inputs": {
                "game": b["packages"]["game"],
                "crafting": b["crafting"],
                "ordinary": o["packages"]["repoe"],
                "display_source": i["packages"]["repoe"],
                "source_verifier": o["source_verifier"],
                "test_fixtures": b["test_fixtures"],
            },
        }
    except KeyError as error:
        raise ValueError(f"Missing accepted role: {error}") from error
    validate_accepted(result)
    return result


def atomic_write(path, raw, *, replace=True):
    path = safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        safe_path(path)
        if replace:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def bootstrap(accepted, destination):
    """Write sequence 1 from completed accepted records, without producing data."""
    validate_accepted(accepted)
    value = {
        "schema": "owned-data-publication/v2",
        "owner": OWNER,
        "target": accepted["target"],
        "sequence": 1,
        "previous": None,
        "scope": SCOPE,
        "components": {r: {"sequence": 1, "input": accepted["inputs"][r]} for r in sorted(ROLES)},
    }
    validate_descriptor(value, accepted)
    destination = safe_path(destination)
    require(not destination.exists(), "Descriptor already exists")
    atomic_write(destination, encoded(value), replace=False)
    return value


def git_blob(repo, expected):
    """Read only the exact local small regular blob; missing objects never fetch."""
    descriptor_pin(expected)
    repo = safe_path(repo)

    def git(*args):
        result = subprocess.run(
            ["git", "--no-lazy-fetch", "--no-replace-objects", "-C", str(repo), *args], capture_output=True, check=False
        )
        require(result.returncode == 0, "Missing/invalid local Git metadata")
        return result.stdout

    require(git("cat-file", "-t", expected["revision"]).strip() == b"commit", "Revision must be a local commit")
    listing = git("ls-tree", "-z", expected["revision"], "--", expected["path"]).split(b"\0")
    require(len(listing) == 2 and listing[0], "Missing exact Git descriptor")
    metadata, name = listing[0].split(b"\t", 1)
    mode, kind, oid = metadata.split()
    require(
        mode == b"100644" and kind == b"blob" and name.decode() == expected["path"],
        "Non-regular/symlink Git descriptor",
    )
    require(int(git("cat-file", "-s", oid.decode())) == expected["bytes"], "Git descriptor size mismatch")
    raw = git("cat-file", "blob", oid.decode())
    require(pin(raw) == {k: expected[k] for k in ("bytes", "sha256")}, "Git descriptor pin mismatch")
    return raw


def transition(previous, current):
    require(
        previous["owner"] == current["owner"]
        and all(previous["target"][k] == current["target"][k] for k in ("game", "realm")),
        "Predecessor owner/target mismatch",
    )
    require(current["sequence"] == previous["sequence"] + 1, "Publication sequence rollback/gap")
    changed = False
    for role in ROLES:
        old, new = previous["components"][role], current["components"][role]
        differs = encoded(old["input"]) != encoded(new["input"])
        require(new["sequence"] == old["sequence"] + int(differs), "Role sequence rollback/reuse/content mismatch")
        changed |= differs
    require(changed, "No new role input to register")


def read_chain(repo, head):
    seen, chain = set(), []
    while head is not None:
        require(len(chain) < 1024, "Predecessor chain limit exceeded")
        identity = encoded(head)
        require(identity not in seen, "Predecessor cycle")
        seen.add(identity)
        value = validate_descriptor(decode(git_blob(repo, head)))
        release_channel = f"{value['target']['game']}-{value['target']['realm']}"
        expected_path = f"publication/releases/{release_channel}/{value['sequence']}.json"
        require(head["path"] == expected_path, "Wrong descriptor release path")
        if chain:
            transition(value, chain[-1][1])
        chain.append((head, value))
        head = value["previous"]
    return chain


def validate_index(value, repo, accepted=None):
    require(isinstance(value, dict) and set(value) == {"schema", "channel", "sequence", "head"}, "Invalid index fields")
    require(value["schema"] == "owned-data-publication-index/v2", "Expected index v2")
    channel(value["channel"])
    positive(value["sequence"])
    chain = read_chain(repo, value["head"])
    require(chain, "Missing index head")
    current = chain[0][1]
    require(value["sequence"] == current["sequence"], "Index sequence mismatch")
    require(value["channel"] == {k: current["target"][k] for k in ("game", "realm")}, "Index channel mismatch")
    validate_descriptor(current, accepted)
    return current


def register(repo, head, index_path, accepted, *, expected_index_sha256=None):
    """Atomically register an already committed descriptor against accepted inputs.

    Existing indexes require compare-and-swap with the caller's frozen SHA-256.
    The cooperative lock serializes writers; failures never write a success index.
    """
    validate_accepted(accepted)
    descriptor_pin(head)
    index_path = safe_path(index_path)
    chain = read_chain(repo, head)
    current = validate_descriptor(chain[0][1], accepted)
    candidate = {
        "schema": "owned-data-publication-index/v2",
        "channel": {k: current["target"][k] for k in ("game", "realm")},
        "sequence": current["sequence"],
        "head": head,
    }
    index_path.parent.mkdir(parents=True, exist_ok=True)
    lock = safe_path(index_path.with_name(index_path.name + ".lock"))
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise ValueError("Index registration already locked") from error
    try:
        os.close(fd)
        before = read_metadata(index_path) if index_path.exists() else None
        if before is None:
            require(expected_index_sha256 is None and current["sequence"] == 1, "Missing predecessor index")
        else:
            require(expected_index_sha256 == pin(before)["sha256"], "Index compare-and-swap mismatch")
            old = decode(before)
            validate_index(old, repo)
            if old["sequence"] == candidate["sequence"]:
                require(old == candidate, "Same sequence with different content")
                return candidate
            require(candidate["sequence"] == old["sequence"] + 1, "Index sequence rollback/gap")
            require(current["previous"] == old["head"], "Wrong index predecessor")
        latest = read_metadata(index_path) if index_path.exists() else None
        require(latest == before, "Index changed during registration")
        atomic_write(index_path, encoded(candidate))
        return candidate
    finally:
        lock.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("bootstrap", "validate", "register"))
    for name in ("build", "ordinary", "imports"):
        parser.add_argument(f"--{name}-lock", required=True, type=Path)
        parser.add_argument(f"--{name}-lock-sha256", required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--index", type=Path, default=Path("publication/index.json"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--descriptor-revision")
    parser.add_argument("--descriptor-path")
    parser.add_argument("--descriptor-bytes", type=int)
    parser.add_argument("--descriptor-sha256")
    parser.add_argument("--expected-index-sha256")
    args = parser.parse_args(argv)
    try:
        hashes = {n: getattr(args, f"{n}_lock_sha256") for n in ("build", "ordinary", "imports")}
        accepted = load_accepted_inputs(args.build_lock, args.ordinary_lock, args.imports_lock, sha256s=hashes)
        if args.operation == "bootstrap":
            require(args.out is not None, "bootstrap requires --out")
            result = bootstrap(accepted, args.out)
        elif args.operation == "validate":
            result = validate_index(decode(read_metadata(args.index)), args.repo, accepted)
        else:
            head = {k: getattr(args, f"descriptor_{k}") for k in ("revision", "path", "bytes", "sha256")}
            result = register(args.repo, head, args.index, accepted, expected_index_sha256=args.expected_index_sha256)
        print(
            json.dumps(
                {
                    "status": f"local-{args.operation}-complete",
                    "sequence": result["sequence"],
                    "fresh_remote_verification": False,
                    "data_production_performed": False,
                },
                sort_keys=True,
            )
        )
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, f"publication-index: {error}\n")


if __name__ == "__main__":
    main()
