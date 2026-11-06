# English gem descriptions

`RePoE.release.gem_descriptions` writes `overlay/gem_descriptions.json`, the
English description of every player gem, for PoBR's data contract 1.3 (defined in
PoBR's [data architecture](https://github.com/ackness/pobr/blob/master/docs/data-architecture.md#3-发布与导入契约)).
`mise run release:build` runs it as the `gem-descriptions` job, only in a
declaration that lists it (`release/0.5.5.5-3/` onwards); `release/0.5.5.5-2/`
has no such job and still reproduces `game/0.5.5.5-2` byte for byte. The job
is Python in this repository and needs no `pobr-data` code, so the adapter stays
pinned to `contract/1.1`; `contract/1.3` only adds the optional file and scopes.

PoBR's English web loads no language package, so the English text has to come
from the game package. The translations are the language owner's: the
`display_texts` scopes of the same names, keyed by the same ids.

## Member

```json
{
  "_meta": {
    "schema": "repoe-gem-descriptions/v1",
    "generator": "RePoE.release.gem_descriptions",
    "facts_manifest_sha256": "<the facts identity the job read>",
    "game_patch": "0.5.5.5"
  },
  "scopes": {
    "ActiveSkills.Description": {"<ActiveSkills.Id>": "<raw English>"},
    "GemEffects.SupportText": {"<GemEffects.Id>": "<raw English>"}
  }
}
```

The snapshot manifest declares it as the overlay domain `gem_descriptions`
(the `snapshot-manifest` job's `add`). Keys are sorted; the layout is PoBR's
runtime JSON (two-space indent, UTF-8, final newline).

## Rows

Only rows reached from the package's own player gems, so every id is one PoBR
can look up:

| Scope | Ids | Text |
| --- | --- | --- |
| `GemEffects.SupportText` | every `variant_id` in `overlay/gem_effects.json` (job `gem-effects`) | facts `gems.json` `effects[].support_text` of the GemEffects row with that `Id` |
| `ActiveSkills.Description` | `active_skill` of the `base/granted_effects.json` (job `skills`) entry each gem effect's `granted_effect_id` names | facts `tables/ActiveSkills.json` `Description` of the row with that `Id` |

Empty (or blank) text is left out. A variant missing from GemEffects, a granted
effect missing from `granted_effects.json`, an `active_skill` missing from
ActiveSkills, or a duplicate `Id` refuses the build.

On `game/0.5.5.5-3` (facts `050fcf93…`, the `rebound` identity): 1120 gem
effects give 614 support texts (all support variants but
`ChanceToFreezeSupport` and `FeedingFrenzySupportTwo`, which have none) and
441 active-skill descriptions; 566 of the 567 trade-catalog supports and 398 of
the 399 trade-catalog active gems (all but Ice Fragments) have one.

## Raw text and markup

Text is the client's string, unchanged: `[A]` and `[A|B]` tags, trailing
spaces and `\r\n` stay, so the translation repository can compare English byte
for byte. PoBR renders `[A|B]` as B and `[A]` as A. These are the only markup
forms in the 0.5.5.5 texts; anything else (an unmatched `[` or `]`, nesting,
more than one `|`, a `|` outside a tag, `<…>`, `{…}`) refuses the build, so a
new form is reviewed before it reaches a display rule that does not know it.

Tests: `tests/release/test_gem_descriptions.py` (selection, raw text,
determinism, refusals) and `test_gem_descriptions_job_reads_the_facts_and_adds_its_member`
in `tests/release/test_build.py` (the job inside a build).
