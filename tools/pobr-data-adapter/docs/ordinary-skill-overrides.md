# Skill overrides from target facts and fixed compatibility inputs

`--ordinary-domain skill-overrides` writes the existing `SkillOverridesDef`
overlay. Target raw facts supply every raw-owned `base_multiplier`. Explicitly
pinned community input supplies the authored entry identities, constant versus
per-level template, and retained prepared interpretations. The output metadata
separates those sources; it does not certify the whole overlay as independent
game rules or a complete target runtime.

## Explicit invocation

Use the existing codec flags for the archived override source and target policy,
and both branch-codec flags for the actual archived export-index codec. All six
are mandatory here. The branch flags are also accepted by skill-stat-map;
quality flags are rejected. Duplicate, missing or cross-domain options fail.

```sh
# Coordinator's fixed binary; the implementation worker does not execute this.
/absolute/path/to/frozen/pobr-data-adapter \
  --ordinary-facts /absolute/path/to/F \
  --facts-manifest-sha256 56e71e00a72c8079d100b64861fc030206b12aaeb5ad655ccb4ab4e6726332d0 \
  --version 0.5.5.5 --ordinary-domain skill-overrides \
  --codec-source /absolute/path/to/skill_overrides.json \
  --codec-source-sha256 02948c49387a0c83fb5bc013552b8bcc1b98edfc1027ceb743de3288d7652397 \
  --codec-policy /absolute/path/to/tools/pobr-data-adapter/policies/skill-overrides/0.5.5.5-facts-compat-policy.json \
  --codec-policy-sha256 fc913c22431fbcd4865c7fea66d72acfcba38e5dac1bfadcfd28153810d6de2b \
  --branch-codec /absolute/path/to/stat_set_labels.json \
  --branch-codec-sha256 825e594f43f07a4115ee29e57622670688e5d1c099f7e11a30ba66b3b80cca06 \
  --out /absolute/path/to/existing-parent/fresh-overrides
```

The initial [policy](../policies/skill-overrides/0.5.5.5-facts-compat-policy.json)
is the frozen target applicability template verbatim. It binds the target patch
and exact manifest, both archival hashes, original metadata, snapshot versions
and archived paths. The two legacy files retain their `0.5.5.4.2` / `bb52d6b3…`
identity. Policy evidence references are descriptive: the producer never opens
the source-check report, old numeric package, vendor or another candidate.
There is no implicit path selection, fallback or download.

The existing `reader::open` authenticates F and only selects Stats,
GrantedEffects, GrantedEffectStatSets, GrantedEffectStatSetsPerLevel and
GrantedEffectsPerLevel. `Tables::selected` checks physical rows and stable IDs.
All three auxiliary SHA checks precede strict JSON parsing. Required column
metadata, foreign references, exact i32s and duplicate table/level/override/codec
keys are checked before reserving output. Ordered reference lists may repeat.

## Conversion contract

| Entry/field | Handling |
| --- | --- |
| Raw-owned base multiplier | Stable effect ID → physical primary `StatSet` → all actual positive `GemLevel` rows, sorted by level. Use `1.0 + f64::from(BaseMultiplier) / 10000.0`, the existing stat-set expression. Signed values and zero are valid. |
| Legacy per-level template | Replace its whole `per_level` list with target points, including new target levels. Old levels/values never fill a target hole or constrain the output. |
| Legacy constant template | Emit a target-derived constant only if all positive target rows are equal. Otherwise replace `value` with actual `per_level` points. Missing/empty positive primary rows fail. |
| GPL | Resolve `GrantedEffect` / `Level` and record pairing only. Do not filter set rows by GPL, fabricate runtime levels or add actor/level scaling. |
| Virtual numeric entry | Preserve raw JSON only under an exact key exception and absent target effect. Newly missing, newly bound or unused exceptions fail. |
| Prepared interpretation | Preserve the whole raw entry, including unknown fields, for the policy's supported `implicit_stat`, `explode_corpse`, `skill_attack_speed_more`, `dot_is_area` categories. Unknown new stat categories require adaptation. |
| Retained branch | Actual `(skill, stat_set)` codec record → stable set ID → target owner's ordered primary/additional refs. Empty labels and duplicate ordered refs remain valid. No raw-order inference or producer primary fallback. |
| Missing retained codec | Only an exact key/presence policy exception may preserve the entry without a target branch claim. New/stale/partial exceptions fail. |
| Implicit stat ID | Resolve the unchanged ID in target Stats; absence is an explicit policy conflict, never a remap or silent deletion. |

