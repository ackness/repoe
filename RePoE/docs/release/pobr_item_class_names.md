# English item class names

The opt-in `item-class-names` release job projects native `ItemClasses.Id`
and `ItemClasses.Name` into `overlay/item_class_names.json`. It reads the
declaration's verified `facts: "rebound"` input, checks its game, patch and
realm against the build target, and verifies the manifest and table pins.
It does not acquire resources or run the native exporter again.

## Member

```json
{
  "_meta": {
    "schema": "repoe-item-class-names/v1",
    "game": "poe2",
    "game_patch": "0.5.5.5",
    "realm": "international"
  },
  "scopes": {
    "ItemClasses.Name": {"<ItemClasses.Id>": "<raw English Name>"}
  }
}
```

The scope is exactly `ItemClasses.Name`, keyed by stable `Id`, never the
physical `_row`. Ids are sorted; encoding uses the build's runtime JSON
layout: UTF-8, two-space indentation and a final newline. The member does
not contain a source lock or producer metadata.

Every Id must be a nonblank string and unique, including rows whose names
are empty. Missing, null or non-string names fail the build. Empty strings
and strings containing only whitespace are counted separately and omitted.
Other Ids and names stay unchanged, including whitespace, case, markup
and line endings. Distinct Ids may have the same name.

## Declaration and receipt

Add this job before `snapshot-manifest` in a new declaration or a local
candidate configuration:

```json
{
  "id": "item-class-names",
  "kind": "item-class-names",
  "facts": "rebound",
  "outputs": {
    "overlay/item_class_names.json": "data/0.5.5.5/overlay/item_class_names.json"
  }
}
```

Add `"overlay/item_class_names.json": "overlay"` to the snapshot job's
`add` object. Existing declarations do not opt in and retain their bytes.

The release receipt records the selected facts identity and manifest pin,
table path and byte pin, original producer and source identity (including
acquisition status), and counts `rows`, `emitted`, `empty` and `whitespace`.
Its top-level producer identifies the implementation commit and dirty state.
No historical identity or source acceptance is upgraded.

The pinned 0.5.5.5 table contains 118 rows: 93 emitted names, 25 empty
strings and no whitespace-only names. A local candidate verifies this
projection and package assembly; it does not authorize publication or
consumer adoption. Formal publication requires the corresponding optional
member's PoBR contract increment and review. `CONTRACT_VERSION` stays 1;
no new Rust type or adapter dependency is needed for this projection.
