# Historical attribute selector projection

`RePoE.pobr_historical_trees` repairs the four retained historical trees in a
**pinned RePoE game part**, using
[`historical-attributes-v1.json`](../../tools/pobr-data-adapter/policies/passive-tree/historical-attributes-v1.json).
It is an owner-side compatibility projection, not a new client export or a
consumer rule that treats all fixed Strength nodes as selectors.

## Original defect and provenance

The immutable PoBR snapshot at
`7793f93b0a0b9e5172a19811b4af856b5b7538f1` carried the historical extractor:

1. `tools/pobr-data-adapter/src/tree_versions.rs:96-105` copies the node's name
   and calls `parse_string_array(node_block, "stats={")`.
2. `tree_variants.rs:231-234` calls `balanced_block`.
3. `tree_coords.rs:195-197` uses the **first substring match**, without checking
   the field's nesting depth.

The historical source at
`PathOfBuildingCommunity/PathOfBuilding-PoE2@bb52d6b368307457eb9c54bb13f1829993d390b1`,
`src/TreeData/0_1..0_4/tree.lua`, already has correct selector semantics:
`isAttribute=true`, `name="Attribute"`, and top-level
`stats={"+5 to any Attribute"}`. But the earlier `options[1].stats` is
`"+5 to Strength"`; the extractor incorrectly selects that nested array.
For example, `0_4` node 1200 starts at line 23831, and its options occur before
its own `stats`. This is not missing source data or an XML choice-import bug.

The exact historical `isAttribute` identity sets were checked against **every**
retained node named `Attribute`, not just the two reported examples. All four
sets match, and every source selector has the generic top-level text:

| Historical version | Total nodes | Lost selectors | Other nodes retained |
| --- | ---: | ---: | ---: |
| `0_1` | 3149 | 288 | 2861 |
| `0_2` | 3404 | 300 | 3104 |
| `0_3` | 4118 | 293 | 3825 |
| `0_4` | 4701 | 293 | 4408 |

The policy records immutable source/code hashes, source roles and the identity
digests. Its official-tree cross-check corroborates nodes 1200 and 11741, but
**does not** supply historical membership or replace old trees with the current
tree. The historical Lua/code references are review evidence only; the producer
never opens them, executes Lua or reads PoBR's vendor directory.

[`publication/0.5.5.5-game.plan.json`](../../publication/0.5.5.5-game.plan.json)
retained those already-defective JSON files byte-for-byte from the snapshot.
Subsequent owner game packages preserved the same four file hashes, including
the sequence-3/4 game input at
`c804bfc764da2cb9eebcb6d418744e09bf5c005d`,
`handoff/game-crafting-20261103/game-build-part.zip`.
The original migration plan and accepted index remain unchanged: rewriting
their pins would conceal the historical defect rather than repair its output.
The retired Lua extractor is not reintroduced into the owner production path.

## Projection contract

The policy pins the complete owner input package, its manifest and each tree.
For each exact tree it binds the node count and the sorted numeric selector
identity set (`data_publication.encoded(ids)`, compact JSON plus LF).
The retained `Attribute` name is only an index into those reviewed bytes,
**not a global heuristic**. Both identity membership and expected shape must
match: numeric string ID, normal kind, exactly `["+5 to Strength"]`, no native
packet, variants, ascendancy or armour application. Stale/new identities,
duplicate skills, changed amounts and already-projected trees fail closed.

Only those nodes' `stats` change to `["+5 to any Attribute"]`, the existing
PoBR selector text contract. Names, IDs, order, all other fields and unknown
extensions survive. Fixed Strength nodes, including the synthetic same-text
negative control and real notable 5710 (Brutal), are untouched. No choice is
selected by the producer; PoBR's imported Str/Dex/Int choice remains the actor.

Every historical tree in the game package and snapshot must be declared in the
policy. A new historical version is an explicit review, not a silent omission.
The package changes only these trees and their four digest entries in
`data/<patch>/manifest.json`. Every other member is copied exactly, including
the current tree, crafting catalog and frozen parser/rule data. The new outer
manifest retains the complete original manifest/limits, immutable input pin,
policy, producer file hashes and per-version before/after pins and changed IDs.
It does not relabel historical compatibility as native facts.

## Offline replay

Use a RePoE repository with the policy's exact game artifact commit already
available. No shared build target, Python environment installation, client
download or consumer checkout is needed. A missing object is an error; neither
a convenient ZIP nor a working-tree snapshot substitutes for it.

```sh
POLICY=tools/pobr-data-adapter/policies/passive-tree/historical-attributes-v1.json
# Authenticate this policy against the reviewed source commit before replay.
POLICY_SHA=$(shasum -a 256 "$POLICY" | cut -d ' ' -f1)
mise run publication:historical-trees -- \
  --repo "$PWD" --policy "$POLICY" --policy-sha256 "$POLICY_SHA" \
  --name historical-tree-attributes-20261103 \
  --out .cache/historical-tree-candidate
```

Outputs use the existing `repoe-data-package/v1` local package contract:
`data.zip`, `manifest.json`, and completion-last `package.json`. Output must be
a fresh directory under this checkout's `.cache`; symlinks and overwrite are
rejected. No tag, commit, index update, remote mutation or consumer adoption is
performed. ZIP replay uses the existing fixed timestamp/order/mode and
DEFLATE-9 conventions; compare exact bytes under the pinned Python/zlib runtime.

```sh
mise exec -- python -B -m unittest discover -s tests -p test_pobr_historical_trees.py -v
# Opt-in full four-version test against the pinned owner artifact, offline:
REPOE_HISTORICAL_GAME_REPO="$PWD" mise exec -- \
  python -B -m unittest discover -s tests -p test_pobr_historical_trees.py -v
```

Synthetic tests cover same-text fixed nodes, guarded identities, unknown-field
preservation, malformed inputs, all-version coverage, deterministic assembly,
snapshot/manifest consistency, source/policy pins and failure without a
completion marker. The real test additionally checks every node, exact changed
package membership, both reported IDs and unchanged fixed Strength effects.
These are projection/package tests, not full-build calculation tests.

## Publication and consumer adoption remain separate

After review, the coordinator can use `publication:git-handoff` on the candidate
directory, publish/verify a **new** immutable `handoff/*` tag and register a new
descriptor changing only the `game` role. The candidate declares
`publication=local-only`; its manifest's `production_ready=false` continues to
record compatibility limits even after publication. Publication does not certify
those limits away, and no existing artifact/tag should be moved.

PoBR then deliberately adopts that descriptor/game input in its data lock,
prepares data, updates the changed snapshot/runtime/release expectations, and
regresses an imported historical `Spec` with choices on nodes 1200 (Dex) and
11741 (Int). Include fixed-node negative controls and all four tree versions.
The 35 active choices in the reported Shaman build include 24 non-Strength
choices; its supported correction is -120 Str, +60 Dex and +60 Int before
attribute scaling. No resource/EHP result is claimed by these owner tests.
Stale rune values and the residual EHP discrepancy remain separate issues.

Other historical limitations (geometry, class variants and any unrelated
nested-field extraction loss) are not certified or repaired here.
