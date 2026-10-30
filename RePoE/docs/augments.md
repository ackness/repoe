### `augments.json` (PoE2)

Exports `SoulCores` and their `SoulCoreStats` rows. The top-level object is keyed
by `BaseItemType.Id`. Rows without a base item relation are skipped, as before.
Each augment has:

- `required_level`: `RequiredLevel`, omitted when zero.
- `type_id`, `type_name`: `Type.Id` and the display `Type.Name`, when present.
- `limit`: Display text from `Limit.Text` formatted with `Limit.Limit`, or the
  string form of the limit if that text is empty.
- `categories`: An object keyed by `StatCategory.Id`, with the fields below.

Each category has:

- `target`: The existing display field: `StatCategory.Display` if nonempty,
  otherwise a list of `TargetItemClasses.Name` strings. Its string/list shape is
  retained for compatibility; it is not a stable identity.
- `target_item_classes`: A list of the exact `TargetItemClasses.Id` strings, in
  source order, even when `target` uses a group display string. An empty source
  list stays empty; the exporter does not infer classes from display text or
  assign gameplay meaning to an empty list.
- `stats`: The regular `Stats` entries paired positionally with `StatsValues`.
- `bonded_stats`: The separate `BondedStats` entries paired positionally with
  `BondedStatsValues`. These retain their bonded condition; they are not added to
  or substituted for the regular stats by the exporter.
- `stat_text`, `bonded_stat_text`: Display translations of the corresponding
  group, when translation returns nonempty lines.

Each stat entry contains the existing `id` (`Stats.Id`) and `local`
(`Stats.IsLocal`) fields, plus `value`: the exact raw integer from its paired
value array. Zero, negative values, order and repeated stat IDs are preserved.
Values are not scaled, summed, inferred from text or interpreted as game effects.
Stat groups with no entries omit their stat and text fields, as before; missing
translations do not remove raw stats or values.

Both stat/value array pairs must have equal lengths, including when either array
is empty. Missing columns fail rather than supplying default values. Duplicate
base item IDs, or duplicate category IDs within one augment, fail instead of
overwriting earlier rows. No new JSON files are written by `augments.write()`
when these input errors occur; any pre-existing output files remain untouched.

The `value` and `target_item_classes` additions preserve the existing fields and
display translation inputs. Consumers that reject unknown fields need to accept
the additions. The offline synthetic fixtures run the actual exporter and verify
both formatted and compact JSON. They do not validate a real client patch,
translation content, target applicability or the gameplay rules for bonding.
