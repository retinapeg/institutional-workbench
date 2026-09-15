import contextlib
import io
import json
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from institutional_workbench.cli import main


class CliErgonomicsTests(unittest.TestCase):
    def test_degraded_qa_warning_is_prominent_in_final_output(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory).resolve()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            output = io.StringIO()
            with (
                patch("pathlib.Path.cwd", return_value=repo),
                patch.object(sys, "argv", ["inst", "hackathon", "demo"]),
                patch("institutional_workbench.cli.Workbench") as workbench,
                contextlib.redirect_stdout(output),
            ):
                workbench.return_value.run.return_value = {
                    "status": "DELIVERED",
                    "qa_status": "UNVERIFIED",
                    "qa_failure": "Sonnet timed out after 90s",
                    "deliverable": "demo",
                    "tests": [],
                    "run_command": "python demo.py",
                    "files_changed": [],
                    "limitations": [],
                    "pitch_outline": [],
                    "fallback": "",
                }
                self.assertEqual(main(), 0)
            self.assertIn(
                "DELIVERED\nQA_STATUS=UNVERIFIED\nQA_FAILURE=Sonnet timed out after 90s",
                output.getvalue(),
            )

    def test_hackathon_default_is_soft_and_explicit_deadline_is_hard(self):
        for flags, hard in (([], False), (["--hard-deadline", "25"], True)):
            with tempfile.TemporaryDirectory() as directory:
                repo = Path(directory).resolve()
                subprocess.run(["git", "init", "-q", str(repo)], check=True)
                with (
                    patch("pathlib.Path.cwd", return_value=repo),
                    patch.object(sys, "argv", ["inst", "hackathon", "Task in 25 minutes", *flags]),
                    patch("institutional_workbench.cli.Workbench") as workbench,
                    patch("institutional_workbench.cli.signal.signal"),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    workbench.return_value.run.return_value = {
                        "status": "BLOCKED",
                        "current_blocker": "mock",
                    }
                    main()
                    runner = workbench.call_args.args[2]
                    self.assertEqual(runner.deadline != float("inf"), hard)

    def test_crunch_control_does_not_cancel_or_launch_work(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory).resolve()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            run = repo / ".institutional-workbench/run"
            run.mkdir(parents=True)
            (run.parent / "active.json").write_text(json.dumps({"run_dir": str(run)}))
            (run / "run.json").write_text(json.dumps({"status": "RUNNING", "mode": "hackathon"}))
            with (
                patch("pathlib.Path.cwd", return_value=repo),
                patch.object(sys, "argv", ["inst", "crunch"]),
                patch("institutional_workbench.cli.Workbench") as workbench,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(), 0)
                workbench.assert_not_called()
            self.assertTrue((run / "crunch").exists())
            self.assertFalse((run / "cancel").exists())

    def test_task_file_preserves_full_task_and_current_repository(self):
        task = (
            'Rank three values. Preserve "quotes", $HOME, `commands`, and Unicode π.\nSecond line.'
        )
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory).resolve()
            task_file = repo / "task.txt"
            task_file.write_text(task, encoding="utf-8")
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            with (
                patch("pathlib.Path.cwd", return_value=repo),
                patch.object(sys, "argv", ["inst", "hackathon", "--task-file", str(task_file)]),
                patch("institutional_workbench.cli.Workbench") as workbench,
                patch("institutional_workbench.cli.signal.signal"),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                workbench.return_value.run.return_value = {
                    "status": "BLOCKED",
                    "current_blocker": "mock",
                }
                self.assertEqual(main(), 1)
                self.assertEqual(workbench.call_args.kwargs["objective"], task)
                self.assertTrue(workbench.call_args.kwargs["routing"])
                self.assertEqual(workbench.call_args.args[0], repo)

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
