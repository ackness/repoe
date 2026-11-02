"""Check that a published game package's keystone rules match its passive tree.

PoBR reads ``generated/special_derived.json`` from the RePoE game package. The
file is derived from the same package's ``base/passive_tree.json`` by
``pobr-data-adapter --emit-special-derived``. This check rebuilds it in a
temporary directory and compares bytes; it never writes into the checkout.

By default the package is the ``game`` input of the descriptor that
``publication/index.json`` names as head, so advancing the index to a new
release makes CI check the new package. ``--pin`` checks a candidate package
before it is published. Either way the package is addressed by Git commit,
path, byte count and SHA-256, and its ``handoff/<name>`` tag on ``origin`` must
peel to that commit. A shallow checkout fetches only the commits it needs.
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
INDEX = ROOT / "publication" / "index.json"
TREE = re.compile(r"^data/([^/]+)/base/passive_tree\.json$")
HANDOFF = re.compile(r"^(handoff/[A-Za-z0-9._-]+)/")

sys.path.insert(0, str(ROOT))
from RePoE.publication_index import decode, git_blob, read_metadata, validate_descriptor  # noqa: E402


def fail(message: str) -> SystemExit:
    return SystemExit(f"keystones: {message}")


def git(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True).stdout


def ensure_commit(revision: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise fail(f"revision must be a 40-character commit: {revision!r}")
    if subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", f"{revision}^{{commit}}"]).returncode:
        git("fetch", "--quiet", "--depth=1", "--no-tags", "origin", revision)


def published_game_package() -> tuple[dict, str]:
    index = decode(read_metadata(INDEX))
    if not isinstance(index, dict) or index.get("schema") != "owned-data-publication-index/v2":
        raise fail(f"{INDEX.relative_to(ROOT)} is not an owned-data-publication-index/v2")
    head = index["head"]
    ensure_commit(head["revision"])
    descriptor = validate_descriptor(decode(git_blob(ROOT, head)))
    if descriptor["sequence"] != index["sequence"]:
        raise fail("index sequence differs from its head descriptor")
    game = descriptor["components"]["game"]["input"]
    source = f"{head['path']} (sequence {descriptor['sequence']})"
    return {k: game[k] for k in ("revision", "path", "bytes", "sha256")}, source


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
    ensure_commit(pin["revision"])
    raw = git("cat-file", "blob", f"{pin['revision']}:{pin['path']}")
    digest = hashlib.sha256(raw).hexdigest()
    if len(raw) != pin["bytes"] or digest != pin["sha256"]:
        raise fail(f"package differs from pin ({len(raw)} B, {digest})")
    return raw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--pin",
        type=Path,
        help="candidate package JSON {revision, path, bytes, sha256[, tag]} (default: the published game input)",
    )
    parser.add_argument("--adapter", type=Path, help="prebuilt pobr-data-adapter binary (default: cargo run --locked)")
    args = parser.parse_args()

    if args.pin:
        pin, source = json.loads(args.pin.read_text(encoding="utf-8")), str(args.pin)
    else:
        pin, source = published_game_package()
    tag = check_tag(pin)
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

    label = f"{pin['path']} @ {pin['revision'][:12]} (tag {tag}, from {source})"
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