The current pinned source has 362 authored entries: 267 raw-owned numeric entries,
one virtual `EnemyExplode` multiplier and 94 prepared entries (84 implicit, eight
corpse explosions, one speed and one area flag). Ten prepared entries have exact
unbound codec decisions. These are source observations, not Rust admission counts
or skill allowlists. The policy is data, not a source of target numeric values.

Both exception lists match the full override key: `skill`, `stat`, and the
optional `stat_set` and `stat_id`. An exception's optional `source_row` is
historical evidence only; inserting or deleting earlier legacy override rows
does not change which exception matches. Duplicate keys and duplicate present
`source_row` values within either list still fail.

Parent preflight found Decimal equality for 6,672 old per-level points and 181
source rows behind 98 constants. The existing f64 expression can serialize
slightly different tails; neither byte equality nor f64 equality is required
against old values. The pinned target has 6,902 positive primary source rows for
these entries: 6,721 for per-level templates (49 level keys absent from the old
template) and 181 for constant templates. All target levels are used; this
identity count is not a producer result. In particular, three constant rows at levels 2–4 of
`GAMediumBeetleChargedSunder` have no GPL partner. The producer records that fact
without inventing pairing; the existing consumer still skips runtime rows absent
from base. Preflight is source evidence, not a producer or full-BD conclusion.

## Output and receipt

```text
fresh-overrides/
  _domain_candidate.json
  overlay/skill_overrides.json
  legacy-skill-overrides.json
  branch-codec.json
  codec-policy.json
  source-manifest.json
  source-lock.json
  producer-receipt.json
```

The three auxiliary sidecars and F manifest/lock retain original bytes. Override
entry order/identity and unknown fields remain; only target-owned numeric
representation and `_meta` change. The existing DTO is parsed for shape checking,
not used to reserialize retained entries. New `_meta.target_numeric` records F;
`_meta.legacy_compatibility` records each archived source and policy separately.

Each receipt entry records its source index/pointer/key and original/output
entry hashes. Numeric entries bind effect/primary physical rows, all raw primary
set level rows, calculated values, output points and GPL pair status. Optional
legacy comparisons are evidence only. Prepared entries record the used codec
row and ordered owner, or exact unbound exception; implicit stat physical rows
are explicit. Unconsumed columns and row ranges remain locatable in F. The
receipt includes actual source/policy/output hashes and compiled implementation
revision, including all new helpers and the unchanged original DTO source.

The receipt's `conversion.exception_row_moved` array is always present. In legacy
source order, it lists each matched exception whose recorded `source_row` differs
from its current row, with `list` (`legacy_numeric_exceptions` or
`unbound_retained_entries`), `key`, `policy_source_row` and actual `source_row`.
It is empty when no rows moved. An absent policy `source_row` is not a move and
remains absent from the entry's embedded `policy_exception`.

### Forward mode

`--mode forward` continues at the following content decisions and records every
issue in [the coverage report](ordinary-coverage.md). The default strict mode
keeps its existing errors and output.

| Decision | Issue kind | Action |
| --- | --- | --- |
| Base multiplier has no target effect and no matching numeric exception | `base-multiplier-no-target` | `retained-legacy`: keep the authored entry unchanged, without target numeric ownership |
| Retained entry has no codec/target binding and no matching presence exception | `retained-unbound` | `retained-legacy`: keep the authored entry without a target branch claim |
| Non-delegated implicit entry's stat ID is absent from target `Stats` | `implicit-stat-absent` | `quarantined`: omit the entry from the overlay |
| Numeric exception now has a target effect, unbound exception now has a binding, or its presence evidence changed | `exception-stale` | `listed`: consume the stale exception and use the current facts/binding checks |
| Numeric or unbound exception has no corresponding override | `exception-unused` | `listed`: report each unused key |

