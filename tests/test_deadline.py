import json
import threading
import time
import unittest

import test_workbench as fixtures
from test_routing import RoutedFake

from institutional_workbench.cli import task_minutes
from institutional_workbench.models import ExpertReport
from institutional_workbench.routing import profile_task, select_specialists


class DeadlineTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.WorkbenchTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_parallel_independence_builds_early_and_validates_demo(self):
        class Parallel(RoutedFake):
            barrier = threading.Barrier(3)
            lock = threading.Lock()
            active = 0
            maximum = 0

            def ask(self, provider, prompt, schema, *, model=None):
                if schema is ExpertReport:
                    self.assert_independent(prompt)
                    with self.lock:
                        self.active += 1
                        self.maximum = max(self.maximum, self.active)
                    self.barrier.wait(timeout=3)  # Serial execution fails deterministically.
                    with self.lock:
                        self.active -= 1
                return super().ask(provider, prompt, schema, model=model)

            def assert_independent(self, prompt):
                assert "reports" not in json.loads(prompt)

        (self.fixture.repo / "demo.py").write_text(
            "from app import VALUE\nassert VALUE == 42\nprint('DEMO 42')\n"
        )
        self.fixture.git("add", "demo.py")
        self.fixture.git("commit", "-m", "demo acceptance")
        fake = Parallel()
        bench = self.fixture.bench(fake, mode="hackathon", routing=True)
        result = bench.run()
        self.assertEqual(result["status"], "DELIVERED")
        self.assertEqual(fake.maximum, 3)
        self.assertLess(result["time_to_build_start"], result["budget_seconds"] * 0.2)
        self.assertLessEqual(result["time_to_build_start"], result["time_to_first_passing_test"])
        self.assertLessEqual(result["time_to_first_passing_test"], result["time_to_working_demo"])
        self.assertEqual(result["demo"]["exit_code"], 0)
        self.assertIn("DEMO 42", result["demo"]["output"])
        ids = [r["call_id"] for r in bench.invocations]
        self.assertEqual(len(ids), len(set(ids)))

    def test_expired_deliberation_freezes_and_builds_without_more_calls(self):
        fake = RoutedFake()
        bench = self.fixture.bench(fake, mode="hackathon", routing=True)
        bench.budget_seconds = 0
        bench.build_deadline = time.monotonic() - 1
        result = bench.run()
        self.assertEqual(result["status"], "DELIVERED")
        self.assertEqual([c[1] for c in fake.calls], ["BuildTask", "QAResult"])
        self.assertTrue(result["decision"]["unknown"])
        self.assertEqual(result["repairs"], 0)

    def test_easy_task_has_two_experts_and_no_challenge(self):
        fake = RoutedFake()
        bench = self.fixture.bench(fake, mode="hackathon", routing=True)
        bench.objective = "Rename a field"
        result = bench.run()
        self.assertEqual(result["status"], "DELIVERED")
        self.assertEqual(len(result["experts"]), 2)
        self.assertNotIn("Challenge", [c[1] for c in fake.calls])

    def test_deadline_and_domain_selection(self):
        self.assertEqual(task_minutes("Build a demo in 25 minutes."), 25)
        self.assertEqual(task_minutes("Rank 25 numbers"), 15)
        roles = select_specialists(
            profile_task(
                "Evaluate taxi demand forecasting with statistical validation",
                "hackathon",
                has_tests=True,
            ),
            "hackathon",
        )
        self.assertIn("Statistician", [r.role for r in roles])
        self.assertLessEqual(len(roles), 4)
