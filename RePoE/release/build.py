"""Rebuild the PoBR game part from pinned inputs and classify every member.

Inputs are handoff packages addressed by commit, path, bytes and SHA-256 and
read from local Git objects; ``--fetch`` fetches a missing pinned commit from
``origin`` (never the game CDN). Producers are the adapter domains and the
Python projections declared in ``release/<patch>/domains.json``. Every other
member is copied from a package named in ``frozen-inputs.json``. The result is
``game-build-part.zip`` plus ``receipt.json`` (how it was built) and
``package.json`` (what was built) under ``.cache/release/``.

Each member has a provenance: ``generated`` (a producer derived it),
``passthrough`` (a producer emitted the payload of one of its own inputs, or
the snapshot manifest carried template fields over) or ``frozen`` (copied).
Generated and passthrough members are further compared with the reference
package of the lock (``-identical``, ``-different``, ``-new``). See RELEASING.md.
"""

import argparse
import copy
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import zipfile

from RePoE import pobr_crafting_catalog, pobr_historical_trees, source_rebinding
from RePoE.data_publication import archive_manifest, decode, encoded, pin, pinned, relative, require

ROOT = Path(__file__).resolve().parents[2]
RELEASES = ROOT / "release"
CACHE = ROOT / ".cache" / "release"
ADAPTER_DIR = ROOT / "tools" / "pobr-data-adapter"
ADAPTER = ADAPTER_DIR / "target" / "release" / "pobr-data-adapter"
POLICIES = ADAPTER_DIR / "policies"
SCHEMAS = {
    "inputs.lock.json": "repoe-release-inputs/v1",
    "domains.json": "repoe-release-domains/v1",
    "frozen-inputs.json": "repoe-release-frozen-inputs/v1",
}
RECEIPT = "repoe-release-receipt/v1"
PACKAGE = "repoe-release-package/v1"
PART_SCHEMA = "pobr-build-data-part/v1"
FACTS_IDENTITIES = ("rebound", "original")
# Adapter file options and the SHA-256 option the adapter requires next to them.
# Directory options pin the directory's manifest.json.
PAIRED = {
    "--codec-source": "--codec-source-sha256",
    "--codec-policy": "--codec-policy-sha256",
    "--branch-codec": "--branch-codec-sha256",
    "--quality-policy": "--quality-policy-sha256",
    "--catalog-policy": "--catalog-policy-sha256",
    "--supplement": "--supplement-manifest-sha256",
    "--player-context": "--player-manifest-sha256",
    "--tree-reference": None,
    "--tree-descriptions": None,
    "--item-descriptions": None,
}
DIRECTORY_OPTIONS = {"--supplement", "--player-context"}
BUSINESS = ("base/", "overlay/", "generated/")
PROVENANCE = ("generated", "passthrough", "frozen")
CLASSES = tuple(f"{p}-{c}" for p in PROVENANCE[:2] for c in ("identical", "different", "new")) + ("frozen", "missing")
KINDS = {"adapter", "special-derived", "historical-trees", "crafting-catalog", "snapshot-manifest"}
CODE = (
    "RePoE/release/build.py",
    "RePoE/source_rebinding.py",
    "RePoE/source_io.py",
    "RePoE/data_publication.py",
    "RePoE/publication_index.py",
    "RePoE/pobr_historical_trees.py",
    "RePoE/pobr_crafting_catalog.py",
    "tools/pobr-data-adapter/Cargo.lock",
)
# Paths whose untracked files can change the build (sources, declarations, policies, toolchain pins).
PRODUCER_PATHS = ("RePoE", "release", "tools/pobr-data-adapter", "mise.toml", "mise.lock", "rust-toolchain.toml")


def runtime_encoded(value):
    """PoBR runtime JSON layout: insertion order, two-space indent, UTF-8, final newline."""
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def file_pin(path):
    digest, size = hashlib.sha256(), 0
    with open(path, "rb") as stream:
        while chunk := stream.read(1 << 20):
            digest.update(chunk)
            size += len(chunk)
    return {"bytes": size, "sha256": digest.hexdigest()}


def write_new(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)


def display(path):
    path = Path(path)
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)


def log(message):
    print(f"release:build: {message}", file=sys.stderr, flush=True)


# --- configuration -------------------------------------------------------------------------------


def patch_key(name):
    parts = name.split(".")
    return tuple(int(part) for part in parts) if all(part.isdigit() for part in parts) else None


