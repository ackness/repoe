"""Check that the adapter depends on PoBR only through ``pobr-data``.

The adapter produces data against PoBR's data contract, so its normal
(production) dependency tree may contain exactly one PoBR crate: ``pobr-data``.
Engine crates (``pobr-core``, ``pobr-gamedata``, ``pobr-item``, ``pobr-tree``)
are allowed only as dev-dependencies, for tests that check how the engine
consumes the produced data.

Every PoBR crate in ``Cargo.lock`` must also resolve to one source (one tag and
commit): mixed tags compile two copies of ``pobr-data`` whose types do not
match. Run after ``cargo test --locked`` so the git dependencies are fetched.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

ADAPTER = Path(__file__).resolve().parents[1]
SELF = "pobr-data-adapter"
ALLOWED = {"pobr-data"}


def is_pobr_crate(name: str) -> bool:
    # Match by name, not source URL, so a [patch] or path override of an engine
    # crate cannot slip past the check.
    return name.startswith("pobr-") and name != SELF


def fail(message: str) -> SystemExit:
    return SystemExit(f"engine-deps: {message}")


def normal_pobr_crates() -> set[str]:
    result = subprocess.run(
        [
            "cargo",
            "tree",
            "--locked",
            "--edges",
            "normal",
            "--target",
            "all",
            "--package",
            "pobr-data-adapter",
            "--prefix",
            "none",
            "--format",
            "{p}",
        ],
        cwd=ADAPTER,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise fail(f"cargo tree failed ({result.returncode}):\n{result.stderr.strip()}")
    out = result.stdout
    lines = [line for line in out.splitlines() if line.strip()]
    if not lines or not lines[0].startswith(f"{SELF} "):
        raise fail(f"unexpected cargo tree output: {out[:200]!r}")
    return {name for name in (line.split()[0] for line in lines[1:]) if is_pobr_crate(name)}


def locked_pobr_packages() -> list[tuple[str, str]]:
    """Every PoBR package in Cargo.lock as (name, source), duplicates kept."""
    lock = tomllib.loads((ADAPTER / "Cargo.lock").read_text(encoding="utf-8"))
    return sorted(
        (package["name"], package.get("source", "<path>"))
        for package in lock.get("package", [])
        if is_pobr_crate(package["name"])
    )


def main() -> None:
    crates = normal_pobr_crates()
    if crates != ALLOWED:
        extra = sorted(crates - ALLOWED)
        missing = sorted(ALLOWED - crates)
        raise fail(
            "the normal dependency tree must contain exactly pobr-data among PoBR crates"
            f" (extra: {extra}, missing: {missing}); move engine crates to [dev-dependencies]"
        )
    packages = locked_pobr_packages()
    names = [name for name, _ in packages]
    sources = {source for _, source in packages}
    if len(sources) != 1 or len(names) != len(set(names)):
        listing = "\n".join(f"  {name}: {source}" for name, source in packages)
        raise fail(f"PoBR crates in Cargo.lock must share one tag and commit, one copy each:\n{listing}")
    (source,) = sources
    print(f"engine-deps: normal PoBR dependency is pobr-data only; {len(packages)} PoBR crates at {source}")


if __name__ == "__main__":
    sys.exit(main())
