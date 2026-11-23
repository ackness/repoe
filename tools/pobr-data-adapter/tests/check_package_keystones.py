"""Check that a published game package's keystone rules match its passive tree.

PoBR reads ``generated/special_derived.json`` from the RePoE game package. The
file is derived from the same package's ``base/passive_tree.json`` by
``pobr-data-adapter --emit-special-derived``. This check rebuilds it in a
temporary directory and compares bytes; it never writes into the checkout.

By default the package is the published game package for the ``current``
declaration named in ``release/ci.json``, derived from that declaration's
``expect.package`` pin, so updating ``release/ci.json`` to a newly published
release makes CI check the new package while newer unpublished declarations do
not displace it. ``--config`` checks another declaration's ``expect.package``
pin, and ``--pin`` checks a candidate package before it is published. A package
is a GitHub Release asset ``{repository, tag, asset, bytes, sha256}``
(downloaded anonymously and verified, see ``RePoE.release.assets``) or a Git
blob ``{revision, path, bytes, sha256}`` whose ``handoff/<name>`` tag on
``origin`` must peel to that commit; a shallow checkout fetches only the
commits it needs.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ADAPTER = Path(__file__).resolve().parents[1]
ROOT = ADAPTER.parents[1]
TREE = re.compile(r"^data/([^/]+)/base/passive_tree\.json$")
HANDOFF = re.compile(r"^(handoff/[A-Za-z0-9._-]+)/")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from RePoE.release import assets, build, ci_declarations, publish  # noqa: E402
from RePoE.release.pins import byte_pin, decode  # noqa: E402


def fail(message: str) -> SystemExit:
    return SystemExit(f"keystones: {message}")


def git(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True).stdout


def ensure_commit(revision: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise fail(f"revision must be a 40-character commit: {revision!r}")
    if subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", f"{revision}^{{commit}}"]).returncode:
        git("fetch", "--quiet", "--depth=1", "--no-tags", "origin", revision)


def published_game_package(config: Path | None = None, *, releases: Path | None = None) -> tuple[dict, str]:
    try:
        if config is None:
            releases_dir = Path(releases) if releases is not None else build.RELEASES
            config_dir = ci_declarations.current(releases_dir)
            kind = "current declaration"
        else:
            config_dir = Path(config).absolute()
            kind = "declaration"
        lock_path = config_dir / "inputs.lock.json"
        lock = decode(lock_path.read_bytes())
    except (ValueError, OSError) as error:
        raise fail(str(error)) from error

    rel_lock = lock_path.relative_to(ROOT).as_posix() if lock_path.is_relative_to(ROOT) else str(lock_path)
    if not isinstance(lock, dict) or lock.get("schema") != "repoe-release-inputs/v1":
        raise fail(f"{rel_lock} is not a repoe-release-inputs/v1 declaration")

    target = lock.get("target")
    if (
        not isinstance(target, dict)
        or set(target) != {"game", "game_patch", "realm"}
        or not isinstance(target.get("game_patch"), str)
    ):
        raise fail(f"{rel_lock} has invalid target")

    sequence = build.declared_sequence(config_dir, target)
    if sequence is None:
        raise fail(f"{config_dir.name!r} does not declare a valid sequence for game_patch {target['game_patch']!r}")

    expect = lock.get("expect")
    if not isinstance(expect, dict) or "package" not in expect:
        raise fail(f"{rel_lock} has no expect.package pin")
    package_pin = expect["package"]
    try:
        byte_pin(package_pin)
    except ValueError as error:
        raise fail(f"{rel_lock} has invalid expect.package pin: {error}") from error

    patch = target["game_patch"]
    pin = {
        "repository": publish.REPOSITORY,
        "tag": publish.tag_name(patch, sequence),
        "asset": publish.asset_name(patch),
        "bytes": package_pin["bytes"],
        "sha256": package_pin["sha256"],
    }
    try:
        assets.validate(pin)
    except ValueError as error:
        raise fail(f"{rel_lock} derived invalid release asset pin: {error}") from error

    source = f"{rel_lock} ({kind} {config_dir.name!r} expect.package)"
    return pin, source


def check_tag(pin: dict) -> str:
    match = HANDOFF.match(pin["path"])
    tag = pin.get("tag") or (match and match.group(1))
    if not tag or (match and tag != match.group(1)):
        raise fail(f"package path {pin['path']!r} must live under its handoff/<name> tag")
    refs = dict(
        reversed(line.split("\t"))
        for line in git("ls-remote", "origin", f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}").decode().splitlines()
    )
    peeled = refs.get(f"refs/tags/{tag}^{{}}") or refs.get(f"refs/tags/{tag}")
    if peeled != pin["revision"]:
        raise fail(f"origin tag {tag} points at {peeled}, not {pin['revision']}")
    return tag


def package_bytes(pin: dict) -> bytes:
    if assets.is_release(pin):
        try:
            return assets.fetch(pin, build.CACHE / "inputs", online=True)
        except ValueError as error:
            raise fail(str(error)) from error
    ensure_commit(pin["revision"])
    raw = git("cat-file", "blob", f"{pin['revision']}:{pin['path']}")
    digest = hashlib.sha256(raw).hexdigest()
    if len(raw) != pin["bytes"] or digest != pin["sha256"]:
        raise fail(f"package differs from pin ({len(raw)} B, {digest})")
    return raw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument(
        "--pin",
        type=Path,
        help=(
            "candidate package JSON {repository, tag, asset, bytes, sha256} or "
            "{revision, path, bytes, sha256[, tag]} (default: the published current game package from release/ci.json)"
        ),
    )
    source_group.add_argument(
        "--config",
        type=Path,
        help="release declaration directory whose expect.package pin should be checked (default: current in release/ci.json)",
    )
    parser.add_argument("--adapter", type=Path, help="prebuilt pobr-data-adapter binary (default: cargo run --locked)")
    args = parser.parse_args(argv)

    if args.pin:
        pin, source = json.loads(args.pin.read_text(encoding="utf-8")), str(args.pin)
    else:
        pin, source = published_game_package(args.config)
    tag = pin["tag"] if assets.is_release(pin) else check_tag(pin)
    with zipfile.ZipFile(io.BytesIO(package_bytes(pin))) as package:
        versions = sorted({m.group(1) for m in map(TREE.match, package.namelist()) if m})
        if len(versions) != 1:
            raise fail(f"expected one data version in the package, found {versions}")
        version = versions[0]
        tree = package.read(f"data/{version}/base/passive_tree.json")
        expected = package.read(f"data/{version}/generated/special_derived.json")

    with tempfile.TemporaryDirectory(prefix="pobr-keystones-") as tmp:
        tree_path = Path(tmp) / "passive_tree.json"
        tree_path.write_bytes(tree)
        out = Path(tmp) / "out"
        command = (
            [str(args.adapter)]
            if args.adapter
            else ["cargo", "run", "--locked", "--quiet", "--manifest-path", str(ADAPTER / "Cargo.toml"), "--"]
        )
        command += ["--emit-special-derived", str(tree_path), "--out", str(out), "--patch", version]
        subprocess.run(command, check=True)
        actual = (out / version / "generated" / "special_derived.json").read_bytes()

    where = pin["asset"] if assets.is_release(pin) else f"{pin['path']} @ {pin['revision'][:12]}"
    label = f"{where} (tag {tag}, from {source})"
    if actual != expected:
        print(
            f"keystones: generated/special_derived.json differs from {label} "
            f"({len(actual)} B rebuilt, {len(expected)} B published)",
            file=sys.stderr,
        )
        return 1
    print(
        f"keystones: {label}, {version}: special_derived.json byte-identical "
        f"({len(actual)} B, {hashlib.sha256(actual).hexdigest()[:12]})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
