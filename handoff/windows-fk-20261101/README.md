# Explicit FK structure v3 candidate

This handoff retains strict v2 and the frozen earlier SC evidence. `source-candidate.zip` contains all 22 files of a new `repoe-localized-tables/v3` candidate. Validate the archive/member pins in `inventory.json` before using them. Source observation patch and realm remain null. There is no CURRENT update or production/source approval.

The policy `stable-key-pinned-fk-structure/v1` is opt-in through an exact pinned `repoe-fk-policy-lock/v1`. Three dependencies (ItemVisualIdentity, ModType, Stats) use `community-reader-language-fallback/v1` for the source-localized namespace. This is explicitly community interpretation, not verified official-client semantics. The original per-side namespaces, SC exact-path absence, index identity, raw pins, acquisition ranges/stability and all physical fields are preserved. The package includes partial F77 payload closure only, and does not require unrelated F77 files.

The Python producer first reproduces the complete original strict-v2 binding. It then compares only the declared FK edges by unique stable key and full reachable physical structure. Ordered arrays, original pointers and unknown/non-normalized fields remain evidence. Default/SC and default/English roles are checked separately. Cycles use visited pairs only to avoid repeated expansion; acceptance is committed after every reachable constraint finishes. The completed closure table is shared by SHA, with exact role/package/payload/row namespaces. No in-progress success cache exists.

All dependency and primary source rows are offline preserved inputs. This implementation does not read the client, download game data, start the client, or access accounts/logs. The three new dependencies were obtained in the prior bounded read-only acquisition, with full receipts inside this candidate. The original 18 game resources were not reread.

```text
python -B -m RePoE.native_fk_tables --base FROZEN_V2 --expected-base-manifest-sha256 PIN --policy-lock LOCK --expected-policy-lock-sha256 PIN --out .cache/fresh-v3
python -B -m unittest discover -s tests -p test_native_fk_binding.py -v
```

For another machine, rewrite absolute input paths in a new lock and record its new SHA; do not rewrite any original raw/schema/payload pin. The original Windows lock is retained as evidence. The source candidate retains the strict parent manifest and binding bytes. It adds a separate binding and exact dependency packages; it does not replace the fixed English target with the Windows default rows.

`validation.json` includes full rejected-root diagnoses and replay equality. Known Mods `MapPowerfulWorkAround` remains rejected for the six Stat1/2/3 min/max differences. Missing keys are unverified regional/version differences, never automatic China-only classification. The companion translation handoff supplies the independently recomputed catalog and separate compile-time verification sidecar. These evidence packages are not intended as player downloads.
