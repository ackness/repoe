"""Derive an export lock from a byte-pinned acquisition lock without changing source claims."""

import argparse
import json
from pathlib import Path

from . import source_io as io
from . import sources as client


def create(*, source_lock, expected_source_lock_sha256, out, sources=None):
    raw = io.read_file(source_lock, 2 * io.MIB)
    if io.sha256(raw) != io.digest(expected_source_lock_sha256):
        raise ValueError("Source lock differs from external expected byte pin")
    lock = io.decode(raw)
    if (
        not isinstance(lock, dict)
        or type(lock.get("schema_version")) is not int
        or lock["schema_version"] != 1
        or not isinstance(lock.get("sources"), dict)
        or not lock["sources"]
    ):
        raise ValueError("Expected a nonempty acquisition source lock")
    selected = list(lock["sources"]) if sources is None else list(sources)
    if not selected or len(set(selected)) != len(selected) or set(selected) - lock["sources"].keys():
        raise ValueError("Select unique, existing acquisition sources")
    for name in lock["sources"]:
        try:
            source, digest = client.load_source(source_lock, name)
        except KeyError as error:
            raise ValueError(
                f"Acquisition source {name!r} is missing {error.args[0]!r}; pins and locations required"
            ) from error
        if digest != expected_source_lock_sha256:
            raise ValueError("Source lock changed during conversion")
        if name in selected:
            lock["sources"][name] = {
                **source,
                "resources": {
                    path: {"sha256": pin["sha256"], "bytes": pin["bytes"]} for path, pin in source["resources"].items()
                },
            }
    lock["sources"] = {name: source for name, source in lock["sources"].items() if name in selected}
    if io.read_file(source_lock, 2 * io.MIB) != raw:
        raise ValueError("Source lock changed during conversion")
    # Preserve insertion order, including the historical export-lock serialization.
    exported = (json.dumps(lock, ensure_ascii=False, indent=2) + "\n").encode()
    io.write_new(out, exported)
    return io.sha256(exported)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-lock", required=True, type=Path)
    parser.add_argument("--expected-source-lock-sha256", required=True)
    parser.add_argument("--source", action="append", dest="sources", help="Repeat to select sources; default: all")
    parser.add_argument("--out", required=True, type=Path, help="New export-lock file; existing files are refused")
    args = parser.parse_args(argv)
    try:
        digest = create(**vars(args))
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, f"client_export_lock: {error}\n")
    print(f"{args.out}: sha256 {digest}")


if __name__ == "__main__":
    main()
