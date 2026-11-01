"""Ingest pinned decoded observations; bind language to separately pinned targets.

No raw DAT is decoded here. The output records remote stdlib memory decoding
and local transfer validation separately from the existing native-table exporter.
"""

import argparse
import base64
from collections import defaultdict
from pathlib import Path
import re
import sys
import zlib

from RePoE import native_descriptions as env
from RePoE import native_facts as facts
from RePoE import native_locale_probe as probe


ROOT = Path(__file__).resolve().parents[1]
FORMAT = "repoe-localized-tables/v2"
POLICY = "stable-key-current-english-all-nontext/v1"
SPEC_SHA = "c9417f03e2205ff649721c3dbf9620ee0c703bf905b3cf53469ce3eda86f1e25"


def pinned(path, expected, cap):
    raw = env._read(Path(path), cap)
    if not env._digest(expected) or env._sha(raw) != expected:
        raise ValueError(f"Input differs from external pin: {path}")
    return raw


def schema_tables():
    raw = pinned(ROOT / "schema/poe2.json", probe.SCHEMA_SHA256, 4 * 1024 * 1024)
    return {table["name"]: table for table in env._decode(raw)["tables"]}


def schemas():
    return {"revision": probe.SCHEMA_REVISION, "sha256": probe.SCHEMA_SHA256, "native_specification_sha256": SPEC_SHA}


def resource(name, value, localized):
    prefix = "data/balance/" + ("simplified chinese/" if localized else "")
    if not isinstance(value, str) or value.casefold() != prefix + name.casefold() + ".datc64":
        raise ValueError("Unexpected indexed table resource path")
    return value


