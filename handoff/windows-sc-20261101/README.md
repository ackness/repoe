# Windows language generation inputs

This branch carries the fixed implementation and the smallest English input closure
needed to bind the already decoded nine-table Windows observation. It is a Git
handoff, not a production data release. All source statuses remain draft; source
patch/realm remain unknown. Target identity stays 0.5.5.5/international.

`english-targets.zip` contains 11 unchanged files (45,005,764 uncompressed bytes).
The original three manifests and each selected payload retain their original
bytes. These directories are selected consumer inputs, **not complete copies of
the original F77 or supplement packages**. `inputs.json` names every file, byte
count and SHA-256, plus the target-lock recipe. No game files or Windows data
were collected to produce this archive.

Archive: 1,497,807 bytes, SHA-256
`2d7bba399172db959b25b07912d7024f23da36edea5fe70fcb4cb4c7b72bfa0d`.
Input inventory SHA-256:
`bfe3e10ee05d1ba073df0662a7aa61d6771939dcc37a33abb22e85b22e0b4099`.

Use a clone with `core.autocrlf=false` so the pinned Python/JavaScript source
bytes match Git. The existing verified Python can validate and unpack these
inputs with its standard library. No game decoding or dependency installation
is needed for this step. Run from the RePoE checkout root:

```python
import hashlib, json, zipfile
from pathlib import Path

source = Path('handoff/windows-sc-20261101')
inventory = (source / 'inputs.json').read_bytes()
assert hashlib.sha256(inventory).hexdigest() == 'bfe3e10ee05d1ba073df0662a7aa61d6771939dcc37a33abb22e85b22e0b4099'
inputs = json.loads(inventory)
archive = source / inputs['archive']['file']
raw = archive.read_bytes()
assert len(raw) == inputs['archive']['bytes']
assert hashlib.sha256(raw).hexdigest() == inputs['archive']['sha256']
dest = Path('.cache/windows-sc-20261101/english-targets').resolve()
dest.mkdir(parents=True, exist_ok=False)
with zipfile.ZipFile(archive) as bundle:
    assert set(bundle.namelist()) == set(inputs['files'])
    for name, pin in inputs['files'].items():
        target = (dest / name).resolve()
        assert target.is_relative_to(dest)
        assert bundle.getinfo(name).file_size == pin['bytes']
        payload = bundle.read(name)
        assert len(payload) == pin['bytes']
        assert hashlib.sha256(payload).hexdigest() == pin['sha256']
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as output:
            output.write(payload)
lock = inputs['target_lock_template']
for selection in lock['tables'].values():
    selection['package'] = str(dest / selection['package'])
lock_raw = (json.dumps(lock, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')
with (dest / 'target-lock.json').open('xb') as output:
    output.write(lock_raw)
print('target-lock SHA256:', hashlib.sha256(lock_raw).hexdigest())
```

The rewritten path-only lock gets a new hash and records the actual local paths.
Every target manifest/payload/raw/schema pin remains unchanged. Follow
[`decoded_locale_tables.md`](../../RePoE/docs/decoded_locale_tables.md) with the
preserved original transfer receipt and all 257 parts from the existing RAM
session. Supply the newly printed target-lock hash explicitly. Record the real
local ingest runtime separately from the original memory-decoder runtime.

The translation checkout uses `src/native-catalog.mjs` at implementation commit
`1213517f31aeaba3a9b33d7c6e0474313232ce29` (five-module closure). Its v2 request
must point at the actual new observed candidate and these same three English
packages. It independently rechecks resource/record binding. Five English raw
resources match the target; BaseItemTypes, Mods, Characters and
AlternateQualityTypes differ and require record-level checks.

Generate into fresh `.cache` output directories. Commit compact archives of the
actual frozen candidate/catalog plus their manifests, file inventories and
bounded validation report on the handoff branches, preserving original bytes
inside the archives. Do not commit expanded duplicate 131 MB transfer JSON or
modify CURRENT. Git conveys the data; thread messages need only exact commit,
manifest and artifact hashes. This operation does not promote a source lock or
certify complete CN-client numerical applicability.
