"""Standard-library-only discovery tests; all TCP servers are loopback fakes."""

from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from RePoE import client_version as client


ROOT = Path(__file__).resolve().parents[1]
CDN = "https://patch-poe2.poecdn.com/9.12.345.6/"
RESULT = {"cdn": CDN, "version": "9.12.345.6"}
RAW = b"\x00\x02\x00" + CDN.encode("utf-16le")


@contextmanager
def server(respond):
    errors = []
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(3)

        def run():
            try:
                with listener.accept()[0] as connection:
                    connection.settimeout(2)
                    handshake = bytearray()
                    while len(handshake) < 2:
                        chunk = connection.recv(2 - len(handshake))
                        if not chunk:
                            raise AssertionError("Client closed before handshake")
                        handshake.extend(chunk)
                    if handshake != b"\x01\x07":
                        raise AssertionError(f"Wrong handshake: {handshake!r}")
                    respond(connection)
            except BaseException as error:
                errors.append(error)

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        try:
            yield {"host": "127.0.0.1", "port": listener.getsockname()[1], "timeout": 1.0}
        finally:
            worker.join(4)
            if worker.is_alive():
                raise AssertionError("Fake server did not finish")
            if errors:
                raise errors[0]


class ParseTests(unittest.TestCase):
    def test_every_tcp_and_utf16_split_on_both_alignments(self):
        for prefix in (b"\x02\x00", b"\x02\x00\x00"):
            raw = prefix + CDN.encode("utf-16le")
            for split in range(len(raw)):
                with self.subTest(alignment=len(prefix) % 2, split=split):
                    self.assertIsNone(client.parse_response(raw[:split]))
                    self.assertEqual(client.parse_response(raw[:split] + raw[split:]), RESULT)

    def test_truncated_wrong_host_garbage_and_nonexact_roots(self):
        for text in (
            "https://patch-poe2.poecdn.com/9.1",
            "https://other.example/9.1/",
            "garbage",
            "http://patch-poe2.poecdn.com/9.1/",
            "//patch-poe2.poecdn.com/9.1/",
            "https://patch-poe2.poecdn.com.evil/9.1/",
            "https://patch-poe2.poecdn.com:443/9.1/",
            "https://patch-poe2.poecdn.com@evil/9.1/",
            "https://patch-poe2.poecdn.com/9/",
            "https://patch-poe2.poecdn.com/9.1a/",
            "https://patch-poe2.poecdn.com/９.１/",
            "https://patch-poe2.poecdn.com/9.1?x/",
        ):
            with self.subTest(text=text):
                self.assertIsNone(client.parse_response(text.encode("utf-16le")))
        # Invalid UTF-16 units must not disappear and join a fabricated URL.
        self.assertIsNone(
            client.parse_response(CDN.replace("https", "ht\ud800tps").encode("utf-16le", "surrogatepass"))
        )
        self.assertIsNone(client.parse_response(b""))
        self.assertIsNone(client.parse_response(b"\x00"))

    def test_exact_size_limit_and_one_byte_overflow(self):
        raw = b"\x00" * (client.MAX_RESPONSE - len(RAW)) + RAW
        self.assertEqual(client.parse_response(raw), RESULT)
        with self.assertRaisesRegex(ValueError, "64 KiB"):
            client.parse_response(raw + b"\x00")


