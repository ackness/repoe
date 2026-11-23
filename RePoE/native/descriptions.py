"""Export byte-pinned, offline CSD branch facts without translation selection."""

import argparse
import json
from pathlib import Path
import sys

from RePoE.client import export_receipt
from RePoE.client.limits import MAX_RESOURCE, MAX_SELECTED_RAW
from RePoE.native import csd as native_csd
from RePoE.native import envelope
from RePoE.native.envelope import ROOT, _json, _publish, _read, _sha


MAX_FILES = 128


def _inputs(source_lock, source, raw, expected_source_lock_sha256):
    lock_bytes, selected = envelope.load_source_lock(
        source_lock,
        source,
        expected_source_lock_sha256,
        limit=1024 * 1024,
        read_fn=_read,
    )
    envelope.validate_source_identity(
        selected,
        identity_error="Explicit PoE2 patch/realm and acquisition declaration required",
        evidence_error="Invalid acquisition evidence fingerprint",
    )
    resources = selected.get("resources")
    envelope.validate_roots(resources, selected.get("roots"), max_files=MAX_FILES)
    verified, raw_root = envelope.verify_raw_resources(
        raw,
        resources,
        max_files=MAX_FILES,
        max_resource_bytes=MAX_RESOURCE,
        max_total_bytes=MAX_SELECTED_RAW,
        validate_name=native_csd.resource_path,
        read_fn=_read,
        fingerprint_error="Invalid CSD fingerprint",
        total_error="CSD inventory exceeds total raw byte limit",
        path_error="Raw CSD escapes input root or has symlink components",
        mismatch_error="Raw CSD identity mismatch",
    )
    return lock_bytes, selected, verified, raw_root


def _payloads(lock_bytes, selected, verified, source):
    files = {name: native_csd.parse_csd(name, data) for name, data in sorted(verified.items())}
    reachable = native_csd.validate_closure(files, selected["roots"])
    if reachable != files.keys():
        raise ValueError("Resource inventory has files outside selected literal include closure")
    descriptions = branches = 0
    languages = set()
    handler_names = set()
    diagnostics = []
    for path, file in files.items():
        for record_index, record in enumerate(file["records"]):
            if record["kind"] != "description":
                continue
            descriptions += 1
            for group_index, group in enumerate(record["groups"]):
                if group["declared_language"] is not None:
                    languages.add(group["declared_language"])
                branches += len(group["branches"])
                for branch_index, branch in enumerate(group["branches"]):
                    handler_names.update(item["name_raw"] for item in branch["quantifiers_lexical"])
                    for diagnostic in branch["template_syntax_diagnostics"]:
                        diagnostics.append(
                            {
                                **diagnostic,
                                "path": path,
                                "record": record_index,
                                "group": group_index,
                                "branch": branch_index,
                                "raw_span": branch["span"],
                                "disposition": "retained raw; no repair or formatter interpretation",
                            }
                        )
    document = {
        "format": "repoe-native-description-branches/v1",
        "roots": selected["roots"],
        "files": files,
        "language_policy": "Explicit lang tokens and implicit defaults only; no fallback or inferred language labels.",
        "selection_policy": "None; includes, suppressions, restrictions and branch order remain lexical facts.",
        "handler_policy": "Tokens only; no numeric or relational handler execution.",
    }
    payloads = {
        "descriptions.json": _json(document),
        "diagnostics.json": _json({"diagnostics": diagnostics}),
        "source-lock.json": lock_bytes,
    }
    summary = {
        "files": len(files),
        "descriptions": descriptions,
        "branches": branches,
        "explicit_languages": sorted(languages),
        "quantifier_names": sorted(handler_names),
        "diagnostics": len(diagnostics),
    }
    manifest = {
        "format": "repoe-native-descriptions/v1",
        "status": "partial-candidate",
        "production_ready": False,
        "source_identity": {
            "source": source,
            "source_lock_sha256": _sha(lock_bytes),
            "selected_source_sha256": _sha(_json(selected)),
            "game": selected["game"],
            "game_patch": selected["game_patch"],
            "realm": selected["realm"],
            "acquisition": selected["acquisition"],
            "raw_resources": {
                name: {"bytes": len(data), "sha256": _sha(data)} for name, data in sorted(verified.items())
            },
        },
        "producer": {
            path: _sha((ROOT / path).read_bytes())
            for path in [
                "RePoE/native/csd.py",
                "RePoE/native/descriptions.py",
                "RePoE/native/envelope.py",
                "pyproject.toml",
                "uv.lock",
            ]
        },
        export_receipt.FIELD: export_receipt.SCHEMA,
        "python_version": sys.version.split()[0],
        "summary": summary,
        "limits": [
            "Selected literal CSD closure only; not all-client translation coverage or source authentication.",
            "No effective branch, suppression, formatter, numerical unit or quality-scope policy is evaluated.",
            "International Simplified Chinese text is not CN-realm numerical or tooltip evidence.",
        ],
        "files": {name: {"bytes": len(data), "sha256": _sha(data)} for name, data in payloads.items()},
    }
    payloads["manifest.json"] = _json(manifest)
    return manifest, payloads


def create_candidate(*, source_lock, source, raw, out, expected_source_lock_sha256, rehearsal=False):
    """Build a new completion-last package under this source checkout's cache."""
    output = Path(out).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Refusing to replace an existing description candidate: {output}")
    cache = ROOT.resolve(strict=True) / ".cache"
    resolved = output.resolve()
    if resolved == cache or not resolved.is_relative_to(cache):
        raise ValueError("Description candidates must be beneath this checkout's .cache/")
    seal = export_receipt.begin(output, "RePoE.native.descriptions", rehearsal=rehearsal)
    lock_bytes, selected, verified, raw_root = _inputs(source_lock, source, raw, expected_source_lock_sha256)
    if resolved.is_relative_to(raw_root):
        raise ValueError("Description output cannot be inside raw input")
    manifest, payloads = _payloads(lock_bytes, selected, verified, source)
    _publish(output, raw_root, payloads, root=ROOT)
    seal(payloads["manifest.json"])
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-lock", required=True, type=Path)
    parser.add_argument("--expected-source-lock-sha256", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--raw", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    export_receipt.add_rehearsal_option(parser)
    args = parser.parse_args()
    try:
        result = create_candidate(**vars(args))
    except (ValueError, OSError, KeyError, TypeError, UnicodeError) as error:
        parser.exit(1, f"Native descriptions rejected: {error}\n")
    print(json.dumps({"format": result["format"], "summary": result["summary"], "production_ready": False}))


if __name__ == "__main__":
    main()