def default_config(releases=RELEASES):
    """The highest game patch directory under ``release/`` (one per patch, named by the patch)."""
    patches = [p for p in Path(releases).iterdir() if (p / "inputs.lock.json").is_file()]
    invalid = sorted(p.name for p in patches if patch_key(p.name) is None)
    require(not invalid, f"Release directories must be named by game patch: {invalid}")
    require(patches, f"No release declaration under {display(releases)}; pass --config")
    return max(patches, key=lambda p: patch_key(p.name))


def load_config(config):
    config = Path(config).absolute()
    documents, pins = {}, {}
    for name, schema in SCHEMAS.items():
        raw = (config / name).read_bytes()
        document = decode(raw)
        require(document.get("schema") == schema, f"{name}: expected schema {schema}")
        documents[name], pins[name] = document, pin(raw)
    lock, domains, frozen = (documents[name] for name in SCHEMAS)
    target = lock["target"]
    require(set(target) == {"game", "game_patch", "realm"}, "Invalid target")
    require(
        config.parent != RELEASES or config.name == target["game_patch"],
        f"{display(config)} declares game patch {target['game_patch']}",
    )
    require(domains["target"] == target and frozen["target"] == target, "Config target mismatch")
    packages = lock["packages"]
    require(isinstance(packages, dict) and packages, "No input packages")
    for name, spec in packages.items():
        require(name.isidentifier(), f"Invalid package name: {name}")
        require(len(spec["revision"]) == 40 and len(spec["sha256"]) == 64, f"{name}: full revision/SHA-256 required")
        relative(spec["path"])
    require(lock["reference"] in packages, "Reference package must be a declared input")
    require(lock["facts"]["package"] in packages, "Facts package must be a declared input")
    seen = set()
    for job in domains["jobs"]:
        require(job.get("kind") in KINDS, f"Unknown job kind: {job.get('kind')}")
        require(isinstance(job.get("id"), str) and job["id"] not in seen, f"Invalid/duplicate job id: {job.get('id')}")
        seen.add(job["id"])
        if "passthrough" in job:
            require(
                isinstance(job["passthrough"], str) and job["passthrough"].strip(),
                f"{job['id']}: passthrough must state why the job carries input content over",
            )
        if job["kind"] == "adapter":
            require(job["facts"] in FACTS_IDENTITIES, f"{job['id']}: facts must be one of {FACTS_IDENTITIES}")
            require(set(job.get("options", {})) <= set(PAIRED), f"{job['id']}: unsupported adapter option")
        for member in job.get("outputs", {}).values():
            relative(member)
    require(frozen["source"] in packages, "Frozen bytes must come from a declared package")
    for member, entry in frozen["members"].items():
        relative(member)
        require(
            {"bytes", "sha256", "category", "origin", "reason", "exit"} <= set(entry),
            f"{member}: incomplete frozen declaration",
        )
    require(domains["manifest"]["mode"] in ("retain-if-identical", "fresh"), "Unknown manifest mode")
    return config, lock, domains, frozen, pins


# --- pinned inputs -------------------------------------------------------------------------------


def git(repo, *args, check=True, online=False):
    """Run Git; unless ``online``, a partial clone must not lazily fetch missing objects."""
    env = os.environ if online else {**os.environ, "GIT_NO_LAZY_FETCH": "1"}
    command = ["git", "--no-replace-objects", "-C", str(repo), *args]
    result = subprocess.run(command, capture_output=True, check=False, env=env)
    require(not check or result.returncode == 0, f"git {' '.join(args[:3])} failed: {result.stderr.decode().strip()}")
    return result


def tag_commit(repo, tag):
    result = git(repo, "rev-parse", "--quiet", "--verify", f"refs/tags/{tag}^{{commit}}", check=False)
    return result.stdout.decode().strip() if result.returncode == 0 else None


def verify_tag(repo, spec, fetch):
    """Check the lock's publication tag names the locked revision.

    A tag missing locally is fetched with ``--fetch``; otherwise it is
    reported as unverified rather than trusted.
    """
    tag = spec["tag"]
    commit = tag_commit(repo, tag)
    if commit is None and fetch:
        git(
            repo,
            "fetch",
            "--quiet",
            "--depth=1",
            "--no-tags",
            "origin",
            f"refs/tags/{tag}:refs/tags/{tag}",
            online=True,
        )
        commit = tag_commit(repo, tag)
    if commit is None:
        return "not-present-locally"
    require(commit == spec["revision"], f"Tag {tag} names {commit}, not the locked revision {spec['revision']}")
    return "verified"


