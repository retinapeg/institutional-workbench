import errno
import fcntl
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from institutional_workbench.cockpit import Advice, Check, Cockpit, Freeze, Plan, Probe, Ruling
from institutional_workbench.runner import Blocked, Deadline


class Adviser:
    def __init__(self, failure=None):
        self.requests = []
        self.failure = failure

    def ask(self, provider, prompt, schema, *, model=None):
        self.requests.append(json.loads(prompt))
        if self.failure:
            raise self.failure
        return Advice(unresolved=["Does DOLocationID exist?"], requested_probes=["columns"])


class CockpitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        (self.repo / ".gitignore").write_text(".institutional-workbench/\n__pycache__/\n")
        (self.repo / "app.py").write_text("VALUE = 0\n")
        (self.repo / "data.csv").write_text("DOLocationID,actual,predicted\n1,10,8\n2,3,5\n")
        (self.repo / "tests").mkdir()
        (self.repo / "tests/test_app.py").write_text(
            "import unittest\nfrom app import VALUE\nclass TestValue(unittest.TestCase):\n"
            " def test_answer(self): self.assertEqual(VALUE,42)\n"
        )
        self.git("init", "-q")
        self.git("add", ".")
        self.git(
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        )
        self.c = Cockpit.start(self.repo, "Implement a correct data utility with tests", 5)
        self.plan = Plan(
            deliverable="VALUE is 42",
            acceptance=["test_answer passes"],
            owned_paths=["app.py", "new.png"],
            checks=[
                Check(
                    name="unit",
                    argv=[sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                )
            ],
            source_paths=["app.py"],
            probes=[
                Probe(name="columns", kind="csv_columns", path="data.csv"),
                Probe(name="rows", kind="read", path="data.csv"),
            ],
        )

    def git(self, *args):
        return subprocess.run(
            ["git", *args], cwd=self.repo, check=True, capture_output=True, text=True
        ).stdout

    def prepare(self):
        self.c.prepare(self.plan)

    def freeze(self):
        self.c.freeze(Freeze(implementation=["Set VALUE to 42"]))

    def edit(self):
        # Actual host write stands in for Claude Edit; separate live test covers Claude itself.
        (self.repo / "app.py").write_text("VALUE = 42\n")

    def cli(self, action, *args):
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "institutional_workbench.cockpit",
                action,
                "--run",
                str(self.c.directory),
                *args,
            ],
            capture_output=True,
            text=True,
        )

    def test_host_edit_tests_and_delivery(self):
        self.prepare()
        self.freeze()
        self.edit()
        self.c.verify()
        self.assertEqual(self.c.state["status"], "DELIVERED")
        self.assertEqual(self.c.state["files_changed"], ["app.py"])
        self.assertEqual(self.c.state["verification"][0]["exit_status"], 0)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.c.state["head"])

    def test_text_only_completion_and_one_repair(self):
        self.prepare()
        self.freeze()
        self.c.state["reports"] = [{"message": "I implemented it and all tests pass"}]
        self.c.verify()
        self.assertEqual(self.c.state["phase"], "REPAIR")
        self.c.verify()
        self.assertEqual(self.c.state["status"], "BLOCKED")
        self.assertEqual(self.c.state["repairs"], 1)

    def test_legitimate_noop_requires_passing_baseline(self):
        self.edit()
        self.prepare()
        self.freeze()
        self.c.verify()
        self.assertEqual(self.c.state["build"], "NO CHANGES REQUIRED")

    def test_named_schema_probe_resolves_fact_without_models(self):
        self.prepare()
        receipt = self.c.probe("columns")
        self.assertIn("DOLocationID", self.c.state["receipts"][receipt]["text"])
        with self.assertRaisesRegex(Blocked, "Unknown probe"):
            self.c.probe("sh -c arbitrary-command")
        self.freeze()
        self.edit()
        self.c.verify()
        self.assertEqual(self.c.state["calls"], 0)
        self.assertEqual(self.c.state["status"], "DELIVERED")

    def test_false_all_rows_finding_rejected_by_source(self):
        self.prepare()
        receipt = self.c.probe("rows")
        decision = Freeze(
            implementation=["Fix VALUE only; reject unsupported metric change"],
            rulings=[
                Ruling(
                    claim="Predicted exceeds actual in all rows",
                    decision="reject",
                    receipt=receipt,
                    evidence_quote="1,10,8",
                    reason="8 < 10 is a counterexample",
                )
            ],
        )
        self.c.freeze(decision)
        self.assertEqual(self.c.state["decision"]["rulings"][0]["decision"], "reject")
        rows = [(10, 8), (3, 5)]
        self.assertFalse(all(predicted > actual for actual, predicted in rows))
        self.assertEqual([predicted - actual for actual, predicted in rows], [-2, 2])

    def test_nonessential_missing_evidence_can_be_deferred(self):
        self.plan.probes.append(Probe(name="optional", kind="read", path="absent.csv"))
        self.prepare()
        receipt = self.c.probe("optional")
        self.assertEqual(self.c.state["receipts"][receipt]["kind"], "probe_unavailable")
        self.c.freeze(
            Freeze(implementation=["Fix VALUE"], unresolved=["Optional data unavailable"])
        )
        self.edit()
        self.c.verify()
        self.assertEqual(self.c.state["status"], "DELIVERED")

    def test_stale_or_fabricated_evidence_cannot_freeze(self):
        self.prepare()
        receipt = self.c.probe("rows")
        ruling = Ruling(
            claim="claim",
            decision="accept",
            receipt=receipt,
            evidence_quote="fabrication",
            reason="reason",
        )
        with self.assertRaisesRegex(Blocked, "not present"):
            self.c.freeze(Freeze(implementation=["edit"], rulings=[ruling]))
        ruling.evidence_quote = "1,10,8"
        (self.repo / "data.csv").write_text("changed\n")
        with self.assertRaisesRegex(Blocked, "Evidence changed"):
            self.c.freeze(Freeze(implementation=["edit"], rulings=[ruling]))

    def test_independence_one_challenge_and_role_cap(self):
        self.prepare()
        provider = Adviser()
        self.c.advice(provider)
        self.assertEqual(len(self.c.state["roles"]), 2)
        self.assertEqual(len(provider.requests), 4)
        for request in provider.requests[:2]:
            self.assertNotIn("peer_reports", request)
        for request in provider.requests[2:]:
            self.assertEqual(len(request["peer_reports"]), 2)
        with self.assertRaisesRegex(Blocked, "One independent"):
            self.c.advice(provider)

    def test_trivial_task_skips_optional_models(self):
        self.c.state["task"] = "Fix literal typo"
        self.prepare()
        provider = Adviser()
        self.c.advice(provider)
        self.assertEqual(provider.requests, [])

    def test_optional_top_tier_failure_does_not_block(self):
        self.c.state["task"] = "Frontier mathematical physics problem"
        self.prepare()
        provider = Adviser(Blocked("Unavailable"))
        self.c.advice(provider)
        self.assertLessEqual(len(provider.requests), 4)
        self.assertEqual(self.c.state["status"], "RUNNING")
        self.freeze()

    def test_eperm_diagnostic_without_retry_storm(self):
        self.prepare()
        popen = subprocess.Popen

        def deny_python(argv, **kwargs):
            if argv[0] == "python3":
                raise PermissionError(errno.EPERM, "Operation not permitted")
            return popen(argv, **kwargs)

        with patch(
            "institutional_workbench.runner.subprocess.Popen",
            side_effect=deny_python,
        ):
            with self.assertRaises(PermissionError):
                self.c.execute(Check(name="failing-operation", argv=["python3", "app.py"]))
        receipt = self.c.state["receipts"][-1]
        self.assertEqual(receipt["operation"], "Runner.run")
        self.assertEqual(receipt["argv"], ["python3", "app.py"])
        self.assertEqual(receipt["cwd"], str(self.repo.resolve()))
        self.assertEqual(receipt["errno"], errno.EPERM)
        self.assertNotEqual(self.c.state["status"], "DELIVERED")

    def test_slow_command_stopped_by_remaining_deadline(self):
        self.prepare()
        self.c.runner.deadline = time.monotonic() + 0.1
        started = time.monotonic()
        with self.assertRaises(Deadline):
            self.c.execute(
                Check(name="slow", argv=[sys.executable, "-c", "import time;time.sleep(10)"])
            )
        self.assertLess(time.monotonic() - started, 3)

    def test_expired_adviser_allowance_builds_with_reserve(self):
        self.prepare()
        self.c.state["started_monotonic"] -= 240
        provider = Adviser()
        self.c.advice(provider)
        self.assertEqual(provider.requests, [])
        self.assertEqual(self.c.view()["next_action"], "VALIDATE_ONLY")
        self.freeze()

    def test_visual_unavailable_is_partial_only_after_tests_pass(self):
        self.plan.visual_required = True
        self.prepare()
        self.freeze()
        self.c.verify()
        self.assertEqual(self.c.state["phase"], "REPAIR")
        self.edit()
        self.c.verify()
        self.assertEqual(self.c.state["status"], "PARTIAL")
        self.assertEqual(self.c.state["visual"]["status"], "UNVERIFIED")

    def test_render_capture_provenance_is_not_visual_interpretation(self):
        self.prepare()
        self.freeze()
        self.edit()
        script = "from pathlib import Path;Path('new.png').write_bytes(bytes([137,80,78,71,13,10,26,10])+b'fixture')"
        self.c.visual("new.png", "1280x800", [sys.executable, "-c", script])
        self.assertEqual(self.c.state["visual"]["status"], "CAPTURED_NOT_INTERPRETED")
        self.assertEqual(self.c.state["visual"]["viewport"], "1280x800")
        # Deliberately only a fake render here: the status must not claim verified layout.
        self.c.verify()
        self.assertEqual(self.c.state["status"], "DELIVERED")

    def test_protected_acceptance_and_outside_ownership(self):
        self.prepare()
        self.freeze()
        self.edit()
        (self.repo / "data.csv").write_text("unauthorised\n")
        with self.assertRaisesRegex(Blocked, "outside frozen"):
            self.c.verify()

    def test_status_after_delivery_cannot_revoke_result(self):
        self.prepare()
        self.freeze()
        self.edit()
        self.c.verify()
        self.c.state["started_monotonic"] -= 1000
        self.c.save()
        result = self.cli("status")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["status"], "DELIVERED")

    def test_lock_conflict_does_not_write_state_and_cancel_bypasses_lock(self):
        before = (self.c.directory / "run.json").read_bytes()
        with (self.c.directory / "lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.cli("status")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((self.c.directory / "run.json").read_bytes(), before)
            self.assertEqual(self.cli("cancel").returncode, 0)
            self.assertTrue((self.c.directory / "cancel").exists())

    def test_dirty_repo_is_preserved(self):
        (self.repo / "app.py").write_text("USER WORK\n")
        with self.assertRaisesRegex(Blocked, "existing work"):
            Cockpit.start(self.repo, "goal", 1)
        self.assertEqual((self.repo / "app.py").read_text(), "USER WORK\n")


if __name__ == "__main__":
    unittest.main()
