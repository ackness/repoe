# Selected actor template literals

`repoe-actor-templates/v1` preserves an explicitly fingerprinted `.ot`/`.otc`
inventory, separately from the DAT actor projection and item `.it` inheritance.
It exports literal syntax and parent links. It does not evaluate scripts, merge
fields, interpret stat names, project a PoBR `mod_list`, or approve/adopt a source.

The offline Python API is `RePoE.native_actor_templates.create_candidate`, with
the same keyword arguments as `native_item_inheritance.create_candidate`:
`source_lock`, `source`, `raw`, `out`, `expected_source_lock_sha256`. There is no
new command or default exporter integration. It reuses the item exporter's
`native_descriptions` JSON, byte verification and completion-last publisher.
The item parser itself remains unchanged: its path/key grammar cannot represent
these actor paths, punctuation-bearing stat keys and multiline event assignments.

The schema-1 source envelope declares an official-client resource candidate,
explicit PoE2 patch/realm, caller-declared acquisition status/evidence, unique
`roots`, and `resources` with positive byte lengths and SHA-256. An external lock
digest establishes byte identity, not authenticity. First-acquisition observed
hashes remain observations; they must not inherit a previous DAT/item acceptance.
The original lock is retained verbatim. Language identity is not inferred from
default paths, the realm declaration or English-looking literals.

Bounds are 64 resources, 1 MiB per resource, 4 MiB selected raw total, 16 resources
per parent traversal, 32 component scopes and 128 nested braces per opaque RHS.
Only portable `Metadata/.../*.ot` and `.otc` paths are accepted. Missing, cyclic
and deep parent traversals receive explicit diagnostics rather than empty field
defaults. Inventory outside the bounded root traversals rejects publication.
All supplied raw pins are checked before syntax parsing and rechecked before
publication. New output directories must be beneath this checkout's `.cache/`,
outside raw input; symlinked resource paths and existing outputs are rejected.

`templates.json.files[resource]` retains:

- Every physical UTF-16LE line, original line ending, raw text and absolute
  half-open byte span including the BOM offset. Joining these lines with the BOM
  reconstructs the entire raw resource.
- Ordered directives, named component blocks, field occurrences and an `order`
  sequence connecting them. Empty/unknown/nested component names and duplicate
  fields remain distinct. Block hashes bind their complete raw slices.
- Original field keys, including punctuation such as `+%`, and RHS literals with
  inline comments. No RHS becomes a numerical default or an evaluated value.
- Balanced braced assignment RHS as `opaque-braced`, including multiline event
  bodies. Their quotes, comments, statements and internal braces remain literal;
  statements are not reclassified as component fields or executed.

The structural scanner ignores braces inside escaped single/double quoted
strings and `//` line comments; `#` whole-line comments are retained too. Supported
headers are `version`, `abstract`, and one literal `extends`. Unsupported syntax,
unbalanced braces/quotes, malformed UTF-16 or trailing text after a braced RHS
reject the candidate before publication. There is no unknown-line filter or
claim of a universal OT grammar. Original acquired raw bytes remain available
when parsing fails. C-style block comments, arbitrary header directives and
general expression/script semantics are not implemented.

`extends` retains its original literal/span. The local path convention appends
the child's `.ot` or `.otc` suffix to a non-`nothing` stem; literal `nothing`
terminates. The fixed PyPoE OT reader uses the same `.ot` stem convention, but
this is not an official inheritance/merge law. A target requires separately
preserved index/location and acquired-byte evidence. A case-insensitive index
hash match does not establish authoritative spelling or rule out hash collision.
The `.otc` suffix branch has synthetic coverage only in this increment.

`roots[resource]` records `chain_child_to_parent`, its termination status and an
optional missing/cycle/depth diagnostic. This graph is separate from the syntax
and from `interpretation`, whose merge law, mod-list and effect evaluation remain
null. It does not combine the six DAT modifier groups or ordered `InheritsFrom`
additions, infer client/server applicability, or equate absent data with zero.

The three output files are `templates.json`, exact `source-lock.json`, and
completion-last `manifest.json`. The partial/non-production manifest binds raw,
output and producer fingerprints, source declarations, syntax counts and unresolved
root counts. Full raw bytes and acquisition/location receipts remain external
inputs owned by RePoE; no complete archive belongs in PoBR Git or artifact refs.

One real international 0.5.5.5 candidate contains six OT files, 11,172 raw bytes,
three roots, 43 blocks, 104 fields and nine opaque RHS fields. BearCompanion and
LivingLightning extend PlayerFollowingMinionBase, which extends
PlayerSummonedMinionBase; SummonedRagingSpirit directly extends the latter.
PlayerSummonedMinionBase extends Monster, which declares `extends "nothing"`.
All three schema-declared OTC candidates lack matches in the selected fixed index.
These are bounded observed facts, not complete directory-name evidence, numerical
effect certification, acquisition acceptance, or a mod-list migration.

## Recovering the observed draft

The immutable handoff is recorded in
[`publication/actor-templates-0.5.5.5-draft.json`](../../publication/actor-templates-0.5.5.5-draft.json).
It pins the RePoE repository, full artifact revision, archive path, byte length,
SHA-256, expanded size and top-level manifest. The source branch contains only
code and publication metadata; the complete data archive is on the separate
RePoE artifact ref. Publication does not change its draft acquisition status.

The archive has schema `repoe-actor-template-source-package/v1`. Authenticate its
outer archive and exact `manifest.json.files` inventory before extracting it to
a fresh temporary directory. `raw/` contains all six acquired resources;
`facts/` contains the corrected producer's three output files. Original receipts,
failed runs, selected index records, the MonsterVarieties table and its original
F77 manifest are under `evidence/`. Only that table is included from the F77
inventory. `portable-path-map.json` locates included copies of historical absolute
receipt paths; those old paths are evidence strings, not replay input paths.

Using the pinned `producer_revision`, replay without network access:

```python
from pathlib import Path
from RePoE.native_actor_templates import create_candidate

restored = Path("/temporary/authenticated-source-package")
create_candidate(
    source_lock=restored / "facts/source-lock.json",
    source="actor-templates-0.5.5.5-draft",
    raw=restored / "raw",
    out=Path(".cache/fresh-actor-replay"),
    expected_source_lock_sha256="60f2be3627ff1be190367c2379d01162841a59c57fd1ca42df7caacc94136f22",
)
```

A fresh remote Git fetch verified all 62 archive members and the producer blobs;
OS-denied-network raw-to-facts replay reproduced all three output files byte for
byte. Replaying the acquisition and full index additionally needs their separately
pinned prior index/range cache and decoder; those large inputs are not embedded
in this small handoff. Neither replay certifies official semantics. In particular,
the meaning of `set_`, OT/DAT precedence and `Special_Mods` applicability remain
unclosed, so BearCompanion, LivingLightning and SummonedRagingSpirit keep their
existing compatibility effects in PoBR.
