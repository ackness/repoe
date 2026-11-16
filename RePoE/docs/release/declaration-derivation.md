# Declaration derivation

`mise run release:declare` writes `inputs.lock.json` and
`frozen-inputs.json` for a new declaration from the published predecessor
declaration and a `release:inputs` stage. Run it after
[policy rebinding](policy-rebinding.md), which must already have written
`release/<new>/domains.json`:

```sh
mise run release:declare -- --config release/0.5.5.8 \
  --staged .cache/release/publish/inputs-poe2-international-<new> \
  --patch <new> --out release/<new> [--add-package NAME ...] [--carry NAME ...] \
  [--cache DIR] [--fetch]
```

`--config` is the predecessor declaration directory, which must be published:
its `expect.package` pin is the only record of the released zip's bytes.
`--staged` is the `release:inputs` output directory with `lock.json` and
`assets/`. `--out` must be a direct child of `release/` whose name is the new
patch (`<new>` or `<new>-<n>`); it must already contain `domains.json` and must
not already contain either output file. `--cache` overrides
`.cache/release/inputs`; `--fetch` allows downloading the predecessor's pinned
Release asset when it is not already in `cache/downloads/`. That asset is the
only thing fetched: the staged zips are read from `--staged/assets/` and the
predecessor declaration and its local publication tag are read in place.

## What the command writes

In `inputs.lock.json`, `target.game_patch` becomes `--patch` and every staged
package replaces its predecessor entry with the `lock.json` spec verbatim. A
predecessor package absent from the stage is carried unchanged, except that a
carried `crafting` entry is still cross-checked against the fresh facts (below).
`packages.previous` is recomputed from the predecessor's publication tag,
derived from its directory name (`release/0.5.5.8` publishes as
`game/0.5.5.8-1`): the command fetches the pinned asset, verifies it against
`expect.package`, and records the zip pin together with the manifest pin and
`expanded_bytes` read from that zip. The stage can never supply `previous`.
The `facts` object is rewritten to the root form of the staged facts package,
which must contain exactly one fresh `repoe-native-facts/v4` candidate: `root`
names its directory and both `identities.original` and `identities.rebound`
pin the fresh manifest's SHA-256. `crafting.input_manifest` — whether staged
or carried — must equal that same manifest pin.

In `frozen-inputs.json`, `target` follows the new patch and every member under
the old `data/<old patch>/` prefix is renamed to `data/<new>/`. Member metadata
(`category`, `origin`, `reason`, `exit`, `unchanged_since_0.5.5.4.2`) is
carried verbatim; `source` and `categories` are unchanged. Each member's
`carried_from` is replaced with the latest hop: the frozen `source` package,
the old member path, the old patch and the predecessor's publication tag.
Members outside the patch prefix keep their names and gain the same hop.

Two things are deliberately not written. The new lock has no `expect`: the
command prints `expect absent: pin it after the first release:build`, and the
pin comes from that build's zip as before. And no `publication` or
`publication_status` marker is added or cleared — staged packages keep
whatever the stage wrote, carried packages keep their old marker.

## What still needs a human

The command reports review obligations instead of deciding them; each is
printed as `H /path: action`:

- `H /inputs.lock.json/packages/<name>/publication` (or
  `publication_status` for `crafting`): a staged package whose lock entry has
  no publication marker. Review and set it before publication.
- `H /inputs.lock.json/packages/<name>/<field>: review carried publication;
  carried value: <value>`: a carried package's retained `publication` or
  `publication_status` marker, echoed for re-review under the new patch.
- `H /inputs.lock.json/packages/<name>: review added package`: a package the
  predecessor did not have, admitted by `--add-package`.
- `H /frozen-inputs.json/members/*/<field>: review carried metadata
  (<n> members)`: the per-field count of carried `category`, `origin`,
  `reason`, `exit` and `unchanged_since_0.5.5.4.2` members.

The change report itself lists every changed JSON path with bounded
single-line `old -> new` values. Frozen members whose only changes are the
rename and the provenance hop are collapsed to `(carried)` lines, and the
summary counts field changes, carried members, additions and removals
separately. `Carried packages:` names the carried set.

