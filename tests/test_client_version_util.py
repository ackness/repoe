"""Focused parser wiring; requires the existing exporter environment."""

from contextlib import redirect_stdout
import io
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from RePoE import client_version, run_parser
from RePoE.parser import util


CDN = "https://patch-poe2.poecdn.com/9.12.345.6/"


class ParserWiringTests(unittest.TestCase):
    def test_poe2_uses_official_query_without_http(self):
        with (
            patch.object(client_version, "query", return_value={"cdn": CDN, "version": "9.12.345.6"}) as query,
            patch.object(util.requests, "get", side_effect=AssertionError("third-party HTTP")),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(util.get_cdn_url(2), CDN)
        query.assert_called_once_with()

    def test_poe2_query_failure_propagates_without_http_fallback(self):
        with (
            patch.object(client_version, "query", side_effect=TimeoutError("official discovery failed")),
            patch.object(util.requests, "get", side_effect=AssertionError("third-party fallback")),
            self.assertRaisesRegex(TimeoutError, "official discovery failed"),
        ):
            util.get_cdn_url(2)

    def test_poe1_preserves_existing_http_behavior(self):
        with (
            patch.object(client_version, "query", side_effect=AssertionError("PoE2 query for PoE1")),
            patch.object(util.requests, "get", return_value=SimpleNamespace(text="  original poe1 url\n")) as http,
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(util.get_cdn_url(1), "original poe1 url")
        http.assert_called_once_with("https://ggpk.exposed/version?poe=1")

    def test_explicit_file_bypasses_discovery_for_both_games(self):
        for flags in ([], ["--poe2"]):
            with (
                self.subTest(flags=flags),
                patch.object(sys, "argv", ["repoe", "all", "--file", "/explicit/local/client", *flags]),
                patch.object(run_parser, "get_parser_modules", return_value=[]),
                patch.object(run_parser, "get_poe2_modules", return_value=[]),
                patch.object(run_parser, "get_cdn_url", side_effect=AssertionError("unexpected discovery")),
                patch.object(client_version, "query", side_effect=AssertionError("unexpected official query")),
                patch.object(util.requests, "get", side_effect=AssertionError("unexpected HTTP")),
                patch.object(run_parser, "load_file_system") as load,
                patch.object(run_parser, "create_relational_reader"),
                redirect_stdout(io.StringIO()),
            ):
                run_parser.main()
            load.assert_called_once_with("/explicit/local/client")
