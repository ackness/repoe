from email.parser import BytesParser
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest
import zipfile

from RePoE.schema_candidate import ROOT


class PackagingTests(unittest.TestCase):
    def test_wheel_preserves_the_pypoe_git_dependency(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
        dependency = next(value for value in project["dependencies"] if value.startswith("pypoe @ git+"))
        with tempfile.TemporaryDirectory(prefix="repoe-wheel-test-") as temporary:
            result = subprocess.run(
                ["uv", "build", "--offline", "--wheel", "--out-dir", temporary],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            wheel = next(Path(temporary).glob("*.whl"))
            with zipfile.ZipFile(wheel) as archive:
                metadata_name = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
                metadata = BytesParser().parsebytes(archive.read(metadata_name))
                self.assertIn(dependency, metadata.get_all("Requires-Dist"))


if __name__ == "__main__":
    unittest.main()
