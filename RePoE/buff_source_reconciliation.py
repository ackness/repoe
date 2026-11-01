"""Check retained reference relocation against two exact, local Git source files.

This compares source evidence, not game semantics. Changed enclosing procedures
keep the compatibility guard closed even when all retained windows still match.
"""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from RePoE.data_publication import decode, pin, pinned, relative, require

SCHEMA = "repoe-retained-buff-source-reconciliation/v1"
REVISIONS = ("old", "new")


def segment(raw, spec):
    """Inclusive one-based lines; preserve every byte including line endings."""
    lines = raw.splitlines(keepends=True)
    start, end = spec["line_start"], spec["line_end"]
    require(type(start) is int and type(end) is int and 1 <= start <= end <= len(lines), "Invalid line range")
    return b"".join(lines[start - 1 : end])


def fnv1a64(raw):
    value = 0xCBF29CE484222325
    for byte in raw:
        value = ((value ^ byte) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"fnv1a64:{value:016x}"


def reference_hash(raw):
    # PoBR's legacy Rust str::lines().join("\n") recipe omits the final
    # terminator and normalizes CRLF. Cryptographic pins retain the raw bytes.
    return fnv1a64(b"\n".join(raw.splitlines()))


def windows(raw, needle):
    """Return all complete line windows, including overlapping occurrences."""
    lines, wanted = raw.splitlines(keepends=True), needle.splitlines(keepends=True)
    return [
        {"line_start": i + 1, "line_end": i + len(wanted)}
        for i in range(len(lines) - len(wanted) + 1)
        if lines[i : i + len(wanted)] == wanted
    ]


def comparison(old, new):
    if old == new:
        return "identical"
    # The sole insertion in the reviewed complete doActorMisc procedure. Do not
    # strip arbitrary comments, whitespace, Lua tokens, or numerical expressions.
    lines = old.splitlines(keepends=True)
    if b"".join(lines[:3] + [b"\t---@class Output\n"] + lines[3:]) == new:
        return "output-annotation-only"
    return "changed"


def git(root, *args):
    env = dict(os.environ, GIT_NO_REPLACE_OBJECTS="1", GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0")
    return subprocess.check_output(
        ["git", "--no-replace-objects", "-C", str(root), *args], env=env, stderr=subprocess.PIPE
    )


def read_sources(root, metadata):
    """Use immutable regular blobs, with neither checkout nor network fallback."""
    require(
        set(metadata["files"]) == {"Modules/CalcPerform.lua", "Modules/CalcDefence.lua"},
        "Only the two retained reference source files are supported",
    )
    result = {}
    for side in REVISIONS:
        revision = metadata["source"][side + "_commit"]
        require(isinstance(revision, str) and re.fullmatch(r"[0-9a-f]{40}", revision), "Full Git commit required")
        require(git(root, "cat-file", "-t", revision) == b"commit\n", "Source object must be a commit")
        for name, spec in metadata["files"].items():
            relative(name)
            path = str(relative(spec["git_path"]))
            require(path == "src/" + name, "Source path does not match vendor_ref.file")
            listing = git(root, "ls-tree", "-z", revision, "--", path)
            rows = listing.split(b"\0")
            require(len(rows) == 2 and not rows[1], "Missing or ambiguous Git source")
            attributes, actual_path = rows[0].split(b"\t", 1)
            mode, kind, oid = attributes.split()
            require(mode == b"100644" and kind == b"blob" and actual_path.decode() == path, "Regular Git blob required")
            result[side, name] = pinned(git(root, "cat-file", "blob", oid.decode()), spec[side])
    return result


def verify(metadata, definitions_raw, sources):
    require(metadata["schema"] == SCHEMA, "Unsupported reconciliation schema")
    require(metadata["semantics_verified"] is False, "Source evidence cannot certify semantics")
    pinned(definitions_raw, metadata["definitions"])
    definitions = decode(definitions_raw)
    require(
        definitions["_meta"]["vendor_commit"] == metadata["source"]["old_commit"], "Definition source commit mismatch"
    )
    require(
        set(sources) == {(side, name) for side in REVISIONS for name in metadata["files"]}, "Source inventory mismatch"
    )
    for (side, name), raw in sources.items():
        pinned(raw, metadata["files"][name][side])

    contexts = metadata["contexts"]
    context_results = {}
    for key, context in contexts.items():
        chunks = [pinned(segment(sources[side, context["file"]], context[side]), context[side]) for side in REVISIONS]
        if context["kind"] == "function":
            for chunk in chunks:
                lines = chunk.splitlines(keepends=True)
                require(lines[0].decode().rstrip("\n") == context["declaration"], "Context function start mismatch")
                require(lines[-1] == b"end\n" and b"end\n" not in lines[1:-1], "Incomplete context function")
        else:
            require(context["kind"] == "region", "Unknown context kind")
        result = comparison(*chunks)
        require(result == context["comparison"], f"Context comparison mismatch: {key}")
        context_results[key] = result

    buffs = definitions["buffs"]
    ids = [buff["id"] for buff in buffs]
    entries = metadata["entries"]
    require(len(set(ids)) == len(ids) and set(ids) == set(entries), "Definition/reference ID inventory mismatch")
    used_contexts = set()
    results = []
    for buff in buffs:
        key, ref = buff["id"], buff["vendor_ref"]
        entry = entries[key]
        name = entry["file"]
        require(name == ref["file"], f"Reference source file mismatch: {key}")
        require(
            {k: entry["old"][k] for k in ("line_start", "line_end", "segment_hash")}
            == {k: ref[k] for k in ref if k != "file"},
            f"Old definition reference mismatch: {key}",
        )
        chunks = [pinned(segment(sources[side, name], entry[side]), entry[side]) for side in REVISIONS]
        require(chunks[0] == chunks[1], f"Changed reference window: {key}")
        for side, chunk in zip(REVISIONS, chunks):
            require(reference_hash(chunk) == entry[side]["segment_hash"], f"Reference FNV mismatch: {key}")
        target = {k: entry["new"][k] for k in ("line_start", "line_end")}
        require(windows(sources["new", name], chunks[0]) == [target], f"Missing or ambiguous new window: {key}")
        local = contexts[entry["local_context"]]
        require(local["file"] == name, f"Local context file mismatch: {key}")
        for side in REVISIONS:
            require(
                local[side]["line_start"]
                <= entry[side]["line_start"]
                <= entry[side]["line_end"]
                <= local[side]["line_end"],
                f"Reference outside complete local context: {key}",
            )
        dependencies = entry["context_dependencies"]
        require(dependencies and entry["local_context"] in dependencies, f"Missing local context dependency: {key}")
        used_contexts.update(dependencies)
        changed = [dependency for dependency in dependencies if context_results[dependency] == "changed"]
        results.append(
            {
                "id": key,
                "window": "unique-byte-identical",
                "local_context": entry["local_context"],
                "local_comparison": context_results[entry["local_context"]],
                "changed_contexts": changed,
            }
        )
    require(used_contexts == set(contexts), "Unaccounted context inventory")
    unchanged = all(not item["changed_contexts"] for item in results)
    require(metadata["full_context_unchanged"] is unchanged, "Full context result mismatch")
    require(metadata["guard_eligible"] is unchanged, "Guard eligibility mismatch")
    return {
        "schema": SCHEMA,
        "evidence_verified": True,
        "definitions": pin(definitions_raw),
        "source": metadata["source"],
        "contexts": context_results,
        "entries": results,
        "full_context_unchanged": unchanged,
        "guard_eligible": unchanged,
        "semantics_verified": False,
    }


def check(metadata_path, metadata_sha256, definitions_path, source_git):
    raw = Path(metadata_path).read_bytes()
    require(pin(raw)["sha256"] == metadata_sha256, "Metadata SHA-256 mismatch")
    metadata = decode(raw)
    result = verify(metadata, Path(definitions_path).read_bytes(), read_sources(source_git, metadata))
    return {"metadata": pin(raw), **result}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--metadata-sha256", required=True, help="Trusted SHA-256 from the accepted RePoE commit")
    parser.add_argument("--defs", required=True)
    parser.add_argument("--source-git", required=True, help="Local Git repository containing both exact commits")
    parser.add_argument(
        "--evidence-only", action="store_true", help="Check evidence without requiring unchanged full context"
    )
    args = parser.parse_args(argv)
    try:
        result = check(args.metadata, args.metadata_sha256, args.defs, args.source_git)
    except (ValueError, KeyError, TypeError, AttributeError, IndexError, OSError, subprocess.SubprocessError) as error:
        print(f"Reconciliation evidence failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, indent=2))
    if not result["guard_eligible"] and not args.evidence_only:
        print("Changed procedural context: retained source compatibility guard remains closed.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
