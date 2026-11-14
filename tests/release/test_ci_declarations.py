"""Full-package CI selection and the workflow's failure boundary; no real packages."""

import io
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest import mock

from RePoE.release import build, ci_declarations
from RePoE.release.pins import decode, encoded


class SelectionTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.releases = Path(self.temporary.name) / "release"
        self.releases.mkdir()
        self.policy = {"schema": "repoe-release-ci/v1", "current": "0.5.5.5-3", "retired": ["0.5.5.5-2"]}
        for name in ["0.5.5.5-2", "0.5.5.5-3"]:
            self.declaration(name)
        self.write_policy(self.policy)

    def declaration(self, name, lock=None):
        directory = self.releases / name
        directory.mkdir()
        for filename in build.SCHEMAS:
            (directory / filename).write_bytes(encoded(lock if filename == "inputs.lock.json" and lock else {}))
        return directory

    def write_policy(self, policy):
        (self.releases / "ci.json").write_bytes(encoded(policy))

    def test_current_and_all_new_declarations_are_selected_regardless_of_expect(self):
        self.declaration("0.5.5.5-4", {"expect": {"package": {}}})
        self.declaration("1.0")
        self.assertEqual(
            [path.name for path in ci_declarations.selected(self.releases)], ["0.5.5.5-3", "0.5.5.5-4", "1.0"]
        )
        # A newer directory never withdraws the explicit current guard; default build still chooses the highest.
        self.assertEqual(build.default_config(self.releases), self.releases / "1.0")
        self.write_policy({**self.policy, "retired": []})
        self.assertEqual(len(ci_declarations.selected(self.releases)), 4)

    def test_invalid_policy_is_a_cli_failure_with_no_partial_stdout(self):
        wrong_schema = {**self.policy, "schema": "other"}
        for policy in [
            [],
            {},
            wrong_schema,
            {**self.policy, "extra": True},
            {**self.policy, "current": None},
            {**self.policy, "retired": "0.5.5.5-2"},
            {**self.policy, "retired": [None]},
            {**self.policy, "current": "release/0.5.5.5-3"},
            {**self.policy, "current": "9.9"},
            {**self.policy, "retired": ["../0.5.5.5-2"]},
            {**self.policy, "retired": ["9.9"]},
            {**self.policy, "retired": ["0.5.5.5-2"] * 2},
            {**self.policy, "retired": ["0.5.5.5-3"]},
        ]:
            with self.subTest(policy=policy):
                self.write_policy(policy)
                self.assert_cli_refusal()
        for raw in [b"{", b'{"schema":"repoe-release-ci/v1","current":"0.5.5.5-3","current":"9.9","retired":[]}']:
            (self.releases / "ci.json").write_bytes(raw)
            self.assert_cli_refusal()
        (self.releases / "ci.json").unlink()
        self.assert_cli_refusal()

    def assert_cli_refusal(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdout", stdout), mock.patch("sys.stderr", stderr), self.assertRaises(SystemExit) as error:
            ci_declarations.main(["--releases", str(self.releases)])
        self.assertEqual(error.exception.code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("release:ci-configs:", stderr.getvalue())

    def test_a_broken_new_directory_fails_instead_of_disappearing(self):
        directory = self.declaration("1.0")
        lock = directory / "inputs.lock.json"
        raw = lock.read_bytes()
        lock.unlink()
        self.assert_cli_refusal()
        lock.write_bytes(raw)
        directory.rename(self.releases / "scratch")
        self.assert_cli_refusal()

    def test_symlink_declarations_fail_even_when_the_target_is_missing(self):
        for target in ["0.5.5.5-3", "missing-declaration"]:
            with self.subTest(target=target):
                link = self.releases / "1.0"
                link.symlink_to(target, target_is_directory=True)
                self.assert_cli_refusal()
                link.unlink()

    def test_repository_policy_keeps_the_consumer_current_and_retires_only_the_old_full_build(self):
        self.assertEqual(decode((build.RELEASES / "ci.json").read_bytes()), self.policy)
        names = [path.name for path in ci_declarations.selected(build.RELEASES)]
        self.assertIn("0.5.5.5-3", names)
        self.assertNotIn("0.5.5.5-2", names)
        # Historical declarations remain explicitly loadable by the ordinary build, including their expect pins.
        self.assertEqual(build.load_config(build.RELEASES / "0.5.5.5-2")[1]["target"]["game_patch"], "0.5.5.5")

    def test_workflow_builds_the_selection_and_stops_before_building_on_selector_failure(self):
        workflow = (build.ROOT / ".github/workflows/release-build.yml").read_text()
        script = re.search(r"(?m)^        run: \|\n((?:          .*\n|\n)+)", workflow).group(1)
        script = "\n".join(line[10:] for line in script.splitlines())
        tasks = tomllib.loads((build.ROOT / "mise.toml").read_text())["tasks"]
        selector = shlex.split(tasks["release:ci-configs"]["run"])
        self.assertEqual(selector[1:], ["-B", "-m", "RePoE.release.ci_declarations"])
        selector[0] = sys.executable
        selector += ["--releases", str(self.releases)]
        record = self.releases.parent / "built.txt"
        shell = (
            "mise() {\n"
            f"  if [ \"$*\" = 'run release:ci-configs' ]; then {shlex.join(selector)};\n"
            "  elif [ \"$1 $2 $3 $4 $6 $7\" = 'run release:build -- --config --fetch --check' ]; then\n"
            f"    printf '%s\\n' \"$5\" >> {shlex.quote(str(record))};\n"
            "  else return 99; fi\n"
            "}\n" + script
        )
        self.declaration("1.0")
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", shell], cwd=build.ROOT, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(record.read_text().splitlines(), [str(self.releases / name) for name in ["0.5.5.5-3", "1.0"]])
        record.unlink()
        for failure in ["invalid-policy", "broken-symlink"]:
            with self.subTest(failure=failure):
                if failure == "invalid-policy":
                    self.write_policy({**self.policy, "retired": [self.policy["current"]]})
                else:
                    self.write_policy(self.policy)
                    (self.releases / "1.0").rename(self.releases.parent / "future-declaration")
                    (self.releases / "1.0").symlink_to("missing-declaration", target_is_directory=True)
                result = subprocess.run(
                    ["bash", "-e", "-o", "pipefail", "-c", shell], cwd=build.ROOT, capture_output=True
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b"")
                self.assertFalse(record.exists())
                if failure == "broken-symlink":
                    self.assertIn(b"Symlink release declaration: 1.0", result.stderr)
