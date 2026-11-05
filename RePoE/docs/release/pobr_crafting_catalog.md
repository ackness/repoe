# PoBR special-currency catalog

`RePoE.release.crafting_catalog` projects the neutral
[seven-table crafting facts](../native/native_crafting_facts.md) into PoBR's runtime file
`data/<patch>/overlay/trade_crafting_sources.json`. `mise run release:build`
runs it as the `crafting-catalog` job of `release/<patch>/domains.json` (see
[RELEASING.md](../../../RELEASING.md)); PoBR imports the resulting game package and
no longer projects crafting data itself. The projector moved here from PoBR's
`pipeline/imports/crafting_inputs.py` (PoBR `897463d5`) without changing its
policy or output bytes.

`facts_document` authenticates the whole crafting package, including the seven
original tables, before reading `crafting.json`; `project` applies the policy
below. Source diagnostics stay in the crafting package's `crafting.json`.

## Catalog policy

The neutral producer retains all physical rows and distinguishes `Mod`,
`DisplayMod`, ordered `OutcomeMods` and raw weights. It preserves all eight stat
slots, regular/hardmode endpoints, nulls, zeros and unknown fields. Only selected
internal references between the seven tables are validated.

The projection applies PoBR's catalog policy:

- Select `CurrencyVerisiumAlloy*`, `CurrencyPerfectEssence*` and
  `CurrencyCorruptedEssence*` currency IDs, labelled `alloy` / `essence`.
- List `OutcomeMods` when present; otherwise list a nonnull `Mod`. This is a
  catalog policy, not proof of eligibility or probability. `DisplayMod` is never
  substituted.
- Aggregate by source label and exact Mods ID, union the identified item classes
  and sort deterministically. Empty classes remain empty, never a wildcard.
- Project every identified regular-stat slot, 1 through 8, without merging
  duplicate stat IDs. Zero and negative endpoints are preserved. A selected
  identified stat with missing or inverted endpoints fails; hardmode values never
  replace the regular channel.

The result is a category/identified-regular-stat catalog, **not a complete mod
effect packet**. A null stat reference with nonzero raw endpoints remains a
diagnostic with its physical row, slot and exact values. No stat ID, zero effect
or probability is invented. Language missing from the source identity remains
unknown; the projection does not observe client identity or accept a source.

## 0.5.5.5 result

The bounded 0.5.5.5 projection selects 89 source rows and produces 92 catalog
records (31,587 bytes, SHA-256
`0c32984db22e5e4d9a7fb8bfe3bd5b79340673ee10c804bf35bcba652da68fb2`), the file
PoBR's snapshot `73b2d77e...` declares. Seven unresolved outcome/weight
alignments are in unselected ordinary currencies and remain source diagnostics.
`AlloyBallistaLimit1`, Mods row 15531, slot 2, has a null stat and regular
endpoints `-20/-20`; it remains explicitly unrepresented in this identified-stat
catalog.