def git_blob(repo, spec, fetch):
    """Read one regular blob of a pinned commit; fetch only that commit, only if asked."""
    present = git(repo, "cat-file", "-e", f"{spec['revision']}^{{commit}}", check=False).returncode == 0
    if not present:
        require(fetch, f"Missing local commit {spec['revision']} ({spec['path']}); rerun with --fetch")
        git(repo, "fetch", "--quiet", "--depth=1", "--no-tags", "origin", spec["revision"], online=True)
    listing = git(repo, "ls-tree", "-z", spec["revision"], "--", spec["path"]).stdout.split(b"\0")
    require(len(listing) == 2 and listing[0], f"Missing Git blob {spec['path']}")
    metadata, name = listing[0].split(b"\t", 1)
    mode, kind, oid = metadata.split()
    require(mode == b"100644" and kind == b"blob" and name.decode() == spec["path"], "Non-regular Git blob")
    return pinned(git(repo, "cat-file", "blob", oid.decode()).stdout, spec)


class Package:
    """An extracted, pinned zip; members are verified on every open."""

    def __init__(self, name, spec, raw, root, members, tag=None):
        self.name, self.spec, self.raw, self.root, self.members = name, spec, raw, root, members
        self.tag = tag

    def path(self, member):
        relative(member)
        require(member in self.members, f"{self.name}: no member {member}")
        return self.root / member

    def directory(self, prefix):
        relative(prefix)
        require(any(m.startswith(prefix + "/") for m in self.members), f"{self.name}: no directory {prefix}")
        return self.root / prefix

    def read(self, member):
        return pinned(self.path(member).read_bytes(), self.members[member])


def open_package(repo, name, spec, cache, fetch):
    raw = git_blob(repo, spec, fetch)
    tag = verify_tag(repo, spec, fetch) if "tag" in spec else None
    root = cache / "packages" / spec["sha256"]
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if "manifest" in spec:
            manifest_raw, manifest = archive_manifest(archive, spec)
            members = {"manifest.json": pin(manifest_raw), **manifest["files"]}
        else:
            members = {info.filename: pin(archive.read(info)) for info in archive.infolist()}
        require(set(members) == set(archive.namelist()), f"{name}: archive inventory differs from its manifest")
        if not (root / ".complete").is_file():
            shutil.rmtree(root, ignore_errors=True)
            stage = root.with_name(root.name + ".partial")
            shutil.rmtree(stage, ignore_errors=True)
            for member in sorted(members):
                write_new(stage / relative(member), archive.read(member))
            (stage / ".complete").write_text(spec["sha256"] + "\n")
            stage.rename(root)
    for member, expected in members.items():
        require(file_pin(root / member) == expected, f"{name}: cached member changed: {member}")
    return Package(name, spec, raw, root, members, tag)


def prepare_facts(package, spec, cache):
    """Verify the portable source envelope; return both facts identities it supports.

    ``rebound`` is the envelope's facts root. ``original`` is the same payload
    bytes with the original manifest and source lock that the envelope proves
    (``payload_byte_equivalence``); domains first produced before the F3 source
    lock correction embed that identity.
    """
    handoff_raw = package.read(spec["handoff"])
    handoff = decode(handoff_raw)
    archive = package.path(spec["archive"])
    root = cache / "facts" / handoff["archive"]["sha256"]
    if not (root / ".complete").is_file():
        shutil.rmtree(root, ignore_errors=True)
        stage = root.with_name(root.name + ".partial")
        shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir(parents=True)
        source_rebinding.verify(archive, handoff, stage / "source")
        original = stage / "original"
        shutil.copytree(stage / "source" / "facts", original)
        for name, provenance in (
            ("manifest.json", "original-manifest.json"),
            ("source-lock.json", "original-source-lock.json"),
        ):
            (original / name).unlink()
            shutil.copyfile(stage / "source" / "provenance" / provenance, original / name)
        (stage / ".complete").write_text(handoff["archive"]["sha256"] + "\n")
        stage.rename(root)
    roots = {
        "rebound": (root / "source" / "facts", handoff["facts_manifest"]),
        "original": (root / "original", handoff["original"]["manifest"]),
    }
    for identity, (facts, manifest_pin) in roots.items():
        require(file_pin(facts / "manifest.json") == manifest_pin, f"{identity} facts manifest changed")
        manifest = decode((facts / "manifest.json").read_bytes())
        for name, expected in manifest["files"].items():
            require(file_pin(facts / relative(name)) == expected, f"{identity} facts member changed: {name}")
    require(spec["identities"] == {k: v[1]["sha256"] for k, v in roots.items()}, "Facts identities differ from lock")
    return {"handoff": pin(handoff_raw), "archive": handoff["archive"], "roots": roots}


# --- jobs ----------------------------------------------------------------------------------------


