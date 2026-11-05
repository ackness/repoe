# RePoE documentation

Formats and contracts, grouped like the code. Release procedure:
[RELEASING.md](../../RELEASING.md); repository rules:
[AGENTS.md](../../AGENTS.md).

## Client acquisition: `RePoE/client/` → [client/](client/)

| Document | Covers |
| --- | --- |
| [client-version.md](client/client-version.md) | `client:version`: observing the patch the official endpoint advertises |
| [client-sources.md](client/client-sources.md) | `client:source`: acquiring one fixed source, offline or with a network budget; ownership and protocol history |
| [client-source-draft.md](client/client-source-draft.md) | `client:draft`: an unreviewed first acquisition |
| [client-index.md](client/client-index.md) | `client:locate`: resource lookup in a fixed index |
| [source-rebinding.md](client/source-rebinding.md) | `source:rebind`: the portable facts envelope a release declaration's `facts` names |

## Native facts: `RePoE/native/` → [native/](native/)

| Document | Covers |
| --- | --- |
| [native_facts.md](native/native_facts.md) | `facts:candidate` / `facts:validate`: the base profile, producer identity and re-validation |
| [native_core_skills.md](native/native_core_skills.md) | Profile `core-skills-a0` |
| [native_gems.md](native/native_gems.md) | Profile `gems-constraints-a1` |
| [native_items_actors.md](native/native_items_actors.md) | Profile `items-actors-bc` |
| [native_tables.md](native/native_tables.md) | `tables:candidate`: supplemental DAT tables |
| [native_descriptions.md](native/native_descriptions.md) | `descriptions:candidate`: CSD description branches |
| [native_item_inheritance.md](native/native_item_inheritance.md) | Item `.it` inheritance |
| [native_actor_templates.md](native/native_actor_templates.md) | Actor `.ot`/`.otc` template literals |
| [native_player_context.md](native/native_player_context.md) | `facts:player`: starting options, glossary and source context |
| [native_crafting_facts.md](native/native_crafting_facts.md) | The seven-table crafting facts |
| [native_locale_probe.md](native/native_locale_probe.md) | Memory locale decoding |
| [decoded_locale_tables.md](native/decoded_locale_tables.md) | Decoded language observations (`repoe-localized-tables/v2`) |
| [description_relations.md](native/description_relations.md) | Observed description-relation tables |

## Game-package release: `RePoE/release/` → [release/](release/)

| Document | Covers |
| --- | --- |
| [pobr_crafting_catalog.md](release/pobr_crafting_catalog.md) | The `crafting-catalog` job |
| [pobr_historical_trees.md](release/pobr_historical_trees.md) | The `historical-trees` job |
| [pobr_gem_descriptions.md](release/pobr_gem_descriptions.md) | The `gem-descriptions` job (English gem descriptions) |
| [buff_source_reconciliation.md](release/buff_source_reconciliation.md) | The retained buff-source reconciliation in `sources/` |

The adapter jobs are documented with the adapter:
[README](../../tools/pobr-data-adapter/README.md), one
[`docs/ordinary-<domain>.md`](../../tools/pobr-data-adapter/docs/) per domain
and the [policies](../../tools/pobr-data-adapter/policies/README.md).

## Legacy JSON formats: `RePoE/parser/`

One page per file the upstream exporters write:
[active_skill_types](active_skill_types.md), [augments](augments.md) (PoE2),
[base_items](base_items.md), [characters](characters.md),
[cluster_jewel_notables](cluster_jewel_notables.md),
[cluster_jewels](cluster_jewels.md), [cost_types](cost_types.md),
[crafting_bench_options](crafting_bench_options.md),
[default_monster_stats](default_monster_stats.md), [essences](essences.md),
[flavour](flavour.md), [fossils](fossils.md), [gem_tags](gem_tags.md),
[gems](gems.md), [item_classes](item_classes.md), [mod_types](mod_types.md),
[mods](mods.md), [stat_translations](stat_translations.md),
[stats](stats.md), [tags](tags.md). Their JSON schemas are in
[`RePoE/schema/`](../schema/).

## Repository history

[history.md](history.md) records the one-time history cut, the commit mapping
([history-rewrite-20261103.json](history-rewrite-20261103.json)) and how to
migrate an existing checkout.