def _transfer(receipt_path, expected, parts_path):
    receipt_raw = pinned(receipt_path, expected, 2 * 1024 * 1024)
    receipt = env._decode(receipt_raw)

    def safe_receipt(value):
        if isinstance(value, dict):
            for entry in value.values():
                safe_receipt(entry)
        elif isinstance(value, list):
            for entry in value:
                safe_receipt(entry)
        elif type(value) is float or (type(value) is int and abs(value) > 2**53 - 1):
            raise ValueError("Unsafe/noninteger receipt number; use exact decimal/hex strings")

    safe_receipt(receipt)
    if (
        receipt.get("format") != "repoe-decoded-table-transfer/v1"
        or receipt.get("status") != "unreviewed-decoded-observation"
        or receipt.get("raw_bytes_transferred") is not False
        or receipt.get("patch_certified") is not False
        or receipt.get("realm_certified") is not False
        or receipt.get("language") != "Simplified Chinese"
        or receipt.get("schema") != {"revision": probe.SCHEMA_REVISION, "sha256": probe.SCHEMA_SHA256}
    ):
        raise ValueError("Unsupported decoded transfer/schema/locale")
    if set(receipt["decoder"]) != {"method", "source_sha256", "python", "zlib"} or not isinstance(
        receipt["decoder"]["zlib"], str
    ):
        raise ValueError("Invalid independent memory-decoder provenance")
    # Reuse exact declaration validation, without performing remote decoding.
    probe.MemoryTransfer(
        observed_client=receipt["observed_client"],
        decoder_source_sha256=receipt["decoder"]["source_sha256"],
        python_version=receipt["decoder"]["python"],
        evidence=receipt["acquisition_evidence"],
    )
    if receipt["decoder"]["method"] != probe.METHOD or receipt["decoder"]["source_sha256"] != env._sha(
        (ROOT / "RePoE/native_locale_probe.py").read_bytes()
    ):
        raise ValueError("Transfer decoder differs from this reviewed memory decoder")
    entries = receipt["tables"]
    if not isinstance(entries, dict) or not 1 <= len(entries) <= 9 or not entries.keys() <= probe.LAYOUTS.keys():
        raise ValueError("Transfer table selection outside nine-table contract")
    parts_raw = env._read(Path(parts_path), 48 * 1024 * 1024)
    parts = {}
    for line in parts_raw.splitlines():
        if not line or len(line) > 26000:
            raise ValueError("Empty/oversized transfer part line")
        part = env._decode(line)
        if set(part) != {"table", "index", "data"} or part["table"] not in entries or type(part["index"]) is not int:
            raise ValueError("Invalid transfer part identity")
        key = (part["table"], part["index"])
        if (
            key in parts
            or not isinstance(part["data"], str)
            or not 0 < len(part["data"]) <= 24576
            or not part["data"].isascii()
        ):
            raise ValueError("Duplicate or invalid transfer part")
        parts[key] = part["data"].encode("ascii")
    tables, total_decoded, total_compressed, consumed, paths = {}, 0, 0, set(), set()
    for name, entry in sorted(entries.items()):
        chunks = entry["parts"]
        if not isinstance(chunks, list) or not 1 <= len(chunks) <= 1024:
            raise ValueError("Invalid transfer part count")
        body = []
        for index, pin in enumerate(chunks):
            data = parts.get((name, index))
            if (
                pin.get("index") != index
                or data is None
                or len(data) != pin["bytes"]
                or env._sha(data) != pin["sha256"]
            ):
                raise ValueError("Missing/reordered/corrupt transfer part")
            consumed.add((name, index))
            body.append(data)
        compressed = base64.b64decode(b"".join(body), validate=True)
        if (
            len(compressed) != entry["compressed"]["bytes"]
            or env._sha(compressed) != entry["compressed"]["sha256"]
            or len(compressed) > 16 * 1024 * 1024
        ):
            raise ValueError("Compressed table transfer pin/bound mismatch")
        limit = entry["decoded"]["bytes"]
        if type(limit) is not int or not 0 < limit <= 128 * 1024 * 1024:
            raise ValueError("Decoded transfer size outside bound")
        total_compressed += len(compressed)
        total_decoded += limit
        if total_compressed > 32 * 1024 * 1024 or total_decoded > 256 * 1024 * 1024:
            raise ValueError("Total transfer exceeds bound")
        decoder = zlib.decompressobj()
        raw = decoder.decompress(compressed, limit + 1)
        if (
            len(raw) != limit
            or not decoder.eof
            or decoder.unused_data
            or decoder.unconsumed_tail
            or env._sha(raw) != entry["decoded"]["sha256"]
        ):
            raise ValueError("Decoded transfer hash/framing/bound mismatch")
        pair = env._decode(raw)
        if set(pair) != {"default", "localized"}:
            raise ValueError("Decoded transfer must retain both complete tables")
        for locale in pair:
            table = pair[locale]
            if (
                probe.validate_table(table) != name
                or entry[locale]["raw_identity"] != table["raw_identity"]
                or entry[locale]["rows"] != len(table["rows"])
                or entry[locale]["columns_sha256"] != probe.COLUMN_PINS[name]
            ):
                raise ValueError("Decoded table differs from transfer receipt")
            path = resource(name, entry[locale]["raw_resource"], locale == "localized")
            if path.casefold() in paths:
                raise ValueError("Case-colliding transfer resources")
            paths.add(path.casefold())
        tables[name] = pair
    if consumed != parts.keys():
        raise ValueError("Unexpected transfer parts outside declared inventory")
    return receipt_raw, receipt, parts_raw, tables