class Context:
    def __init__(self, target, packages, facts, work, adapter, policies=POLICIES):
        self.target, self.packages, self.facts, self.work, self.adapter = target, packages, facts, work, adapter
        self.policies = Path(policies)
        self.outputs = {}  # job id -> {relative output: Path}
        self.members = {}  # package member -> (bytes, job id)
        self.inputs = {}  # input reference -> pin
        self.job_inputs = {}  # job id -> {input reference: Path} (files only)

    def resolve(self, ref, job, directory=False):
        """Return the local path of a declared input reference and record its pin."""
        if isinstance(ref, dict):
            path = materialize_policy(self, ref, job)
            key = f"{job['id']}:materialized:{path.name}"
        else:
            source, _, rest = ref.partition(":")
            if source == "policy":
                path = self.policies / relative(rest)
                require(path.is_file(), f"Missing policy {rest}")
            elif source == "job":
                producer, _, output = rest.partition(":")
                require(output in self.outputs.get(producer, {}), f"{job['id']}: no earlier output {rest}")
                path = self.outputs[producer][output]
            else:
                require(source in self.packages, f"Unknown input source in {ref}")
                package = self.packages[source]
                path = package.directory(rest) if directory else package.path(rest)
            key = ref
        self.inputs[key] = file_pin(path / "manifest.json") if directory else file_pin(path)
        if not directory:
            self.job_inputs.setdefault(job["id"], {})[key] = path
        return path


def pointer_parent(document, pointer):
    for key in pointer[:-1]:
        document = document[key]
    return document


def expand_template(value, bindings):
    """Expand ``{"$retained": "<dotted.key>"}`` with the retained binding values."""
    if isinstance(value, dict):
        if set(value) == {"$retained"}:
            key = value["$retained"]
            if key in bindings:
                return copy.deepcopy(bindings[key])
            current = bindings
            for part in key.split("."):
                current = current[part]
            return copy.deepcopy(current)
        return {key: expand_template(child, bindings) for key, child in value.items()}
    if isinstance(value, list):
        return [expand_template(child, bindings) for child in value]
    return value


def materialize_policy(ctx, spec, job):
    """Write a policy whose only change is the reviewed facts-manifest pointer.

    ``template`` policies first expand retained bindings. ``rebind`` replaces the
    original facts identity at the pointer with the job's facts identity; the
    original value must be exactly the envelope's original manifest.
    """
    source = ctx.resolve(spec["policy"], job)
    raw = source.read_bytes()
    if "bindings" in spec:
        raw = runtime_encoded(expand_template(decode(raw), decode(ctx.resolve(spec["bindings"], job).read_bytes())))
    if "rebind" in spec:
        document = decode(raw)
        parent, field = pointer_parent(document, spec["rebind"]), spec["rebind"][-1]
        original = ctx.facts["roots"]["original"][1]["sha256"]
        require(parent[field] == original, f"{job['id']}: policy pointer is not the original facts identity")
        parent[field] = ctx.facts["roots"][job["facts"]][1]["sha256"]
        raw = runtime_encoded(document)
    if "expect" in spec:
        require(pin(raw) == spec["expect"], f"{job['id']}: materialized policy differs from its declared pin")
    path = ctx.work / "policies" / job["id"] / PurePosixPath(spec["policy"].partition(":")[2]).name
    write_new(path, raw)
    return path


def run_adapter_job(ctx, job, out):
    facts_root, manifest_pin = ctx.facts["roots"][job["facts"]]
    command = [
        str(ctx.adapter),
        "--ordinary-facts",
        str(facts_root),
        "--facts-manifest-sha256",
        manifest_pin["sha256"],
        "--version",
        ctx.target["game_patch"],
        "--ordinary-domain",
        job["domain"],
        "--out",
        str(out),
    ]
    for flag, ref in job.get("options", {}).items():
        directory = flag in DIRECTORY_OPTIONS
        path = ctx.resolve(ref, job, directory=directory)
        command += [flag, str(path)]
        if PAIRED[flag]:
            command += [PAIRED[flag], file_pin(path / "manifest.json" if directory else path)["sha256"]]
    execute(command, ctx.work / "logs" / job["id"])
    receipt = decode((out / "producer-receipt.json").read_bytes())
    files = receipt["files"]
    business = {name for name in files if name.startswith(BUSINESS)}
    require(business == set(job["outputs"]), f"{job['id']}: adapter outputs {sorted(business)} != declared")
    for name in business:
        require(file_pin(out / name) == files[name], f"{job['id']}: output differs from its receipt: {name}")
    portable = portable_receipt(ctx, job, receipt, facts_root)
    return {name: out / name for name in business}, {"receipt": portable, "adapter": receipt.get("adapter")}


