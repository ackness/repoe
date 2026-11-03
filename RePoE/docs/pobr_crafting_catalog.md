# PoBR special-currency catalog

`RePoE.pobr_crafting_catalog` projects the neutral
[seven-table crafting facts](native_crafting_facts.md) into PoBR's runtime file
`data/<patch>/overlay/trade_crafting_sources.json` and adds it to a published game
part. PoBR then imports the game part as a fixed artifact; it no longer projects
crafting data itself. The projector moved here from PoBR's
`pipeline/imports/crafting_inputs.py` (PoBR `897463d5`) without changing its
policy or output bytes.

## Assembly

```sh
git fetch origin tag handoff/native-crafting-20261101
mise run publication:crafting-catalog -- assemble \
  --sequence 2 --name game-crafting-20261103 --out .cache/publication/game-crafting
mise run publication:git-handoff -- --package .cache/publication/game-crafting
mise run publication:crafting-catalog -- game-input --package .cache/publication/game-crafting
```

`assemble` takes the `game` and `crafting` inputs of one validated sequence of
`publication/index.json` (default: the head) and reads both archives from local
Git objects; it never fetches. It authenticates the whole crafting package,
including the seven original tables, before reading `crafting.json`. The new
part copies every original game member byte for byte and adds only the projected
file. Assembly fails unless the projected bytes equal the SHA-256 that the game
part's own snapshot manifest (`data/<patch>/manifest.json`) already declares, so
the consumer's snapshot and runtime identities cannot change by accident. A part
that already contains the catalog is rejected. The ZIP is deterministic: a replay
of the same inputs and module produces the same bytes and, through
`publication:git-handoff`, the same orphan commit.

The part's `manifest.json` keeps the consumer contract `pobr-build-data-part/v1`
and records:

- `retained_input_package`: the complete source game declaration;
- `projection.crafting_input`: the complete crafting declaration;
- `projection.producer`: the SHA-256 of this module at assembly time;
- `projection.output`, `summary` and the projection `diagnostics`.

Source diagnostics stay in the crafting package's `crafting.json`. `game-input`
prints the index `game` input for `publication_index draft` after the handoff tag
has been pushed. Publishing remains a separate coordinator action.

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
