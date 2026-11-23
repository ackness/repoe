"""Shared source-envelope validation, hashing, strict JSON and safe publication for native exporters."""

import hashlib
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
HEX_SHA256 = re.compile(r"[a-f0-9]{64}")
NUMERIC_PATCH = re.compile(r"[0-9]+(?:\.[0-9]+)+")
REALMS = frozenset({"international", "china"})
ACQUISITION_STATUSES = frozenset({"unreviewed-acquisition-draft", "reviewed-source-input"})


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def canonical_json(value):
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def decode_json(raw):
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


def is_digest(value):
    return isinstance(value, str) and HEX_SHA256.fullmatch(value) is not None


def pin(data):
    return {"bytes": len(data), "sha256": sha256(data)}


_sha = sha256
_json = canonical_json
_decode = decode_json
_digest = is_digest
read_bounded = _read


def load_source_lock(
    source_lock,
    source,
    expected_source_lock_sha256,
    *,
    limit=2 * 1024 * 1024,
    pin_error="Source lock differs from external expected byte pin",
    read_fn=None,
):
    """Read, externally authenticate, and strictly decode one entry from a v1 source lock."""
    reader = _read if read_fn is None else read_fn
    lock_bytes = reader(Path(source_lock), limit)
    if not is_digest(expected_source_lock_sha256) or sha256(lock_bytes) != expected_source_lock_sha256:
        raise ValueError(pin_error)
    lock = decode_json(lock_bytes)
    if not isinstance(lock, dict) or type(lock.get("schema_version")) is not int or lock["schema_version"] != 1:
        raise ValueError("Unsupported source lock schema")
    selected = lock["sources"][source]
    if not isinstance(selected, dict):
        raise ValueError("Invalid selected source")
    return lock_bytes, selected


def validate_acquisition(
    acquisition,
    *,
    statuses=ACQUISITION_STATUSES,
    strict_evidence_keys=True,
    identity_error="Explicit patch, realm and acquisition evidence required",
    evidence_error="Invalid acquisition evidence",
):
    """Validate an acquisition block and each evidence entry fingerprint."""
    if (
        not isinstance(acquisition, dict)
        or acquisition.get("status") not in statuses
        or not isinstance(acquisition.get("evidence"), list)
        or not acquisition["evidence"]
    ):
        raise ValueError(identity_error)
    for item in acquisition["evidence"]:
        if (
            not isinstance(item, dict)
            or (strict_evidence_keys and set(item) != {"kind", "sha256"})
            or not isinstance(item.get("kind"), str)
            or not item["kind"]
            or not is_digest(item.get("sha256"))
        ):
            raise ValueError(evidence_error)


def validate_source_identity(
    selected,
    *,
    numeric_patch=False,
    realms=REALMS,
    profile=None,
    statuses=ACQUISITION_STATUSES,
    strict_evidence_keys=True,
    identity_error="Explicit patch, realm and acquisition evidence required",
    evidence_error="Invalid acquisition evidence",
):
    """Validate explicit PoE2 candidate identity, patch/realm declaration, and acquisition evidence."""
    patch = selected.get("game_patch")
    if (
        selected.get("kind") != "official-client-resource-candidate"
        or selected.get("game") != "poe2"
        or (profile is not None and selected.get("profile") != profile)
        or not isinstance(patch, str)
        or not patch
        or (numeric_patch and NUMERIC_PATCH.fullmatch(patch) is None)
        or selected.get("realm") not in realms
    ):
        raise ValueError(identity_error)
    validate_acquisition(
        selected.get("acquisition"),
        statuses=statuses,
        strict_evidence_keys=strict_evidence_keys,
        identity_error=identity_error,
        evidence_error=evidence_error,
    )


def validate_decoder(selected, expected, *, error="Decoder/schema pin mismatch", include_key=False):
    """Require exact pinned decoder/schema fields on a selected source."""
    decoder = selected["decoder"]
    for key, value in expected.items():
        if decoder.get(key) != value:
            raise ValueError(f"{error}: {key}" if include_key else error)


def validate_roots(
    resources, roots, *, max_files, error="Explicit unique roots and bounded resource inventory required"
):
    """Validate a bounded resource dict paired with an explicit non-empty list of unique roots."""
    if (
        not isinstance(resources, dict)
        or not 0 < len(resources) <= max_files
        or not isinstance(roots, list)
        or not roots
        or any(not isinstance(path, str) or path not in resources for path in roots)
        or len(set(roots)) != len(roots)
    ):
        raise ValueError(error)


def verify_raw_resources(
    raw,
    resources,
    *,
    max_files,
    max_resource_bytes,
    max_total_bytes,
    min_files=1,
    validate_name=None,
    check_case_collision=False,
    check_raw_dir=True,
    sort_items=False,
    read_fn=None,
    inventory_error="Explicit bounded resource inventory required",
    case_collision_error="Case-colliding resources",
    fingerprint_error="Invalid raw fingerprint",
    total_error="Raw resource inventory exceeds byte bound",
    path_error="Raw resource escapes root or contains symlink",
    mismatch_error="Raw resource fingerprint mismatch",
):
    """Verify every pinned raw resource beneath ``raw`` against size, path, symlink and SHA-256 bounds."""
    if not isinstance(resources, dict) or not min_files <= len(resources) <= max_files:
        raise ValueError(inventory_error)
    raw_root = Path(raw).resolve(strict=True)
    if check_raw_dir and not raw_root.is_dir():
        raise ValueError("Raw input root is not a directory")
    reader = _read if read_fn is None else read_fn
    verified, total, seen = {}, 0, set()
    items = sorted(resources.items()) if sort_items else resources.items()
    for name, fingerprint in items:
        if validate_name is not None:
            validate_name(name)
        if check_case_collision:
            folded = name.casefold()
            if folded in seen:
                raise ValueError(case_collision_error)
            seen.add(folded)
        if (
            not isinstance(fingerprint, dict)
            or type(fingerprint.get("bytes")) is not int
            or not 0 < fingerprint["bytes"] <= max_resource_bytes
            or not is_digest(fingerprint.get("sha256"))
        ):
            raise ValueError(f"{fingerprint_error}: {name}")
        total += fingerprint["bytes"]
        if total > max_total_bytes:
            raise ValueError(total_error)
        path = raw_root / name
        # Verify every path component, including symlinks pointing back inside.
        if not path.resolve(strict=True).is_relative_to(raw_root) or any(
            parent.is_symlink() for parent in (path, *path.parents) if parent != raw_root.parent
        ):
            raise ValueError(f"{path_error}: {name}")
        data = reader(path, fingerprint["bytes"])
        if len(data) != fingerprint["bytes"] or sha256(data) != fingerprint["sha256"]:
            raise ValueError(f"{mismatch_error}: {name}")
        verified[name] = data
    return verified, raw_root


def _publish_windows(output, raw_root, payloads, *, root=None):
    """Lock directory ancestors against rename and reject Windows reparse points."""
    import ctypes
    from ctypes import wintypes

    root = (ROOT if root is None else Path(root)).resolve(strict=True)
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


def _publish(output, raw_root, payloads, *, root=None):
    """Anchor exclusive writes to directory handles; completion manifest is last."""
    if os.name == "nt":
        return _publish_windows(output, raw_root, payloads, root=root)
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        raise ValueError("Description publication requires POSIX directory-relative operations")
    root = (ROOT if root is None else Path(root)).resolve(strict=True)
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


publish = _publish
