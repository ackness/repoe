"""Check that a published game package's keystone rules match its passive tree.

PoBR reads ``generated/special_derived.json`` from the RePoE game package. The
file is derived from the same package's ``base/passive_tree.json`` by
``pobr-data-adapter --emit-special-derived``. This check rebuilds it in a
temporary directory and compares bytes; it never writes into the checkout.

The package is addressed by Git commit, path, byte count and SHA-256 (see
``keystone-package.json``). A shallow checkout fetches only that commit.
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
PIN = ADAPTER / "tests" / "keystone-package.json"
TREE = re.compile(r"^data/([^/]+)/base/passive_tree\.json$")


def git(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True).stdout


def package_bytes(pin: dict) -> bytes:
    revision = pin["revision"]
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise SystemExit(f"keystones: revision must be a 40-character commit: {revision!r}")
    if subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", f"{revision}^{{commit}}"]).returncode:
        git("fetch", "--quiet", "--depth=1", "--no-tags", "origin", revision)
    raw = git("cat-file", "blob", f"{revision}:{pin['path']}")
    digest = hashlib.sha256(raw).hexdigest()
    if len(raw) != pin["bytes"] or digest != pin["sha256"]:
        raise SystemExit(f"keystones: package differs from pin ({len(raw)} B, {digest})")
    return raw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pin", type=Path, default=PIN, help="package pin JSON (default: %(default)s)")
    parser.add_argument("--adapter", type=Path, help="prebuilt pobr-data-adapter binary (default: cargo run --locked)")
    args = parser.parse_args()

    pin = json.loads(args.pin.read_text(encoding="utf-8"))
    with zipfile.ZipFile(io.BytesIO(package_bytes(pin))) as package:
        versions = sorted({m.group(1) for m in map(TREE.match, package.namelist()) if m})
        if len(versions) != 1:
            raise SystemExit(f"keystones: expected one data version in the package, found {versions}")
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

    if actual != expected:
        print(
            f"keystones: generated/special_derived.json differs from {pin['path']} @ {pin['revision'][:12]} "
            f"({len(actual)} B rebuilt, {len(expected)} B published)",
            file=sys.stderr,
        )
        return 1
    print(
        f"keystones: {pin['path']} @ {pin['revision'][:12]} ({version}): "
        f"special_derived.json byte-identical ({len(actual)} B, {hashlib.sha256(actual).hexdigest()[:12]})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