def _targets(lock_path, expected, names, source_schemas):
    lock_raw = pinned(lock_path, expected, 2 * 1024 * 1024)
    lock = env._decode(lock_raw)
    if lock.get("format") != "repoe-language-target-lock/v1" or set(lock.get("tables", {})) != set(names):
        raise ValueError("Explicit exact selected target table inventory required")
    tables, pins, identity, verified = {}, {}, None, []
    cache = {}
    for name, selection in sorted(lock["tables"].items()):
        package = Path(selection["package"])
        expected_manifest = selection["manifest_sha256"]
        if (str(package), expected_manifest) not in cache:
            raw = pinned(package / "manifest.json", expected_manifest, 4 * 1024 * 1024)
            manifest = env._decode(raw)
            cache[(str(package), expected_manifest)] = manifest
            verified.append((package / "manifest.json", expected_manifest, 4 * 1024 * 1024))
        manifest = cache[(str(package), expected_manifest)]
        if manifest.get("status") != "partial-candidate" or manifest.get("production_ready") is not False:
            raise ValueError("Target must be an explicit partial native candidate")
        if manifest.get("format") not in {
            "repoe-native-facts/v4",
            "repoe-native-tables/v1",
            "repoe-localized-tables/v1",
        }:
            raise ValueError("Unsupported pinned English target package")
        source = manifest["source_identity"]
        current = {key: source[key] for key in ["game", "game_patch", "realm"]}
        if (
            current["game"] != "poe2"
            or not isinstance(current["game_patch"], str)
            or not re.fullmatch(r"\d+(?:\.\d+){2,5}", current["game_patch"])
            or current["realm"] not in {"international", "china"}
            or source.get("language", "English") != "English"
        ):
            raise ValueError("Target requires explicit known English game/patch/realm")
        if identity is not None and current != identity:
            raise ValueError("Target package game/patch/realm mismatch")
        identity = current
        if any(manifest["schema"].get(key) != value for key, value in schemas().items()):
            raise ValueError("Target native schema differs from selected source schema")
        payload = "tables.json" if "tables.json" in manifest["files"] else f"tables/{name}.json"
        payload_pin = manifest["files"][payload]
        payload_raw = pinned(package / payload, payload_pin["sha256"], 128 * 1024 * 1024)
        if len(payload_raw) != payload_pin["bytes"]:
            raise ValueError("Target payload byte count mismatch")
        verified.append((package / payload, payload_pin["sha256"], 128 * 1024 * 1024))
        document = env._decode(payload_raw)
        table = document[name] if payload == "tables.json" else document
        fields = [field for field, _ in probe.LAYOUTS[name]]
        if (
            table["table"] != name
            or table["physical_fields"] != fields
            or table["columns"] != facts._columns(source_schemas[name], fields)
        ):
            raise ValueError("Target physical columns differ from fixed source schema")
        path = resource(name, table["raw_resource"], False)
        raw_pin = source["raw_resources"][path]
        # This proxy only checks value shapes. It is never emitted as decoding provenance.
        proxy = {
            **table,
            "wire_layout": probe.LAYOUTS[name],
            "schema": {
                "revision": probe.SCHEMA_REVISION,
                "sha256": probe.SCHEMA_SHA256,
                "columns_sha256": probe.COLUMN_PINS[name],
            },
            "raw_identity": raw_pin,
            "validation": {key: table["validation"][key] for key in ["rows", "schema_row_bytes", "actual_row_bytes"]},
            "decoder_method": probe.METHOD,
            "foreign_tail_observations": [],
        }
        probe.validate_table(proxy)
        tables[name] = table
        pins[name] = {
            **current,
            "language": "English",
            "manifest_sha256": expected_manifest,
            "payload": payload,
            "payload_sha256": payload_pin["sha256"],
            "payload_bytes": payload_pin["bytes"],
            "table_pointer": "/" + name if payload == "tables.json" else "",
            "raw_resource": path,
            "raw_identity": raw_pin,
            "schema": schemas(),
            "columns_sha256": probe.COLUMN_PINS[name],
        }
    return lock_raw, tables, pins, identity, verified


