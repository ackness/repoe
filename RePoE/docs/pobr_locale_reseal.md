# Retained game-part locale reseal

The schema-3 full snapshot inside a game part binds the separately owned locale
files by SHA-256. After a language-only publication those bindings must advance
before PoBR can adopt the complete composition. `RePoE.pobr_locale_reseal`
performs that owner operation without generating game facts or changing PoBR.

The caller authenticates a plan containing the old game input, the immutable
`ackness/poe2-zh-cn-stats` manifest and an explicit before/after locale hash map.
The helper reads only pinned Git blobs, checks every game and language manifest
member, requires the full locale inventory to match the snapshot, and rejects
any difference outside the declared hash map. It copies every game member except
`data/<patch>/manifest.json` unchanged. The enclosing part manifest retains all
historical metadata, updates that member's pin, and appends a reseal receipt.
Language files are never copied into RePoE's game part.

The [Shaman alias plan](../../publication/0.5.5.5-shaman-locale-reseal.plan.json)
binds the sequence-5 game to the language owner's sequence-3 publication. Only
`i18n/zh-CN/stat_lines.json` changes; the other 12 locale hashes stay fixed.
The plan's evidence pins the language owner's merged discovery index and its
immutable descriptor. These are provenance, not a current-freshness assertion.

```sh
python3 -B -m RePoE.pobr_locale_reseal \
  --repo . --language-repo /path/to/local/language-owner \
  --plan publication/0.5.5.5-shaman-locale-reseal.plan.json \
  --plan-sha256 80915b69b01d36e09a8ca2232c9d1c29e89bc7861dd21bc77702d200984562e5 \
  --name shaman-locale-reseal-20261103 \
  --out .cache/shaman-locale-reseal-20261103/package
python3 -B -m RePoE.data_publication git-handoff \
  --package .cache/shaman-locale-reseal-20261103/package
python3 -B -m unittest discover -s tests -p test_pobr_locale_reseal.py -v
```

The output uses the existing package and orphan handoff contracts. It is local
only. Preserve all previous snapshots and tags. Coordinator publication, fresh
remote verification, index registration and PoBR adoption remain separate steps;
see the [publication contract](publication_index.md). A draft exercised against
a local staging origin does not establish publication to GitHub. No client
acquisition, raw table export, Cargo build or runtime adoption is needed here.
