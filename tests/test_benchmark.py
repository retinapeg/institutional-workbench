import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "benchmarks"
spec = importlib.util.spec_from_file_location("bench", ROOT / "run.py")
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


@unittest.skipUnless(
    sys.platform == "darwin", "Harness deliberately fails closed without macOS sandbox"
)
class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_equivalent_clean_independent_repositories(self):
        output = self.root / "run"
        baseline, head = bench.prepare(ROOT / "queueboard/repo", output)
        for name in bench.CONTENDERS:
            repo = output / name / "repo"
            self.assertEqual(bench.tree(repo), baseline)
            self.assertEqual(bench.git(repo, "status", "--porcelain"), "")
            self.assertEqual(bench.git(repo, "rev-parse", "HEAD").strip(), head)
            self.assertTrue((repo / ".git").is_dir())
        (output / "claude/repo/board.py").write_text("changed")
        self.assertEqual(bench.tree(output / "codex/repo"), baseline)

    def test_output_outside_disposable_roots_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "temporary directory"):
            bench.prepare(ROOT / "queueboard/repo", ROOT / "must-not-create")

    def test_os_isolation_denies_other_outputs_and_global_writes(self):
        work, runtime, other = (self.root / p for p in ("work", "runtime", "other"))
        for path in (work, runtime, other):
            path.mkdir()
        (other / "secret").write_text("must not read")
        protected = self.root / "protected"
        protected.write_text("unchanged")
        script = (
            "from pathlib import Path\n"
            "Path('allowed').write_text('ok')\n"
            f"for path,action in [(Path({str(other / 'secret')!r}),'read'), (Path({str(protected)!r}),'write')]:\n"
            " try:\n"
            "  path.read_text() if action=='read' else path.write_text('BAD')\n"
            " except PermissionError: pass\n"
            " else: raise AssertionError('sandbox escaped')\n"
        )
        profile = bench.sandbox(work, runtime, [other])
        result = bench.run_process(
            ["sandbox-exec", "-p", profile, sys.executable, "-c", script],
            work,
            3,
            self.root / "logs",
        )
        self.assertEqual(result["status"], "completed", (self.root / "logs/stderr.log").read_text())
        self.assertEqual(protected.read_text(), "unchanged")

    def test_timeout_preserves_progress_and_kills_detached_descendant(self):
        script = (
            "import subprocess,sys,time\n"
            "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],start_new_session=True)\n"
            "print(p.pid,flush=True)\nprint('progress',flush=True)\ntime.sleep(30)\n"
        )
        result = bench.run_process(
            [sys.executable, "-c", script], self.root, 0.4, self.root / "logs"
        )
        self.assertEqual(result["status"], "timeout")
        lines = (self.root / "logs/stdout.log").read_text().splitlines()
        self.assertEqual(lines[1], "progress")
        child = int(lines[0])
        status = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(child)], capture_output=True, text=True
        ).stdout.strip()
        self.assertTrue(not status or status.startswith("Z"), status)
        self.assertLess(result["elapsed_seconds"], 1)

    @unittest.skipUnless(shutil.which("codex"), "Local Codex sandbox binary required; no inference")
    def test_codex_native_sandbox_same_boundaries_without_nesting(self):
        work, runtime, other = (self.root / p for p in ("work", "runtime", "other"))
        for path in (work, runtime, other):
            path.mkdir()
        (other / "secret").write_text("must not read")
        protected = self.root / "protected"
        protected.write_text("unchanged")
        script = (
            "from pathlib import Path\nPath('allowed').write_text('ok')\n"
            f"for path,action in [(Path({str(other / 'secret')!r}),'read'), (Path({str(protected)!r}),'write')]:\n"
            " try:\n  path.read_text() if action=='read' else path.write_text('BAD')\n"
            " except PermissionError: pass\n"
            " else: raise AssertionError('sandbox escaped')\n"
        )
        argv = ["codex", "sandbox", "--include-managed-config", "-P", "benchmark", "-C", str(work)]
        argv += bench.codex_permissions(runtime, [other]) + [sys.executable, "-c", script]
        result = bench.run_process(argv, work, 5, self.root / "native-logs")
        self.assertEqual(
            result["status"], "completed", (self.root / "native-logs/stderr.log").read_text()
        )
        self.assertEqual(protected.read_text(), "unchanged")

    def test_spawn_failure_is_recorded(self):
        result = bench.run_process(
            ["/definitely-missing-program"], self.root, 1, self.root / "logs"
        )
        self.assertEqual(result["status"], "failed")
        self.assertIn("FileNotFoundError", result["error"])

    def test_common_grader_catches_semantic_stub(self):
        output = self.root / "run"
        bench.prepare(ROOT / "queueboard/repo", output)
        results = []
        for contender in bench.CONTENDERS:
            results.append(
                bench.verify(
                    output / contender / "repo",
                    ROOT / "queueboard/verify.py",
                    output / contender / "verify",
                    [],
                )
            )
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[1], results[2])
        self.assertEqual(len(results[0]["checks"]), 11)
        self.assertFalse(
            next(c["passed"] for c in results[0]["checks"] if c["name"] == "reopened-clock")
        )

    def test_mocked_abc_run_collects_failures_and_continues(self):
        output = self.root / "run"
        fake = {
            "claude": [
                sys.executable,
                "-c",
                "import time;print('partial',flush=True);time.sleep(10)",
            ],
            "codex": [sys.executable, "-c", "import sys;sys.exit(2)"],
            "institutional": [sys.executable, "-c", "print('claims DELIVERED')"],
        }
        report = bench.benchmark(ROOT / "queueboard", output, 0.4, overrides=fake)
        self.assertEqual(
            report["results"]["claude"]["status"], "timeout", report["results"]["claude"]
        )
        self.assertEqual(report["results"]["codex"]["exit_code"], 2)
        self.assertEqual(report["results"]["institutional"]["outcome"], "failed")
        self.assertIsNone(report["winner"])
        self.assertTrue((output / "REPORT.md").is_file())
        self.assertEqual(
            json.loads((output / "report.json").read_text())["starting_files"],
            report["starting_files"],
        )

    def test_time_to_working_is_not_invented_from_claims(self):
        log = self.root / "stream"
        log.write_text(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"model": "observed-model", "content": "all tests pass"},
                }
            )
        )
        observed = bench.observations(log)
        self.assertIsNone(observed["model_calls"])
        self.assertEqual(observed["resolved_models_observed"], ["observed-model"])

    def test_grader_accepts_known_correct_responses(self):
        # A canned protocol oracle tests the grader, not a benchmark submission.
        output = self.root / "run"
        bench.prepare(ROOT / "queueboard/repo", output)
        repo = output / "claude/repo"
        responses = {
            "empty": [],
            "resolved-absent": [],
            "boundary-and-order": [("B", 30, True), ("A", 120, True)],
            "reopened-clock": [("A", 10, False)],
            "future-priority-ignored": [("A", 60, False)],
            "priority-keeps-age": [("A", 60, True)],
            "unordered-offset-duplicate": [("A", 60, True)],
        }
        script = (
            "import sys,json,html\nfrom pathlib import Path\n"
            f"responses={responses!r}\nname=Path(sys.argv[1]).stem\n"
            "if name=='html-escaping':\n"
            " print(html.escape('<script>alert(\"x\")</script>')+' active breached');sys.exit(0)\n"
            "if name not in responses: print('invalid input',file=sys.stderr);sys.exit(2)\n"
            "rows=[dict(ticket_id=t,age_minutes=a,breached=b,title='Question',priority='normal') for t,a,b in responses[name]]\n"
            "print(json.dumps(dict(tickets=rows,summary=dict(active_count=len(rows),breached_count=sum(r['breached'] for r in rows)))))\n"
        )
        (repo / "board.py").write_text(script)
        result = bench.verify(repo, ROOT / "queueboard/verify.py", output / "checks", [])
        self.assertEqual(sum(c["passed"] for c in result["checks"]), 11, result)


if __name__ == "__main__":
    unittest.main()
