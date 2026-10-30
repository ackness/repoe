from contextlib import ExitStack, redirect_stderr, redirect_stdout
from copy import deepcopy
import gzip
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import warnings

from PyPoE.poe.file.translations import TranslationFile, TranslationFileCache

from RePoE import run_parser
from RePoE.parser.poe2.stat_translations import stat_translations
from RePoE import trade_snapshot as snapshot


FIXTURE = Path(__file__).parent / "fixtures/trade-snapshot"
ROOT = Path(__file__).resolve().parents[1]


def client_fixture():
    tf = TranslationFile()
    tf.read((FIXTURE / "descriptions.csd.txt").read_text().encode("utf-16"))
    files = ["Data/StatDescriptions/z.csd", "Data/StatDescriptions/a.csd"]
    # Hash-seed dependent discovery exercises deterministic file ordering.
    node = SimpleNamespace(
        children={name: SimpleNamespace(name=name, is_file=True) for name in set(["z.csd", "a.csd"])}
    )
    fs = SimpleNamespace(build_directory=lambda: {"Data": {"StatDescriptions": node}})
    return fs, {name: tf for name in files}


def no_network(stack):
    for target in (
        "socket.socket.connect",
        "socket.create_connection",
        "urllib.request.urlopen",
        "requests.sessions.Session.request",
    ):
        stack.enter_context(patch(target, side_effect=AssertionError(f"Unexpected network call: {target}")))


def export_fixture(directory, trade=None):
    fs, translations = client_fixture()
    exporter = stat_translations(
        file_system=fs,
        relational_reader={},
        data_path=str(directory) + os.sep,
        language="English",
        caches={TranslationFileCache: translations},
        sequel=2,
        trade_snapshot=trade,
    )
    with ExitStack() as stack, redirect_stdout(io.StringIO()):
        no_network(stack)
        stack.enter_context(patch("RePoE.parser.poe2.stat_translations.install_data_dependant_quantifiers"))
        exporter.write()
    return {p.relative_to(directory).as_posix(): p.read_bytes() for p in Path(directory).rglob("*.json")}


class TradeSnapshotTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="repoe-trade-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.directory = self.root / "snapshot"
        shutil.copytree(FIXTURE, self.directory)

    def manifest(self):
        return json.loads((self.directory / "manifest.json").read_bytes())

    def write_manifest(self, value):
        (self.directory / "manifest.json").write_text(json.dumps(value), encoding="utf-8")

    def replace_body(self, body):
        (self.directory / "raw/trade-en.json.gz").write_bytes(gzip.compress(body, mtime=0))
        document = self.manifest()
        document["sources"][0].update(snapshot.fingerprint(body))
        self.write_manifest(document)

    def cli(self, args):
        fs, translations = client_fixture()
        with ExitStack() as stack, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            no_network(stack)
            stack.enter_context(patch.object(sys, "argv", ["repoe", *args]))
            discover = stack.enter_context(patch.object(run_parser, "get_cdn_url"))
            files = stack.enter_context(patch.object(run_parser, "load_file_system", return_value=fs))
            reader = stack.enter_context(patch.object(run_parser, "create_relational_reader", return_value={}))
            stack.enter_context(patch.object(run_parser, "get_parser_modules", return_value=[]))
            stack.enter_context(patch.object(run_parser, "get_poe2_modules", return_value=[stat_translations]))
            stack.enter_context(patch.object(stat_translations, "get_cache", return_value=translations))
            stack.enter_context(patch("RePoE.parser.poe2.stat_translations.install_data_dependant_quantifiers"))
            try:
                run_parser.main()
            except SystemExit as error:
                self.assertEqual(error.code, 2)
                discover.assert_not_called()
                files.assert_not_called()
                reader.assert_not_called()
                return False
        discover.assert_not_called()
        files.assert_called_once_with("client")
        reader.assert_called_once()
        return True

    def rejected_without_side_effects(self, extra=None):
        output = self.root / "output"
        output.mkdir(exist_ok=True)
        previous = {
            name: f"previous {name}".encode()
            for name in (
                "stat_value_handlers.json",
                "stat_translations.provenance.json",
                "stat_translations/a.min.json",
            )
        }
        for name, raw in previous.items():
            path = output / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(raw)
        args = ["stat_translations", "--poe2", "--file", "client", "--outdir", str(output)]
        self.assertFalse(self.cli([*args, *(extra or ["--trade-snapshot", str(self.directory)])]))
        self.assertEqual({p.relative_to(output).as_posix(): p.read_bytes() for p in output.rglob("*.json")}, previous)

    def test_pure_client_and_explicit_cli_keep_schema_and_bind_output_bytes(self):
        for trade in (False, True):
            with self.subTest(trade=trade):
                output = self.root / str(trade)
                args = ["stat_translations", "--poe2", "--file", "client", "--outdir", str(output)]
                expected = snapshot.fingerprint((self.directory / "manifest.json").read_bytes())["sha256"]
                if trade:
                    args += ["--trade-snapshot", str(self.directory), "--trade-snapshot-sha256", expected]
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always", ResourceWarning)
                    self.assertTrue(self.cli(args))
                self.assertFalse([w for w in caught if issubclass(w.category, ResourceWarning)])
                descriptions = json.loads((output / "stat_translations/a.min.json").read_bytes())
                self.assertEqual(descriptions[0]["ids"], ["synthetic_mana"])
                self.assertEqual(descriptions[0]["English"][0]["string"], "{0} to maximum Mana")
                if trade:
                    self.assertEqual(descriptions[0]["trade_stats"][0]["id"], "explicit.stat_mana")
                    self.assertEqual([e["text"] for e in descriptions[1]["trade_stats"]], ["First #", "Second #"])
                    self.assertEqual(descriptions[2]["trade_stats"][0]["id"], "explicit.stat_constant")
                    self.assertEqual(descriptions[3]["trade_stats"][0]["id"], "explicit.stat_option")
                    self.assertEqual(descriptions[4]["trade_stats"][0]["id"], "explicit.stat_branch")
                    self.assertNotIn("trade_stats", descriptions[5])
                else:
                    self.assertTrue(all("trade_stats" not in entry for entry in descriptions))
                    pretty = json.loads((output / "stat_translations/a.json").read_bytes())
                    self.assertTrue(all(entry["trade_stats"] is None for entry in pretty))
                provenance = json.loads((output / "stat_translations.provenance.json").read_bytes())
                self.assertEqual(
                    provenance, json.loads((output / "stat_translations.provenance.min.json").read_bytes())
                )
                self.assertIsNone(provenance["game_patch"])
                self.assertIn("not game-stat identity proof", provenance["association_evidence"])
                for name, identity in provenance["outputs"].items():
                    self.assertEqual(snapshot.fingerprint((output / name).read_bytes()), identity)
                if trade:
                    inputs = provenance["trade_snapshot"]
                    self.assertEqual(
                        inputs["manifest"], snapshot.fingerprint((self.directory / "manifest.json").read_bytes())
                    )
                    self.assertEqual(inputs["expected_manifest_sha256"], expected)
                    self.assertEqual(inputs["source"], self.manifest()["sources"][0])
                    self.assertEqual(
                        inputs["compressed_response"],
                        snapshot.fingerprint((self.directory / "raw/trade-en.json.gz").read_bytes()),
                    )
                    self.assertIsNone(inputs["game_patch"])
                else:
                    self.assertIsNone(provenance["trade_snapshot"])

    def test_invalid_options_never_read_client_or_network_or_write(self):
        cases = [
            ["--trade-snapshot-sha256", "0" * 64],
            ["--trade-snapshot-sha256", ""],
            ["--trade-snapshot", ""],
            ["--trade-realm", "international"],
            ["--trade-realm", "china"],
            ["--trade-snapshot", str(self.directory), "--language", "French"],
            ["--trade-snapshot", str(self.directory), "--language", "all"],
            ["--trade-snapshot", str(self.directory), "--trade-realm", "china"],
            ["--trade-snapshot", str(self.directory), "--trade-snapshot-sha256", "0" * 64],
            ["--trade-snapshot", str(self.directory), "--trade-snapshot-sha256", "invalid"],
            ["--trade-snapshot", str(self.root / "missing")],
            ["--trade-snapshot", str(self.directory), "--no-poe2"],
        ]
        for args in cases:
            with self.subTest(args=args):
                self.rejected_without_side_effects(args)

    def test_invalid_snapshot_does_not_discover_a_client_or_create_output_directory(self):
        output = self.root / "must-not-be-created"
        self.assertFalse(
            self.cli(
                [
                    "stat_translations",
                    "--poe2",
                    "--outdir",
                    str(output),
                    "--trade-snapshot",
                    str(self.root / "missing"),
                ]
            )
        )
        self.assertFalse(output.exists())

    def test_missing_selected_module_is_not_silently_ignored(self):
        class tags:
            pass

        for args in (["tags", "--poe2"], ["all", "--poe2", "--resume-from", "tags"]):
            with ExitStack() as stack, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                stack.enter_context(
                    patch.object(sys, "argv", ["repoe", *args, "--trade-snapshot", str(self.directory)])
                )
                stack.enter_context(patch.object(run_parser, "get_parser_modules", return_value=[]))
                stack.enter_context(
                    patch.object(run_parser, "get_poe2_modules", return_value=[stat_translations, tags])
                )
                load = stack.enter_context(patch.object(run_parser, "load_file_system"))
                discover = stack.enter_context(patch.object(run_parser, "get_cdn_url"))
                with self.assertRaises(SystemExit):
                    run_parser.main()
                load.assert_not_called()
                discover.assert_not_called()

    def test_malformed_manifests_and_sources_preserve_existing_outputs(self):
        good = self.manifest()
        mutations = [
            lambda m: m.update(schema_version=True),
            lambda m: m.update(schema_version=2),
            lambda m: m.update(id="../escape"),
            lambda m: m.update(sources={}),
            lambda m: m.update(pages=None),
            lambda m: m.pop("game_patch"),
            lambda m: m["config"]["trade"].update(en=snapshot.TRADE_CN_URL),
            lambda m: m["sources"].append(deepcopy(m["sources"][0])),
            lambda m: m["sources"].append(None),
            lambda m: m["sources"].pop(0),
        ]
        bad_fields = {
            "key": [None, "../trade-en"],
            "url": [snapshot.TRADE_CN_URL, "https://evil.invalid/api/trade2/data/stats"],
            "file": ["../escape.gz", "/raw/trade-en.json.gz", "raw/../trade-en.json.gz", "raw/trade-cn.json.gz"],
            "sha256": [None, "invalid"],
            "bytes": [True, -1, 0, snapshot.MAX_BODY_BYTES + 1],
            "status": [None, 429],
            "fetched_at": [None, ""],
        }
        for key, values in bad_fields.items():
            for value in values:
                mutations.append(lambda m, k=key, v=value: m["sources"][0].update({k: v}))
        for mutate in mutations:
            value = deepcopy(good)
            mutate(value)
            self.write_manifest(value)
            with self.subTest(manifest=value):
                self.rejected_without_side_effects()

    def test_corrupt_gzip_hash_size_and_malformed_bodies_preserve_outputs(self):
        body = gzip.decompress((self.directory / "raw/trade-en.json.gz").read_bytes())
        compressed = gzip.compress(body, mtime=0)
        for raw in (b"not gzip", compressed[:-8], compressed[:-1] + bytes([compressed[-1] ^ 1])):
            (self.directory / "raw/trade-en.json.gz").write_bytes(raw)
            self.rejected_without_side_effects()
        for wrong in ({"bytes": len(body) + 1}, {"sha256": "0" * 64}):
            self.replace_body(body)
            manifest = self.manifest()
            manifest["sources"][0].update(wrong)
            self.write_manifest(manifest)
            self.rejected_without_side_effects()
        malformed = [
            b"{",
            b"\xff",
            b'{"result":[],"result":[]}',
            b'{"result":NaN}',
            b"{}",
            b"[]",
            b'{"result":[]}',
            b'{"result":[null]}',
        ]
        for raw in malformed:
            self.replace_body(raw)
            self.rejected_without_side_effects()
        catalog = json.loads(body)
        mutations = [
            lambda d: d["result"][0]["entries"][0].pop("id"),
            lambda d: d["result"][0]["entries"][0].update(extra="must not drop"),
            lambda d: d["result"][0]["entries"][0].update(text=42),
            lambda d: d["result"][0]["entries"].append(deepcopy(d["result"][0]["entries"][0])),
            lambda d: d["result"][0]["entries"][-1]["option"].update(options=[]),
            lambda d: d["result"].append(deepcopy(d["result"][0])),
        ]
        for mutate in mutations:
            data = deepcopy(catalog)
            mutate(data)
            self.replace_body(json.dumps(data).encode())
            self.rejected_without_side_effects()

    def test_limits_are_enforced_on_manifest_compressed_and_expanded_bytes(self):
        original = (self.directory / "manifest.json").read_bytes()
        with patch.object(snapshot, "MAX_MANIFEST_BYTES", len(original) - 1):
            self.rejected_without_side_effects()
        size = (self.directory / "raw/trade-en.json.gz").stat().st_size
        with patch.object(snapshot, "MAX_GZIP_BYTES", size - 1):
            self.rejected_without_side_effects()
        (self.directory / "raw/trade-en.json.gz").write_bytes(
            gzip.compress(b" " * (snapshot.MAX_BODY_BYTES + 1), mtime=0)
        )
        self.rejected_without_side_effects()

    def test_symlinks_and_noncanonical_paths_are_rejected(self):
        alias = self.root / "alias"
        alias.symlink_to(self.directory, target_is_directory=True)
        self.rejected_without_side_effects(["--trade-snapshot", str(alias)])
        self.rejected_without_side_effects(["--trade-snapshot", str(self.root / "snapshot/../snapshot")])
        for relative in ("manifest.json", "raw/trade-en.json.gz", "raw"):
            source = self.directory / relative
            destination = self.root / (source.name + ".original")
            source.rename(destination)
            source.symlink_to(destination, target_is_directory=destination.is_dir())
            self.rejected_without_side_effects()
            source.unlink()
            destination.rename(source)

    def test_missing_and_non_regular_selected_inputs_are_rejected(self):
        source = self.directory / "raw/trade-en.json.gz"
        source.unlink()
        self.rejected_without_side_effects()
        source.mkdir()
        self.rejected_without_side_effects()

    def test_consumed_bytes_remain_bound_if_source_changes_after_validation(self):
        trade = snapshot.load_trade_snapshot(self.directory)
        original = trade.provenance["response"]
        self.replace_body(b"{}")
        output = self.root / "replay"
        export_fixture(output, trade)
        provenance = json.loads((output / "stat_translations.provenance.json").read_bytes())
        self.assertEqual(provenance["trade_snapshot"]["response"], original)
        self.assertIn("trade_stats", json.loads((output / "stat_translations/a.min.json").read_bytes())[0])

    def test_trade_patch_metadata_does_not_establish_client_patch(self):
        document = self.manifest()
        document["game_patch"] = "synthetic-trade-patch"
        self.write_manifest(document)
        artifacts = export_fixture(self.root / "export", snapshot.load_trade_snapshot(self.directory))
        provenance = json.loads(artifacts["stat_translations.provenance.min.json"])
        self.assertEqual(provenance["trade_snapshot"]["game_patch"], "synthetic-trade-patch")
        self.assertIsNone(provenance["game_patch"])

    def test_deterministic_replay_across_processes_and_snapshot_locations(self):
        alternate = self.root / "copied-snapshot"
        shutil.copytree(self.directory, alternate)
        artifacts = []
        for seed, directory in (("1", self.directory), ("49", alternate)):
            output = self.root / seed
            script = (
                "import sys; from pathlib import Path; sys.path.insert(0, 'tests'); "
                "from test_trade_snapshot import export_fixture; "
                "from RePoE.trade_snapshot import load_trade_snapshot; "
                "export_fixture(Path(sys.argv[1]), load_trade_snapshot(sys.argv[2]))"
            )
            result = subprocess.run(
                [sys.executable, "-W", "error::ResourceWarning", "-c", script, str(output), str(directory)],
                cwd=ROOT,
                env={**os.environ, "PYTHONHASHSEED": seed},
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("ResourceWarning", result.stderr)
            artifacts.append({p.relative_to(output).as_posix(): p.read_bytes() for p in output.rglob("*.json")})
        self.assertEqual(artifacts[0], artifacts[1])

    @unittest.skipUnless(os.environ.get("REPOE_TEST_TRADE_SNAPSHOT"), "optional fixed real snapshot replay")
    def test_real_committed_translation_snapshot_without_api_calls(self):
        with ExitStack() as stack:
            no_network(stack)
            trade = snapshot.load_trade_snapshot(
                os.environ["REPOE_TEST_TRADE_SNAPSHOT"],
                expected_sha256="97f77435167945c52637a2b7314ab3a073c8bd1b20738267c051d96f58c7645b",
            )
        self.assertEqual(
            trade.provenance["response"],
            {"sha256": "3e601b7b31c4a5569912c7a35406a8a754453baf08f9e8702d0f73775cff6e82", "bytes": 853713},
        )
        self.assertEqual(sum(map(len, trade.index.values())), 8303)
        first = export_fixture(self.root / "first", trade)
        second = export_fixture(self.root / "second", trade)
        self.assertEqual(first, second)
        description = json.loads(first["stat_translations/a.min.json"])[0]
        self.assertTrue(description["trade_stats"])
        self.assertTrue(all(e["text"] == "# to maximum Mana" for e in description["trade_stats"]))


if __name__ == "__main__":
    unittest.main()
