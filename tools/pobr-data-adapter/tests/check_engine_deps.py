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
POBR_SOURCE = "git+https://github.com/ackness/pobr"
ALLOWED = {"pobr-data"}


def fail(message: str) -> SystemExit:
    return SystemExit(f"engine-deps: {message}")


def normal_pobr_crates() -> set[str]:
    out = subprocess.run(
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
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    lines = [line for line in out.splitlines() if line.strip()]
    if not lines or not lines[0].startswith("pobr-data-adapter "):
        raise fail(f"unexpected cargo tree output: {out[:200]!r}")
    return {line.split()[0] for line in lines if "github.com/ackness/pobr" in line}


def locked_pobr_sources() -> dict[str, str]:
    lock = tomllib.loads((ADAPTER / "Cargo.lock").read_text(encoding="utf-8"))
    return {
        package["name"]: package["source"]
        for package in lock.get("package", [])
        if package.get("source", "").startswith(POBR_SOURCE)
    }


def main() -> None:
    crates = normal_pobr_crates()
    if crates != ALLOWED:
        extra = sorted(crates - ALLOWED)
        missing = sorted(ALLOWED - crates)
        raise fail(
            "the normal dependency tree must contain exactly pobr-data among PoBR crates"
            f" (extra: {extra}, missing: {missing}); move engine crates to [dev-dependencies]"
        )
    sources = locked_pobr_sources()
    if len(set(sources.values())) != 1:
        listing = "\n".join(f"  {name}: {source}" for name, source in sorted(sources.items()))
        raise fail(f"PoBR crates in Cargo.lock must share one tag and commit:\n{listing}")
    (source,) = set(sources.values())
    print(f"engine-deps: normal PoBR dependency is pobr-data only; {len(sources)} PoBR crates at {source}")


if __name__ == "__main__":
    sys.exit(main())
