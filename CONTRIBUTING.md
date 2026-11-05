# Contributing to RePoE

This fork exports Path of Exile 2 client facts and publishes the game package
[PoBR](https://github.com/ackness/pobr) uses. The rules for a change are in
[AGENTS.md](AGENTS.md); releases are in [RELEASING.md](RELEASING.md).

## Which repository owns the fix

| Problem | Repository |
| --- | --- |
| Wrong or missing game facts, client decoding, or how facts become PoBR runtime JSON (`tools/pobr-data-adapter`) | ackness/repoe (here) |
| Chinese game text: affix and stat wording, item and skill names | [ackness/poe2-zh-cn-stats](https://github.com/ackness/poe2-zh-cn-stats) |
| Calculations, modifier rules, build import, the app | [ackness/pobr](https://github.com/ackness/pobr) |

A fix here reaches PoBR when a new `game/<patch>-<n>` Release is published and
PoBR moves its data lock to it.

## A pull request

- Set up with `mise trust && mise install --locked`,
  `mise bootstrap --only packages` and `mise run setup`.
- Keep it to one problem. Put code in the package of its role (`RePoE/client/`,
  `RePoE/native/`, `RePoE/release/`) and leave upstream paths in place.
- Do not edit pinned bytes (declarations under `release/`, `schema/`, policies,
  historical producer identities); the list and the reasons are in
  [AGENTS.md](AGENTS.md#never-move-or-rewrite).
- Run the checks for your change ([validation by change type](AGENTS.md#validation-by-change-type)),
  at least `mise run check`, and say in the PR what you ran.
- Commit subjects look like `fix(native): keep the row order`; the body says
  why. Pull requests are merged with a merge commit.
