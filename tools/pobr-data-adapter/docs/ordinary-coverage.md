# Strict and forward mode, and the coverage report

`--mode strict|forward` selects how a domain converter treats a per-entity
content gap: a new, removed or changed entity that the pinned policy does not
cover yet. The default is `strict`. An unknown value, a missing value or a
repeated `--mode` is an error.

| Mode | On a content gap | Receipt |
| --- | --- | --- |
| `strict` | Fails at the first gap with the same error string, at the same point, as before the flag existed | Same fields and content, apart from the compiled `adapter.implementation_revision` |
| `forward` | Records the gap as an issue, applies the issue's action and continues, so one run reports every gap | `conversion.coverage` (below), present even with no issues |

Integrity errors fail in both modes: pins, envelopes, column contracts,
duplicate keys and dangling foreign keys. Only the per-entity decision points a
domain lists in its own page become issues; forward mode never catches a
converter's error. Coverage is a report: the adapter exits 0 in forward mode
when only issues were found, and the output keeps the same file set.

The flag is accepted for every domain. The converters that take the coverage
collector are skills, gem-quality, stat-set-codec, gem-effects, skill-stat-map,
skill-overrides and passive-tree. Until a domain's page lists forward decision
points, its forward output equals its strict output and the coverage report is
empty.

## Issue

Each issue is one JSON object:

| Field | Type | Meaning |
| --- | --- | --- |
| `domain` | string | The domain label, equal to the `--ordinary-domain` value of every converter that takes the collector (`gem-effects`, `passive-tree`, ...) |
| `kind` | string | Stable kebab-case name of the decision site, listed in the domain's page |
| `entity` | string | The stable business identity a policy entry would key on (gem base item id, granted effect id, node id, override key); never a bare physical row |
| `action` | string | `quarantined`: the entity is omitted. `emitted-with-gap`: the entity is emitted, but some of its fields are not owned. `retained-legacy`: the old entry is kept unchanged. `listed`: informational only |
| `message` | string | Exactly the error that strict mode returns at this point; for informational issues, describes the gap that strict mode already tolerates |
| `observed` | object, optional | Free-form JSON object with sorted keys: the values needed to write the policy entry that closes the issue (for example `definition_sha256`, `candidate_lines`, a field list). Omitted when empty |

## `conversion.coverage`

Written into the domain receipt's `conversion` object in forward mode only. It
adds no top-level receipt key.

```json
{
  "format": "pobr-adapter-coverage/v1",
  "counts": {"emitted-with-gap": 0, "listed": 1, "quarantined": 0, "retained-legacy": 0},
  "issues": [
    {"domain": "gem-effects", "kind": "new-gem", "entity": "...", "action": "listed", "message": "...", "observed": {"candidate_lines": ["..."]}}
  ]
}
```

- `counts` always has all four actions, including zeros.
- `issues` is sorted by `domain`, `kind`, `entity`, then `action` and `message`,
  each compared as a plain byte string, so another tool can reproduce the order.
- Object keys are serialized in sorted order, like the rest of the receipt.

Changing this shape is a coordinated change: the adapter
(`src/ordinary_facts/coverage.rs`), the release build that aggregates the
reports, and this page.
