# Windows observed language candidate

These archives preserve the existing Windows memory observation and a locally
validated nine-table candidate. They do not certify the observed game patch,
realm, numerical applicability, production readiness, or CURRENT activation.
The observation retains null patch/realm; only the independently pinned target
is `poe2 / 0.5.5.5 / international`.

- `source-candidate.zip`: all seven original files from `actual-final-a`.
  A separate CLI invocation produced byte-identical `actual-final-b` files.
- `observed-transfer.zip`: nine original compressed table pairs, the exact
  canonical transfer/acquisition receipts, original decoder source, and the
  preservation manifest. No raw DAT or bundle bytes are included.
- `inventory.json`: exact archive and member lengths/hashes. Every ZIP member
  was reread and verified after packaging.
- `manifest.json`: unchanged candidate completion manifest, also inside the ZIP.
- `source-validation.json`: row counts, complete binding rejection summaries,
  per-file pins, five equal/four different default raw identities, and runtime.
- `execution-report.json`: actual failures, the Windows publication repair,
  five passing publication tests, and the unchanged source-status boundary.

The candidate contains all 351 physical fields. Binding accepts 686 BaseItemTypes
and 6,515 Mods records from the four differing resources; all Characters and
AlternateQualityTypes records remain rejected for this target. The full accepted
and rejected records, including missing keys and differing fields, are preserved
in `target_binding.json`. Do not substitute the Windows default for a differing
English target or silently discard these rejections.

The original RAM process remains available, but replay no longer depends on it.
To reconstruct the same 257 parts without game reads or raw DAT decoding:

1. Verify `inventory.json` against this fixed Git commit, then verify and extract
   `observed-transfer.zip` to a fresh checkout-local
   `.cache/windows-sc-observation-20261101/` directory.
2. Copy `prepare-inputs.py` into that directory and run it with the existing
   Python (`-I -B -S -X utf8`). The script location is intentional: it resolves
   the checkout through `.cache/<observation>/`. It checks every compressed body
   and every part against the original receipt before writing `parts.jsonl`.
   It also verifies/unpacks the separately committed English handoff archive and
   rewrites only local paths in a new target lock.
3. Invoke `python -B -S -m RePoE.native_decoded_tables` using the documented CLI,
   original receipt pin, regenerated parts, and newly observed local lock hash.
   Use a fresh output under the same checkout's `.cache/` for each run.

Relocating the target lock changes its own hash and therefore the new manifest;
it does not change original target manifests, payloads, raw pins, or schema.
The archived candidate and its original Windows target lock stay unchanged.
The source decoder was not upgraded or rerun. Windows publication was repaired
in `native_descriptions.py`; that exact producer hash is in the candidate.
