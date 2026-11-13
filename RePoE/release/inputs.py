"""Package a patch's extracted inputs and publish them as the GitHub Release ``inputs/<patch>-<n>``.

Each ``--package NAME=DIR`` becomes one deterministic zip,
``repoe-input-<NAME>-<patch>.zip``: every regular file under ``DIR`` at its
relative path, plus a root ``manifest.json`` (``repoe-release-input/v1``)
pinning each file. A ``crafting`` package keeps its exporter's root manifest.
The bytes depend only on the files, never on timestamps,
the checkout or the commit. ``SHA256SUMS`` pins the zips. The command prints
(and stages as ``lock.json``) the ``inputs.lock.json`` package entries that
pin each zip as a Release asset, so ``release:build`` reads them by
``{repository, tag, asset, bytes, sha256}``.

Publishing works like ``release:publish``: without ``--yes`` nothing is
tagged, pushed or released (the zips are staged under
``.cache/release/publish/inputs-<game>-<realm>-<patch>/`` and the commands
printed); ``--yes`` refuses a dirty tree, a HEAD not on origin/master, a stray
local tag or a missing ``gh``, never gives a commit a second ``inputs/<patch>-*``
number, and resumes an interrupted publish (push, create, or finish a complete
draft). See RELEASING.md.

A candidate written by a native exporter must carry ``producer_receipt`` and
have its export receipt beside its directory (``RePoE.client.export_receipt``).
A receipt that says rehearsal or dirty, or names a commit that is not on
origin/master, is a listed problem and is never published.
"""

import argparse
from contextlib import contextmanager
import io
import os
from pathlib import Path
import re
import stat
import tempfile
import zipfile

from RePoE.client import export_receipt
from RePoE.release.pins import archive_manifest, decode, encoded, pin, regular, relative, require
from RePoE.release import build, crafting_catalog, publish

SCHEMA = "repoe-release-input/v1"
TAG_PREFIX = "inputs/"
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Exact output layout from the China capture procedure. Raw client resources have no place here.
CHINA_CANDIDATES = {
    "stat-descriptions/china": ("repoe-native-descriptions/v1", ("descriptions.json", "diagnostics.json")),
    "display-tables/default": ("repoe-native-tables/v1", ("tables.json",)),
    "display-tables/simplified-chinese": ("repoe-localized-tables/v1", ("tables.json",)),
}
CHINA_CAPTURE = {"capture/capture-receipt.json", "capture/request.json", "capture/SHA256SUMS"}
CHINA_MEMBERS = CHINA_CAPTURE | {
    f"{directory}/{member}"
    for directory, (_, payloads) in CHINA_CANDIDATES.items()
    for member in (*payloads, "source-lock.json", "manifest.json")
}
CANDIDATE_FORMATS = export_receipt.FORMATS | {crafting_catalog.FORMAT}


def asset_name(name, patch):
    return f"repoe-input-{name}-{patch}.zip"


def raise_error(error):
    raise error


def validate_china_text(files):
    """Allow only the complete derived layout, with candidates pinned by their own manifests."""
    # Each candidate's export receipt sits beside its directory; package() checks what it says.
    members = CHINA_MEMBERS | {export_receipt.receipt_name(directory) for directory in CHINA_CANDIDATES}
    for member in sorted(set(files) - members):
        raise ValueError(
            f"china_text: unexpected file {member}; only allowlisted derived text and receipts may be published"
        )
    for member in sorted(members - set(files)):
        raise ValueError(f"china_text: missing derived file {member}")

    def document(member):
        try:
            result = decode(files[member].read_bytes())
            require(isinstance(result, dict), "Expected a JSON object")
            return result
        except (ValueError, UnicodeError) as error:
            raise ValueError(f"china_text: invalid derived file {member}: {error}") from error

    for directory, (format_, payloads) in CHINA_CANDIDATES.items():
        member = f"{directory}/manifest.json"
        manifest = document(member)
        require(manifest.get("format") == format_, f"china_text: invalid candidate format in {member}")
        expected = {name: build.file_pin(files[f"{directory}/{name}"]) for name in (*payloads, "source-lock.json")}
        require(manifest.get("files") == expected, f"china_text: derived file pins differ in {member}")
    for member, schema in (
        ("capture/capture-receipt.json", "repoe-client-capture-receipt/v1"),
        ("capture/request.json", "repoe-client-capture-request/v1"),
    ):
        require(document(member).get("schema") == schema, f"china_text: invalid schema in {member}")


