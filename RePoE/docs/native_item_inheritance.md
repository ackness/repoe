# Selected item inheritance

`repoe-item-inheritance/v1` exports an explicitly pinned item `.it` closure,
complementing physical `BaseItemTypes.InheritsFrom` and `Tags`. It excludes actor
`.ot`, unique affix membership, units and mod applicability.

```sh
python -B -m RePoE.native_item_inheritance \
  --source-lock /path/to/lock.json --expected-source-lock-sha256 <external-sha256> \
  --source <key> --raw /path/to/raw --out .cache/inheritance/new-candidate
```

This offline standard-library command verifies every raw resource before parsing.
Its schema-1 source lock uses the selected-description envelope: explicit PoE2
patch/realm, official-client candidate kind, acquisition evidence/status, `roots`
and `resources` with positive `bytes` and SHA-256. Only canonical
`Metadata/Items/.../*.it` paths are accepted. Bounds are 128 files, 1 MiB per file,
16 MiB total and 12 parent edges. Missing parents, cycles, unrecognized syntax,
malformed UTF-16 and resources outside the root closure reject publication.

The three completion-last files are `inheritance.json`, `source-lock.json`, and
`manifest.json`. The manifest has `format: repoe-item-inheritance/v1`, the existing
`source_identity` envelope, payload/lock byte pins in `files`, producer fingerprints,
summary counts and `representation: {payload, format, tag_policy_id}`. Status is
partial and `production_ready` is false. Destinations must be new and beneath
this checkout's `.cache/`.

`inheritance.json.files[resource]` retains every physical line, ordered block,
ordered field and directive: unknown/empty/nested blocks, duplicate field keys,
original RHS strings, CRLF and absolute half-open UTF-16 byte spans including BOM.
`extends` retains its literal and target resource; only literal `nothing` yields
a null parent. Block hashes bind their raw slices. Other scalar fields stay raw.

`roots[resource]` contains `chain_child_to_parent`, `base_tag_occurrences`, and the
separate `tag_interpretation`. Each occurrence retains its resource, field and
block ordinals, scope, RHS, optional quoted literal, line, byte span and raw text.
Duplicates remain duplicated in this evidence list.

The opt-in ID `pypoe-66d1d744-base-tag-child-first-ordered-union/v1` visits child
to parent, reads top-level Base.tag in field order and retains the first occurrence
of each exact string. Authority is `community-parser-interpretation`; the policy
records the pinned PyPoE revision/source fingerprints and explicitly does not
certify official merge semantics. Multiple top-level Base blocks or nonliteral/
empty tags produce rejected interpretation, null tags and diagnostics; raw facts
remain. Rarity, socket and other merge rules are not inferred.

Consumers join an exact nonempty `BaseItemTypes.InheritsFrom` stem plus `.it`,
verify the chain/occurrences against pinned files, explicitly choose the policy
ID and identify direct DAT tags separately. Missing/rejected roots require a
diagnostic or explicit compatibility decision. Never invent an empty tag list.
The fixed 0.5.5.5 inventory has 5,496 nonempty base stems, 82 roots, 89 files,
284 fields and 71 literal Base.tag occurrences; these are observed versioned
counts, not universal constants or release-membership proof.