def bind_table(name, default, localized, target, target_pin):
    key = "HASH32" if name == "Words" else "Id"
    text_fields = probe.TEXT_FIELDS[name]
    fields = default["physical_fields"]
    nontext = [field for field in fields if field not in text_fields]
    groups = []
    for table in [default, localized, target]:
        grouped = defaultdict(list)
        for row in table["rows"]:
            grouped[row["values"][key]].append(row)
        groups.append(grouped)
    resource_equal = default["raw_identity"] == target_pin["raw_identity"]
    records = []
    for identity in sorted(
        set().union(*(g.keys() for g in groups)), key=lambda value: (type(value).__name__, str(value))
    ):
        rows = [g.get(identity, []) for g in groups]
        reasons = []
        for role, entries in zip(["source-default", "source-localized", "target"], rows):
            if not entries:
                reasons.append(role + "-missing-key")
            elif len(entries) != 1:
                reasons.append(role + "-duplicate-key")
        if identity is None or identity == "":
            reasons.append("invalid-stable-key")
        comparison = {"source_nontext_equal": None, "target_nontext_equal": None, "target_english_equal": None}
        english, differing = {}, {}
        if len(rows[2]) == 1:
            english = {
                field: rows[2][0]["values"][field] for field in text_fields + (["Text"] if name == "Words" else [])
            }
        if all(len(entries) == 1 for entries in rows):
            a, b, c = [entries[0]["values"] for entries in rows]
            differing = {
                "source_nontext": [field for field in nontext if a[field] != b[field]],
                "target_nontext": [field for field in nontext if a[field] != c[field]],
                "target_english": [
                    field for field in text_fields + (["Text"] if name == "Words" else []) if a[field] != c[field]
                ],
            }
            comparison = {
                "source_nontext_equal": not differing["source_nontext"],
                "target_nontext_equal": not differing["target_nontext"],
                "target_english_equal": not differing["target_english"],
            }
            reasons.extend(label + "-mismatch" for label, columns in differing.items() if columns)
        records.append(
            {
                "table": name,
                "key_field": key,
                "id": identity,
                "decision": "rejected" if reasons else "accepted",
                "binding_kind": "resource-bound" if resource_equal else "record-bound",
                "reason_codes": reasons,
                "source_default_rows": [r["_row"] for r in rows[0]],
                "source_localized_rows": [r["_row"] for r in rows[1]],
                "target_rows": [r["_row"] for r in rows[2]],
                "english": english,
                "comparison": comparison,
                "differing_fields": differing,
            }
        )
    return {
        "target_pins": target_pin,
        "text_fields": text_fields,
        "nontext_fields": nontext,
        "key_field": key,
        "source_default_raw_equals_target": resource_equal,
        "records": records,
    }


def _payloads(receipt_raw, receipt, parts_raw, pairs, lock_raw, targets, target_pins, target_identity, source_schemas):
    localized, defaults, bindings, wires = {}, {}, {}, {}
    for name, pair in pairs.items():
        fields = [field for field, _ in probe.LAYOUTS[name]]
        for role, out in [("default", defaults), ("localized", localized)]:
            source = pair[role]
            out[name] = {
                "table": name,
                "raw_resource": receipt["tables"][name][role]["raw_resource"],
                "row_key": facts.ROW_KEY,
                "physical_fields": fields,
                "columns": facts._columns(source_schemas[name], fields),
                "rows": source["rows"],
                "validation": source["validation"],
            }
        bindings[name] = bind_table(name, pair["default"], pair["localized"], targets[name], target_pins[name])
        # Safe exact strings in receipt-side wire evidence; payload integers never pass through JS.
        wires[name] = {
            role: [
                {"context": item["context"], "raw_second_word_decimal": str(item["raw_second_word"])}
                for item in pair[role]["foreign_tail_observations"]
            ]
            for role in pair
        }
    binding = {
        "policy_id": POLICY,
        "target_identity": target_identity,
        "tables": bindings,
        "row_addresses_are_identity": False,
        "reference_policy": "Physical schema values compared; no cross-client reference meaning inferred.",
    }
    payloads = {
        "tables.json": env._json(localized),
        "default-tables.json": env._json(defaults),
        "target_binding.json": env._json(binding),
        "wire-observations.json": env._json(wires),
        "transfer-receipt.json": receipt_raw,
        "target-lock.json": lock_raw,
    }
    summaries = {
        name: {
            "accepted": sum(r["decision"] == "accepted" for r in b["records"]),
            "rejected": sum(r["decision"] == "rejected" for r in b["records"]),
        }
        for name, b in bindings.items()
    }
    source = {
        "source": "decoded-observation-" + env._sha(receipt_raw),
        "kind": "decoded-client-language-observation",
        **{k: receipt["observed_client"][k] for k in ["game", "game_patch", "realm"]},
        "language": "Simplified Chinese",
        "observation_receipt_sha256": env._sha(receipt_raw),
        "raw_resources": {
            entry["localized"]["raw_resource"]: entry["localized"]["raw_identity"]
            for entry in receipt["tables"].values()
        },
        "acquisition": {"status": "unreviewed-decoded-observation", "evidence": receipt["acquisition_evidence"]},
    }
    manifest = {
        "format": FORMAT,
        "status": "partial-observation-candidate",
        "production_ready": False,
        "source_identity": source,
        "observed_client": {
            **receipt["observed_client"],
            "resources": {
                entry[role]["raw_resource"]: entry[role]["raw_identity"]
                for entry in receipt["tables"].values()
                for role in ["default", "localized"]
            },
        },
        "target_binding": {
            "policy_id": POLICY,
            **target_identity,
            "file": "target_binding.json",
            "tables": {
                name: {
                    "target_pins": entry["target_pins"],
                    "text_fields": entry["text_fields"],
                    "nontext_fields": entry["nontext_fields"],
                }
                for name, entry in bindings.items()
            },
        },
        "schema": schemas(),
        "decoder": receipt["decoder"],
        "ingest": {
            "method": "decoded-observation-validation/v1",
            "python_version": sys.version.split()[0],
            "raw_dat_redecoded": False,
            "transfer_receipt_sha256": env._sha(receipt_raw),
            "parts_jsonl_sha256": env._sha(parts_raw),
            "target_lock_sha256": env._sha(lock_raw),
        },
        "producer": {
            name: env._sha((ROOT / name).read_bytes())
            for name in [
                "RePoE/native_decoded_tables.py",
                "RePoE/native_locale_probe.py",
                "RePoE/native_descriptions.py",
                "RePoE/native_facts.py",
                "schema/poe2.json",
            ]
        },
        "summary": {"tables": {name: len(table["rows"]) for name, table in localized.items()}, "bindings": summaries},
        "scope": "Observed client language only. Null patch/realm remain unknown; target-bound accepted text records do not certify source version/realm or numerical equivalence. Rejected/missing/duplicate keys remain evidence. No original native-table-export provenance is claimed.",
        "files": {name: {"bytes": len(raw), "sha256": env._sha(raw)} for name, raw in payloads.items()},
    }
    payloads["manifest.json"] = env._json(manifest)
    return manifest, payloads