def collect(directory, package_name=None):
    """``{relative path: Path}`` of every regular file under ``directory``.

    Symlinks, special files, dot files and directories (e.g. a cache's
    ``.complete`` marker) and an unreadable directory refuse rather than
    silently changing the package.
    """
    root = Path(directory).absolute()
    require(root.is_dir() and not root.is_symlink(), f"{directory}: not a directory")
    files = {}
    for current, folders, names in os.walk(root, onerror=raise_error, followlinks=False):
        base = Path(current)
        for folder in folders:
            require(not (base / folder).is_symlink(), f"Symlinked directory in an input: {base / folder}")
            require(not folder.startswith("."), f"Dot directory in an input: {base / folder}")
        for item in names:
            path = base / item
            require(not item.startswith("."), f"Dot file in an input: {path}")
            require(stat.S_ISREG(path.lstat().st_mode), f"Not a regular file: {path}")
            name = path.relative_to(root).as_posix()
            relative(name)
            files[name] = path
    require(files, f"{directory}: no files")
    if package_name == "china_text":
        validate_china_text(files)
    require(
        package_name == "crafting" or "manifest.json" not in files,
        f"{directory}: manifest.json is reserved for the package manifest",
    )
    return dict(sorted(files.items()))


def validate_targets(archive, target, directory):
    """Check candidate identities, including the facts inside a historical envelope zip."""

    def check(raw, member):
        try:
            document = decode(raw)
        except (ValueError, UnicodeError) as error:
            raise ValueError(f"{member}: invalid JSON: {error}") from error
        if not isinstance(document, dict):
            return
        if document.get("format") not in CANDIDATE_FORMATS and "source_identity" not in document:
            return
        identity = document.get("source_identity")
        if not isinstance(identity, dict):
            identity = {}
        for key, expected in target.items():
            actual = identity.get(key)
            require(actual == expected, f"{member}: source_identity.{key}: expected {expected!r}, actual {actual!r}")

    def walk(archive, prefix):
        for member in archive.namelist():
            path = f"{prefix}{member}"
            if member.endswith("manifest.json"):
                check(archive.read(member), path)
            elif member.lower().endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(archive.read(member))) as nested:
                    walk(nested, f"{path}!")

    walk(archive, f"{Path(directory).absolute()}/")


def package(name, directory, target, out):
    """Write ``out/<asset>``; return its lock fields (asset, pins, manifest pin, expanded bytes) and export receipts."""
    require(NAME.fullmatch(name), f"Invalid input package name: {name!r} (it becomes the lock key)")
    files = collect(directory, name)
    pins = {member: build.file_pin(path) for member, path in files.items()}
    extra = {}
    if name == "crafting":
        require("manifest.json" in files, f"{directory}: crafting requires its exported manifest.json")
        manifest_raw = files["manifest.json"].read_bytes()
        manifest = decode(manifest_raw)
        extra = {
            "publication": "published",
            "producer": manifest["producer"],
            "input_manifest": manifest["input_package"]["manifest"],
        }
        source = Path(directory).absolute()
        sibling = source.with_name(export_receipt.receipt_name(source.name))
        if export_receipt.FIELD in manifest or sibling.exists() or sibling.is_symlink():
            extra["export_receipt"] = decode(regular(sibling).read_bytes())
    else:
        manifest_raw = encoded({"schema": SCHEMA, "name": name, "target": target, "files": pins})
    path = Path(out) / asset_name(name, target["game_patch"])
    build.write_zip(path, {**files, "manifest.json": manifest_raw})
    spec = {
        "asset": path.name,
        **build.file_pin(path),
        "manifest": pin(manifest_raw),
        "expanded_bytes": len(manifest_raw) + sum(p["bytes"] for n, p in pins.items() if n != "manifest.json"),
        **extra,
    }
    with zipfile.ZipFile(path) as archive:
        validate_targets(archive, target, directory)
        try:
            receipts = export_receipt.package_receipts(archive.namelist(), archive.read, export_receipt.FORMATS)
        except ValueError as error:
            raise ValueError(f"{name}: {error}") from error
        # The files must not have changed while they were read.
        if name == "crafting":
            crafting_catalog.facts_document(archive, {"repository": publish.REPOSITORY, **spec}, target)
            if "export_receipt" in spec:
                receipts["export_receipt"] = spec["export_receipt"]
        else:
            _, manifest = archive_manifest(archive, spec)
            for member, expected in manifest["files"].items():
                require(pin(archive.read(member)) == expected, f"{name}: {member} changed while packaging")
    return spec, receipts


