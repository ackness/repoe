"""Read exactly six indexed dependency resources; never write the installation."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parent
NODE = r"C:\Users\10138\AppData\Local\mise\installs\node\26.12.1\node.exe"
INDEX_SHA = "1fa59396c8f9a57de082098ec024f680dd9218c78ca11497f7887032f54e1578"
READ_RULE = r"--allow-fs-read=C:\WeGameApps\rail_apps\流放之路：降临(2002052)\Bundles2\*"
phase = {"network": True, "subprocess": False}


def audit(event, args):
    if event == "open":
        mode, flags = args[1:3]
        writing = isinstance(mode, str) and any(c in mode for c in "wax+") or isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
        if writing and not (isinstance(args[0], int) and phase["subprocess"]):
            if not isinstance(args[0], (str, bytes, os.PathLike)) or not Path(os.fsdecode(args[0])).resolve().is_relative_to(ROOT):
                raise RuntimeError("Write outside independent dependency cache prohibited")
    if event.startswith("socket.") and not phase["network"]:
        raise RuntimeError("Network closed after fixed decoder fetch")
    if event == "subprocess.Popen" and not phase["subprocess"]:
        raise RuntimeError("Unplanned subprocess")
    if event in ("os.remove", "os.rename", "os.rmdir", "os.truncate", "os.system"):
        raise RuntimeError("Unneeded filesystem/process mutation")


sys.addaudithook(audit)
sha = lambda raw: hashlib.sha256(raw).hexdigest()
encoded = lambda value: (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
with urllib.request.urlopen("https://registry.npmjs.org/ooz-wasm/-/ooz-wasm-2.0.0.tgz", timeout=30) as response:
    package = response.read(2097153)
assert sha(package) == "9d620bfee0d4ec98f304c291a49af4cd5bafaa9b6a1ef6e9248808d2467d05fe"
with tarfile.open(fileobj=io.BytesIO(package), mode="r:gz") as archive:
    javascript = archive.extractfile("package/build/ooz.js").read()
assert sha(javascript) == "5aed30da1da505793fd1e3383db4572797bcce8a0e9e71176d1f6a5d60ec0e6c"
wasm = base64.b64decode(re.search(rb"data:application/octet-stream;base64,([A-Za-z0-9+/=]+)", javascript).group(1))
assert sha(wasm) == "be3ceea0fc7b4a9ea24715781ea55de9645964a8f2347a1b06c0c859a2eb4bcd"
phase["network"] = False
environment = dict(os.environ)
environment.update(NODE_OPTIONS="", NODE_DISABLE_COMPILE_CACHE="1")


def start(code):
    phase["subprocess"] = True
    try:
        return subprocess.Popen([NODE, "--permission", READ_RULE, "--expose-gc", "--max-old-space-size=192", "-e", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="strict", env=environment, creationflags=subprocess.CREATE_NO_WINDOW)
    finally:
        phase["subprocess"] = False


lookup = json.loads((ROOT / "lookup.json").read_bytes())
assert lookup["status"] == "completed", lookup.get("error")
assert lookup["index"]["stable"] and lookup["index"]["sha256"] == INDEX_SHA
items = []
for table in lookup["tables"]:
    default = table["default"]
    localized = [p for p in table["simplified_chinese"] if p["status"] == "present"]
    assert default["status"] == "present" and default["directory_confirmed"]
    assert len(localized) == 0, "Scope is the three default dependencies after exact SC absence observation"
    for locale, choice in [("default", default)]:
        items.append({"table": table["table"], "locale": locale, "path": choice["observed_exact_path"], "record": choice["record"]})
payload = {"wasm": base64.b64encode(wasm).decode("ascii"), "items": items, "expected_index": lookup["index"], "script": (ROOT / "extractor.js").read_text(encoding="utf-8")}
process = start('const d=JSON.parse(require("node:fs").readFileSync(0,"utf8"));new Function("require","data",d.script)(require,d);')
process.stdin.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))
process.stdin.close()
observations = []
receipt = None
for line in process.stdout:
    entry = json.loads(line)
    if entry["kind"] == "resource":
        raw = base64.b64decode(entry.pop("base64"), validate=True)
        assert len(raw) == entry["identity"]["bytes"] and sha(raw) == entry["identity"]["sha256"]
        suffix = "default" if entry["locale"] == "default" else "sc"
        filename = entry["table"] + "." + suffix + ".datc64"
        with (ROOT / filename).open("xb") as output:
            output.write(raw)
        assert sha((ROOT / filename).read_bytes()) == entry["identity"]["sha256"]
        observations.append({**entry, "file": filename})
    elif entry["kind"] == "receipt":
        receipt = entry["receipt"]
    else:
        raise ValueError("Unexpected extraction record")
stderr = process.stderr.read()
if process.wait() or receipt is None or len(observations) != 3:
    raise RuntimeError("Dependency extraction incomplete: " + stderr[:4000])
receipt["lookup_receipt_sha256"] = sha(encoded(lookup))
receipt["local_preservation"] = {"path": str(ROOT), "scope": "Independent task cache; game installation read-only", "resources": observations, "source_scripts": {name: sha((ROOT / name).read_bytes()) for name in ["lookup.js", "extractor.js", "acquire_dependencies.py"]}}
with (ROOT / "acquisition.json").open("xb") as output:
    output.write(encoded(receipt))
print(json.dumps({"status": "completed", "index_sha256": lookup["index"]["sha256"], "index_stable": True, "index_rehashed": True, "acquisition_sha256": sha(encoded(receipt)), "resources": observations, "lookup_stats": lookup["stats"], "extraction_stats": receipt["stats"]}, ensure_ascii=True))
