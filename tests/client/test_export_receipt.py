"""Export receipts: checkout identity, the dirty-tree refusal, receipt checks and the package pairing rule."""

from pathlib import Path
import unittest
from unittest import mock

from RePoE.client import export_receipt
from RePoE.client.source_io import decode, encoded
from tests.release.test_publish import GitRepoCase

TARGET = {"game": "poe2", "game_patch": "9.9", "realm": "international"}
DIRTY = ("RePoE/native/x.py",)


def identity(commit="c" * 40, dirty_paths=()):
    return {
        "repository": export_receipt.REPOSITORY,
        "commit": commit,
        "dirty": bool(dirty_paths),
        "dirty_paths": list(dirty_paths),
    }


def checkout(test, **changes):
    """Export as from the checkout ``identity(**changes)``: the exporter tests run in trees under edit."""
    patcher = mock.patch.object(export_receipt, "checkout_identity", return_value=identity(**changes))
    patcher.start()
    test.addCleanup(patcher.stop)


def candidate(format_="repoe-native-tables/v1", target=TARGET, **fields):
    """Manifest bytes of a receipted candidate."""
    return encoded(
        {"format": format_, "source_identity": target, export_receipt.FIELD: export_receipt.SCHEMA, **fields}
    )


def receipt_for(manifest_raw, *, rehearsal=False, **changes):
    """Receipt bytes of a candidate manifest exported from ``identity(**changes)``."""
    return export_receipt.receipt_bytes(manifest_raw, "RePoE.native.test", identity(**changes), rehearsal)


def sibling(directory):
    return directory.with_name(export_receipt.receipt_name(directory.name))


def check_exporter(test, export, exporter):
    """What every exporter guarantees; ``export(name, **options)`` writes a new candidate, returns its directory."""
    clean = export("receipt-clean")
    manifest = (clean / "manifest.json").read_bytes()
    test.assertEqual(decode(manifest)[export_receipt.FIELD], export_receipt.SCHEMA)
    verified = export_receipt.verify(sibling(clean).read_bytes(), manifest)
    test.assertEqual((verified["exporter"], verified["producer"], verified["rehearsal"]), (exporter, identity(), False))
    with test.assertRaises(FileExistsError):
        export_receipt.begin(clean, exporter)
    dirty = identity(dirty_paths=DIRTY)
    with mock.patch.object(export_receipt, "checkout_identity", return_value=dirty):
        with test.assertRaisesRegex(ValueError, r"dirty checkout \(RePoE/native/x\.py\)"):
            export("receipt-refused")
        refused = clean.with_name("receipt-refused")
        test.assertFalse(refused.exists() or sibling(refused).exists())
        rehearsal = export("receipt-rehearsal", rehearsal=True)
    # The same bytes as the clean export: a rehearsal shows what the real run will write.
    test.assertEqual((rehearsal / "manifest.json").read_bytes(), manifest)
    verified = export_receipt.verify(sibling(rehearsal).read_bytes(), manifest)
    test.assertEqual((verified["producer"], verified["rehearsal"]), (dirty, True))
    test.assertEqual(export_receipt.refusal(verified), "is a rehearsal")


class CheckoutIdentityTest(GitRepoCase):
    def write(self, name):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("changed")

    def test_dirty_means_exporter_code_or_environment_tracked_or_untracked(self):
        head = self.commit("pyproject.toml")
        self.assertEqual(export_receipt.checkout_identity(self.repo), identity(head))
        # A new patch's locks, request files, declarations and policies change before the export.
        for name in (
            "a.txt",
            "sources/lock.json",
            "RePoE/client/new-request.json",
            "release/9.9/inputs.lock.json",
            "tools/pobr-data-adapter/policies/p.json",
            "RePoE/release/build.py",
        ):
            self.write(name)
        self.assertEqual(export_receipt.checkout_identity(self.repo), identity(head))
        dirty = (
            "RePoE/__init__.py",
            "RePoE/client/limits.py",
            "RePoE/client/source_io.py",
            "RePoE/native/facts.py",
            "RePoE/native/with space.py",
            "mise.toml",
            "pyproject.toml",
            "schema/poe2.json",
        )
        for name in dirty:
            self.write(name)
        self.assertEqual(export_receipt.checkout_identity(self.repo), identity(head, dirty))

    def test_a_directory_without_a_commit_is_an_error(self):
        empty = Path(self.temporary.name) / "empty"
        empty.mkdir()
        export_receipt.git(empty, "init", "-q")
        with self.assertRaisesRegex(ValueError, "git rev-parse --verify .* failed"):
            export_receipt.checkout_identity(empty)


