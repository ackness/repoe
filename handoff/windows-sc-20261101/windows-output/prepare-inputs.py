"""Preserve the existing compressed transfer and relocate pinned English inputs."""

import base64
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[2]
OBS = Path(__file__).resolve().parent


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(value):
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


receipt_raw = (OBS / "transfer.receipt.json").read_bytes()
assert sha(receipt_raw) == "12e26ae654e73270ab1c83934313fd575278b95c752b0b072969958da5f737d2"
assert (
    sha((OBS / "acquisition.receipt.json").read_bytes())
    == "0d2cce020b2d0336a393263d1b56dce88bcdf8c86b32b7193d8279022d3bea43"
)
assert (
    sha((ROOT / "RePoE/native_locale_probe.py").read_bytes())
    == "12b751d31bbbc0991e5fceb12df3752e76cebae476e08515b3e1f343410d79cc"
)
receipt = json.loads(receipt_raw)
lines = []
for name, entry in sorted(receipt["tables"].items()):
    compressed = (OBS / (name + ".pair.json.zlib")).read_bytes()
    assert len(compressed) == entry["compressed"]["bytes"] and sha(compressed) == entry["compressed"]["sha256"]
    body = base64.b64encode(compressed).decode("ascii")
    for part in entry["parts"]:
        index = part["index"]
        text = body[index * 24576 : (index + 1) * 24576]
        assert len(text) == part["bytes"] and sha(text.encode("ascii")) == part["sha256"]
        lines.append(encode({"table": name, "index": index, "data": text}))
assert len(lines) == 257
parts_raw = b"".join(lines)
with (OBS / "parts.jsonl").open("xb") as output:
    output.write(parts_raw)
source = ROOT / "handoff/windows-sc-20261101"
inventory = (source / "inputs.json").read_bytes()
assert sha(inventory) == "bfe3e10ee05d1ba073df0662a7aa61d6771939dcc37a33abb22e85b22e0b4099"
inputs = json.loads(inventory)
archive = source / inputs["archive"]["file"]
raw = archive.read_bytes()
assert len(raw) == inputs["archive"]["bytes"] and sha(raw) == inputs["archive"]["sha256"]
dest = ROOT / ".cache/windows-sc-20261101/english-targets"
dest.mkdir(parents=True, exist_ok=False)
with zipfile.ZipFile(archive) as bundle:
    assert set(bundle.namelist()) == set(inputs["files"])
    for name, pin in inputs["files"].items():
        target = (dest / name).resolve()
        assert target.is_relative_to(dest) and bundle.getinfo(name).file_size == pin["bytes"]
        payload = bundle.read(name)
        assert len(payload) == pin["bytes"] and sha(payload) == pin["sha256"]
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as output:
            output.write(payload)
        assert sha(target.read_bytes()) == pin["sha256"]
lock = inputs["target_lock_template"]
for selection in lock["tables"].values():
    selection["package"] = str(dest / selection["package"])
lock_raw = encode(lock)
with (dest / "target-lock.json").open("xb") as output:
    output.write(lock_raw)
report = {
    "parts": {"count": len(lines), "bytes": len(parts_raw), "sha256": sha(parts_raw)},
    "target_lock": {"path": str(dest / "target-lock.json"), "sha256": sha(lock_raw)},
    "target_files": len(inputs["files"]),
    "target_total_bytes": sum(pin["bytes"] for pin in inputs["files"].values()),
    "game_read": False,
    "decompressed_pairs": False,
}
with (OBS / "prepared-inputs.json").open("xb") as output:
    output.write(encode(report))
print(json.dumps(report))