def stage(packages, target, out, tag=None):
    """Package every ``{name: directory}`` into ``out/assets`` with ``SHA256SUMS``; no network or Git."""
    with staging(packages, target, out, tag) as staged:
        return staged


@contextmanager
def staging(packages, target, out, tag=None):
    """Keep the previous stage until the caller finishes validating its replacement."""
    out = Path(out)
    for directory in packages.values():
        source, target_dir = Path(directory).resolve(), out.resolve()
        require(not target_dir.is_relative_to(source), f"The stage {out} is inside the input {directory}")
        require(not source.is_relative_to(target_dir), f"The input {directory} is inside the stage {out}")
    if out.exists():
        require((out / publish.MARKER).is_file(), f"Refusing to replace a non-publish directory: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{out.name}-", dir=out.parent) as temporary:
        pending, previous = Path(temporary) / "pending", Path(temporary) / "previous"
        assets = pending / "assets"
        assets.mkdir(parents=True)
        (pending / publish.MARKER).write_text("generated by RePoE.release.inputs\n")
        specs, receipts = {}, {}
        for name, directory in sorted(packages.items()):
            specs[name], found = package(name, directory, target, assets)
            receipts.update({f"{name}:{member}": receipt for member, receipt in found.items()})
        pins = {spec["asset"]: {k: spec[k] for k in ("bytes", "sha256")} for spec in specs.values()}
        (assets / "SHA256SUMS").write_text(publish.sha256sums({name: value["sha256"] for name, value in pins.items()}))
        pins["SHA256SUMS"] = build.file_pin(assets / "SHA256SUMS")
        staged = {
            "directory": out,
            "assets": dict(sorted(pins.items())),
            "packages": specs,
            "target": target,
            "receipts": receipts,
        }
        if tag is not None:
            (pending / "release-notes.md").write_text(release_body(staged, tag))
            (pending / "tag-message.txt").write_text(tag_message(staged, tag))
            (pending / "lock.json").write_bytes(build.runtime_encoded(lock_entries(staged, tag)))
        if out.exists():
            out.rename(previous)
        try:
            pending.rename(out)
            yield staged
        except BaseException:
            if out.exists():
                out.rename(pending)
            if previous.exists():
                previous.rename(out)
            raise


def receipt_problems(repo, receipts):
    """Why the staged export receipts cannot be published: a rehearsal, a dirty checkout or unreviewed code."""
    problems = publish.unpublishable(receipts)
    commits = {}
    for name, receipt in receipts.items():
        commits.setdefault(receipt["producer"]["commit"], []).append(name)
    for commit, names in sorted(commits.items()):
        # Reviewed code is a commit of the published branch, which preflight has fetched.
        if status := publish.off_branch(repo, commit):
            reason = "is not on" if status == 1 else "cannot be checked against"
            problems.append(
                f"export commit {commit} {reason} {publish.REMOTE}/{publish.BRANCH} "
                f"({len(names)} receipts, e.g. {names[0]})"
            )
    return problems


