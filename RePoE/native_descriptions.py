"""Export byte-pinned, offline CSD branch facts without translation selection."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from RePoE import native_csd


ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_FILES = 128


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _json(value):
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def _decode(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def bad_number(value):
        raise ValueError(f"Nonfinite JSON number: {value}")

    return json.loads(raw, object_pairs_hook=unique, parse_constant=bad_number)


def _read(path, limit):
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Expected regular input file: {path}")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"Input exceeds byte limit: {path}")
    return data


def _digest(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _inputs(source_lock, source, raw, expected_source_lock_sha256):
    lock_bytes = _read(Path(source_lock), 1024 * 1024)
    if not _digest(expected_source_lock_sha256) or _sha(lock_bytes) != expected_source_lock_sha256:
        raise ValueError("Source lock differs from external expected byte pin")
    lock = _decode(lock_bytes)
    if not isinstance(lock, dict) or type(lock.get("schema_version")) is not int or lock["schema_version"] != 1:
        raise ValueError("Unsupported source lock schema")
    selected = lock["sources"][source]
    if not isinstance(selected, dict):
        raise ValueError("Invalid selected source")
    acquisition = selected.get("acquisition")
    if (
        selected.get("kind") != "official-client-resource-candidate"
        or selected.get("game") != "poe2"
        or not isinstance(selected.get("game_patch"), str)
        or not selected["game_patch"]
        or selected.get("realm") not in {"international", "china"}
        or not isinstance(acquisition, dict)
        or acquisition.get("status") not in {"unreviewed-acquisition-draft", "reviewed-source-input"}
        or not isinstance(acquisition.get("evidence"), list)
        or not acquisition["evidence"]
    ):
        raise ValueError("Explicit PoE2 patch/realm and acquisition declaration required")
    for evidence in acquisition["evidence"]:
        if (
            not isinstance(evidence, dict)
            or set(evidence) != {"kind", "sha256"}
            or not isinstance(evidence["kind"], str)
            or not evidence["kind"]
            or not _digest(evidence["sha256"])
        ):
            raise ValueError("Invalid acquisition evidence fingerprint")
    resources = selected.get("resources")
    roots = selected.get("roots")
    if (
        not isinstance(resources, dict)
        or not 0 < len(resources) <= MAX_FILES
        or not isinstance(roots, list)
        or not roots
        or any(not isinstance(path, str) for path in roots)
        or len(set(roots)) != len(roots)
        or any(path not in resources for path in roots)
    ):
        raise ValueError("Explicit unique roots and bounded resource inventory required")
    raw_root = Path(raw).resolve(strict=True)
    if not raw_root.is_dir():
        raise ValueError("Raw input root is not a directory")
    verified = {}
    total = 0
    for name, fingerprint in resources.items():
        native_csd.resource_path(name)
        if (
            not isinstance(fingerprint, dict)
            or type(fingerprint.get("bytes")) is not int
            or not 0 < fingerprint["bytes"] <= MAX_FILE_BYTES
            or not _digest(fingerprint.get("sha256"))
        ):
            raise ValueError(f"Invalid CSD fingerprint: {name}")
        total += fingerprint["bytes"]
        if total > MAX_TOTAL_BYTES:
            raise ValueError("CSD inventory exceeds total raw byte limit")
        path = raw_root / name
        if not path.resolve(strict=True).is_relative_to(raw_root):
            raise ValueError(f"Raw CSD escapes input root: {name}")
        # Verify every path component, including symlinks pointing back inside.
        if any(parent.is_symlink() for parent in [path, *path.parents] if parent != raw_root.parent):
            raise ValueError(f"Raw CSD has symlink components: {name}")
        data = _read(path, fingerprint["bytes"])
        if {"bytes": len(data), "sha256": _sha(data)} != {key: fingerprint[key] for key in ["bytes", "sha256"]}:
            raise ValueError(f"Raw CSD identity mismatch: {name}")
        verified[name] = data
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
            for path in ["RePoE/native_csd.py", "RePoE/native_descriptions.py", "pyproject.toml", "uv.lock"]
        },
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


def _publish_windows(output, raw_root, payloads):
    """Lock directory ancestors against rename and reject Windows reparse points."""
    import ctypes
    from ctypes import wintypes

    root = ROOT.resolve(strict=True)
    relative = output.relative_to(root)
    if not relative.parts or relative.parts[0] != ".cache" or any(part in {".", ".."} for part in relative.parts):
        raise ValueError("Invalid cache output path")
    if output.resolve().is_relative_to(raw_root.resolve(strict=True)):
        raise ValueError("Description output cannot enter raw input directory")
    for name in payloads:
        if not name or Path(name).name != name or name in {".", ".."} or ":" in name:
            raise ValueError("Invalid publication payload name")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL

    class Attributes(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("tag", wintypes.DWORD)]

    handles = []

    def lock_directory(directory):
        # No FILE_SHARE_DELETE: held ancestors cannot be renamed or replaced.
        handle = kernel.CreateFileW(str(directory), 0x80000000, 0x3, None, 3, 0x02200000, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        handles.append(handle)
        info = Attributes()
        if not kernel.GetFileInformationByHandleEx(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not info.attributes & 0x10 or info.attributes & 0x400:
            raise ValueError("Publication ancestor is not a plain directory")

    try:
        # Lock from the volume root, so replacing a checkout ancestor also fails.
        for directory in reversed(root.parents):
            lock_directory(directory)
        lock_directory(root)
        directory = root
        for part in relative.parts[:-1]:
            directory /= part
            directory.mkdir(exist_ok=True)
            lock_directory(directory)
        output.mkdir()
        lock_directory(output)
        names = [name for name in payloads if name != "manifest.json"]
        if "manifest.json" in payloads:
            names.append("manifest.json")
        for name in names:
            with (output / name).open("xb") as stream:
                stream.write(payloads[name])
                stream.flush()
                os.fsync(stream.fileno())
    finally:
        for handle in reversed(handles):
            kernel.CloseHandle(handle)


def _publish(output, raw_root, payloads):
    """Anchor exclusive writes to directory handles; completion manifest is last."""
    if os.name == "nt":
        return _publish_windows(output, raw_root, payloads)
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        raise ValueError("Description publication requires POSIX directory-relative operations")
    root = ROOT.resolve(strict=True)
    relative = output.relative_to(root)
    if relative.parts[0] != ".cache" or any(part in {".", ".."} for part in relative.parts):
        raise ValueError("Invalid cache output path")
    raw_identity = os.stat(raw_root)
    handles = []
    identities = []

    def open_directory(path, *, parent=None, create=False):
        if create:
            try:
                os.mkdir(path, dir_fd=parent)
            except FileExistsError:
                pass
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        handles.append(fd)
        identity = os.fstat(fd)
        if (identity.st_dev, identity.st_ino) == (raw_identity.st_dev, raw_identity.st_ino):
            raise ValueError("Description output cannot enter raw input directory")
        return fd

    def check_namespace():
        for path, fd in identities:
            current, opened = os.stat(path, follow_symlinks=False), os.fstat(fd)
            if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
                raise ValueError("Description output namespace changed")

    try:
        parent = open_directory(root)
        path = root
        identities.append((path, parent))
        for part in relative.parts[:-1]:
            parent = open_directory(part, parent=parent, create=True)
            path = path / part
            identities.append((path, parent))
        check_namespace()
        os.mkdir(relative.name, dir_fd=parent)
        directory = open_directory(relative.name, parent=parent)
        identities.append((path / relative.name, directory))
        for name, data in payloads.items():
            check_namespace()
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=directory)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
        check_namespace()
    finally:
        for fd in reversed(handles):
            os.close(fd)


def create_candidate(*, source_lock, source, raw, out, expected_source_lock_sha256):
    """Build a new completion-last package under this source checkout's cache."""
    output = Path(out).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Refusing to replace an existing description candidate: {output}")
    cache = ROOT.resolve(strict=True) / ".cache"
    resolved = output.resolve()
    if resolved == cache or not resolved.is_relative_to(cache):
        raise ValueError("Description candidates must be beneath this checkout's .cache/")
    lock_bytes, selected, verified, raw_root = _inputs(source_lock, source, raw, expected_source_lock_sha256)
    if resolved.is_relative_to(raw_root):
        raise ValueError("Description output cannot be inside raw input")
    manifest, payloads = _payloads(lock_bytes, selected, verified, source)
    _publish(output, raw_root, payloads)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-lock", required=True, type=Path)
    parser.add_argument("--expected-source-lock-sha256", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--raw", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = create_candidate(**vars(args))
    except (ValueError, OSError, KeyError, TypeError, UnicodeError) as error:
        parser.exit(1, f"Native descriptions rejected: {error}\n")
    print(json.dumps({"format": result["format"], "summary": result["summary"], "production_ready": False}))


if __name__ == "__main__":
    main()
