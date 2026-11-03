# Raw-material source ledger

`sources.lock.json` is RePoE's raw-material provenance ledger. Its
`schema_version: 1` `sources` map records admitted official inputs (the GGG
skill-tree export and the fixed `official-client-resource-candidate` used by
`--source-lock` callers such as `mise run client:source` and
`mise run facts:candidate`), and `acquisition_acceptances` records the bounded
coordinator decisions that admitted exact observed acquisition bytes and
physical payloads.

The acquisition chain that produced these records — index discovery, draft
collection, strict replay and physical decoding — is implemented in this
repository ([client-index](../RePoE/docs/client-index.md),
[client-sources](../RePoE/docs/client-sources.md),
[client-source-draft](../RePoE/docs/client-source-draft.md)). Acceptance entries
are exact evidence decisions, not a runtime release gate: original draft
envelope statuses stay frozen, new bytes do not inherit acceptance, and no entry
switches a consumer's current data.

## Relocation provenance

Relocated on 2026-11-03 from `ackness/pobr` `pipeline/imports/sources.lock.json`
at commit `860ded5059fc41e0983b3f1f85dae19b131e4d6b` (file SHA-256
`4fc8aa497347e4202a7545697483329286d23f4a5bc3fc717eae079ada1ee2ae`; last content
change in `0fb6f913cc3fac980f9d84e855b26103860d6b96`). The `sources` and
`acquisition_acceptances` sections are copied verbatim; entry keys, pins and
decision text are unchanged. PoBR's companion narrative remains
`pipeline/imports/client-source-draft.md` in that repository.

Per the shared [data
architecture](https://github.com/ackness/pobr/blob/master/docs/data-architecture.md),
the raw-material and acquisition ledger belongs to RePoE, locale curation
belongs to `poe2-zh-cn-stats`, and PoBR keeps consumption-scope acceptance
decisions. The sibling `retained_input_acceptances` section therefore stays in
PoBR; its `acceptance_key`/`registry_key`/`source_pins` references continue to
resolve against the entry keys preserved here.

Historical artifact pins inside entries still name `ackness/pobr` revisions and
`handoff/ordinary-0.5.5.5/*` paths; they are retained as the original
provenance, not re-pinned. Two later entries (`actor-ot`,
`description-relations`) already pin `ackness/repoe` `handoff/*` artifacts. The
`sources.official-passive-tree.corrections` record keeps its original PoBR
path; the byte-identical policy now lives at
`tools/pobr-data-adapter/policies/tree-corrections/bd87e6512c92b868542eddfb1ba4ea8b6dc2da36.json`
(SHA-256 `f031327c…` unchanged).

## Bounded decisions recorded

- `f77-0.5.5.5-international` — the selected 78-resource acquisition and its
  retained evidence binding; the 40-resource ancestor is a subset, not a second
  acquisition.
- `six-supplement-dat-0.5.5.5-international` — five lookup tables plus
  MonsterCategories (20,878 raw bytes / 321 physical rows), bound to manifests
  `b3927aab` and `c0f2a23f`; four other lookup tables exactly reuse accepted
  F77.
- `tree-and-inheritance-0.5.5.5-international` — Ascendancy and
  AscendancyPassiveSkillOverrides (15,891 raw bytes / 50 physical rows) plus 89
  item `.it` resources (38,664 raw bytes / 82 roots), bound to manifests
  `54e72ff9` and `f8642243`; six other tree tables reuse complete F77 objects.
  The `.it` path proof establishes fixed-index hash/location resolution, not a
  complete directory-name inventory or independent authoritative spelling.
  Literal fields and finite inheritance chains do not certify official merge
  law; `Base.tag` remains the named PyPoE66d1 community interpretation.
- `ten-csd-0.5.5.5-international` — gem, passive, skill, global, active-gem,
  four snipe statsets and aura CSDs (42,841,910 raw bytes), bound to manifests
  `c8a475ba` and `922aece0`. Four OS-denied-network strict replays match all
  ten raw pins; the initial failed gem download remains a failure closed by
  retained HTTP bodies, the later cached receipt and exact import ledgers. The
  four snipe CSDs have their own evidence, independent of F77.
- `locale-native-tables-0.5.5.5-international` — nine explicitly named
  Traditional Chinese DATs, default Words, default AlternateQualityTypes and
  ModEffectStats (12 resources / 24,088,336 raw bytes / 39,907 physical rows),
  bound to manifests `94dcfdc5`, `a9597d71` and `edad16f5`. This admits the
  byte acquisition only: no all-locale/UI use, SC client identity,
  cross-language conversion or gameplay approval. Locale curation is the
  translation repository's separate record.
- `actor-ot-0.5.5.5-international` — six observed OT files for BearCompanion,
  LivingLightning and SummonedRagingSpirit (11,172 raw bytes) with their
  retained index/range chain, lexical spans and three literal parent paths;
  RePoE package pin `9f20e64c`. Official merge/setter rules, effect scope and
  `mod_list` ownership stay excluded.
- `description-relations-0.5.5.5-international` — two present DAT resources
  (110 raw bytes), bound to RePoE package `80feccaf`.
  `IndexableSupportGems` has zero rows; `AfflictionRewardTypeVisuals` has one
  row with signed raw key `0` named `Delirium`. The missing
  `IndexableNonActiveSupportGems` is outside the successful subset; empty
  support data does not validate nonempty row layout or an index/name
  relation.

Endpoint and request realm declarations, local hashes and retained responses
are not official signatures or independent client-build/patch/realm/language
attestations. No entry accepts a whole outer archive as gameplay data or
changes runtime adoption; redistribution rights and production readiness stay
out of scope (`production_ready: false`).
