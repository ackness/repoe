# Unique relations from pinned facts and the retained catalog

`--ordinary-domain uniques` writes a new `overlay/unique_relations.json`
(`unique_relations/v1`): a structured `unique -> base -> mods/roll/variant`
relation over every entry of the pinned published `overlay/uniques.json`, with
vendor base-name text resolved against target `BaseItemTypes`/`ItemClasses` by
exact `Name` equality.

The PoE2 client has no unique item definition table: unique->base and
unique->mods/roll/variant assignment is server-side and the community PoB2
catalog is the retained source. This domain does not re-certify that text as
target facts. It preserves every vendor field byte-traceable (`raw` is copied
unchanged), adds a stable, machine-readable projection, and records which
fragments are verified joins versus retained compatibility.

Use the standard `--ordinary-facts`, `--facts-manifest-sha256`, `--version`,
and fresh `--out`, plus all four pinned compatibility arguments:
`--codec-source`, `--codec-source-sha256`, `--codec-policy`, and
`--codec-policy-sha256`. The compatibility source is the exact published
`0.5.5.5/overlay/uniques.json` member of the game part; the
[relations policy](policies/uniques/0.5.5.5-relations-policy.json)
binds its bytes, declared member path, vendor repository/revision and
`uniques/v1` source metadata. Policy version, source hash/size and vendor
identity must match before parsing; unexpected `_meta` vendor fields are kept
under `_meta.legacy_metadata`, but unexpected per-unique fields reject rather
than being dropped silently.

## Output shape

Each `uniques[]` entry carries `name`, `item_type`, `raw` (byte-preserved),
`bases`, `selection`, `implicit_count`, `mods` and `directives`:

- `bases[]`: raw lines that exactly name a target `BaseItemTypes.Name`, with
  `source_line` (0-based index into `raw`), annotations and `base_items`
  candidates (`row`, stable `Id`, resolved `ItemClasses` Id). `resolution` is
  `resolved` or `ambiguous`; ambiguous names keep every candidate, never a
  guess. Vendor base lines that resolve to no target row are not dropped: they
  remain mod lines, matching today's consumer, and the index `base` column is
  cross-checked in diagnostics.
- `selection`: parsed `Variant:`/`Version:` declarations (ordered names; the
  `{variant:N}`/`{version:N}` ordinals index them), `alt_variant_slots`,
  `groups` (every `{group:N}` id observed), and any `Selected Variant`,
  `Selected Version`, `Selected Alt Variant<n>`, `Selected Variant Group:`
  `g=v` and `Allow Duplicate Variants` lines with their values and source
  lines.
- `mods[]`: each effect line with `source_line`, `kind` (`mod` or
  `grants_skill`), stripped `text`, `implicit` flag driven by `Implicits:`,
  annotation fields (`variants`, `versions`, `groups`, `tags`, `flags`,
  `range`, `corrupted_range`) and any unmodelled annotations kept verbatim in
  `annotations` (`{key, value}` pairs). `Grants Skill:` lines add a
  `grants_skill` convenience object — `level` as `{min,max}`/`{value}` for
  `Level (a-b)`/`Level N` forms, `skill_name` alone for unlevelled vendor
  forms; unparseable forms are diagnostics. Roll templates `[+-]?(min-max)`
  (optional sign, negative
  and decimal endpoints) emit `rolls` entries `{min, max, sign}`; integral
  endpoints stay integers.
- `directives[]`: remaining item-text headers (`Sockets:`, `Limited to:`,
  `Radius:`, `League:`, `Source:`, `Upgrade:`, `Replica`, `Crafted:`, `Note:`,
  `Item Level:`, `LevelReq:`, `Quality:`, `Requires `) kept verbatim with
  `kind` and `source_line`.