Every issue's entity is the complete override key
`skill/stat[/stat_set=…][/stat_id=…]`. Observed evidence includes the key and
missing stat ID, codec/effect presence, or the exception and its policy list.
A changed unbound presence exception produces both `retained-unbound` and
`exception-stale`: the first records the retained entry, the second the stale
policy evidence. Consumed stale exceptions are not listed again as unused.

Quarantined entries retain their original source index, key and hash in
`entry_records`, with `emitted: false` and a null output hash. They remain in
the verbatim archived source and are excluded from emitted-entry counts.
V2 delegated implicit entries retain their existing handling; their old stat
IDs do not become target-presence gates. `exception_row_moved` stays receipt
evidence, including for consumed stale exceptions, and never produces a
coverage issue.

Pins, input shapes, duplicate identities and dangling references still fail.
A codec set outside its target owner and missing/empty positive primary
numeric rows also remain fatal: these paths cannot establish the target
ownership needed to emit the entry.

Validation and serialization finish before output reservation. The existing
Output directory-handle protection covers all auxiliary parents, F, production
data, symlinks and existing leaves. The domain marker is first and receipt last.
No base files or complete runtime manifest are emitted. Source remains draft,
`complete_runtime` is false, adoption is `not-adopted`, and CURRENT is untouched.
Remaining assets, target gameplay-law correctness, complete package and ordinary
BD/Web/accuracy acceptance remain separate work.

## Coordinator validation

New synthetic regressions are authored **UNRUN** by the worker. They exercise
target changes/new levels, constant-to-variable conversion, no fallback for holes,
ordered refs/aliases, exact/stale exceptions, unknown-field fidelity, original DTO,
strict metadata/keys/pins, CLI/output isolation and ten previous domains. Parent
must also compare actual old/new binaries; same-binary fixture replay alone is
not proof of unchanged older production bytes.

```sh
mise exec -- cargo test --locked --manifest-path tools/pobr-data-adapter/Cargo.toml ordinary_facts::skill_overrides::tests
mise exec -- cargo test --locked --manifest-path tools/pobr-data-adapter/Cargo.toml
mise exec -- cargo clippy --locked --manifest-path tools/pobr-data-adapter/Cargo.toml --all-targets -- -D warnings
```

Parent uses its existing warm target and fixed binary for two source-limited
productions, a complete independent numeric/retained-entry/receipt comparison,
ten older domains and guards. No worker Cargo, producer, Lua, core/WASM rebuild,
new target, source acquisition or CI is required for this handoff.

## Raw-owned implicit-stat membership

The optional [v2 implicit ownership policy](../policies/skill-overrides/0.5.5.5-implicit-ownership-policy.json)
delegates each target-bound `implicit_stat` entry to the existing ordinary-skills
producer. That producer already fills `SkillStatSetDef.implicit_stats` from
`GrantedEffectStatSets.ImplicitStats` and `IgnoredStats`, including its existing
primary/additional-set normalization. Keeping an old overlay injection would add
a removed source member back after loading the current base. V2 removes that
injection; it does not create a new stat merge or an export-index mapping.

The actual pinned codec must bind the entry to a set owned by the target effect.
Raw primary and selected set arrays, every physical stat reference and ordered
occurrence remain in the receipt. Their columns/types/references are checked.
The old entry, including unknown fields, remains in the exact archived source;
its original index/hash and explicit non-emission are recorded. Old stat presence
is reported, not required for a delegated entry. The target may remove, replace
or add members without a legacy equality gate. Unbound entries retain the same
exact policy exceptions and unchanged compatibility behavior.

Current-source inspection found 77 of the 84 implicit overlay entries already
supplied by target ordinary base sets, and seven without a target codec binding.
Under v2 those 77 are delegated and the seven remain explicit compatibility.
The eight corpse flags, one attack-speed interpretation, one area flag and the
virtual multiplier remain authored rules. The historical `(skill,index)` codec
also retains its separate ownership; none is presented as a raw client field.

The original v1 policy still preserves every prepared entry. V2 keeps the same
output DTO and existing loaders; the receipt distinguishes source entry count,
emitted entry count and delegated source indices. Focused regressions run the
actual ordinary-skills source converter and `GameData::skill_stat_sets` together
to demonstrate removed/replaced/duplicate source members without old
re-injection, retained raw unknowns and invalid-source/policy rejection. These
tests are authored but UNRUN by the worker; integration owns runtime validation.
