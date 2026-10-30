# Native core-skill facts

The opt-in `core-skills-a0` profile extends the [base facts producer](native_facts.md)
with labels, active-skill metadata, cost types, per-level facts and interpolation
constants. It emits `repoe-native-facts/v2`, a **partial candidate**, with
`production_ready: false`. It does not activate data in PoBR. Existing CLI
defaults and the default `base-v1` resource inventory remain unchanged.

The explicit [`gems-constraints-a1` profile](native_gems.md) adds gem-item,
family, weapon and ordered constraint facts through this same ingress; it does
not change the v2 profile's resource inventory or semantic payloads.

## Inputs and offline commands

Use the same explicit source-lock, source key and raw root as the base producer,
but select `--profile core-skills-a0` for both generation and acceptance:

```sh
mise run facts:candidate -- --profile core-skills-a0 \
  --source-lock /path/to/proposed-sources.lock.json \
  --source official-client-0.5.5.5-core-skills-draft \
  --raw /path/to/raw --out .cache/core-skills/candidate-a
mise run facts:validate -- --profile core-skills-a0 \
  --source-lock /path/to/proposed-sources.lock.json \
  --source official-client-0.5.5.5-core-skills-draft \
  --raw /path/to/raw --facts .cache/core-skills/candidate-a \
  > .cache/core-skills/acceptance.json
```

No network, discovery or source-lock update runs here. Raw inputs remain at their
game-relative paths. Alongside the base eight DATs and Default PSG, the source
entry must contain exactly these seven additional resources:

- `Data/Balance/GrantedEffectLabels.datc64`
- `Data/Balance/ActiveSkills.datc64`
- `Data/Balance/ActiveSkillType.datc64`
- `Data/Balance/CostTypes.datc64`
- `Data/Balance/GrantedEffectsPerLevel.datc64`
- `Data/Balance/GrantedEffectStatSetsPerLevel.datc64`
- `Data/Balance/EffectivenessCostConstants.datc64`

All base game/patch/realm, resource size/hash, schema and trusted decoder checks
apply. This profile currently accepts international PoE2 `0.5.5.5` only. Its
selected source entry also requires:

```json
{
  "profile": "core-skills-a0",
  "acquisition": {
    "status": "unreviewed-acquisition-draft",
    "evidence": [
      {"kind": "acquisition-receipt", "sha256": "<64 lowercase hex digits>"}
    ]
  }
}
```

`reviewed-source-input` is the other permitted acquisition status. Both status
and evidence fingerprints are **caller-declared**. The exporter validates their
shape and preserves them, but does not fetch evidence, authenticate a source or
approve a draft. Observed raw hashes can support a private proposal without
being promoted to the application's reviewed source lock. Source review must
verify those bytes and the acquisition chain independently. Even a reviewed
input produces a partial, non-production candidate here.

## Preserved facts and output contract

There are 21 payloads plus `manifest.json`: fifteen complete physical tables,
the four base graph/passive/quality/diagnostic documents, `skill_core.json` and
the exact input bytes of `source-lock.json`. Table row order, generated physical
field names, column/schema metadata, unknown fields and all raw arrays remain
present. `source-lock.json` is byte-preserved; other JSON payloads use the base
producer's deterministic UTF-8 encoding. A source lock may contain other source
entries: the exact file is retained and fingerprinted, not just its selection.

`skill_core.json` contains source-ordered collections:

| Collection | Facts |
| --- | --- |
| `labels`, `stat_set_labels` | Label IDs/text and nullable stat-set label relations; row zero is a valid reference, distinct from null and empty text |
| `active_skill_types`, `active_skills` | Stable IDs, optional flag-stat identity and the original `ActiveSkills.GrantedEffect` **string**, never a numeric row join |
| `effect_metadata` | Effect ID, nullable active-skill relation and ordered cost-type identities |
| `cost_types` | ID, nullable stat identity, raw divisor, per-minute flag and display format |
| `interpolation_constants` | ID and raw multiplier |
| `effect_levels` | Every physical row, effect identity, raw level/actor context, raw costs and complete raw-row reference |
| `stat_set_levels` | Every physical row, stat-set identity, raw level/actor context, crit channels, base multiplier/values, additional/float stat channels and interpolation channels |

Identities use `{row,id}`. Rows are ephemeral source positions within this exact
package; string IDs identify definitions. Level rows retain their physical row
and owner relation; repeated owner/level combinations are not deduplicated, and
actor context is not discarded. `raw` points to the complete table row values
using a package-relative payload and JSON Pointer. Fields not repeated in the
projection, including cooldown, reservation, additional flags and unknown data,
remain available there.

Equal-length cost-type and amount arrays produce ordered `costs` entries with
`slot`, `cost_type` and `amount_raw`. An unequal pair remains intact, sets
`costs: null` and emits `unresolved_cost_array_alignment`; it is not truncated
or defaulted. Unequal additional/float stat arrays likewise remain intact and
emit `unresolved_level_stat_array_alignment`. These diagnostics flag an
unresolved alignment, rather than inventing gameplay policy. All nonnull
foreign rows whose target is among the fifteen acquired tables must resolve;
references to unavailable targets remain physical facts with diagnostics.

No unit conversion, rounding, interpolation, quality application, per-minute
calculation or effective-level policy runs here. In particular, raw names such
as `ActorLevel` are community schema interpretations. Neither these labels nor
array alignment alone certify game semantics. No physical radii, complete gem
catalogue, text/locale closure or complete foreign-key closure is inferred.
The existing Snipe scope discrepancy and absent-base graph relations remain.

## Acceptance and update boundary

The manifest records `profile`, complete payload hashes, source-lock/selection
identity, acquisition metadata, schema, trusted decoder inventory and producer
file hashes, including `native_skills.py`. The acceptance command checks this
profile explicitly, verifies the exact source-lock bytes, requires all 117
trusted decoder files, replays all physical tables and projections, and retains
the independent repeated-graph invariant from v1. A rehashed projection cannot
pass merely by changing its own manifest. The current v2 validator requires the
current replay producer fingerprints; use the fixed exporter revision for an
older v2 artifact. Optional `--manifest-sha256` additionally pins an externally
approved artifact, rather than authenticating its upstream source.

Input errors precede output publication. Existing outputs are refused; the
completion manifest is published last. Generate another package in a new path
for each independent-process replay. Review raw acquisition evidence, physical
fields and relations before recording a new external manifest pin. PoBR must
explicitly adopt this profile and its semantics; a green exporter test or facts
receipt is not a runtime migration, numerical accuracy or Chinese-client claim.
