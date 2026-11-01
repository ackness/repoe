# Retained buff reference source reconciliation

`publication/retained-buff-source-reconciliation.v1.json` is independently owned
RePoE source metadata, schema `repoe-retained-buff-source-reconciliation/v1`.
It binds the retained 14,694-byte definition, SHA-256
`0fd267716e0e4d1bee9dadf76c2a794b28f0941c1dd301b5c6b2ec3bf9009026`, to actual
community Git sources at `ce8bffaba31f8e68cfce70579e1c96465e7c133c` and
`bb52d6b368307457eb9c54bb13f1829993d390b1`. It contains no runtime definition,
source file snapshot, official semantics certification, or source acceptance.

The exact old commit is now available. The 15 old recorded FNV hashes match;
each recorded old segment occurs once at its new range. `Onslaught` and
`OnslaughtFlask` intentionally reference the same segment. `ArcaneSurge` uses
`Modules/CalcDefence.lua`; the other 14 use `Modules/CalcPerform.lua`.

## Reviewed result and limits

The complete `doActorMisc` procedure moves from old lines 578–850 to new lines
584–857. Its sole change is insertion of `\t---@class Output` after its first
three lines. Its bindings, `env.mode_combat` gate, Fortification precursor,
per-buff guards, nested branches, calculations and subsequent enemy processing
are unchanged. Thus 14 entries have `output-annotation-only` local context.

The complete Arcane Surge branch moves from 1606–1617 to 1655–1666. Its
`AffectedByArcaneSurge OR Condition:ArcaneSurge` gate, LifeRegen/ManaRegen
redirect, maximum overrides, cast-speed effect and optional damage branch are
byte-identical. It sits directly in `calcs.defence`, with no enclosing combat
gate. The preceding pool/reservation/darkness calls and this entire branch are
also byte-identical (old 1595–1617 / new 1644–1666). This observation does not
change the retained definition's `mode_gate` or any of its `verified` fields.

Full upstream context is **changed; equivalence is not established**:

- `calcs.perform` adds `AbyssalWastingImpliesCondition` (new 1264–1277), before
  player/enemy `doActorMisc`. When `AbyssalWasted` is active it can write
  `v.condition` and `Condition:<v.condition>` flags into player/enemy modifier
  databases. The two files do not establish the actual LIST contents or prove
  that any particular retained trigger is granted. Minion effects are unproven.
- `AbyssalWastingAlsoGrants` (new 3440–3454) copies and optionally scales supplied
  mods after `doActorMisc`, before `calcs.defence`. Arcane Surge's input
  equivalence cannot be inferred from its unchanged branch.
- `calcs.defence` adds `MovementSpeedAppliesToEnergyShieldRecharge` and
  `LifeRegenAppliesToManaRegen` conversions before Arcane Surge, and changes
  resource conversions, block calculations, Ward handling and recovery.
  Its earlier pool call now passes `skipBreakdown=true`.
- The immediately called `doActorLifeManaSpiritReservation` adds
  `activeInWeaponSet` eligibility. The complete helper can update reserved pools,
  LowLife/LowMana/LowSpirit conditions and ExtraAura inputs. This does not imply
  a different Arcane Surge result for every build. The pool and darkness helper
  bodies themselves remain byte-identical.

Whole old/new `doActorMisc`, `calcs.perform`, `calcs.defence`, reservation,
pool and darkness procedures are pinned independently; the Arcane Surge prelude
is pinned as a region. Full source file pins also cover changed bindings such
as `local calcs = ...` becoming `require("Modules.CalcBase")`. These are source
comparison findings; called implementations in other modules and runtime inputs
are outside this bounded comparison.

Every entry depends on the changed caller; Arcane Surge also depends on the
changed defence/reservation procedures. The metadata therefore retains
`full_context_unchanged=false`, `guard_eligible=false`, `semantics_verified=false`.
Its successful evidence check must never become a compatibility pass.

## Concrete consumer contract

Acquire the metadata as a regular Git blob from an accepted full RePoE commit,
and bind its own byte count/SHA-256 in the consumer's source lock. This is a
separate source-reconciliation input, outside current/rollback runtime payloads
and existing game/ordinary package plans. This commit does not publish it or
update any consumer lock. The metadata's revision and SHA-256 must come from the
accepted publication, rather than being inferred from a local mutable file.

`files` maps the exact vendor-relative paths to `src/` Git paths and complete
old/new file pins. `contexts` maps scope IDs to inclusive one-based ranges,
raw-byte pins and a reviewed comparison. `entries` maps every retained ID to its
file, `old`/`new` ranges, original-compatible FNV hashes, raw-byte pins,
`local_context` and `context_dependencies`. `findings` and `condition_review`
explain the limits; they are reviewed prose, not inferred game semantics.

For each entry the consumer must authenticate the metadata, exact full
definition bytes, both commit identities and both complete source files; match
the retained ID inventory and old `vendor_ref`; verify raw old/new segment
pins/equality, legacy FNV hashes and exactly one complete new line window;
verify every declared complete context pin and its comparison, including
dependencies beyond the local branch. Preserve local and upstream results
separately. No nearest-match lookup, mutable HEAD, source substitution or
definition rewrite is allowed.

SHA-256 segment/context pins include all original line terminators, including
the last newline. The legacy FNV recipe follows PoBR's
`str::lines().join("\n")`, normalizing CRLF and omitting the final terminator.
The initial comparison's segment SHA-256 excluded that last newline; these raw
segment pins deliberately distinguish that recipe. Complete file pins agree.

## Offline verifier

`RePoE.buff_source_reconciliation` uses only the standard library and local
Git objects. It reads precisely these two regular files at both full commit
IDs, disables replacement objects and lazy fetching, and never reads a source
checkout, downloads data or changes Git refs. Complete function bounds are
checked against the reviewed files' top-level declaration/`end` layout; this is
not a general Lua parser. Only the exact single annotation insertion described
above is accepted as `output-annotation-only`.

```sh
mise exec -- python -B -m RePoE.buff_source_reconciliation \
  --metadata publication/retained-buff-source-reconciliation.v1.json \
  --metadata-sha256 aeb62b23fdd9504f3d0c05b602b05a8a73e7dbf837071080a1f42b1f6267608d \
  --defs /path/to/exact/buff_definitions.json \
  --source-git /path/to/local/community-source.git
```

Exit status **2** means all declared source evidence authenticated, but the
procedural context changed and the guard remains closed. Status **1** means
evidence failed (including missing objects, definition/source/context pin
mismatch, altered/ambiguous windows or inconsistent comparison claims).
`--evidence-only` returns **0** for authenticated evidence while still emitting
`guard_eligible=false`. It is an inspection mode, never an acceptance switch.
The JSON report is written to stdout; the default closed-guard diagnostic goes
to stderr. Consumers must inspect the result and exit status, not just the
`evidence_verified` field. PoBR's existing `check-buff-refs` is untouched and
continues to fail on its old ranges; this artifact does not authorize a bypass.

```sh
mise exec -- python -B -m unittest discover -s tests -p test_buff_source_reconciliation.py -v
```

Tests use small synthetic source strings and bare Git objects without checkouts.
They cover changed outer gates with unchanged inner windows, ambiguous windows,
changed effects despite refreshed pins, definition/source/metadata mismatches,
truncated context, wrong file/range/hash/ID mapping and false pass claims.
Actual 15-entry proof requires the fixed real Git objects and retained definition,
not synthetic test success. No Cargo/WASM, full-client replay or unchanged large
runtime/corpus validation is needed for this source-only operation.
