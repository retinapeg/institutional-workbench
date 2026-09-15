import sys
import time
import unittest

import test_workbench as fixtures
from test_routing import RoutedFake

from institutional_workbench.models import BuildTask, ExpertReport
from institutional_workbench.runner import Deadline, Runner


class SoftBudgetTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.WorkbenchTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_soft_expiry_preserves_running_child_and_per_call_timeout(self):
        runner = Runner(self.fixture.repo / "cancel", 0.01, hard_deadline=False)
        code, out, _ = runner.run(
            [sys.executable, "-c", "import time; time.sleep(.08); print('healthy')"],
            self.fixture.repo,
            timeout=1,
        )
        self.assertEqual((code, out.strip()), (0, "healthy"))
        runner.check()
        with self.assertRaisesRegex(RuntimeError, "Command timed out"):
            runner.run(
                [sys.executable, "-c", "import time; time.sleep(10)"],
                self.fixture.repo,
                timeout=0.05,
            )

    def test_soft_expiry_still_builds_and_uses_elapsed_policy(self):
        bench = self.fixture.bench(RoutedFake(), mode="hackathon", routing=True)
        bench.runner.deadline = float("inf")
        bench.runner.advisory_deadline = time.monotonic() - 1
        bench.budget_seconds = 0
        bench.build_deadline = time.monotonic() - 1
        result = bench.run()
        self.assertEqual(result["status"], "DELIVERED")
        self.assertEqual(result["repairs"], 0)
        self.assertTrue(
            all(r["task_profile"]["latency_sensitivity"] == "critical" for r in bench.invocations)
        )
        self.assertEqual(
            [r["task_or_phase"] for r in bench.invocations], ["4/7 BUILD", "6/7 RED TEAM"]
        )

    def test_explicit_hard_deadline_terminates_child(self):
        runner = Runner(self.fixture.repo / "cancel", 0.05, hard_deadline=True)
        with self.assertRaises(Deadline):
            runner.run(
                [sys.executable, "-c", "import time; time.sleep(10)"], self.fixture.repo, timeout=5
            )

    def test_crunch_finishes_atomic_call_skips_optional_work_and_pauses(self):
        class Crunch(RoutedFake):
            finished = False

            def ask(inner, provider, prompt, schema, *, model=None):
                if schema is ExpertReport:
                    (bench.run_dir / "crunch").touch()
                    time.sleep(0.02)  # Current operation finishes, never cancelled.
                    inner.finished = True
                return super().ask(provider, prompt, schema, model=model)

        fake = Crunch()
        bench = self.fixture.bench(fake, mode="hackathon", routing=True)
        result = bench.run()
        self.assertTrue(fake.finished)
        self.assertEqual(result["status"], "PAUSED")
        types = [c[1] for c in fake.calls]
        self.assertNotIn("Challenge", types)
        self.assertNotIn("Decision", types)
        self.assertEqual(types.count("BuildTask"), 1)
        self.assertEqual(result["repairs"], 0)
        self.assertEqual((self.fixture.repo / "app.py").read_text(), "VALUE = 0\n")
        self.assertEqual((bench.work / "app.py").read_text(), "VALUE = 42\n")
        self.assertEqual(
            set(result["checkpoint"]),
            {
                "WORKING NOW",
                "WHAT REMAINS",
                "TEST STATUS",
                "DEMO STATUS",
                "CURRENT RISKS",
                "BEST NEXT ACTION",
            },
        )
        self.assertTrue(all(t["exit_code"] == 0 for t in result["checkpoint"]["TEST STATUS"]))
        self.assertFalse(bench.runner.cancel_file.exists())

    def test_crunch_keeps_separate_one_repair_limit(self):
        class CrunchBuild(RoutedFake):
            def ask(inner, provider, prompt, schema, *, model=None):
                if schema is BuildTask:
                    (bench.run_dir / "crunch").touch()
                return super().ask(provider, prompt, schema, model=model)

        bench = self.fixture.bench(CrunchBuild(bad_build=True), mode="hackathon", routing=True)
        result = bench.run()
        self.assertEqual(result["status"], "PAUSED")
        self.assertEqual(result["repairs"], 1)
        self.assertTrue(all(t["exit_code"] == 0 for t in result["checkpoint"]["TEST STATUS"]))