def create_candidate(
    *, transfer_receipt, expected_transfer_receipt_sha256, parts, target_lock, expected_target_lock_sha256, out
):
    sys.dont_write_bytecode = True
    output = Path(out).absolute()
    cache = ROOT.resolve(strict=True) / ".cache"
    if output.exists() or output.is_symlink():
        raise FileExistsError("Refusing to replace decoded-language candidate")
    if output.resolve() == cache or not output.resolve().is_relative_to(cache):
        raise ValueError("Decoded candidate must be under this checkout's .cache/")
    source_schemas = schema_tables()
    receipt_raw, receipt, parts_raw, pairs = _transfer(transfer_receipt, expected_transfer_receipt_sha256, parts)
    lock_raw, targets, target_pins, target_identity, verified = _targets(
        target_lock, expected_target_lock_sha256, pairs, source_schemas
    )
    manifest, payloads = _payloads(
        receipt_raw, receipt, parts_raw, pairs, lock_raw, targets, target_pins, target_identity, source_schemas
    )
    if (
        env._read(Path(transfer_receipt), 2 * 1024 * 1024) != receipt_raw
        or env._read(Path(parts), 48 * 1024 * 1024) != parts_raw
        or env._read(Path(target_lock), 2 * 1024 * 1024) != lock_raw
    ):
        raise ValueError("Decoded ingest inputs changed before publication")
    for path, expected, cap in verified:
        pinned(path, expected, cap)
    for name, expected in manifest["producer"].items():
        if env._sha((ROOT / name).read_bytes()) != expected:
            raise ValueError("Decoded ingest producer changed before publication")
    env._publish(output, Path(parts).resolve().parent, payloads)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in [
        "transfer-receipt",
        "expected-transfer-receipt-sha256",
        "parts",
        "target-lock",
        "expected-target-lock-sha256",
        "out",
    ]:
        parser.add_argument("--" + name, required=True)
    try:
        manifest = create_candidate(**vars(parser.parse_args()))
    except (ValueError, KeyError, TypeError, OSError, zlib.error) as error:
        parser.exit(1, f"Decoded-language ingress rejected: {error}\n")
    print(env._json(manifest["summary"]).decode(), end="")


if __name__ == "__main__":
    main()
