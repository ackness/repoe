# Independent versioned data publication

RePoE stores game exports and explicitly retained compatibility inputs. Language
data belongs to `poe2-zh-cn-stats`. PoBR owns its domain schemas, interpretation,
selection and calculation code; its CI imports these external data temporarily.
Moving existing processed bytes here does not make them native RePoE facts.

`RePoE.data_publication` is a standard-library-only offline publisher. It accepts
explicit local ZIPs or immutable Git trees, authenticates their byte inventories,
and writes an independent deterministic ZIP. It does not acquire clients, decode
resources, search adjacent caches, read snapshot files from a working tree, or
publish remotely. Artifact Git staging creates an orphan bare repository in the
ignored cache for eventual publication to **ackness/repoe**, not another data
repository or checkout. Data archives are not committed to the source branch.

## Replay and handoff

The versioned plans under `publication/` contain source revisions, paths, lengths,
SHA-256 values, per-file ownership and explicit exclusions. Authenticate the plan
itself with a trusted full SHA-256 before invoking the publisher:

```sh
mise run publication:package -- \
  --plan publication/0.5.5.5-ordinary.plan.json --plan-sha256 <trusted-plan-sha256> \
  --input ordinary=/path/to/pinned-original.zip \
  --input tree-policy=/path/to/local-pobr-git \
  --out .cache/publication/replay-ordinary
mise run publication:git-handoff -- --package .cache/publication/replay-ordinary

mise run publication:package -- \
  --plan publication/0.5.5.5-game.plan.json --plan-sha256 <trusted-plan-sha256> \
  --input snapshot=/path/to/local-pobr-git \
  --out .cache/publication/replay-game
mise run publication:git-handoff -- --package .cache/publication/replay-game
```

`git-tree` inputs read only `git cat-file` blobs from the plan's full revision,
with an exact `ls-tree` inventory and regular-file modes. The checkout may be
absent; dirty/untracked files cannot supply missing data. These PoBR source
references describe the one-time migration provenance. Consumers retrieve the
new RePoE artifact, without access to the old PoBR archives or snapshot.

`package.json` and `git-handoff.json` provide the existing acquisition contract:
`repository`, full `revision`, `path`, ZIP `bytes`/`sha256`, internal `manifest`
`bytes`/`sha256`, and `expanded_bytes`. `git-handoff.json` also records the local
bare staging path and ref. `publication:git-handoff` neither pushes nor declares
remote publication. A coordinator must publish the exact commit and verify a
fresh remote fetch before changing a downstream publication lock.

## Two independent package surfaces

The ordinary package has root `manifest.json`, schema
`repoe-data-publication/v1`, exact `target` and
`files: {relative_path: {bytes, sha256}}`. All 29 selected original members keep
their paths and bytes. They include the pinned F77 input archive, selected CSD,
tables/inheritance, original manifests/locks and historical prepared codecs.
Their original producer metadata and candidate limits remain unchanged. The
original outer manifest is retained at
`publication-provenance/ordinary-manifest.json`; its excluded-file pins are
historical evidence, not instructions to acquire those files.

The ten complete `*/codec-policy/*` members are excluded. PoBR reconstructs its
policies from its small source templates and the external data object
`retained-policy-bindings/passive-tree-v4.json`. This object contains only
`compatibility_bindings`, `excluded`, `class_bindings`, `ascendancy` and
`base_policy.legacy_metadata.value` from the fixed original policy. Nested
insertion order and values are preserved using UTF-8, `ensure_ascii=False`,
`indent=2`, **without sorting**. This permits byte-identical reconstruction of
the original policy before its existing one-pointer source rebinding. The
publisher does not interpret the bindings, rewrite policy targets, or certify
node eligibility. The mapping's provenance and source pin are in the outer
manifest, outside the mapping object.

The game build part uses the consumer contract `pobr-build-data-part/v1`,
`kind: game`, the same exact `target` and file-pin map. Its 62 members preserve
`data/0.5.5.5/...` and selected `data/overlay-common/...` paths. It contains the
original snapshot manifest, but no language files, `CURRENT`, complete portable
core archive, or full shared policy set. The source manifest has SHA-256
`2a03ad79cc33b10e103895e2bae8b5984cadf341c0cc58425ac97dacb90348fd`;
only the combined game, language and PoBR policy inputs can restore runtime
`d7ac23c544a4d8ccc50b3237e20301e4fb1164c40a84745a9d3d4f1602dee9e8`.

Nine mixed processed outputs are retained as original opaque compatibility:
`base/{base_player_mods,character_constants,enemy_presets,game_constants,
non_damaging_ailments,weapon_types}.json`,
`overlay/{mirage_configs,trigger_configs}.json`, and
`generated/special_derived.json`. Numerical constants are not reclassified as
consumer code. The manifest records the original snapshot producer where no
independent exporter identity exists, and preserves embedded producer metadata,
including historical absolute command paths. No computation is reimplemented.

The shared split is explicit:

| Retained shared files | Role and applicability |
| --- | --- |
| `totem_varieties`, `passive_jewel_slots`, `boss_poise_thresholds`, `item_granted_skills` | Historical GGG table transcriptions, with their original 0.5.5.4.2 metadata and selection/interpretation limits |
| `high_precision_mods`, `vendor_name_aliases`, `buff_definitions` | External retained compatibility, including original PoBR/vendor mapping provenance and buff-reference drift limits |

The other eleven shared files (`special_mods`, `local_mods` and nine config
files) remain PoBR interpretation/static configuration code to materialize in
CI. This split does not certify official merge laws, source freshness, complete
unique mod/roll/variant ownership, or the seven missing crafting tables. Trade
catalogue/crafting compatibility retains its exact identity; missing inputs are
not recollected or replaced with empty values.

The separate [retained buff source reconciliation](buff_source_reconciliation.md)
binds the unchanged definition to exact old/new community Git sources and full
procedural context pins. Its 15 relocated references authenticate, but changed
upstream context keeps `guard_eligible=false`. This metadata is outside both
runtime package plans and does not update source acceptance or runtime bytes.

The metadata-only `publication/0.5.5.4.2-recovery.json` records the initial exact
recovery inventory and the coordinator's subsequent publication of separate
game/language rollback artifacts. The coordinator also reported successful
offline restoration of the previous runtime. Full acquisition pins belong to
its rollback lock; short status prefixes in the inventory are not import pins.
This does not add official-source certification. Remote current/rollback
acceptance and removal of tracked copies remain the coordinator's responsibility.

## Verification

```sh
mise exec -- python -B -m unittest discover -s tests -p test_data_publication.py -v
```

Tests cover deterministic bytes, unknown/null preservation, policy exclusion,
input/plan/member pins, missing inputs without fallback, unsafe archives,
immutable Git inventories, ordered data extraction, language rejection from a
game part, and a real fresh Git fetch after original inputs have been removed.
New client decoding, Rust/WASM builds and full unchanged verification buffers
are outside this publication operation.