class QueryTests(unittest.TestCase):
    def test_fragmented_tcp_success_and_client_closes_without_server_eof(self):
        closed = []

        def respond(connection):
            for chunk in (RAW[:13], RAW[13:44], RAW[44:-1], RAW[-1:]):
                connection.sendall(chunk)
                time.sleep(0.003)
            closed.append(connection.recv(1))

        with server(respond) as options:
            self.assertEqual(client.query(**options), RESULT)
        self.assertEqual(closed, [b""])

    def test_eof_rejects_original_three_invalid_responses(self):
        for text in ("https://patch-poe2.poecdn.com/9.1", "https://other.example/9.1/", "garbage", ""):
            with self.subTest(text=text), server(lambda c: c.sendall(text.encode("utf-16le"))) as options:
                with self.assertRaisesRegex(ValueError, "ended without a complete"):
                    client.query(**options)

    def test_size_overflow_fails_and_closes(self):
        closed = []

        def respond(connection):
            connection.sendall(b"x" * (client.MAX_RESPONSE + 1))
            closed.append(connection.recv(1))

        with server(respond) as options, self.assertRaisesRegex(ValueError, "64 KiB"):
            client.query(**options)
        self.assertEqual(closed, [b""])

    def test_exact_size_success(self):
        raw = b"x" * (client.MAX_RESPONSE - len(RAW)) + RAW
        with server(lambda c: c.sendall(raw)) as options:
            self.assertEqual(client.query(**options), RESULT)

    def test_silent_timeout_closes_connection(self):
        closed = []
        with server(lambda c: closed.append(c.recv(1))) as options:
            with self.assertRaisesRegex(TimeoutError, "timed out"):
                client.query(**{**options, "timeout": 0.05})
        self.assertEqual(closed, [b""])

    def test_absolute_deadline_is_not_reset_by_drip_traffic(self):
        def respond(connection):
            for _ in range(100):
                try:
                    connection.sendall(b"x")
                except (BrokenPipeError, ConnectionResetError):
                    return
                time.sleep(0.01)

        with server(respond) as options:
            started = time.monotonic()
            with self.assertRaisesRegex(TimeoutError, "timed out"):
                client.query(**{**options, "timeout": 0.08})
            self.assertLess(time.monotonic() - started, 0.4)

    def test_dns_wait_is_bounded_and_late_resolution_never_connects(self):
        release = threading.Event()
        finished = threading.Event()

        def resolve(*args, **kwargs):
            try:
                release.wait(2)
                return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 13060))]
            finally:
                finished.set()

        with (
            patch.object(client.socket, "getaddrinfo", side_effect=resolve),
            patch.object(client.socket, "socket") as tcp,
        ):
            try:
                with self.assertRaisesRegex(TimeoutError, "DNS"):
                    client.query(host="fake.invalid", timeout=0.03)
            finally:
                release.set()
                self.assertTrue(finished.wait(1))
            tcp.assert_not_called()

    def test_dns_error_is_explicit_without_connection(self):
        for error in (socket.gaierror("synthetic DNS failure"), UnicodeError("synthetic invalid DNS name")):
            with (
                self.subTest(error=error),
                patch.object(client.socket, "getaddrinfo", side_effect=error),
                patch.object(client.socket, "socket") as tcp,
                self.assertRaises(type(error)),
            ):
                client.query(host="fake.invalid")
            tcp.assert_not_called()

    def test_connect_error_uses_one_address_and_no_retry(self):
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", port)) for port in (1, 2)]
        resource = MagicMock()
        connection = resource.__enter__.return_value
        connection.connect.side_effect = OSError("synthetic connect failure")
        with (
            patch.object(client.socket, "getaddrinfo", return_value=addresses),
            patch.object(client.socket, "socket", return_value=resource) as tcp,
            self.assertRaisesRegex(OSError, "synthetic connect failure"),
        ):
            client.query(host="fake.invalid")
        tcp.assert_called_once()
        connection.connect.assert_called_once_with(("127.0.0.1", 1))
        resource.__exit__.assert_called_once()

    def test_read_error_is_explicit_and_resource_is_released(self):
        resource = MagicMock()
        connection = resource.__enter__.return_value
        connection.recv.side_effect = ConnectionResetError("synthetic reset")
        with (
            patch.object(client.socket, "socket", return_value=resource),
            self.assertRaisesRegex(ConnectionResetError, "synthetic reset"),
        ):
            client.query(host="127.0.0.1")
        resource.__exit__.assert_called_once()

    def test_dns_connect_send_and_read_share_one_deadline(self):
        clock = [10.0]
        resource = MagicMock()
        connection = resource.__enter__.return_value

        def address(*args):
            clock[0] += 0.02
            return socket.AF_INET, socket.SOCK_STREAM, 0, ("127.0.0.1", 13060)

        def advance(amount, result=None):
            def operation(*args):
                clock[0] += amount
                return result

            return operation

        connection.connect.side_effect = advance(0.03)
        connection.sendall.side_effect = advance(0.02)
        connection.recv.side_effect = advance(0.04, RAW)
        with (
            patch.object(client, "_address", side_effect=address),
            patch.object(client.time, "monotonic", side_effect=lambda: clock[0]),
            patch.object(client.socket, "socket", return_value=resource),
            self.assertRaisesRegex(TimeoutError, "absolute deadline"),
        ):
            client.query(host="127.0.0.1", timeout=0.1)
        for call, expected in zip(connection.settimeout.call_args_list, (0.08, 0.05, 0.03), strict=True):
            self.assertAlmostEqual(call.args[0], expected)
        resource.__exit__.assert_called_once()

    def test_invalid_bounds_fail_before_socket(self):
        with patch.object(client.socket, "socket") as tcp:
            for options in (
                {"timeout": 0},
                {"timeout": 8.1},
                {"timeout": float("nan")},
                {"timeout": True},
                {"timeout": None},
                {"port": 0},
                {"port": 65536},
                {"port": True},
                {"host": ""},
                {"host": "bad\nhost"},
            ):
                with self.subTest(options=options), self.assertRaises(ValueError):
                    client.query(**options)
        tcp.assert_not_called()


class ObservationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="repoe client version ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.out = self.root / "fresh"

    def test_exact_raw_receipt_and_completion_last(self):
        writes = []
        write = client.source_io.write_new

        def record(path, raw):
            writes.append(path.name)
            write(path, raw)

        with (
            server(lambda c: c.sendall(RAW)) as options,
            patch.object(client.source_io, "write_new", side_effect=record),
        ):
            observation = client.observe(**options, out=self.out)
        self.assertEqual(observation.result, RESULT)
        self.assertEqual(observation.raw, RAW)
        receipt = observation.receipt
        self.assertEqual(json.loads((self.out / client.RECEIPT).read_bytes()), receipt)
        self.assertEqual((self.out / "response.bin").read_bytes(), RAW)
        self.assertEqual(
            receipt["response"], {"path": "response.bin", "bytes": len(RAW), "sha256": client.source_io.sha256(RAW)}
        )
        self.assertEqual(receipt["endpoint"]["host"], "127.0.0.1")
        self.assertEqual(receipt["endpoint"]["peer"]["address"], "127.0.0.1")
        self.assertEqual(receipt["handshake_hex"], "0107")
        self.assertLessEqual(
            datetime.fromisoformat(receipt["started_at_utc"]), datetime.fromisoformat(receipt["observed_at_utc"])
        )
        self.assertEqual(receipt["producer"]["code_sha256"], client._producer_pins())
        self.assertEqual(
            set(receipt["producer"]["code_sha256"]),
            {"RePoE/__init__.py", "RePoE/client_version.py", "RePoE/source_io.py"},
        )
        self.assertNotIn("language", receipt)
        self.assertNotIn("realm", receipt)
        self.assertEqual(writes, ["response.bin", client.RECEIPT])

    def test_observe_without_output_keeps_bytes_in_memory(self):
        with server(lambda c: c.sendall(RAW)) as options:
            observation = client.observe(**options)
        self.assertEqual(observation.raw, RAW)
        self.assertEqual(observation.result, RESULT)
        self.assertFalse(self.out.exists())

    def test_query_failure_has_no_success_receipt(self):
        with server(lambda c: c.sendall(b"bad")) as options, self.assertRaises(ValueError):
            client.observe(**options, out=self.out)
        self.assertFalse((self.out / client.RECEIPT).exists())

    def test_raw_mutation_or_write_failure_has_no_receipt(self):
        write = client.source_io.write_new

        def corrupt(path, raw):
            write(path, b"changed")

        for action, error in ((corrupt, ValueError), (OSError("synthetic disk failure"), OSError)):
            with (
                self.subTest(action=action),
                server(lambda c: c.sendall(RAW)) as options,
                patch.object(client.source_io, "write_new", side_effect=action),
                self.assertRaises(error),
            ):
                client.observe(**options, out=self.out)
            self.assertFalse((self.out / client.RECEIPT).exists())
            self.out = self.root / "next"

    def test_producer_changes_have_no_success_receipt(self):
        pins = client._producer_pins()
        with (
            server(lambda c: c.sendall(RAW)) as options,
            patch.object(client, "_producer_pins", side_effect=[pins, {}]),
            self.assertRaisesRegex(ValueError, "Producer files changed"),
        ):
            client.observe(**options, out=self.out)
        self.assertFalse((self.out / client.RECEIPT).exists())

    def test_existing_symlink_and_protected_outputs_fail_before_query(self):
        self.out.mkdir()
        (self.out / "keep").write_bytes(b"original")
        symlink = self.root / "link"
        symlink.symlink_to(self.out, target_is_directory=True)
        with patch.object(client, "_exchange", side_effect=AssertionError("query before validation")):
            for path in (
                self.out,
                symlink,
                symlink / "child",
                ROOT / "data/observation",
                ROOT / "RePoE/data/observation",
            ):
                with self.subTest(path=path), self.assertRaises((ValueError, FileExistsError)):
                    client.observe(out=path)
        self.assertEqual((self.out / "keep").read_bytes(), b"original")


class CLITests(unittest.TestCase):
    def cli(self, *args):
        return subprocess.run(
            [sys.executable, "-B", "-S", "-m", "RePoE.client_version", *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=5,
        )

    def test_help_without_site_packages_or_network(self):
        result = self.cli("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--out", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_cli_success_stdout_is_only_two_field_json(self):
        with server(lambda c: c.sendall(RAW)) as options:
            result = self.cli("--host", options["host"], "--port", str(options["port"]))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), RESULT)
        self.assertEqual(result.stderr, "")

    def test_cli_out_and_failure_streams(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary).resolve() / "fresh"
            with server(lambda c: c.sendall(RAW)) as options:
                result = self.cli("--host", options["host"], "--port", str(options["port"]), "--out", str(out))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), RESULT)
            self.assertTrue((out / client.RECEIPT).is_file())
        with server(lambda c: c.sendall(b"bad")) as options:
            result = self.cli("--host", options["host"], "--port", str(options["port"]))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("client_version:", result.stderr)

    def test_cli_validation_error_has_no_json(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr), self.assertRaises(SystemExit) as error:
            client.main(["--timeout", "nan"])
        self.assertEqual(error.exception.code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("at most 8", stderr.getvalue())