def portable_receipt(ctx, job, receipt, facts_root):
    """Pin the adapter receipt with its absolute facts root replaced by the facts identity.

    The adapter records the canonical path of ``--ordinary-facts``; that path
    depends on the checkout, so the release receipt pins a copy that names
    the identity (``facts:<identity>``, whose manifest pin the receipt holds)
    instead. The adapter's own file stays next to its outputs.
    """
    require(
        receipt.get("input", {}).get("root") == str(Path(facts_root).resolve()),
        f"{job['id']}: adapter receipt names another facts root",
    )
    portable = copy.deepcopy(receipt)
    portable["input"]["root"] = f"facts:{job['facts']}"
    raw = encoded(portable)
    path = ctx.work / "receipts" / f"{job['id']}.json"
    write_new(path, raw)
    return {"path": path.relative_to(ctx.work.parent).as_posix(), **pin(raw)}


def run_special_derived(ctx, job, out):
    tree = ctx.resolve(job["tree"], job)
    execute(
        [str(ctx.adapter), "--emit-special-derived", str(tree), "--out", str(out), "--patch", ctx.target["game_patch"]],
        ctx.work / "logs" / job["id"],
    )
    produced = out / ctx.target["game_patch"]
    outputs = {p.relative_to(produced).as_posix(): p for p in sorted(produced.rglob("*")) if p.is_file()}
    require(set(outputs) == set(job["outputs"]), f"{job['id']}: unexpected outputs {sorted(outputs)}")
    return outputs, {}


def run_historical_trees(ctx, job, out):
    """``publication:historical-trees`` projection applied to the pinned historical tree inputs."""
    policy = decode(ctx.resolve(job["policy"], job).read_bytes())
    require(policy.get("schema") == pobr_historical_trees.POLICY, f"{job['id']}: unsupported policy")
    require(set(job["trees"]) == set(policy["versions"]), f"{job['id']}: tree versions differ from policy")
    outputs, records = {}, {}
    for version, ref in sorted(job["trees"].items()):
        projected, records[version] = pobr_historical_trees.project(
            ctx.resolve(ref, job).read_bytes(), policy["versions"][version]
        )
        name = f"base/passive_trees/{version}.json"
        write_new(out / name, projected)
        outputs[name] = out / name
    require(set(outputs) == set(job["outputs"]), f"{job['id']}: outputs differ from declaration")
    return outputs, {"trees": {v: {k: r[k] for k in ("input", "output", "selectors")} for v, r in records.items()}}


def run_crafting_catalog(ctx, job, out):
    """``publication:crafting-catalog`` projection of the pinned crafting facts package."""
    package = ctx.packages[job["package"]]
    with zipfile.ZipFile(io.BytesIO(package.raw)) as archive:
        facts = pobr_crafting_catalog.facts_document(archive, package.spec, ctx.target)
    document, decisions = pobr_crafting_catalog.project(
        facts,
        source_manifest_sha256=package.spec["manifest"]["sha256"],
        facts_manifest_sha256=package.spec["input_manifest"]["sha256"],
        target=ctx.target,
    )
    ctx.inputs[f"{package.name}:crafting.json"] = package.members["crafting.json"]
    (name,) = job["outputs"]
    write_new(out / name, pobr_crafting_catalog.runtime_encoded(document))
    return {name: out / name}, {"summary": decisions["summary"]}


def execute(command, logs):
    logs.mkdir(parents=True, exist_ok=True)
    with (logs / "stdout.txt").open("wb") as stdout, (logs / "stderr.txt").open("wb") as stderr:
        process = subprocess.run(command, stdout=stdout, stderr=stderr, check=False)
    (logs / "command.json").write_bytes(encoded({"command": command, "exit_code": process.returncode}))
    if process.returncode:
        detail = (logs / "stderr.txt").read_text(errors="replace").strip().splitlines()[-1:] or ["no stderr"]
        raise ValueError(f"Producer failed ({process.returncode}): {detail[0]}; logs in {logs}")


RUNNERS = {
    "adapter": run_adapter_job,
    "special-derived": run_special_derived,
    "historical-trees": run_historical_trees,
    "crafting-catalog": run_crafting_catalog,
}


def json_payload(raw):
    """The decoded document without its ``_meta`` stamp, or None when it is not a JSON object."""
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, ValueError):
        return None
    return {k: v for k, v in value.items() if k != "_meta"} if isinstance(value, dict) else None