def lock_entries(staged, tag, repository=publish.REPOSITORY):
    """The ``inputs.lock.json`` ``packages`` entries pinning the staged zips as Release assets."""
    return {name: {"repository": repository, "tag": tag, **spec} for name, spec in staged["packages"].items()}


def release_body(staged, tag):
    target = staged["target"]
    lines = [
        f"RePoE release inputs for {target['game']} {target['game_patch']} ({target['realm']}).",
        "",
        "Each zip holds one input package and a root `manifest.json` pinning its files "
        "(`repoe-release-input/v1`, or the crafting export's own manifest):",
        "",
    ]
    for name, spec in staged["packages"].items():
        lines.append(f"- `{spec['asset']}` ({name}): {spec['bytes']} bytes, SHA-256 `{spec['sha256']}`")
    lines += [
        "",
        "Pin them in `release/<patch>[-<n>]/inputs.lock.json` with these `packages` entries:",
        "",
        "```json",
        build.runtime_encoded(lock_entries(staged, tag)).decode().rstrip(),
        "```",
        "",
        "Generated by `mise run release:inputs`.",
        "",
    ]
    return "\n".join(lines)


def tag_message(staged, tag):
    target = staged["target"]
    sums = publish.sha256sums({n: v["sha256"] for n, v in staged["assets"].items() if n != "SHA256SUMS"})
    return f"RePoE release inputs {target['game_patch']} ({tag})\n\n{sums}"


def main(argv=None, runner=None):
    parser = argparse.ArgumentParser(
        prog="release:inputs", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--patch", required=True, help="game patch, e.g. 0.5.5.6")
    parser.add_argument("--game", default="poe2")
    parser.add_argument("--realm", default="international")
    parser.add_argument(
        "--package", action="append", required=True, metavar="NAME=DIR", help="an input package (repeatable)"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="stage and print the plan only (the default)")
    mode.add_argument("--yes", action="store_true", help="tag, push and create the GitHub Release")
    parser.add_argument("--repo", type=Path, default=build.ROOT, help=argparse.SUPPRESS)
    parser.add_argument("--stage", type=Path, default=publish.STAGE, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    run = runner or publish.default_runner(args.repo)
    target = {"game": args.game, "game_patch": args.patch, "realm": args.realm}
    try:
        require(build.config_key(args.patch) is not None and "-" not in args.patch, f"Invalid patch {args.patch!r}")
        packages = {}
        for item in args.package:
            name, separator, directory = item.partition("=")
            require(separator and directory and name not in packages, f"Use unique NAME=DIR packages: {item!r}")
            packages[name] = Path(directory)
        commit, problems, warnings = publish.preflight(args.repo)
        tags = publish.list_remote_tags(args.repo, prefix=TAG_PREFIX)
        decision = publish.plan(args.repo, args.patch, commit, tags, prefix=TAG_PREFIX)
        problems += decision["problems"]
        if args.yes and (problem := publish.gh_problem(run)):
            problems.append(problem)
        if args.yes and (problems or warnings):
            parser.exit(1, "release:inputs: refusing to publish:\n" + publish.bullets(problems + warnings))
        sequence = decision["sequence"]
        tag = publish.tag_name(args.patch, sequence if sequence is not None else "<n>", TAG_PREFIX)
        with staging(packages, target, args.stage / f"inputs-{args.game}-{args.realm}-{args.patch}", tag) as staged:
            directory = staged["directory"]
            steps, action = publish.release_steps(run, staged, tag, commit, decision["action"])
        problems += receipt_problems(args.repo, staged["receipts"])
    except (ValueError, KeyError, TypeError, OSError, zipfile.BadZipFile) as error:
        parser.exit(1, f"release:inputs: {error}\n")
    print(f"inputs.lock.json packages: {build.display(directory / 'lock.json')}")
    print(build.runtime_encoded(lock_entries(staged, tag)).decode(), end="")
    if steps is None:
        print(f"already published: {tag} names HEAD and its Release assets equal the staged ones")
        return
    publish.carry_out(parser, run, staged, tag, commit, steps, action, problems, warnings, args.yes)


if __name__ == "__main__":
    main()
