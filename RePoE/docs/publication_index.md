# Complete owner publication index (v2)

`publication/index.json` locates one explicitly ordered RePoE declaration for
`poe2/international`. Its `head` pins an immutable small descriptor by full Git
commit, relative path, integer byte length and SHA-256. Reading the source default
branch only locates this index; it does not imply that all data was generated at
that source revision. Each role keeps its own existing artifact/code revision.

The current descriptor is
[`publication/releases/poe2-international/3.json`](../../publication/releases/poe2-international/3.json).
The old `publication/0.5.5.5-handoffs.json` remains historical v1 evidence: its
`e00695a9...` game and absent crafting are unsuitable as the current complete head.
Every original artifact commit must remain fetchable for exact current and
historical replay. Each is kept by a `refs/tags/handoff/<name>` tag; the
same-named branches were retired on 2026-11-02 without changing any revision
(see [artifact identity and retention](data_publication.md#artifact-identity-and-retention)).
Index registration does not rename, delete or republish them.

## Current delivery

Sequence 2 migrates retrieval locations after the [fork-history cut](history.md).
The game, crafting, display-source and verifier inputs retain their file bytes
and digests at new commit IDs; the original sequence-1 declaration remains
historical evidence. The history map resolves its old producer identities.
Consumers must use the current index and the updated PoBR data lock.

Sequence 3 is the first sequence registered with `draft`/`register`. It changes
only the `game` role, to the part that carries the
[PoBR special-currency catalog](pobr_crafting_catalog.md); the other five roles
keep their sequence 2 inputs. The original bootstrap published sequence 1.
PoBR's `pipeline/data.lock.json` records the index revision and descriptor commit
it adopted, together with the translation owner's publication. Index validation
is not a rerun of the exporter CI or of PoBR's Full validation. Downstream
unattended adoption has separate activation requirements.

## Scope and trust

The descriptor schema is `owned-data-publication/v2`, with owner
`ackness/repoe`, exact `{game, game_patch, realm}` target, positive `sequence`,
`previous` (null only at sequence 1), `components`, and `scope`. `previous` has
exactly the same `{revision, path, bytes, sha256}` shape as the index head.
The index schema is `owned-data-publication-index/v2`, with only `schema`,
`channel: {game, realm}`, `sequence`, and `head`.

Exactly six roles are required: `game`, `crafting`, `ordinary`, `display_source`,
`source_verifier`, `test_fixtures`. Each is `{sequence, input}`. `input` is copied
as a complete existing declaration, including manifest/producer/input-manifest
pins, file inventories, unknown identities and original applicability metadata.
The verifier retains its Git-files form; no artificial package or publication
field is added. The historical display source has no publication field; exact
comparison with the explicitly accepted lock authenticates that legacy shape.
Explicit pending/local-only states are rejected for every package role.

`scope` is exactly:

```json
{
  "complete": true,
  "meaning": "declared-role-dependencies-only",
  "official_semantics_certified": false,
  "client_identity_certified": false
}
```

This means the declared six-role dependency set is present in accepted delivery
records. It does not certify every game domain, official semantics, freshness of
upstream resources, raw client identity or PoBR applicability. Original candidate
and historical limits remain inside the referenced artifacts. The descriptor
contains no PoBR snapshot/runtime expectations, policy or translation selection;
PoBR owns its composition and cross-owner binding checks.

Sequence 1 reused the coordinator's already accepted/published records.
`RePoE.publication_index` is a standard-library **bootstrap/validate/draft/
register** API, not a collector, data producer, uploader or automatic publisher.
Every CLI result reports `fresh_remote_verification: false` and
`data_production_performed: false`; `draft` and `register` also report how they
verified artifacts. Bootstrap does not repeat archive downloads, exports or large
closure validation. The bootstrap locks are evidence adapters for sequence 1
only, not runtime dependencies in the owner descriptor.

A later sequence does not use them. It inherits every unchanged role from its
predecessor, which was verified when that sequence was registered, and checks
each changed role against this repository's Git objects:

- an artifact role's commit is local, its blob at `path` matches `bytes`/`sha256`,
  the ZIP's `manifest.json` matches `manifest` and its members add up to
  `expanded_bytes`;
- exactly one `handoff/*` tag on `origin` peels to that commit, so PoBR can resolve
  the tag and the commit stays fetchable;
- the source verifier's commit is reachable from `origin/master` and each listed
  file matches its pin.

Fetch the published tag before drafting (`git fetch origin tag handoff/<name>`).
A local commit equal to the one the origin tag names has the published content.
An untagged or local-only artifact fails, so computing a hash of unpublished
metadata is still not evidence of publication.

## Current accepted records

The bootstrap adapter authenticates three explicit historical lock files against
caller-supplied SHA-256 values before extracting only the owner roles. These are
sequence-1 acceptance evidence, not PoBR's current input declaration. They remain
available in the [fixed PoBR tree](https://github.com/ackness/pobr/tree/0fb6f913cc3fac980f9d84e855b26103860d6b96/pipeline),
at the paths below; export that revision when replaying bootstrap. Current PoBR
uses only `pipeline/data.lock.json`, which this legacy bootstrap API does not read.

| Evidence file | Bytes | Accepted SHA-256 |
| --- | ---: | --- |
| `pipeline/runtime/build-data.lock.json` | 5202 | `e8892d6d05a7d24d2eb4f67c975333bebc6ccc73559a82a4cb6ed741b1f96e07` |
| `pipeline/runtime/ordinary/ordinary-inputs.lock.json` | 11565 | `c025b56d7306794c19b2bbf4ffeeaebfc3b0551c83657beff15ba32eb8fc9c20` |
| `pipeline/imports/data-imports.lock.json` | 2948 | `2c6f854acce2f87a9ed467c9361fa4404c8b07c0f8083234fcf7e6af4b7b36ac` |

Extraction is exact: build `packages.game`, `crafting`, `test_fixtures`; ordinary
`packages.repoe`, `source_verifier`; display imports `packages.repoe`. Lock targets
must agree and match the descriptor. Build/ordinary v1 are rejected by this
adapter, without changing any historical loader or producer. Other lock fields
are not copied. No new remote acceptance was performed in this owner delivery.

## API and CLI

`load_accepted_inputs(build, ordinary, imports, sha256s=...)` verifies the three
small trusted records and returns `{target, inputs}`. `bootstrap(accepted, out)`
writes a new sequence-1 descriptor without overwriting an existing file.
`validate_descriptor(value, accepted=None)` checks structure; supplying accepted
records additionally checks exact role declaration equality.

`validate_index(value, repo, accepted=None)` verifies the local immutable head,
all exact predecessors back to sequence 1, and every transition. Supplying the
accepted record also verifies current completion declarations. Structural
validation alone does not attest a new remote publication.

`draft(repo, index, inputs, out, game_patch=None)` writes the next descriptor:
the index head with each given complete role input replaced, the changed roles'
sequences advanced, `previous` set to the head, and each changed role verified
as above. `out` must be `releases/<game>-<realm>/<sequence>.json`, and an existing
file is never overwritten. An input file has the same form as the descriptor's
`components.<role>.input`; `--game-patch` moves the target to a new patch of the
same channel.

`register(repo, head, index_path, accepted=None, expected_index_sha256=None)`
requires an already committed local descriptor. Sequence 1 requires the accepted
records; a later sequence without them verifies its changed roles. It checks
the entire small predecessor chain before an atomic index replacement. An existing
index requires the caller's frozen index SHA-256 and the next descriptor's exact
`previous == old.head`. The cooperative exclusive lock prevents concurrent
registrations. An identical retry preserves existing index bytes. A failed check
or replacement preserves the previous index, or leaves no index on first use.
Registration never writes a descriptor or performs a Git commit/push.

Publishing sequence N+1 from the RePoE checkout, after the new artifact's tag is
pushed and fetched:

```sh
python3 -B -m RePoE.publication_index draft \
  --role game=.cache/publication/game-input.json \
  --out publication/releases/poe2-international/2.json
# Commit the descriptor first. Supply its actual immutable commit and byte pin:
python3 -B -m RePoE.publication_index register \
  --repo . --index publication/index.json \
  --descriptor-revision FULL40 --descriptor-path publication/releases/poe2-international/2.json \
  --descriptor-bytes INTEGER --descriptor-sha256 HEX64 --expected-index-sha256 HEX64
python3 -B -m RePoE.publication_index validate --repo . --index publication/index.json
```

Sequence 1 was bootstrapped with the three accepted historical PoBR records
supplied explicitly (replace `POBR` with the read-only tree at the fixed revision
above, rather than a current PoBR checkout):

```sh
accepted=(
  --build-lock POBR/pipeline/runtime/build-data.lock.json
  --build-lock-sha256 e8892d6d05a7d24d2eb4f67c975333bebc6ccc73559a82a4cb6ed741b1f96e07
  --ordinary-lock POBR/pipeline/runtime/ordinary/ordinary-inputs.lock.json
  --ordinary-lock-sha256 c025b56d7306794c19b2bbf4ffeeaebfc3b0551c83657beff15ba32eb8fc9c20
  --imports-lock POBR/pipeline/imports/data-imports.lock.json
  --imports-lock-sha256 2c6f854acce2f87a9ed467c9361fa4404c8b07c0f8083234fcf7e6af4b7b36ac
)
python3 -B -m RePoE.publication_index bootstrap "${accepted[@]}" \
  --out publication/releases/poe2-international/1.json
# Commit the descriptor first. Supply its actual immutable commit and byte pin:
python3 -B -m RePoE.publication_index register "${accepted[@]}" \
  --repo . --index publication/index.json \
  --descriptor-revision FULL40 --descriptor-path publication/releases/poe2-international/1.json \
  --descriptor-bytes INTEGER --descriptor-sha256 HEX64
python3 -B -m RePoE.publication_index validate "${accepted[@]}" \
  --repo . --index publication/index.json
```

Keep descriptor/code in one commit, then commit the index pointing to that exact
commit. This avoids a self-referential Git hash. The coordinator must publish and
retain that descriptor commit as well as the final index commit; squashing or
rewriting commits requires registering a new correct head before publication.
This local owner task does not publish either commit or activate a consumer.

## Strict ordering and bounded verification

Within a game/realm channel, publication sequences advance by one with an exact
predecessor. Sequence 1's target must match the explicit accepted records, and a
later target changes only through an explicit `--game-patch`; a new patch is never
inferred from source metadata. Changed role input declarations advance that role's sequence by one;
unchanged declarations keep their old sequence. Same sequence/different content,
role rollback, empty advances, missing predecessors and owner/target mismatches
fail. Predecessors must belong to the same owner and game/realm channel. The API
does not infer compatibility or applicability from a patch string.

Full lowercase revisions and hashes, nonnegative integer byte lengths, canonical
relative paths and ordinary regular files are mandatory. Duplicate JSON keys,
nonfinite numbers, symlinks (including path ancestors and Git tree entries),
missing local objects and wrong hashes fail closed. Metadata is limited to
256 KiB per file and 1024 chain entries. Git reads use `--no-lazy-fetch` and
`--no-replace-objects`; data blobs are never fetched. Only a changed role's
artifact blob is read, from local objects. Neither dates,
branch names nor artifact ancestry decide which publication is next.

Focused synthetic regression:

```sh
python3 -B -m unittest discover -s tests -p test_publication_index.py -v
```

Tests use only tiny bare Git object stores under `.cache/`, with no checkout,
decoder, Rust/WASM, source acquisition or network request. Artifact tests build
small synthetic ZIPs and use a local bare repository as `origin`.
Fixtures remain available there for inspection. Existing publisher plans,
parsers and producer behavior are unchanged; their large closures and full
regression suite are outside this metadata-only verification budget.
