# Native gem and constraint facts

`--profile gems-constraints-a1` extends the same [native ingress](native_facts.md)
and [skill-core contract](native_core_skills.md) with 24 physical tables. The
output format is `repoe-native-facts/v3`, a partial candidate with
`production_ready: false`. Neither a playable catalogue nor evaluated support
eligibility is claimed. Default `base-v1` and explicit `core-skills-a0` remain
available with their existing formats and semantic payload contracts.

## Offline input and commands

This profile requires exactly 39 native DAT resources plus the Default PSG, at
their existing game-relative paths under the caller's raw root. It uses the same
fixed international `0.5.5.5`, decoder and schema checks as the earlier profiles;
no filesystem discovery, download, legacy JSON helper or virtual view runs here.
The extra tables are:

```text
SkillGems                    GemEffects                GemTags
SupportGems                  SupportGemFamily          ItemExperienceTypes
ItemExperiencePerLevel       SkillCraftingData         SkillGemSearchTerms
SkillGemSupports             BaseItemTypes             ItemClasses
Tags                         ActionTypes               ActiveSkillWeaponRequirement
WieldableClasses             ClientStrings             AlternateSkillTargetingBehaviours
VirtualStatContextFlags      ShapeShiftForms           MinionType
PassiveSkillStatCategories   ItemClassCategories       ItemStances
```

Each is `Data/Balance/<Table>.datc64`. The exact selected table list is maintained
in [`native_gems.TABLES`](../native_gems.py). Every raw size/hash is checked before
decoding, all acquired foreign rows/string-ID joins must resolve, and exact row
widths, variable spans and decoder warnings retain the existing rejection rules.

The selected schema-1 source entry requires `profile: "gems-constraints-a1"` and
the same explicit acquisition evidence/status shape as the skill-core profile.
Only caller-declared `unreviewed-acquisition-draft` or `reviewed-source-input` is
accepted. Evidence fingerprints remain opaque declarations, not authenticated
documents or automatic approval. Even reviewed input produces a non-runtime
partial candidate. A proposed source lock can record observed draft hashes
without modifying PoBR's reviewed source lock.

```sh
mise run facts:candidate -- --profile gems-constraints-a1 \
  --source-lock /path/to/proposed-sources.lock.json \
  --source official-client-0.5.5.5-gems-constraints-draft \
  --raw /path/to/raw --out .cache/gems/candidate-a
mise run facts:validate -- --profile gems-constraints-a1 \
  --source-lock /path/to/proposed-sources.lock.json \
  --source official-client-0.5.5.5-gems-constraints-draft \
  --raw /path/to/raw --facts .cache/gems/candidate-a \
  > .cache/gems/acceptance.json
```

Output has **47 payloads plus the manifest**: 39 complete physical tables, the
existing graph/passive/quality/diagnostics/skill-core documents, exact source-lock
bytes, `gems.json` and `constraints.json`. Physical fields, unknown flags, source
row order and arrays are retained. No data row is removed because PoB lacks it.
The manifest also fingerprints `native_gems.py`, the current replay producer and
all 117 trusted decoder sources. Existing-output refusal and completion-last
publication are unchanged.

## Gem item identity and relations

`gems.json` is a **source inventory**. Every `SkillGems` row produces an `items`
entry. `gem` contains its physical row and related `BaseItemTypes {row,id}`.
There is no invented `SkillGems.Id`: the base item's metadata ID identifies the
item. Names, gem effects and display text are not unique item keys. Repeated base
owners remain separate rows with `duplicate_gem_item_identity`; an operational
unique catalogue must resolve that ambiguity before use.

Each entry preserves base name/class/tags, raw gem type/colour and attribute/minimum
requirements, experience/global-level relations, separate variant relations and
all matching support metadata rows. `base_skill_gem`, regular and awakened variants
use the same row-plus-item shape; the Vaal item relation targets BaseItemTypes.
Source rows and named unknown flags remain reachable through complete raw refs.

`items[].gem_effects` retains each `SkillGems.GemEffects` source slot, including
duplicates, shared effects and nullable slots. The separate `effects` collection
preserves every `GemEffects` identity, primary granted effect, ordered additional
granted effects and tags. Their stat sets are linked by the existing `skills.json`
effects collection, preserving that distinct nesting level. No execution order or
actor ownership is inferred. `ActiveSkills.GrantedEffect` remains its original
string in skill-core facts; it is not used to fabricate reverse links.

Other source-ordered collections retain tags and their stat identities, support
owners/family arrays/lineage, family text, SkillGemSupports associations, experience
types and every experience-level row. Repeated family/association links and equal
owner/level rows are not collapsed. Same display names do not merge IDs. Empty
families and missing support metadata stay visible, rather than implying an item
is unusable or supports nothing.

Diagnostics distinguish duplicate support owners, nullable gem-effect slots,
unreferenced gem-effect definitions, empty support families, support-class items
without metadata, and disagreement between native effect support flags and
metadata presence. These are source observations, not filters or final gameplay
verdicts. `SkillGemSupports` is not treated as an exhaustive whitelist.

## Ordered constraints and remaining policy

`constraints.json` contains separate source-ordered `effects`, `active_skills`,
`weapon_requirements` and `wieldable_classes` collections. It retains the named
support/minion flags, type arrays, active/action/weapon/shape relations, visibility
facts, requirement stat/client-string links and wieldable item-class/tag relations.
WieldableClasses has no stable Id; its physical row remains paired with related
item-class identity and its raw evidence, not a manufactured class ID.

Allowed/excluded/added type arrays retain ordered `ActiveSkillType {row,id}`
identities. This includes actual `OR`, `AND` and `NOT` rows. They are not flattened
to sets and are not evaluated by a support VM. Nulls and duplicates survive.
Unknown flags are not renamed "hidden", "legacy" or "playable". Website visibility
and source item class do not determine the player-accessible catalogue.

Requirements, item/gem/current/effective/actor levels, experience, quality, stat
units, interpolation and rounding are not calculated here. CSD/text/locale closure,
actor formulas, metadata inheritance and full foreign-key closure remain outside
this profile. Existing Snipe scope and absent-base tree diagnostics are retained.
Unavailable relationship groups add `target_kind` in v3, distinguishing
`schema-enumeration`, `unavailable-physical-table` and `unknown`; schema enums are
context, not missing DAT downloads or certified game formulas.

The maintained acceptance command verifies exact inventory/hashes/source-lock
bytes, current producer/trusted decoder identity, complete raw replay and the
independent repeated-graph invariant. Independently comparing projections to source
rows remains necessary: replay alone shares producer logic. A correct facts seal
does not activate data, certify all rows playable or prove full game correctness.
