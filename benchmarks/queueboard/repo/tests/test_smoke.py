import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class Smoke(unittest.TestCase):
    def test_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.json"
            path.write_text("[]")
            result = subprocess.run(
                [
                    sys.executable,
                    "board.py",
                    str(path),
                    "--as-of",
                    "2026-01-02T12:00:00Z",
                    "--format",
                    "json",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(json.loads(result.stdout)["summary"]["active_count"], 0)

    def test_help(self):
        result = subprocess.run([sys.executable, "board.py", "--help"], capture_output=True)
        self.assertEqual(result.returncode, 0)
