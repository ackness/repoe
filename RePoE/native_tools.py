"""Bind native decoding to reviewed Git bytes, including the bytes Python executes.

The pin is repository-owned, never taken from an installed wheel's RECORD or a
candidate manifest. A private import context avoids cached bytecode and already
loaded modules. This is not a sandbox against a hostile Python process or OS.
"""

from contextlib import contextmanager
import hashlib
import importlib.abc
import importlib.machinery
import importlib.metadata
import importlib.util
import io
import json
from pathlib import Path
import sys


PIN = Path(__file__).resolve().parents[1] / "schema/pypoe-sources.json"
REVISION = "66d1d7442c5718260e1a8efd24989d22987e91af"
URL = "https://github.com/repoe-fork/pypoe.git"


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _matches_origin(spec, expected):
    if spec is None or spec.origin is None:
        return False
    return Path(spec.origin).resolve(strict=True) == expected.resolve(strict=True)


def _sources(root, pin):
    paths = {path.relative_to(root).as_posix(): path for path in root.rglob("*.py")}
    if paths.keys() != pin.keys():
        raise ValueError("PyPoE source inventory differs from trusted Git pin")
    sources = {}
    for name, path in paths.items():
        if not path.resolve(strict=True).is_relative_to(root):
            raise ValueError(f"PyPoE source escapes installed package: {name}")
        raw = path.read_bytes()
        if _sha(raw) not in pin[name]:
            raise ValueError(f"PyPoE source differs from trusted Git pin: {name}")
        sources[name] = raw
    return sources


class _SourceLoader(importlib.abc.Loader):
    def __init__(self, path, raw, sources):
        self.path, self.raw, self.sources = path, raw, sources

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        # Compile the verified buffer, never a timestamp-valid or sourceless pyc.
        module.__file__ = str(self.path)
        if module.__name__ == "PyPoE.poe.file.specification.generation.import_dat_schema":
            # The converter reads template.py as data before exec'ing generated
            # Python. Bind that read to the same verified buffer as its imports.
            template = self.path.with_name("template.py")

            def pinned_open(file, mode="r", *args, **kwargs):
                if Path(file) != template or mode != "r" or args or kwargs:
                    raise ValueError("Unexpected native converter file access")
                return io.StringIO(self.sources["poe/file/specification/generation/template.py"].decode("utf-8"))

            module.open = pinned_open
        exec(compile(self.raw, str(self.path), "exec", dont_inherit=True), module.__dict__)


class _Finder(importlib.abc.MetaPathFinder):
    def __init__(self, root, sources):
        self.root, self.sources = root, sources

    def find_spec(self, fullname, path=None, target=None):
        if fullname != "PyPoE" and not fullname.startswith("PyPoE."):
            return None
        relative = fullname.replace(".", "/").removeprefix("PyPoE").lstrip("/")
        package = f"{relative}/__init__.py" if relative else "__init__.py"
        name = package if package in self.sources else relative + ".py"
        if name not in self.sources:
            raise ValueError(f"PyPoE module is outside the native tool pin: {fullname}")
        expected = self.root / name
        resolved = importlib.machinery.PathFinder.find_spec(fullname, path)
        if not _matches_origin(resolved, expected):
            raise ValueError(f"PyPoE import path differs from pinned installation: {fullname}")
        return importlib.util.spec_from_file_location(
            fullname,
            expected,
            loader=_SourceLoader(expected, self.sources[name], self.sources),
            submodule_search_locations=[str(expected.parent)] if name == package else None,
        )


def _is_pypoe(name):
    return name == "PyPoE" or name.startswith("PyPoE.")


@contextmanager
def pinned_pypoe():
    """Use verified sources for this synchronous native operation, then restore imports.

    Preloaded PyPoE objects and their bytecode are never used. Callers must not
    import/use PyPoE concurrently in other threads during this operation.
    """
    sys.dont_write_bytecode = True
    pin_bytes = PIN.read_bytes()
    pin = json.loads(pin_bytes)
    package = importlib.metadata.distribution("PyPoE")
    installed = json.loads(package.read_text("direct_url.json") or "{}")
    if (
        pin["revision"] != REVISION
        or installed.get("vcs_info", {}).get("commit_id") != REVISION
        or installed.get("url") != URL
        or installed.get("dir_info", {}).get("editable")
    ):
        raise ValueError("Installed PyPoE differs from the noneditable Git pin")
    root = Path(package.locate_file("PyPoE")).resolve(strict=True)
    resolved = importlib.machinery.PathFinder.find_spec("PyPoE")
    if not _matches_origin(resolved, root / "__init__.py"):
        raise ValueError("PyPoE import path differs from pinned installation")
    sources = _sources(root, pin["sources"])
    previous = {name: module for name, module in sys.modules.copy().items() if _is_pypoe(name)}
    finder = _Finder(root, sources)
    try:
        for name in previous:
            del sys.modules[name]
        sys.meta_path.insert(0, finder)
        yield {"pin_sha256": _sha(pin_bytes), "sources": {name: _sha(raw) for name, raw in sources.items()}}
        if PIN.read_bytes() != pin_bytes or _sources(root, pin["sources"]) != sources:
            raise ValueError("Pinned PyPoE inputs changed during native operation")
    finally:
        sys.meta_path.remove(finder)
        for name in list(sys.modules):
            if _is_pypoe(name):
                del sys.modules[name]
        sys.modules.update(previous)
