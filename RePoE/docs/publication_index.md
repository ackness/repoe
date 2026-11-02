# Complete owner publication index (v2)

`publication/index.json` locates one explicitly ordered RePoE declaration for
`poe2/international`. Its `head` pins an immutable small descriptor by full Git
commit, relative path, integer byte length and SHA-256. Reading the source default
branch only locates this index; it does not imply that all data was generated at
that source revision. Each role keeps its own existing artifact/code revision.

The current descriptor is
[`publication/releases/poe2-international/1.json`](../../publication/releases/poe2-international/1.json).
The old `publication/0.5.5.5-handoffs.json` remains historical v1 evidence: its
`e00695a9...` game and absent crafting are unsuitable as the current complete head.
Every original artifact commit must remain fetchable for exact current and
historical replay. Each is kept by a `refs/tags/handoff/<name>` tag; the
same-named branches were retired on 2026-11-02 without changing any revision
(see [artifact identity and retention](data_publication.md#artifact-identity-and-retention)).
Index registration does not rename, delete or republish them.

## Current delivery

PR14 is merged into `master` (`aa737740`) and sequence 1 is published. PoBR's
`pipeline/latest/data-composition.json` pins this index revision and its original
`154913f4...` descriptor commit, together with the translation owner's publication.
The exact-head exporter CI and downstream PoBR Full validation have passed at
their recorded revisions; index validation is not a rerun of those checks.
A new upstream production/publication sequence has not been established by this
bootstrap, and downstream unattended adoption has separate activation requirements.

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

This delivery reuses the coordinator's already accepted/published records.
`RePoE.publication_index` is a standard-library, offline **bootstrap/register/
validate** API, not a collector, data producer, uploader or automatic publisher.
Every CLI result explicitly reports `fresh_remote_verification: false` and
`data_production_performed: false`. Bootstrap does not repeat archive downloads,
exports or large closure validation. A future real owner production/publishing
entry point must complete production, upload, fresh remote verification and
acceptance before supplying its trusted completion records to registration.
The bootstrap locks are evidence adapters, not runtime dependencies in the owner
descriptor. Changes to their accepted identities require new acceptance evidence;
computing a hash of arbitrary new metadata is not evidence of publication.

## Current accepted records

The bootstrap adapter authenticates three explicit local lock files against
caller-supplied SHA-256 values before extracting only the owner roles:

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

`register(repo, head, index_path, accepted, expected_index_sha256=None)` requires
accepted completion records and an already committed local descriptor. It checks
the entire small predecessor chain before an atomic index replacement. An existing
index requires the caller's frozen index SHA-256 and the next descriptor's exact
`previous == old.head`. The cooperative exclusive lock prevents concurrent
registrations. An identical retry preserves existing index bytes. A failed check
or replacement preserves the previous index, or leaves no index on first use.
Registration never writes a descriptor or performs a Git commit/push.

Example from the RePoE checkout, with the three accepted PoBR records supplied
explicitly (replace `POBR` with their read-only root):

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
predecessor. Each current target must match the explicit accepted records; a new
patch is never inferred from source metadata. Changed role input declarations advance that role's sequence by one;
unchanged declarations keep their old sequence. Same sequence/different content,
role rollback, empty advances, missing predecessors and owner/target mismatches
fail. Predecessors must belong to the same owner and game/realm channel. The API
does not infer compatibility or applicability from a patch string.

Full lowercase revisions and hashes, nonnegative integer byte lengths, canonical
relative paths and ordinary regular files are mandatory. Duplicate JSON keys,
nonfinite numbers, symlinks (including path ancestors and Git tree entries),
missing local objects and wrong hashes fail closed. Metadata is limited to
256 KiB per file and 1024 chain entries. Git reads use `--no-lazy-fetch` and
`--no-replace-objects`; data blobs are never fetched or replayed. Neither dates,
branch names nor artifact ancestry decide which publication is next.

Focused synthetic regression:

```sh
python3 -B -m unittest discover -s tests -p test_publication_index.py -v
```

Tests use only tiny bare Git object stores under `.cache/`, with no checkout,
archive production, decoder, Rust/WASM, source acquisition or network request.
Fixtures remain available there for inspection. Existing publisher plans,
parsers and producer behavior are unchanged; their large closures and full
regression suite are outside this metadata-only verification budget.