def carried_inputs(ctx, job, outputs):
    """Outputs whose bytes, or whose payload apart from ``_meta``, equal one of the job's own inputs.

    Such an output is not derived by the job; it is the input carried over (a
    pass-through), and the job must declare it (``passthrough``).
    """
    inputs = ctx.job_inputs.get(job["id"], {})
    raws = {key: path.read_bytes() for key, path in inputs.items()}
    payloads = {}
    carried = {}
    for member, raw in outputs.items():
        for key, source in raws.items():
            if raw == source:
                carried[member] = {"input": key, "carried": "verbatim"}
                break
        else:
            payload = json_payload(raw)
            if payload is None:
                continue
            for key, source in raws.items():
                if key not in payloads:
                    payloads[key] = json_payload(source)
                if payloads[key] == payload:
                    carried[member] = {"input": key, "carried": "payload-except-_meta"}
                    break
    return carried


def check_passthrough(job, carried):
    declared = "passthrough" in job
    require(
        not carried or declared,
        f"{job['id']}: outputs carry input content over without a passthrough declaration: {sorted(carried)}",
    )
    require(not declared or carried, f"{job['id']}: declared passthrough, but no output carries an input over")


def snapshot_manifest(ctx, job, members):
    """Re-pin the version snapshot manifest over the assembled members.

    Entries naming package members get the assembled bytes' SHA-256. Entries
    for files another owner ships (locale) keep the template's pins; they are
    reported as retained external pins. Every other top-level field is the
    template's, so the member is a pass-through of the template.
    """
    template = decode(ctx.resolve(job["template"], job).read_bytes())
    prefix = f"data/{ctx.target['game_patch']}/"
    require(template.get("poe_version") == ctx.target["game_patch"], f"{job['id']}: template version mismatch")
    own = {m[len(prefix) :] for m in members if m.startswith(prefix)}
    files, retained = {}, {}
    for name, digest in template["files"].items():
        if name in own:
            files[name] = sha256(members[prefix + name][0])
        else:
            require(name.startswith(tuple(job["external"])), f"{job['id']}: snapshot entry without a member: {name}")
            files[name] = retained[name] = digest
    missing = own - set(template["files"])
    require(not missing, f"{job['id']}: members missing from the snapshot template: {sorted(missing)}")
    template["files"] = files
    fields = sorted(set(template) - {"files", "poe_version"})
    carried = {}
    if fields or retained:
        carried[job["member"]] = {
            "input": job["template"],
            "carried": "template",
            "fields": fields,
            "retained_pins": len(retained),
            "regenerated_pins": len(files) - len(retained),
        }
    return runtime_encoded(template), {"retained_external_pins": retained}, carried


# --- assembly ------------------------------------------------------------------------------------


