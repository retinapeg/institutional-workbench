import contextlib
import io
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from institutional_workbench.cli import main


class CliErgonomicsTests(unittest.TestCase):
    def test_entry_points_share_unchanged_cli(self):
        project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
        self.assertEqual(
            project["project"]["scripts"]["inst2"], project["project"]["scripts"]["inst"]
        )

    def test_modes_use_current_repository_and_keep_explain_flag(self):
        for mode in ("engineering", "hackathon", "economy", "dev", "hack"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                repo = Path(directory).resolve()
                subprocess.run(["git", "init", "-q", str(repo)], check=True)
                with (
                    patch("pathlib.Path.cwd", return_value=repo),
                    patch.object(sys, "argv", ["inst2", mode, "Test task", "--explain-routing"]),
                    patch("institutional_workbench.cli.Workbench") as workbench,
                    patch("institutional_workbench.cli.signal.signal"),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    workbench.return_value.run.return_value = {
                        "status": "BLOCKED",
                        "current_blocker": "mock: no model calls",
                    }
                    self.assertEqual(main(), 1)
                    self.assertEqual(workbench.call_args.args[0], repo)
                    self.assertEqual(workbench.call_args.kwargs["mode"], mode)
                    self.assertTrue(workbench.call_args.kwargs["explain_routing"])


if __name__ == "__main__":
    unittest.main()
