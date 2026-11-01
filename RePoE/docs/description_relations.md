# Observed description-relation tables

The fixed 0.5.5.5 international client index was checked for exactly three
schema-declared resources under `Data/Balance/`. This bounded observation adds
raw and physical table evidence; it does not enable description formatters.

| Exact resource | Observation |
| --- | --- |
| `IndexableSupportGems.datc64` | 12 raw bytes; zero rows. No observed Index, SupportGem FK or Name value. |
| `AfflictionRewardTypeVisuals.datc64` | 98 raw bytes; one row with signed raw enum key `0`, Id `DeliriumRewardGeneric`, Name `Delirium`. |
| `IndexableNonActiveSupportGems.datc64` | Exact hash not matched in the selected index; no raw, empty table or success receipt is supplied. |

Three-resource discovery remains incomplete. The two present resources have a
separate complete subset acquisition receipt. Six bounded HTTP range responses
totalled 157,643 body bytes; the prior index and decoder were reused. Original
responses, serialized headers, range records, selected index evidence, draft lock,
typed rows and failure diagnostics are preserved in the independent package.
Serialized headers are not claimed to be exact wire bytes.

The existing `RePoE.native_tables` exporter was used unchanged. The support table's
zero rows do not validate its declared nonempty row layout. The reward observation
establishes raw key `0` only; physical row zero, an enum's declared indexing and a
stat ID suffix do not establish a general key conversion.

The fixed community PyPoE formatter registers `display_indexable_support` and
`affliction_reward_type` only under `sequel == 1`. Its PoE2 physical table specs
and the corresponding CSD tokens are separately observed facts. They do not
authorize applying the PoE1 formatter policy to PoE2.

The selected CSD compounds order support level before support index and apply
the formatter to member 2. Nine separate reward descriptors apply their formatter
to wildcard member 1; suffixes `_1` through `_9` are not fixed raw enum values.
No complete support-name mapping or PoE2 formatter contract was established.
All 13 scoped consumer gaps remain open; no runtime handler is enabled.

## Recovery

[`publication/description-relations-0.5.5.5-draft.json`](../../publication/description-relations-0.5.5.5-draft.json)
pins the RePoE artifact repository, full revision, ZIP path, bytes/SHA-256,
top-level manifest and expanded size. The source branch contains metadata and
this contract; complete raw/fact data stays on the separate RePoE artifact ref.

Authenticate the ZIP and exact `manifest.json.files` inventory before extracting
to a fresh temporary directory. The archive schema is
`repoe-description-relation-observation-package/v1`; `raw/` and
`candidate/source-lock.json` are the explicit replay inputs. `candidate/` preserves
the original three exporter outputs. Use the pinned producer revision and its
locked decoder with the existing API:

```python
from pathlib import Path
from RePoE.native_tables import create_candidate

restored = Path("/temporary/authenticated-observation-package")
create_candidate(
    source_lock=restored / "candidate/source-lock.json",
    expected_source_lock_sha256="ca40e6366d721660d56e15f5f4bcc780103704d182bc72fea20b853c951a1c98",
    source="description-relations-0.5.5.5-observation-draft",
    raw=restored / "raw",
    out=Path(".cache/fresh-description-relation-replay"),
    language="English",
)
```

A fresh remote Git fetch verified all 92 archive members and 11 producer blobs.
OS-denied-network replay from the restored raw resources reproduced all three
outputs byte for byte. Full index replay needs its separately pinned external
inputs; this small archive does not contain the entire client index.

Acquisition remains `unreviewed-acquisition-draft`, `production_ready=false` and
`not-adopted`. Raw hashes freeze first observations; they are not independent
expected pins or official signatures. Patch, realm and the English default
resource namespace remain explicit target declarations, not independently
observed client identities. Source acceptance, formatter interpretation and
PoBR adoption remain separate decisions.