def write_zip(path, members):
    """The publication tools' archive convention; reproduces published zips byte for byte."""
    with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for member in sorted(members):
            info = zipfile.ZipInfo(member, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, members[member], compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def producer_identity(repo, adapter, config, config_pins):
    """The producer commit; dirty on any tracked change or any untracked file under the build's inputs."""
    head = git(repo, "rev-parse", "HEAD").stdout.decode().strip()
    tracked = git(repo, "status", "--porcelain", "--untracked-files=no").stdout.decode().splitlines()
    inputs = git(repo, "status", "--porcelain", "--untracked-files=all", "--", *PRODUCER_PATHS).stdout.decode()
    dirty = sorted({line[3:] for line in tracked + inputs.splitlines() if line})
    return {
        "repository": "ackness/repoe",
        "commit": head,
        "dirty": bool(dirty),
        "dirty_paths": dirty,
        "config": {display(config / name): value for name, value in config_pins.items()},
        "code": {name: file_pin(ROOT / name) for name in CODE},
        "adapter_binary": file_pin(adapter),
    }


def classify(members, reference, passthrough=()):
    """Class of every member: provenance (generated/passthrough/frozen) and comparison with the reference."""
    result, counts = {}, {}
    for member, (raw, origin) in sorted(members.items()):
        value = pin(raw)
        expected = reference.get(member)
        provenance = "passthrough" if member in passthrough else "generated"
        if origin == "frozen":
            kind = "frozen"
        elif expected is None:
            kind = f"{provenance}-new"
        else:
            kind = f"{provenance}-identical" if expected == value else f"{provenance}-different"
        entry = {"class": kind, **value, "producer": origin}
        if expected is not None and expected != value:
            entry["reference"] = expected
        result[member] = entry
        counts[kind] = counts.get(kind, 0) + 1
    for member in sorted(set(reference) - set(members) - {"manifest.json"}):
        result[member] = {"class": "missing", "reference": reference[member]}
        counts["missing"] = counts.get("missing", 0) + 1
    return result, counts


def provenance_counts(counts):
    totals = {}
    for kind, count in counts.items():
        if kind != "missing":
            group = kind.split("-", 1)[0]
            totals[group] = totals.get(group, 0) + count
    return {group: totals[group] for group in PROVENANCE if group in totals}


def fresh_manifest(target, files, receipt_pin, producer):
    return {
        "schema": PART_SCHEMA,
        "kind": "game",
        "target": target,
        "production_ready": False,
        "release_build": {"receipt": receipt_pin, "producer": {k: producer[k] for k in ("repository", "commit")}},
        "limits": [
            "Generated members come from the declared release producers; frozen members are copied from "
            "release/frozen-inputs.json with their recorded origin and exit condition.",
            "No source acceptance, gameplay certification, remote publication or consumer adoption is claimed.",
        ],
        "files": files,
    }


def build(
    config=None,
    out=None,
    adapter=ADAPTER,
    cache=CACHE,
    fetch=False,
    manifest_mode=None,
    repo=ROOT,
    policies=POLICIES,
):
    config, lock, domains, frozen, config_pins = load_config(config or default_config())
    target = lock["target"]
    name = f"{target['game']}-{target['realm']}-{target['game_patch']}"
    out = Path(out or cache / name).absolute()
    require(out.is_relative_to(ROOT / ".cache") or not out.is_relative_to(ROOT), "Output must be under .cache/")
    adapter = Path(adapter).absolute()
    require(adapter.is_file() and os.access(adapter, os.X_OK), f"Adapter binary not found: {adapter} (cargo build)")
    if out.exists():
        require((out / ".release-build").is_file(), f"Refusing to replace a non-release directory: {out}")
        shutil.rmtree(out)
    work = out / "work"
    work.mkdir(parents=True)
    (out / ".release-build").write_text("generated by RePoE.release.build\n")

    log(f"opening {len(lock['packages'])} pinned packages")
    packages = {key: open_package(repo, key, spec, cache / "inputs", fetch) for key, spec in lock["packages"].items()}
    log("verifying the portable facts envelope")
    facts = prepare_facts(packages[lock["facts"]["package"]], lock["facts"], cache / "inputs")
    ctx = Context(target, packages, facts, work, adapter, policies)
    prefix = f"data/{target['game_patch']}/"
    jobs, snapshot_job, passthrough = {}, None, {}
    for job in domains["jobs"]:
        if job["kind"] == "snapshot-manifest":
            snapshot_job = job
            continue
        log(f"job {job['id']}")
        (work / "jobs").mkdir(exist_ok=True)
        outputs, evidence = RUNNERS[job["kind"]](ctx, job, work / "jobs" / job["id"])
        ctx.outputs[job["id"]] = {name: path for name, path in outputs.items()}
        for output, member in job["outputs"].items():
            require(member not in ctx.members, f"{member} produced twice")
            ctx.members[member] = (outputs[output].read_bytes(), job["id"])
        carried = carried_inputs(ctx, job, {m: ctx.members[m][0] for m in job["outputs"].values()})
        check_passthrough(job, carried)
        passthrough.update(carried)
        jobs[job["id"]] = {
            "kind": job["kind"],
            **evidence,
            "outputs": {m: pin(ctx.members[m][0]) for m in job["outputs"].values()},
            **({"passthrough": carried} if carried else {}),
        }

    source = packages[frozen["source"]]
    for member, entry in frozen["members"].items():
        if member in ctx.members:
            raise ValueError(f"{member} is both generated and frozen")
        raw = source.read(member)
        require(pin(raw) == {"bytes": entry["bytes"], "sha256": entry["sha256"]}, f"Frozen bytes changed: {member}")
        ctx.members[member] = (raw, "frozen")

    if snapshot_job:
        member = snapshot_job["member"]
        require(member == prefix + "manifest.json" and member not in ctx.members, "Invalid snapshot member")
        raw, evidence, carried = snapshot_manifest(ctx, snapshot_job, ctx.members)
        check_passthrough(snapshot_job, carried)
        passthrough.update(carried)
        ctx.members[member] = (raw, snapshot_job["id"])
        jobs[snapshot_job["id"]] = {
            "kind": "snapshot-manifest",
            **evidence,
            "outputs": {member: pin(raw)},
            **({"passthrough": carried} if carried else {}),
        }

    reference = packages[lock["reference"]]
    reference_manifest = decode(reference.read("manifest.json"))
    classes, counts = classify(ctx.members, reference_manifest["files"], passthrough)
    files = {member: pin(raw) for member, (raw, _) in sorted(ctx.members.items())}
    producer = producer_identity(repo, adapter, config, config_pins)
    mode = manifest_mode or domains["manifest"]["mode"]
    identical = files == reference_manifest["files"]
    receipt = {
        "schema": RECEIPT,
        "target": target,
        "producer": producer,
        "inputs": {
            "packages": lock["packages"],
            "tags": {name: package.tag for name, package in packages.items() if package.tag},
            "facts": {
                "handoff": facts["handoff"],
                "archive": facts["archive"],
                "identities": {k: v[1] for k, v in facts["roots"].items()},
            },
            "files": dict(sorted(ctx.inputs.items())),
        },
        "jobs": jobs,
        "frozen": {
            "source": frozen["source"],
            "members": {m: e["category"] for m, e in sorted(frozen["members"].items())},
        },
        "members": classes,
        "summary": counts,
        "provenance": provenance_counts(counts),
        "reference": {"package": lock["reference"], "members_identical": identical},
    }
    # receipt.json is complete before the package exists, so a fresh manifest
    # inside the zip can pin it; package.json then pins the zip and receipt.
    receipt_raw = encoded(receipt)
    receipt_pin = {"path": "receipt.json", **pin(receipt_raw)}
    (out / "receipt.json").write_bytes(receipt_raw)
    if mode == "retain-if-identical" and identical:
        manifest_raw, manifest_class = reference.read("manifest.json"), "retained-reference-manifest"
    else:
        manifest = fresh_manifest(target, files, receipt_pin, producer)
        manifest_raw, manifest_class = encoded(manifest), "fresh-manifest"
    all_members = {member: raw for member, (raw, _) in ctx.members.items()}
    all_members["manifest.json"] = manifest_raw
    zip_path = out / "game-build-part.zip"
    write_zip(zip_path, all_members)
    package_pin = file_pin(zip_path)
    reference_spec = lock["packages"][lock["reference"]]
    outcome = {
        "schema": PACKAGE,
        "target": target,
        "receipt": receipt_pin,
        "manifest": {"class": manifest_class, **pin(manifest_raw)},
        "package": {
            "path": zip_path.name,
            **package_pin,
            "expanded_bytes": sum(len(raw) for raw in all_members.values()),
            "identical_to_reference": package_pin["sha256"] == reference_spec["sha256"],
            "reference": {k: reference_spec[k] for k in ("bytes", "sha256")},
        },
    }
    outcome_raw = encoded(outcome)
    (out / "package.json").write_bytes(outcome_raw)
    (out / "manifest.json").write_bytes(manifest_raw)
    (out / "SHA256SUMS").write_text(
        f"{package_pin['sha256']}  game-build-part.zip\n"
        f"{receipt_pin['sha256']}  receipt.json\n"
        f"{sha256(outcome_raw)}  package.json\n"
    )
    return out, receipt, outcome


def report(receipt, outcome):
    lines = []
    for kind in CLASSES:
        names = [m for m, e in receipt["members"].items() if e["class"] == kind]
        if names:
            lines.append(f"{kind}: {len(names)}")
            lines += [f"  {m}  ({receipt['members'][m].get('producer', '-')})" for m in names]
    counts = receipt["provenance"]
    lines.append("members: " + ", ".join(f"{counts[group]} {group}" for group in PROVENANCE if group in counts))
    package = outcome["package"]
    lines.append(f"manifest.json: {outcome['manifest']['class']}")
    lines.append(f"game-build-part.zip: {package['bytes']} bytes sha256 {package['sha256']}")
    lines.append(f"identical to reference package: {package['identical_to_reference']}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--config",
        type=Path,
        help="release declaration directory release/<patch> (default: the highest patch under release/)",
    )
    parser.add_argument("--out", type=Path, help="output directory under .cache/ (default .cache/release/<target>)")
    parser.add_argument("--adapter", type=Path, default=ADAPTER, help="built pobr-data-adapter binary")
    parser.add_argument("--cache", type=Path, default=CACHE, help="input extraction cache")
    parser.add_argument("--fetch", action="store_true", help="fetch missing pinned commits from origin (Git only)")
    parser.add_argument("--manifest", choices=["retain-if-identical", "fresh"], help="override the manifest mode")
    parser.add_argument("--check", action="store_true", help="exit 1 unless the zip equals the reference package")
    args = parser.parse_args(argv)
    try:
        out, receipt, outcome = build(args.config, args.out, args.adapter, args.cache, args.fetch, args.manifest)
    except (ValueError, KeyError, TypeError, OSError, zipfile.BadZipFile) as error:
        parser.exit(1, f"release:build: {error}\n")
    print(report(receipt, outcome))
    print(f"output: {out}")
    if args.check and not outcome["package"]["identical_to_reference"]:
        parser.exit(1, "release:build: package differs from the reference package\n")


if __name__ == "__main__":
    main()
