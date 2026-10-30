# Native item and actor facts

`--profile items-actors-bc` extends the same [native ingress](native_facts.md)
and [A1 profile](native_gems.md) with exact physical item/mod/socketable and
actor facts. It emits `repoe-native-facts/v4`, **partial-candidate**, with
`production_ready: false`. This is a development fact package, not a published
PoBR runtime snapshot. Legacy exporters and the three existing profiles retain
their behavior and exact selected resource inventories.

## Input and output boundary

Exactly **77 DATs and the Default PSG** are required. The previous 39 DATs are
extended by the 25 names in `native_items.TABLES` and 13 names in
`native_actor_facts.TABLES`. Inputs remain the fixed PoE2 international 0.5.5.5
candidate, native schema and full trusted decoder profile described in the base
contract. No API, network, compatibility views or legacy specification loading
is used by this exporter. Existing raw bytes are verified before decoding.

The selected schema-1 source entry must explicitly declare
`profile: "items-actors-bc"`, exact size/hash identities for all 78 resources,
and an acquisition declaration with evidence fingerprints. Its status remains
caller-declared; a new observed hash or a successful export does not approve
source acquisition. The whole external lock is retained byte-for-byte.

```sh
mise run facts:candidate -- --profile items-actors-bc \
  --source-lock /path/to/proposed-sources.lock.json \
  --source official-client-0.5.5.5-items-actors-draft \
  --raw /path/to/raw --out .cache/items-actors-a
mise run facts:validate -- --profile items-actors-bc \
  --source-lock /path/to/proposed-sources.lock.json \
  --source official-client-0.5.5.5-items-actors-draft \
  --raw /path/to/raw --facts .cache/items-actors-a \
  --manifest-sha256 <externally-recorded-manifest-sha256>
```

There are **87 payloads plus the manifest**: 77 complete physical tables, the
four base documents, `source-lock.json`, `skill_core.json`, `gems.json`,
`constraints.json`, `items.json` and `actors.json`. All physical fields,
unknowns, schema metadata, source order and null values remain in the canonical
tables. The thirteen producer fingerprints include `native_items.py` and
`native_actor_facts.py`. These are source fingerprints, not a claim that an
unsigned manifest authenticates a client installation.

Domain references use source table, physical row and actual string IDs where
available. Numeric `Id` columns do not acquire stable-ID semantics. Names are
display text; repeated and empty names never merge rows. Source whitespace is
preserved, including constant IDs with trailing spaces. Evidence references
point into this package; no runtime re-opening of external files is proposed.

## Item facts

`items.json` contains these source-ordered collections:

- `mods`: eight explicit source slots, nullable stat identities, regular min/max
  and separate hardmode min/max/flag; ordered families, direct/implicit tags,
  spawn/generation weights, raw domain/generation/level fields, crafting class
  restrictions and granted-effect/buff references. Source endpoints are not
  rolled item-instance values; hardmode meaning is not inferred.
- `base_items`: native metadata identity, name, dimensions, drop level, class,
  domain, inheritance stem, direct tags and implicit mods. Unique owner joins
  retain armour, requirements, shields, weapons/reload, spirit, inherent skills
  and flasks as complete component rows. Charges use the declared **string ID**
  join, not a numeric row or display-name guess. Missing components remain null.
- `soul_cores` and `soul_core_categories`: item identity, type, limit, next tier,
  every constraint/unknown field, categories, and separate regular/bonded
  stat/value groups. Empty class arrays and `Unknown0` do not imply a wildcard
  category. Empty stat groups remain visible and diagnosed. Duplicate
  core/category occurrences remain separate rows with a diagnostic.
- `utility_buffs`: primary `BuffDefinitions.Stats`/`UtilityFlaskBuffs.StatValues`
  pairs, the independent secondary value array, and separate granted flags,
  granted stats and condition stats. An empty secondary array does not erase
  primary values or immunity flags.
- `essence_mods`: declared essence/category/mod/display-mod links, ordered
  outcome mods and raw weights. Only equal-length arrays also get paired
  `outcomes`. Unequal arrays retain both sides, `outcomes: null`, and an
  `essence_outcome_weight_alignment_unresolved` diagnostic. No uniform or
  default probabilities are invented.

Auxiliary rows retain ModType/ModFamily, WeaponClasses, SoulCoreTypes/Limits
and essence definitions/categories/replacement types. Every row has an exact
physical reference. Actual component units and inherited `.it` tags require
separate evidence before applicability or runtime conversions are implemented.

## Actor facts

`actors.json` retains every exact constant Value/Divisor triple, all 100
DefaultMonsterStats rows, MonsterVarieties and MonsterTypes, resistance rows,
summoned-monster links, intrinsic minion stat/value facts and spectre overrides.
Auxiliary physical rows preserve MinionType/MinionStats, every gem-level scaling
lookup, totem variations and the empty display/on-death tables.

Monster metadata stems/add-on order, raw category/armour/segment links, class
relations, ordered mods/tags/effects and nullable targets remain separate.
`SummonedSpecificMonsters.Id` stays `id_raw`; no effect-to-variety bridge or
stable identity is inferred from it. Source floats, negative zero, duplicate
level owners and nullable monster references are retained. A repeated minion
level row is not deduplicated or interpolated.

No constant divisor is a universal game unit. The exact source DisplayLevel
order 1..100 and nonzero constant divisors are checked for this fixed profile;
server formulas, selected-enemy presets, per-actor defaults and gem-to-minion
identity still need independent validation. This does not certify a playable
monster/minion catalogue or Chinese-realm numerical facts.

## Acceptance and remaining work

Native decoding, acquired-target relationships, source identities and complete
graph-instance acceptance use the existing checks. Ambiguous component/charge
owners, broken acquired references, inverted nonnull regular mod intervals and
unequal required stat/value or weight arrays reject generation before output.
The separately unproved Essence outcome alignment is retained as described
above; the exporter never truncates an array to manufacture agreement.

`facts:validate` independently checks graph instances and replays all physical
tables/projections under the same pinned tools. This replay shares producer
logic and is not independent gameplay verification. Real-source field/primitive
comparison and independent review remain necessary before accepting an increment.
The focused synthetic regression suite is `test_native_items_actors.py`; it
covers eight slots, owner ambiguity, unknown/empty/null distinctions, separate
channels, exact floats/IDs, negative cases and fresh-process determinism.

No CSD interpreter is part of this profile. Complete `.it`/`.ot` inheritance,
description includes and formatting, item/actor units, SoulCore category policy,
unique-item catalogue curation, support expression semantics, quality scope and
runtime adoption remain separate. Keeping a complete source inventory here does
not require publishing every physical row in a player-facing runtime package.