Annotation parsing mirrors the consumer's `parse_mod_line` loop for
`variant`/`tags`/boolean flags and extends it with `version`/`group` typed
lists (the consumer's draft path reads those by raw-string split); unknown
keys are preserved verbatim in `annotations` rather than lossily folded into
`tags`.

## Diagnostics, not certification

`_meta.diagnostics` (mirrored into the receipt) records, per entry:
`name_line_mismatches` (raw line 1 vs index `name`), `base_column_mismatches`
(index `base` vs first resolved base line), `no_bases`, `unresolved_bases`
(index `base` naming no resolved line), `ambiguous_bases`,
`index_column_mismatches` (index `variants`/`league`/`source`/`upgrade` vs
parsed lines; parsed text stays authoritative), `unparsed_grants_skill`,
`repeated_implicits`, and coverage `counts`. Malformed `{variant:}`/`{version:}`
/`{group:}` id lists and malformed `Implicits:`/`Selected`/`Has Alt Variant`
values reject; unresolvable text never does.

The original legacy bytes and policy bytes are archived as
`legacy-uniques.json` and `codec-policy.json`. The existing `uniques.json`,
its DTO, loaders and consumers are unchanged: this artifact is a domain-only
candidate for the consumer's independent relation gap, not adopted, with no
runtime manifest, download or `CURRENT` update.

## Publication integration

The published `0.5.5.5` game part already ships the codec source byte-for-byte
(`data/0.5.5.5/overlay/uniques.json`), so the relations policy above and the
domain archive make every compatibility byte traceable from a fixed published
member. To carry the codec source inside the ordinary inputs package the same
way the other codec domains carry theirs, the candidate plan
[publication/0.5.5.5-ordinary-uniques.plan.json](../../publication/0.5.5.5-ordinary-uniques.plan.json)
derives only from RePoE-published, tag-retained artifacts: the published
ordinary package (`handoff/independent-ordinary-20261101` @
`aed5f7348f41dcff6abd526d882c6a95d8acce0b`,
`handoff/independent-0.5.5.5/ordinary-inputs.zip`), whose stored bytes already
carry the field selections, and the published game part
(`handoff/game-crafting-20261103` @ `c804bfc764da2cb9eebcb6d418744e09bf5c005d`,
`handoff/game-crafting-20261103/game-build-part.zip`), which supplies the
`uniques/codec-source/uniques.json` bytes. No `ackness/pobr` source is needed.

```sh
mkdir -p .cache/publication/inputs
git fetch --depth=1 origin aed5f7348f41dcff6abd526d882c6a95d8acce0b \
  c804bfc764da2cb9eebcb6d418744e09bf5c005d
git cat-file blob aed5f7348f41dcff6abd526d882c6a95d8acce0b:handoff/independent-0.5.5.5/ordinary-inputs.zip \
  > .cache/publication/inputs/previous.zip
git cat-file blob c804bfc764da2cb9eebcb6d418744e09bf5c005d:handoff/game-crafting-20261103/game-build-part.zip \
  > .cache/publication/inputs/game.zip
mise run publication:package -- \
  --plan publication/0.5.5.5-ordinary-uniques.plan.json --plan-sha256 10b4992e8bb2d908eaec48db052a08cd785c252a75de3c969aa0e455113a6de2 \
  --input previous=.cache/publication/inputs/previous.zip \
  --input game=.cache/publication/inputs/game.zip \
  --out .cache/publication/ordinary-uniques
mise run publication:git-handoff -- --package .cache/publication/ordinary-uniques
```

A verified replay produced `ordinary-inputs.zip` (40020250 bytes, SHA-256
`a1290a172e280f08bd46722684e9ac7304634f906cfa400cfed34f9eebb84141`).
The published handoff is `0f68afc31192bc23c734ec1439789244aedec25a`, retained by
`handoff/ordinary-uniques-20261103`; a fresh remote fetch verified the archive,
manifest and all member pins before sequence 4 registration. Sequence 4 advances
only `ordinary`, preserving all other roles and the descriptor scope.
The obsolete local handoff `9fc8bc1159e11877f16fc91b716fa0b778fabe15` came from
the superseded PoBR-sourced plan and must not replace the published tag.
The projected
`overlay/unique_relations.json` is produced by the ordinary domain output, not
by a game-part member: it is a candidate artifact for consumer adoption, not a
published member.
