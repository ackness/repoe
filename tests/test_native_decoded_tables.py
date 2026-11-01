"""Decoded observation integrity, partial identity and stable-key text binding."""

import copy
import base64
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from RePoE import native_decoded_tables as ingest
from RePoE import native_descriptions as env
from RePoE import native_facts as facts
from RePoE import native_locale_probe as probe
from RePoE import schema_candidate
from RePoE.native_tools import pinned_pypoe
from test_native_facts import dat_bytes


class DecodedIngestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with pinned_pypoe():
            _, cls.spec = schema_candidate._native_specification(
                (schema_candidate.ROOT / "schema/poe2.json").read_bytes()
            )
        cls.schemas = ingest.schema_tables()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="decoded-ingest-test-", dir=ingest.ROOT / ".cache")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()
        self.default = [{"Id": "Lich", "Name": "Lich", "FlavourText": "English", "Unknown0": -7}]
        self.localized = [{**self.default[0], "Name": "巫妖", "FlavourText": "原文😀"}]

    def decode(self, name, rows):
        raw = dat_bytes(self.spec, name, rows)
        return probe.decode_table(name, raw, expected_bytes=len(raw), expected_sha256=env._sha(raw))

    def prepare(self, name="Ascendancy", default=None, localized=None, target=None):
        default = self.default if default is None else default
        localized = self.localized if localized is None else localized
        target = default if target is None else target
        a, b, c = [self.decode(name, rows) for rows in [default, localized, target]]
        transfer = probe.MemoryTransfer(
            observed_client={"game": "poe2", "game_patch": None, "realm": None, "index_sha256": "a" * 64},
            decoder_source_sha256=env._sha((ingest.ROOT / "RePoE/native_locale_probe.py").read_bytes()),
            python_version="synthetic-memory-test",
            evidence=[{"kind": "synthetic-not-game-source", "sha256": "b" * 64}],
        )
        transfer.add_pair(
            a,
            b,
            default_resource=f"data/balance/{name.lower()}.datc64",
            localized_resource=f"data/balance/simplified chinese/{name.lower()}.datc64",
        )
        self.receipt = self.inputs / "receipt.json"
        self.receipt.write_bytes(env._json(transfer.receipt()))
        self.parts = self.inputs / "parts.jsonl"
        self.parts.write_bytes(
            b"".join(env._json(transfer.part(name, i)) for i in range(len(transfer.tables[name]["parts"])))
        )
        package = self.root / "target"
        package.mkdir()
        table = {
            "table": name,
            "raw_resource": f"Data/Balance/{name}.datc64",
            "physical_fields": c["physical_fields"],
            "columns": facts._columns(self.schemas[name], c["physical_fields"]),
            "validation": c["validation"],
            "rows": c["rows"],
        }
        raw = env._json({name: table})
        (package / "tables.json").write_bytes(raw)
        manifest = {
            "format": "repoe-native-tables/v1",
            "status": "partial-candidate",
            "production_ready": False,
            "source_identity": {
                "game": "poe2",
                "game_patch": "0.5.5.5",
                "realm": "international",
                "raw_resources": {table["raw_resource"]: c["raw_identity"]},
            },
            "schema": ingest.schemas(),
            "files": {"tables.json": {"bytes": len(raw), "sha256": env._sha(raw)}},
        }
        (package / "manifest.json").write_bytes(env._json(manifest))
        self.lock = self.inputs / "target-lock.json"
        self.lock.write_bytes(
            env._json(
                {
                    "format": "repoe-language-target-lock/v1",
                    "tables": {
                        name: {
                            "package": str(package),
                            "manifest_sha256": env._sha((package / "manifest.json").read_bytes()),
                        }
                    },
                }
            )
        )
        self.transfer = transfer
        return a, b, c

    def create(self, out="actual-a"):
        return ingest.create_candidate(
            transfer_receipt=self.receipt,
            expected_transfer_receipt_sha256=env._sha(self.receipt.read_bytes()),
            parts=self.parts,
            target_lock=self.lock,
            expected_target_lock_sha256=env._sha(self.lock.read_bytes()),
            out=self.root / out,
        )

    def binding(self, table="Ascendancy"):
        return env._decode((self.root / "actual-a/target_binding.json").read_bytes())["tables"][table]

    def test_resource_bound_preserves_null_identity_full_tables_and_replay(self):
        self.prepare()
        with patch("socket.socket", side_effect=AssertionError("offline")):
            first = self.create()
            self.assertEqual(first, self.create("actual-b"))
        self.assertEqual(first["format"], "repoe-localized-tables/v2")
        self.assertIsNone(first["source_identity"]["game_patch"])
        self.assertIsNone(first["observed_client"]["realm"])
        self.assertEqual(first["target_binding"]["game_patch"], "0.5.5.5")
        self.assertFalse(first["ingest"]["raw_dat_redecoded"])
        self.assertEqual(set(first["files"]) >= {"tables.json", "default-tables.json", "target_binding.json"}, True)
        record = self.binding()["records"][0]
        self.assertEqual((record["decision"], record["binding_kind"]), ("accepted", "resource-bound"))
        self.assertEqual(record["english"], {"Name": "Lich", "FlavourText": "English"})
        self.assertEqual(record["source_default_rows"], [0])
        with self.assertRaises(FileExistsError):
            self.create()

    def test_record_binding_joins_stable_keys_after_row_order_changes(self):
        default = self.default + [{**self.default[0], "Id": "Other", "Name": "Other"}]
        localized = [{**row, "Name": "译名"} for row in reversed(default)]
        self.prepare(default=default, localized=localized, target=list(reversed(default)))
        self.create()
        records = self.binding()["records"]
        self.assertEqual([r["decision"] for r in records], ["accepted", "accepted"])
        self.assertEqual(records[0]["binding_kind"], "record-bound")
        self.assertEqual(records[0]["source_default_rows"], [0])
        self.assertEqual(records[0]["source_localized_rows"], [1])
        self.assertEqual(records[0]["target_rows"], [1])

    def test_duplicates_missing_and_unknown_nontext_changes_reject_without_first_row(self):
        self.prepare(default=self.default * 2, localized=self.localized, target=[{**self.default[0], "Unknown0": 99}])
        self.create()
        record = self.binding()["records"][0]
        self.assertEqual(record["decision"], "rejected")
        self.assertEqual(record["source_default_rows"], [0, 1])
        self.assertIn("source-default-duplicate-key", record["reason_codes"])
        a, b, c = [
            self.decode("Ascendancy", rows)
            for rows in [self.default, self.localized, [{**self.default[0], "Unknown0": 99}, {"Id": "Missing"}]]
        ]
        records = ingest.bind_table("Ascendancy", a, b, c, {"raw_identity": c["raw_identity"]})["records"]
        self.assertIn("target_nontext-mismatch", records[0]["reason_codes"])
        self.assertIn("source-default-missing-key", records[1]["reason_codes"])

    def test_words_text_identity_is_nontext_and_inflection_is_not_inferred(self):
        self.prepare(
            name="Words",
            default=[{"HASH32": 8, "Text": "English", "Text2": "English", "Wordlist": 3}],
            localized=[{"HASH32": 8, "Text": "changed", "Text2": "译名", "Wordlist": 3}],
        )
        self.create()
        binding = self.binding("Words")
        self.assertEqual(binding["text_fields"], ["Text2", "Inflection"])
        self.assertIn("Text", binding["nontext_fields"])
        self.assertIn("source_nontext-mismatch", binding["records"][0]["reason_codes"])
        self.assertEqual(binding["records"][0]["english"]["Inflection"], "")

    def test_bad_missing_and_duplicate_parts_reject_before_output(self):
        self.prepare()
        original = self.parts.read_bytes()
        for number, raw in enumerate([b"", original + original, original.replace(b'"data":"', b'"data":"A', 1)]):
            self.parts.write_bytes(raw)
            with self.assertRaises((ValueError, KeyError)):
                self.create(str(number))
            self.assertFalse((self.root / str(number)).exists())

    def test_target_payload_pin_and_receipt_schema_mismatch_reject(self):
        self.prepare()
        package = self.root / "target/tables.json"
        package.write_bytes(package.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "external pin"):
            self.create()
        receipt = env._decode(self.receipt.read_bytes())
        receipt["observed_client"]["game_patch"] = "0.5.5.5"
        self.receipt.write_bytes(env._json(receipt))
        with self.assertRaisesRegex(ValueError, "unknown-patch"):
            self.create()

    def test_typed_value_and_schema_drift_are_not_silently_accepted(self):
        a, _, _ = self.prepare()
        malformed = copy.deepcopy(a)
        malformed["rows"][0]["values"]["Unknown0"] = True
        with self.assertRaisesRegex(ValueError, "integer"):
            probe.validate_table(malformed)
        malformed = copy.deepcopy(a)
        del malformed["rows"][0]["values"]["Unknown0"]
        with self.assertRaisesRegex(ValueError, "columns"):
            probe.validate_table(malformed)

    def test_all_eighteen_text_fields_exist_in_fixed_physical_schema(self):
        self.assertEqual(sum(map(len, probe.TEXT_FIELDS.values())), 18)
        for name, fields in probe.TEXT_FIELDS.items():
            self.assertTrue(set(fields) <= dict(probe.LAYOUTS[name]).keys())

    def test_current_english_mismatch_rejects_record_bound_identity(self):
        self.prepare(target=[{**self.default[0], "Name": "Different current English"}])
        self.create()
        record = self.binding()["records"][0]
        self.assertEqual(record["decision"], "rejected")
        self.assertIn("target_english-mismatch", record["reason_codes"])
        self.assertEqual(record["english"]["Name"], "Different current English")

    def test_unsafe_receipt_numbers_and_decompression_overflow_reject(self):
        self.prepare()
        receipt = env._decode(self.receipt.read_bytes())
        receipt["observed_client"]["index_sha256"] = 18374403900871474942
        self.receipt.write_bytes(env._json(receipt))
        with self.assertRaisesRegex(ValueError, "Unsafe/noninteger"):
            self.create()
        receipt = self.transfer.receipt()
        receipt["tables"]["Ascendancy"]["decoded"]["bytes"] = 128 * 1024 * 1024 + 1
        self.receipt.write_bytes(env._json(receipt))
        with self.assertRaisesRegex(ValueError, "outside bound"):
            self.create()

    def test_trailing_compressed_data_is_rejected_even_with_matching_part_pins(self):
        self.prepare()
        original = self.transfer.part("Ascendancy", 0)["data"]
        compressed = base64.b64decode(original) + b"trailing"
        data = base64.b64encode(compressed).decode("ascii")
        self.parts.write_bytes(env._json({"table": "Ascendancy", "index": 0, "data": data}))
        receipt = self.transfer.receipt()
        receipt["tables"]["Ascendancy"]["compressed"] = {"bytes": len(compressed), "sha256": env._sha(compressed)}
        receipt["tables"]["Ascendancy"]["parts"] = [{"index": 0, "bytes": len(data), "sha256": env._sha(data.encode())}]
        self.receipt.write_bytes(env._json(receipt))
        with self.assertRaisesRegex(ValueError, "framing/bound"):
            self.create()


if __name__ == "__main__":
    unittest.main()