class ReceiptTest(unittest.TestCase):
    def test_verify_binds_the_receipt_to_the_manifest_bytes_and_target(self):
        manifest = candidate()
        raw = receipt_for(manifest)
        verified = export_receipt.verify(raw, manifest)
        self.assertEqual(verified["target"], TARGET)
        self.assertIsNone(export_receipt.refusal(verified))
        changes = (
            ("receipt pins another manifest", lambda r: r["manifest"].update(sha256="0" * 64)),
            ("receipt target differs", lambda r: r["target"].update(game_patch="8.8")),
            ("not a repoe-export-receipt/v1 receipt", lambda r: r.update(schema="repoe-export-receipt/v2")),
            ("not a repoe-export-receipt/v1 receipt", lambda r: r.update(extra=1)),
            ("receipt names no exporter", lambda r: r.update(exporter="")),
            ("invalid receipt producer", lambda r: r["producer"].update(commit="c" * 39)),
            ("invalid receipt producer", lambda r: r["producer"].update(repository="other/repoe")),
            ("invalid receipt producer", lambda r: r["producer"].update(dirty_paths=["x.py"])),
            ("invalid receipt rehearsal flag", lambda r: r.update(rehearsal=0)),
            ("a dirty export must be a rehearsal", lambda r: r["producer"].update(dirty=True, dirty_paths=["x.py"])),
        )
        for message, change in changes:
            with self.subTest(message=message):
                changed = decode(raw)
                change(changed)
                with self.assertRaisesRegex(ValueError, message):
                    export_receipt.verify(encoded(changed), manifest)
        stripped = decode(manifest)
        del stripped[export_receipt.FIELD]
        with self.assertRaisesRegex(ValueError, "lacks producer_receipt"):
            export_receipt.verify(raw, encoded(stripped))
        with self.assertRaisesRegex(ValueError, "receipt pins another manifest"):
            export_receipt.verify(raw, manifest + b"\n")

    def test_refusal_reads_the_content_and_treats_an_absent_rehearsal_field_as_false(self):
        published = {"producer": {"commit": "c" * 40, "dirty": False}}
        self.assertIsNone(export_receipt.refusal(published))
        for expected, receipt in (
            ("is a rehearsal", {**published, "rehearsal": True}),
            ("is a rehearsal", {**published, "rehearsal": "false"}),
            ("was produced from a dirty checkout", {"producer": {"dirty": True}, "rehearsal": False}),
            ("was produced from a dirty checkout", {"producer": {}}),
            ("is not a receipt", {"rehearsal": False}),
            ("is not a receipt", None),
        ):
            self.assertEqual(export_receipt.refusal(receipt), expected)

    def test_a_package_pairs_each_candidate_manifest_with_the_receipt_beside_its_directory(self):
        manifest = candidate()
        beside = receipt_for(manifest)
        historical = encoded({"format": "repoe-native-facts/v4", "source_identity": TARGET})
        members = {
            "manifest.json": manifest,  # the package's own manifest (crafting keeps its exporter's)
            "a/b/manifest.json": manifest,
            "a/b.export-receipt.json": beside,
            "a/b/parent-manifest.json": manifest,  # embedded copies are payloads
            "crafting/input-manifest.json": manifest,
            "old/manifest.json": historical,
            "notes/manifest.json": b"[]\n",
        }

        def receipts(members, formats=()):
            return export_receipt.package_receipts(members, members.__getitem__, formats)

        self.assertEqual(receipts(members), {"a/b.export-receipt.json": decode(beside)})
        for message, change in (
            ("a/b/manifest.json: no export receipt a/b.export-receipt.json", {"a/b.export-receipt.json": None}),
            ("a/b/manifest.json: receipt pins another manifest", {"a/b/manifest.json": manifest + b"\n"}),
            (
                "a/b/manifest.json: Duplicate JSON key",
                {"a/b/manifest.json": manifest.replace(b"{", b'{"format":1,', 1)},
            ),
            ("old.export-receipt.json: export receipt without a candidate", {"old.export-receipt.json": beside}),
            ("b.export-receipt.json: export receipt without a candidate", {"b.export-receipt.json": beside}),
        ):
            with self.subTest(message=message):
                changed = {name: raw for name, raw in {**members, **change}.items() if raw is not None}
                with self.assertRaisesRegex(ValueError, message):
                    receipts(changed)
        # A listed format must be receipted, so an export stripped of the field is not taken for a historical one.
        with self.assertRaisesRegex(ValueError, "old/manifest.json: no export receipt old.export-receipt.json"):
            receipts(members, formats={"repoe-native-facts/v4"})
        with self.assertRaisesRegex(ValueError, "old/manifest.json: candidate manifest lacks producer_receipt"):
            receipts({**members, "old.export-receipt.json": beside}, formats={"repoe-native-facts/v4"})
        rehearsed = {"a/manifest.json": manifest, "a.export-receipt.json": receipt_for(manifest, rehearsal=True)}
        self.assertTrue(receipts(rehearsed)["a.export-receipt.json"]["rehearsal"])


if __name__ == "__main__":
    unittest.main()
