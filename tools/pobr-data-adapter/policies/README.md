# Domain policies for pobr-data-adapter

These small JSON files record bounded interpretation decisions. They are inputs
to adapters and regression tests, not generated game databases or temporary output.
Source acquisition and publication happen in this repository's exporters.

| Domain | Policy scope |
| --- | --- |
| `actors/` | Minion/spectre records, prepared compatibility and skill links |
| `base-items/` | Inherited tags and retained base-item fields |
| `stat-descriptions/` | Description rendering, relational lookups and diagnostics |
| `passive-tree/`, `tree-corrections/` | Tree compatibility templates and the exact historical orphan quarantine |
| `skill-codec/`, `skill-overrides/`, `skill-stat-map/` | Skill branches, stat sets and explicitly retained mappings |
| [gem-quality/](gem-quality/README.md) | Target quality facts and the preserved effect-wide interpretation |
| `runtime-constants/`, `boss-poise/`, `unarmed/` | Explicit constants, representative presets and unarmed facts |
| `socketables/`, `catalysts/`, `item-grants/` | Socketable, catalyst and item-granted skill decisions |
| `uniques/` | Pinned retained unique catalog bound for the relation projection |

These policies are inputs of `tools/pobr-data-adapter`, and its Rust tests read
them. They moved here from PoBR `pipeline/policies/` with the adapter. Historical provenance
fields inside a policy or source receipt retain their original paths and hashes;
they describe the recorded input, rather than a path to resolve in today's checkout.

Changing a policy needs source evidence and relevant consumer verification. Moving
one does not approve a source, change a game value or close an unresolved semantic gap.
