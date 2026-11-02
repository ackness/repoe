"""Small synthetic historical-input regressions; all HTTP is mocked."""

import copy
import io
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from RePoE import official_tree_input as tree


BASE = "2c645ad54724e386b40137e92d49b89925bee57b"


class HistoricalInputTests(unittest.TestCase):
    def setUp(self):
        (tree.ROOT / ".cache").mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=tree.ROOT / ".cache")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.raw = b'{"unknown":null,"overridePairs":[[19680,40837],[55194,57601]],"value":-3}\r\n'
        self.plan = tree.sio.decode((tree.ROOT / "publication/0.5.5-official-tree-input.plan.json").read_bytes())
        self.plan["input"] = tree._pin(self.raw)
        self.plan["source"]["sha256"] = tree.sio.sha256(self.raw)
        self.cache = self.root / "cache"
        self.body = self.cache / tree.sio.sha256(self.raw) / "data.json"
        tree.sio.write_new(self.body, self.raw)
        self.plan_path = self.root / "plan.json"
        self.out = self.root / "output"
        # Synthetic exports exercise fingerprints without claiming our uncommitted
        # implementation exists in BASE. Real committed closure is tested in handoff.
        committed = patch.object(tree, "_committed", side_effect=lambda rev, name: (tree.ROOT / name).read_bytes())
        committed.start()
        self.addCleanup(committed.stop)
        self.worker = patch.object(tree, "_download", side_effect=tree._http_body)
        self.worker.start()
        self.addCleanup(self.worker.stop)
        network = patch.object(socket, "socket", side_effect=AssertionError("No live network"))
        network.start()
        self.addCleanup(network.stop)

    def write_plan(self):
        raw = tree.sio.encoded(self.plan)
        self.plan_path.write_bytes(raw)
        return tree.sio.sha256(raw)

    def acquire(self, **kwargs):
        return tree.acquire(self.plan_path, self.write_plan(), self.cache, **kwargs)

    def export(self, output=None, **kwargs):
        return tree.export(self.plan_path, self.write_plan(), self.cache, output or self.out, BASE, **kwargs)

    def response(self, raw=None, **changes):
        class Response(io.BytesIO):
            status = 200

            def geturl(inner):
                return tree.source_url(self.plan["source"])

        result = Response(self.raw if raw is None else raw)
        result.headers = {"Content-Length": str(len(self.raw))}
        for key, value in changes.items():
            setattr(result, key, value)
        return result

    def opener(self, response):
        class Opener:
            def open(inner, request, timeout):
                self.assertEqual(request.full_url, tree.source_url(self.plan["source"]))
                self.assertEqual(timeout, 2)
                self.assertEqual(request.get_header("Accept-encoding"), "identity")
                return response

        return patch.object(tree.urllib.request, "build_opener", return_value=Opener())

    def test_offline_exact_bytes_manifest_pins_and_deterministic_replay(self):
        first = self.export()
        second = self.export(self.root / "replay")
        self.assertEqual(first, second)
        raw = (self.out / "data.zip").read_bytes()
        self.assertEqual(raw, (self.root / "replay/data.zip").read_bytes())
        self.assertEqual(tree._pin(raw), {key: first[key] for key in ("bytes", "sha256")})
        with zipfile.ZipFile(self.out / "data.zip") as archive:
            self.assertEqual(archive.namelist(), ["data.json", "manifest.json"])
            self.assertEqual(archive.read("data.json"), self.raw)
            manifest_raw, manifest = tree.pub.archive_manifest(archive, first)
            self.assertEqual(tree._pin(manifest_raw), first["manifest"])
            self.assertEqual(manifest["schema"], tree.FORMAT)
            self.assertEqual(manifest["source"], self.plan["source"])
            self.assertFalse(manifest["production_ready"])
            self.assertIsNone(manifest["source"]["game_patch"])
            self.assertNotIn("corrections", manifest["source"])
            self.assertEqual(set(manifest["producer"]["files"]), set(tree.PRODUCERS))
            self.assertTrue(all(info.compress_type == zipfile.ZIP_STORED for info in archive.infolist()))
            self.assertEqual(first["expanded_bytes"], len(manifest_raw) + len(self.raw))

    def test_cache_hit_never_downloads_even_online(self):
        with patch.object(tree, "_download", side_effect=AssertionError("No HTTP on hit")):
            self.assertEqual(self.acquire(offline=False)["transport"], "existing-cache")

    def test_corrupt_cache_fails_without_network_repair(self):
        self.body.write_bytes(b"broken")
        with patch.object(tree, "_download", side_effect=AssertionError("No repair")):
            for offline in (True, False):
                with self.subTest(offline=offline), self.assertRaisesRegex(ValueError, "bytes/SHA"):
                    self.acquire(offline=offline)
        self.assertEqual(self.body.read_bytes(), b"broken")

    def test_oversized_cache_rejected_without_reading_or_download(self):
        self.body.write_bytes(self.raw + b"x")
        with self.assertRaisesRegex(ValueError, "bounded regular"):
            self.acquire(offline=False)

    def test_corrupt_cache_directory_never_triggers_network(self):
        self.body.unlink()
        self.body.parent.rmdir()
        self.body.parent.write_bytes(b"not a directory")
        with patch.object(tree, "_download", side_effect=AssertionError("No network repair")):
            with self.assertRaisesRegex(ValueError, "Corrupt cache directory"):
                self.acquire(offline=False)

    def test_publication_paths_and_ref_cannot_escape_fixed_handoff(self):
        original = copy.deepcopy(self.plan)
        for key, value in (
            ("repository", "other/data"),
            ("path", "../data.zip"),
            ("path", "/data.zip"),
            ("path", "data\\data.zip"),
            ("ref", "refs/heads/main"),
            ("ref", "refs/heads/handoff/a..b"),
            ("ref", "refs/heads/handoff/a.lock"),
            ("ref", "refs/heads/handoff/.hidden"),
        ):
            self.plan = copy.deepcopy(original)
            self.plan["publication"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.export()
        self.assertFalse(self.out.exists())

    def test_offline_miss_fails_without_output(self):
        self.body.unlink()
        with self.assertRaisesRegex(ValueError, "Offline cache miss"):
            self.export()
        self.assertFalse(self.out.exists())

    def test_fixed_git_url_and_mock_http_replay(self):
        self.body.unlink()
        with self.opener(self.response()):
            result = self.acquire(offline=False, timeout=2)
        self.assertEqual(result["transport"], "fixed-git-blob-http")
        self.assertEqual(self.body.read_bytes(), self.raw)
        self.assertEqual(self.acquire()["transport"], "existing-cache")

    def test_bad_download_bytes_never_enter_cache(self):
        self.body.unlink()
        for body in (b"short", b"x" * len(self.raw), self.raw + b"extra"):
            with self.subTest(body=len(body)), self.opener(self.response(body)):
                with self.assertRaisesRegex(ValueError, "Downloaded bytes/SHA"):
                    self.acquire(offline=False, timeout=2)
            self.assertFalse(self.body.exists())

    def test_wrong_http_identity_encoding_length_status_and_redirect(self):
        self.body.unlink()
        cases = [
            {"status": 206},
            {"geturl": lambda: "https://example.invalid/data.json"},
            {"headers": {"Content-Length": "100"}},
            {"headers": {"Content-Length": str(len(self.raw)), "Transfer-Encoding": "chunked"}},
            {"headers": {"Content-Length": str(len(self.raw)), "Content-Encoding": "gzip"}},
            {"headers": {"Content-Length": str(len(self.raw)), "content-length": str(len(self.raw))}},
        ]
        for case in cases:
            with self.subTest(case=case), self.opener(self.response(**case)):
                with self.assertRaises(ValueError):
                    self.acquire(offline=False, timeout=2)
        with self.assertRaisesRegex(ValueError, "Redirects"):
            tree._NoRedirect().redirect_request(None, None, 302, None, None, "https://example.invalid")
        self.assertFalse(self.body.exists())

    def test_timeout_errors_never_enter_cache(self):
        self.body.unlink()
        for timeout in (0, -1, 31, float("inf"), float("nan"), True):
            with self.subTest(timeout=timeout), self.assertRaisesRegex(ValueError, "timeout"):
                self.acquire(offline=False, timeout=timeout)
        with patch.object(tree.urllib.request, "build_opener") as opener:
            opener.return_value.open.side_effect = TimeoutError("synthetic timeout")
            with self.assertRaises(TimeoutError):
                self.acquire(offline=False, timeout=2)
        self.assertFalse(self.body.exists())

    def test_http_worker_has_wall_deadline_and_verifies_returned_bytes(self):
        self.worker.stop()
        self.body.unlink()
        with patch.object(tree.subprocess, "run") as run:
            run.return_value.stdout = self.raw
            self.acquire(offline=False, timeout=2)
            self.assertEqual(run.call_args.kwargs["timeout"], 2)
            self.assertEqual(run.call_args.args[0][1:3], ["-B", "-S"])
            self.assertEqual(run.call_args.kwargs["cwd"], tree.ROOT)
            self.assertEqual(tree.sio.decode(run.call_args.kwargs["input"])["input"], self.plan["input"])
        self.body.unlink()
        with patch.object(tree.subprocess, "run", side_effect=subprocess.TimeoutExpired("synthetic worker", 2)):
            with self.assertRaises(subprocess.TimeoutExpired):
                self.acquire(offline=False, timeout=2)
        with patch.object(tree.subprocess, "run") as run:
            run.return_value.stdout = b"bad worker bytes"
            with self.assertRaisesRegex(ValueError, "Downloaded bytes/SHA"):
                self.acquire(offline=False, timeout=2)
        self.assertFalse(self.body.exists())

    def test_bad_source_identity_and_pins_fail_before_acquisition(self):
        original = copy.deepcopy(self.plan)
        cases = [
            ("repository", "https://github.com/other/source"),
            ("revision", "main"),
            ("revision", "f" * 39),
            ("path", "../data.json"),
            ("kind", "client"),
            ("realm", "china"),
            ("game_patch", "0.5.5.5"),
            ("sha256", "0" * 64),
            ("corrections", {}),
        ]
        for key, value in cases:
            self.plan = copy.deepcopy(original)
            self.plan["source"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.export()
        for size in (True, 0, -1, tree.MAX_BYTES + 1):
            self.plan = copy.deepcopy(original)
            self.plan["input"]["bytes"] = size
            with self.subTest(size=size), self.assertRaises(ValueError):
                self.export()
        self.assertFalse(self.out.exists())

    def test_plan_pin_duplicate_keys_and_mutation(self):
        self.write_plan()
        with self.assertRaisesRegex(ValueError, "Plan SHA"):
            tree.acquire(self.plan_path, "0" * 64, self.cache)
        self.plan_path.write_bytes(b'{"schema":1,"schema":2}')
        with self.assertRaisesRegex(ValueError, "Duplicate JSON"):
            tree.acquire(self.plan_path, tree.sio.sha256(self.plan_path.read_bytes()), self.cache)
        original_archive = tree._archive

        def mutate(*args):
            self.plan_path.write_bytes(b"changed")
            return original_archive(*args)

        with patch.object(tree, "_archive", side_effect=mutate):
            with self.assertRaisesRegex(ValueError, "plan changed"):
                self.export()
        self.assertFalse((self.out / "package.json").exists())

    def test_symlink_traversal_and_overlap_rejected(self):
        alias = self.root / "alias"
        alias.symlink_to(self.cache, target_is_directory=True)
        self.write_plan()
        with self.assertRaisesRegex(ValueError, "Symlink"):
            tree.acquire(self.plan_path, self.write_plan(), alias)
        with self.assertRaisesRegex(ValueError, "unsafe path"):
            self.export(self.root / "other" / ".." / "output")
        for output in (self.cache / "output", self.root, self.plan_path):
            with self.subTest(output=output), self.assertRaises(ValueError):
                self.export(output)
        with self.assertRaisesRegex(ValueError, "overlaps"):
            tree.acquire(self.plan_path, self.write_plan(), self.root)
        self.body.unlink()
        self.body.symlink_to(self.plan_path)
        with self.assertRaisesRegex(ValueError, "Symlink"):
            self.acquire(offline=False)

    def test_input_changed_before_completion(self):
        archive = tree._archive

        def mutate(*args):
            self.body.write_bytes(b"changed")
            return archive(*args)

        with patch.object(tree, "_archive", side_effect=mutate):
            with self.assertRaisesRegex(ValueError, "bytes/SHA"):
                self.export()
        self.assertFalse((self.out / "package.json").exists())

    def test_producer_commit_and_end_fingerprint_checks(self):
        with patch.object(tree, "_committed", return_value=b"wrong code"):
            with self.assertRaisesRegex(ValueError, "Producer differs"):
                self.export()
        with self.assertRaisesRegex(ValueError, "Full Git revision"):
            tree._producer("main")
        with patch.object(tree.subprocess, "check_output", return_value=b"tree\n"):
            with self.assertRaisesRegex(ValueError, "actual commit"):
                tree._producer(BASE)
        producer = tree._producer(BASE)
        changed = copy.deepcopy(producer)
        changed["files"]["RePoE/official_tree_input.py"]["sha256"] = "0" * 64
        with patch.object(tree, "_producer", side_effect=[producer, changed]):
            with self.assertRaisesRegex(ValueError, "Producer changed"):
                self.export()
        self.assertFalse((self.out / "package.json").exists())

    def test_output_failure_and_completion_write_failure_leave_no_completion(self):
        write = tree.sio.write_new
        for failure in ("data.zip", "manifest.json", "package.json"):
            output = self.root / failure

            def fail(path, raw):
                if path.name == failure:
                    raise OSError("synthetic disk failure")
                return write(path, raw)

            with self.subTest(failure=failure), patch.object(tree.sio, "write_new", side_effect=fail):
                with self.assertRaisesRegex(OSError, "disk failure"):
                    self.export(output)
            self.assertFalse((output / "package.json").exists())

    def test_existing_output_unchanged_and_output_tamper_no_completion(self):
        self.out.mkdir()
        marker = self.out / "keep"
        marker.write_bytes(b"existing")
        with self.assertRaisesRegex(ValueError, "Fresh"):
            self.export()
        self.assertEqual(marker.read_bytes(), b"existing")
        write = tree.sio.write_new

        def tamper(path, raw):
            write(path, raw)
            if path.name == "data.zip":
                path.write_bytes(b"changed")

        with patch.object(tree.sio, "write_new", side_effect=tamper):
            with self.assertRaisesRegex(ValueError, "bytes/SHA"):
                self.export(self.root / "tamper")
        self.assertFalse((self.root / "tamper/package.json").exists())

    def test_local_bare_handoff_and_fresh_fetch_without_original_cache(self):
        spec = self.export()
        handoff = tree.pub.git_handoff(self.out)
        self.body.unlink()
        bare = self.root / "consumer.git"
        subprocess.run(["git", "init", "--bare", "--quiet", str(bare)], check=True)
        subprocess.run(
            ["git", "--git-dir", str(bare), "fetch", "--quiet", handoff["bare"], handoff["ref"]], check=True
        )
        raw = subprocess.check_output(
            ["git", "--git-dir", str(bare), "cat-file", "blob", f"{handoff['revision']}:{handoff['path']}"]
        )
        self.assertEqual(tree._pin(raw), {key: spec[key] for key in ("bytes", "sha256")})
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertEqual(archive.read("data.json"), self.raw)

    def test_cli_acquire_requires_explicit_pins_and_offline_is_default(self):
        import sys

        args = [sys.executable, "-B", "-S", "-m", "RePoE.official_tree_input", "acquire"]
        result = subprocess.run(
            [*args, "--plan", str(self.plan_path), "--plan-sha256", self.write_plan(), "--cache", str(self.cache)],
            capture_output=True,
            check=True,
        )
        self.assertEqual(tree.sio.decode(result.stdout)["transport"], "existing-cache")
        self.body.unlink()
        failed = subprocess.run(
            [*args, "--plan", str(self.plan_path), "--plan-sha256", self.write_plan(), "--cache", str(self.cache)],
            capture_output=True,
        )
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn(b"Offline cache miss", failed.stderr)


if __name__ == "__main__":
    unittest.main()
