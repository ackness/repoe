# Player source context

`facts:player` exports `repoe-native-player-context/v1` from an explicitly pinned
native v4 parent and a separate raw-resource lock. It complements the shared
facts pipeline with starting options, glossary records and literal AO/OT source
context. It is a partial fact archive, not a runtime pack or an actor model.

```sh
mise run facts:player -- \
  --source-lock /path/to/proposed-player-sources.lock.json \
  --expected-source-lock-sha256 <independently-recorded-byte-pin> \
  --source official-client-0.5.5.5-player-context-draft \
  --raw /path/to/pinned-client-raw-resources \
  --parent-facts /path/to/native-v4-parent \
  --expected-parent-manifest-sha256 <independently-recorded-parent-pin> \
  --out .cache/new-player-candidate
```

Use the normal mise + uv setup. Export itself is offline; it neither requests a
trade API nor contacts a game server. Acquisition and cache replay remain separate
tools. A freshly observed local digest is not authentication or source approval.
Output must be absent and below this checkout's `.cache`; inputs are not modified.
Every payload is prepared first, and the completion manifest is published last
through the existing directory-relative candidate writer.

The schema-1 source lock's selected entry declares:

- `kind: official-client-resource-candidate`, `profile: player-context-a2`, game,
  exact patch, realm and unreviewed acquisition evidence fingerprints.
- `character_id`, resolved against `Characters.Id` rather than `BaseClass` or a
  guessed physical row.
- `metadata_roots.character_ao`, exactly the selected row's `AOFile`, and
  `metadata_roots.generic_stats_ot`, a separately declared OT root.
- Exact byte/SHA-256 fingerprints for `StartingPassiveSkills.datc64`,
  `KeywordPopups.datc64`, and the literal metadata closure. At most 32 files,
  8 MiB each and 16 MiB total are accepted.
- Fixed PyPoE revision, dat-schema revision and schema-byte pin in `decoder`.
  The exporter verifies and executes the repository-owned 117-source decoder
  pin and frozen native schema, not a caller-supplied generated specification.

All parent payload bytes are checked against the external manifest pin. Consumed
physical tables are `Characters`, `PassiveSkills`, `Stats` and
`ClassPassiveSkillOverrides`; complete parent semantics are not independently
re-audited by this command. The original parent manifest is retained, with its
full transitive resource identity. Parent game/realm/patch must match the new
source declaration.

The package retains two complete native physical tables, all unknown columns,
row widths/warnings and schema column metadata. Starting option references resolve
to the pinned parent's stable passive IDs in original order. The selected
character and its exact class-override rows remain separate; sharing `BaseClass`
with another character does not apply that other character's overrides.

`metadata.json` retains every source line, UTF-16 byte range, ordered scope/block
identity and standalone assignment. Values remain lexical strings. Repeated
blocks and keys are not collapsed; nested/client scopes are not promoted to
unconditional stats. Quoted braces and line comments do not change scopes.
Unsupported inline block names remain raw with diagnostics. Includes/parents are
checked as a bounded literal graph; no occurrence expansion or effective merge
is performed. Source paths and declared extensions distinguish AO from OT:
`Character.ao` never implicitly inherits `Character.ot`.

`player_context.json` joins plain top-level Stats assignments to exact native
stat IDs when known, preserving unknown keys and source positions. It retains
starting relationships, not automatic allocations or stat grants. Glossary text
is retained in the physical KeywordPopups table, not parsed into executable rules.
Each row reference declares its `origin` (`player` or `parent`), exact payload,
JSON pointer and stable ID where available. Local tables resolve in this package;
parent tables resolve in the externally pinned parent package.
`diagnostics.json`, exact source lock and parent manifest complete the provenance.
The manifest pins payloads, producer sources, Python, decoder and schema identity.

The real current candidate uses six international `0.5.5.5` raw resources. It
does not certify China-realm numerical equivalence. Generic critical bonus100,
per-level resource growth and attribute coefficients are source facts; applying
the generic OT to Sorceress still requires an explicit PoBR model policy. Pool
initialization offsets, intrinsic accuracy baseline, exact gem attribute
requirements and effective server cadence remain unproven here. No formula,
default resistance trait, uptime, event sequence or quality scope is invented.
Candidates remain `production_ready: false`. GGG retains rights to game facts and
text; the code license does not grant additional rights to client content.
