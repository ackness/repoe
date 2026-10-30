from contextlib import redirect_stderr, redirect_stdout
import io
import sys
import unittest
from unittest.mock import patch

from RePoE import run_parser
from RePoE import schema_candidate


class SchemaCliTests(unittest.TestCase):
    def test_candidate_is_passed_to_the_selected_export_reader(self):
        calls = []

        class stats:
            def __init__(self, **kwargs):
                calls.append(kwargs)

            def write(self):
                pass

        spec = object()
        args = ["repoe", "stats", "--poe2", "--file", "client", "--outdir", "output", "--schema-candidate", "candidate"]
        with (
            patch.object(sys, "argv", args),
            redirect_stdout(io.StringIO()),
            patch.object(run_parser, "get_parser_modules", return_value=[]),
            patch.object(run_parser, "get_poe2_modules", return_value=[stats]),
            patch.object(schema_candidate, "load_candidate", return_value=spec) as verify,
            patch.object(run_parser, "get_cdn_url") as discover,
            patch.object(run_parser, "load_file_system", return_value="client-files") as files,
            patch.object(run_parser, "create_relational_reader", return_value="native-reader") as reader,
        ):
            run_parser.main()
        verify.assert_called_once_with("candidate")
        discover.assert_not_called()
        files.assert_called_once_with("client")
        reader.assert_called_once_with("client-files", "English", True, schema_spec=spec)
        self.assertEqual(calls[0]["relational_reader"], "native-reader")
        self.assertEqual(calls[0]["data_path"], "output/")
        self.assertEqual(calls[0]["sequel"], 2)

    def test_candidate_requires_explicit_poe2_client_and_output_before_network(self):
        arguments = [
            ["stats", "--schema-candidate", "missing"],
            ["stats", "--poe2", "--schema-candidate", "missing"],
            ["stats", "--poe2", "--file", "client", "--schema-candidate", "missing"],
        ]
        for args in arguments:
            with self.subTest(args=args), patch.object(sys, "argv", ["repoe", *args]):
                with patch.object(run_parser, "get_cdn_url") as discover:
                    with patch.object(run_parser, "load_file_system") as load:
                        with (
                            self.assertRaises(SystemExit) as error,
                            redirect_stderr(io.StringIO()),
                            redirect_stdout(io.StringIO()),
                        ):
                            run_parser.main()
                        self.assertEqual(error.exception.code, 2)
                        discover.assert_not_called()
                        load.assert_not_called()


if __name__ == "__main__":
    unittest.main()