`--add-package NAME` and `--carry NAME` are the two opt-ins; both repeat.
`--add-package` admits a staged package the predecessor did not declare.
`--carry` keeps a predecessor package the stage does not supply (for example
`legacy`). Neither is ever inferred: an unlisted new package refuses with
`unadded-package` and an unlisted omitted package with `unconfirmed-carry`,
naming the packages in question.

## Refusals

Every refusal exits 1 as `release:declare: <kind>…` and leaves no new
declaration file; verified cache entries may remain. Checks cover output
location and cache safety, existing outputs, the new `domains.json`, the
transition against the three input documents, the output directory name,
staged packages, the previous zip, and finally the derived trio in a temporary
directory. Files created during final publication are removed if publication
raises an exception; abrupt process termination is not a two-file atomic
transaction.

Existing symlinks in the cache root, download entries, extraction directories
and temporary paths are refused before opening packages. Use a private cache:
this preflight does not make concurrent cache mutation safe.

| Kind | Catches |
| --- | --- |
| `invalid-output` | `--out` is not a direct child of `release/`, or its name does not name `--patch` |
| `invalid-cache` | `--cache` is inside `release/` or overlaps the config, stage or output directory, in either direction |
| `existing-output` | `inputs.lock.json` or `frozen-inputs.json` already exists in `--out`; the command never overwrites |
| `missing-domains` | `--out` has no `domains.json`; run `policy:rebind` first |
| `invalid-patch` | `--patch` is not a dotted numeric patch |
| `unchanged-patch` | `--patch` equals the predecessor's `target.game_patch` |
| `invalid-predecessor` | the `--config` directory name does not name its own `target.game_patch`, or its reference and frozen source are not both `previous` |
| `missing-expect` | the predecessor has no `expect.package` pin, so `previous` cannot be derived |
| `missing-inputs` | the stage `lock.json` is empty |
| `reference-package` | the stage tries to supply a `previous` entry |
| `unadded-package` | a staged package is new and no `--add-package` admitted it |
| `invalid-added-package` | `--add-package` names a package that is not a new staged one |
| `invalid-package` | a staged package name is not a valid identifier |
| `stage-package` | a staged entry carries `revision`; staged inputs must be Release assets, not Git paths |
| `invalid-input-tag` | a staged tag is not `inputs/<new patch>-<n>` with `n >= 1`; placeholders and other patches refuse |
| `missing-counterpart` | the staged lock omits the package `facts.package` names |
| `unconfirmed-carry` | a predecessor package is absent from the stage and not listed by `--carry` |
| `invalid-carry` | `--carry` names a package that is not being carried |
| `target-mismatch` | the predecessor's frozen target, the previous package's tag or patch, the new `domains.json` target, a staged package's manifest identity or the previous zip's manifest target disagrees with the declared transition |
| `crafting-input-mismatch` | the carried or staged `crafting.input_manifest` is not the fresh facts manifest pin |
| `invalid-expanded-bytes` | the verified previous zip yielded no usable `expanded_bytes` |
| `invalid-facts-identity` | the fresh facts manifest pin is not a SHA-256 |
| `frozen-member-conflict` | the `data/<new>/` rename would collide with an existing member name |
| `missing-tag` | the predecessor's publication tag is not a local Git tag; fetch it first |
| `facts-root` | the staged facts package does not contain exactly one fresh `repoe-native-facts/v4` candidate |
| pin-layer errors | `Unsafe` paths, `Symlink` outputs or caches, `Corrupt cache` entries, `Byte pin mismatch` on staged assets, and `rerun with --fetch` when the previous zip is not cached |

## Validation and interruption

Both documents are encoded and then loaded in a temporary directory together
with the new `domains.json` by `build.load_config`, the same reader the
release build uses. A declaration that would fail the build's own checks is
never written. Only after the trio loads are the two files created, each with
an exclusive create; if the second write fails or loses a race to a concurrent
file, the first is rolled back.

A process killed between the two writes is the one gap: `release/<new>/` can
be left holding `inputs.lock.json` without `frozen-inputs.json`. That state
refuses everywhere it is read — `build.load_config` cannot open the missing
file and the CI selector rejects the directory as an incomplete declaration —
and the fix is to delete the stray file and rerun with the same stage. A rerun
never needs anything else: nothing already published is touched, and the
predecessor declaration and stage are only read.

The command does not approve policies, does not regenerate codec evidence,
does not stage or publish inputs, and does not move `current` in
`release/ci.json`.
