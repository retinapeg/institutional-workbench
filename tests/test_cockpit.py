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

from institutional_workbench.cockpit import (
    Action,
    Advice,
    Check,
    Cockpit,
    Freeze,
    Plan,
    Probe,
    Ruling,
    Shipping,
)
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
                    argv=[sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"],
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
        self.c.verify(deliver=True)
        self.assertEqual(self.c.state["status"], "DELIVERED")
        self.assertEqual(self.c.state["files_changed"], ["app.py"])
        self.assertEqual(self.c.state["verification"][0]["exit_status"], 0)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.c.state["head"])

    def test_unverified_core_demo_cannot_claim_delivered(self):
        self.plan.core_demo_checklist = ["main interaction"]
        self.prepare()
        self.edit()
        self.c.verify(deliver=True)
        self.assertEqual(self.c.state["status"], "PARTIAL")
        self.assertIn(
            "Core demo unverified: main interaction", self.c.state["final_report"]["remaining"]
        )

    def test_optional_visual_refusal_preserves_working_run_and_existing_image(self):
        self.prepare()
        self.edit()
        self.c.verify()
        checkpoint = self.c.state["last_working_commit"]
        (self.repo / "new.png").write_bytes(b"existing user image")
        manifest = self.c.directory / "render.json"
        manifest.write_text(
            json.dumps(
                {
                    "screenshot": "new.png",
                    "viewport": "1280x800",
                    "argv": [sys.executable, "-c", "raise AssertionError('must not run')"],
                }
            )
        )
        result = self.cli("visual", "--file", str(manifest))
        self.assertEqual(result.returncode, 1)
        self.assertIn("fresh screenshot", json.loads(result.stdout)["refused"])
        saved = Cockpit(self.c.directory)
        self.assertEqual(saved.state["status"], "RUNNING")
        self.assertEqual(saved.state["last_working_commit"], checkpoint)
        self.assertEqual((self.repo / "new.png").read_bytes(), b"existing user image")
        saved.verify(deliver=True)
        self.assertEqual(saved.state["status"], "DELIVERED")

    def test_optional_render_failure_does_not_block_delivery(self):
        self.prepare()
        self.edit()
        manifest = self.c.directory / "render-failure.json"
        manifest.write_text(
            json.dumps(
                {
                    "screenshot": "failed.png",
                    "viewport": "1280x800",
                    "argv": [sys.executable, "-c", "raise SystemExit(2)"],
                }
            )
        )
        result = self.cli("visual", "--file", str(manifest))
        self.assertEqual(result.returncode, 1)
        self.assertIn("Render did not produce", json.loads(result.stdout)["refused"])
        saved = Cockpit(self.c.directory)
        self.assertEqual(saved.state["status"], "RUNNING")
        saved.verify(deliver=True)
        self.assertEqual(saved.state["status"], "DELIVERED")

    def test_text_only_completion_and_one_repair(self):
        self.prepare()
        self.freeze()
        self.c.state["reports"] = [{"message": "I implemented it and all tests pass"}]
        self.c.verify(deliver=True)
        self.assertEqual(self.c.state["phase"], "REPAIR")
        self.c.verify(deliver=True)
        self.assertEqual(self.c.state["status"], "BLOCKED")
        self.assertEqual(self.c.state["repairs"], 1)

    def test_legitimate_noop_requires_passing_baseline(self):
        self.edit()
        self.prepare()
        self.freeze()
        self.c.verify(deliver=True)
        self.assertEqual(self.c.state["build"], "NO CHANGES REQUIRED")

    def test_named_schema_probe_resolves_fact_without_models(self):
        self.prepare()
        receipt = self.c.probe("columns")
        self.assertIn("DOLocationID", self.c.state["receipts"][receipt]["text"])
        with self.assertRaisesRegex(Blocked, "Unknown probe"):
            self.c.probe("sh -c arbitrary-command")
        self.freeze()
        self.edit()
        self.c.verify(deliver=True)
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
        self.c.verify(deliver=True)
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
        self.c.advice(provider, question="Implement a correct data utility", challenge=True)
        self.assertEqual(len(self.c.state["roles"]), 2)
        self.assertEqual(len(provider.requests), 3)
        for request in provider.requests[:2]:
            self.assertNotIn("peer_reports", request)
        for request in provider.requests[2:]:
            self.assertEqual(len(request["peer_reports"]), 2)
        with self.assertRaisesRegex(Blocked, "One independent"):
            self.c.advice(provider, question="Implement a correct data utility")

    def test_trivial_task_skips_optional_models(self):
        self.c.state["task"] = "Fix literal typo"
        self.prepare()
        provider = Adviser()
        self.c.advice(provider, question="Fix literal typo")
        self.assertEqual(provider.requests, [])

    def test_optional_top_tier_failure_does_not_block(self):
        self.c.state["task"] = "Frontier mathematical physics problem"
        self.prepare()
        provider = Adviser(Blocked("Unavailable"))
        self.c.advice(provider, question="Frontier mathematical physics problem")
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
        self.c.advice(provider, question="Implement a correct data utility")
        self.assertEqual(provider.requests, [])
        self.assertEqual(self.c.view()["deadline_phase"], "FEATURE_FREEZE")
        self.freeze()

    def test_visual_unavailable_is_partial_only_after_tests_pass(self):
        self.plan.visual_required = True
        self.prepare()
        self.freeze()
        self.c.verify(deliver=True)
        self.assertEqual(self.c.state["phase"], "REPAIR")
        self.edit()
        self.c.verify(deliver=True)
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
        self.c.verify(deliver=True)
        self.assertEqual(self.c.state["status"], "DELIVERED")

    def test_claude_may_edit_gitignore_and_files_outside_deprecated_ownership(self):
        self.prepare()
        self.edit()
        (self.repo / ".gitignore").write_text(".institutional-workbench/\n__pycache__/\n*.tmp\n")
        (self.repo / "data.csv").write_text("replacement\n")
        self.c.verify(deliver=True)
        self.assertEqual(self.c.state["status"], "DELIVERED")
        self.assertIn(".gitignore", self.c.state["files_changed"])
        self.assertIn("data.csv", self.c.state["files_changed"])

    def test_status_after_delivery_cannot_revoke_result(self):
        self.prepare()
        self.freeze()
        self.edit()
        self.c.verify(deliver=True)
        self.c.state["started_monotonic"] -= 1000
        self.c.save()
        result = self.cli("status")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["status"], "DELIVERED")

    def test_prepare_starts_build_without_an_adviser_or_freeze_gate(self):
        self.prepare()
        self.assertEqual(self.c.state["phase"], "BUILD")
        self.assertEqual(self.c.state["calls"], 0)
        self.assertNotIn("decision", self.c.state)
        self.edit()
        self.c.verify(deliver=True)
        self.assertEqual(self.c.state["status"], "DELIVERED")
        self.assertEqual(self.c.state["calls"], 0)

    def test_useful_advice_has_no_forced_challenge(self):
        self.prepare()
        provider = Adviser()
        self.c.advice(provider)
        self.assertEqual(provider.requests, [])
        self.c.advice(provider, question="Which physical stability invariant must hold?")
        self.assertEqual(len(provider.requests), 2)
        self.assertTrue(all(r["phase"] == "INDEPENDENT" for r in provider.requests))
        self.assertTrue(all("peer_reports" not in r for r in provider.requests))
        self.assertEqual(self.c.state["phase"], "BUILD")

    def test_working_checkpoints_are_recoverable_without_touching_head_or_index(self):
        self.prepare()
        self.assertEqual(self.c.state["last_working_commit"], "")
        self.edit()
        self.git("add", "app.py")
        index = (self.repo / ".git/index").read_bytes()
        head = self.git("rev-parse", "HEAD")
        self.c.verify()
        first = self.c.state["last_working_commit"]
        self.assertEqual(self.c.state["status"], "RUNNING")
        self.assertEqual(self.git("show", first + ":app.py"), "VALUE = 42\n")
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertEqual((self.repo / ".git/index").read_bytes(), index)
        self.c.begin(Action(kind="polish", current_action="Clarify the implementation"))
        (self.repo / "app.py").write_text("VALUE = 42  # Tested answer\n")
        self.c.verify()
        second = self.c.state["last_working_commit"]
        self.assertNotEqual(first, second)
        self.assertEqual(self.git("rev-parse", second + "^"), head)
        self.assertEqual(self.git("show", first + ":app.py"), "VALUE = 42\n")
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertEqual((self.repo / ".git/index").read_bytes(), index)
        self.assertEqual(self.c.state["iteration"], 1)

    def test_failed_checks_never_replace_last_working_checkpoint(self):
        self.prepare()
        self.c.verify()
        self.assertEqual(self.c.state["last_working_commit"], "")
        self.assertEqual(self.c.state["breaker_findings"][-1]["exit_status"], 1)
        self.assertIn("0 != 42", self.c.state["breaker_findings"][-1]["evidence"])
        self.edit()
        self.c.verify()
        working = self.c.state["last_working_commit"]
        self.c.begin(Action(kind="feature", current_action="Next visible improvement"))
        (self.repo / "app.py").write_text("VALUE = -1\n")
        self.c.verify()
        self.assertEqual(self.c.state["last_working_commit"], working)
        self.assertEqual(self.git("show", working + ":app.py"), "VALUE = 42\n")
        self.assertEqual(self.c.state["phase"], "REPAIR")

    def test_begin_cannot_reset_a_failed_iterations_repair_budget(self):
        self.prepare()
        self.c.verify()
        with self.assertRaisesRegex(Blocked, "Repair and verify"):
            self.c.begin(Action(kind="feature", current_action="Try to reset the allowance"))
        self.c.begin(Action(kind="fix", current_action="Repair the actual failure"))
        self.assertTrue(self.c.state["repair_used"])
        self.assertEqual(self.c.state["repairs"], 1)
        self.assertEqual(self.c.state["iteration"], 0)
        self.c.verify()
        self.assertEqual(self.c.state["status"], "BLOCKED")
        self.assertEqual(self.c.state["repairs"], 1)

    def test_optional_adviser_failure_preserves_working_build(self):
        self.prepare()
        self.edit()
        self.c.verify()
        working = self.c.state["last_working_commit"]
        provider = Adviser(Blocked("Reviewer unavailable"))
        self.c.advice(provider, question="Which numerical stability invariant matters?")
        self.assertGreater(len(provider.requests), 0)
        self.assertLessEqual(len(provider.requests), 4)
        self.assertEqual(self.c.state["last_working_commit"], working)
        self.assertEqual(self.c.state["status"], "RUNNING")
        self.assertEqual((self.repo / "app.py").read_text(), "VALUE = 42\n")
        self.c.verify(deliver=True)
        self.assertEqual(self.c.state["status"], "DELIVERED")

    def test_steering_reprioritizes_same_run_and_preserves_progress(self):
        self.prepare()
        self.edit()
        self.c.verify()
        identity = (self.c.directory, self.c.state["started_monotonic"], self.c.state["head"])
        working = self.c.state["last_working_commit"]
        instruction = "Stop backend work; make the visible interaction clearer"
        self.c.steer(instruction)
        restored = Cockpit(self.c.directory)
        self.assertEqual(restored.state["next_action"], instruction)
        self.assertFalse(restored.state["steering_requests"][-1]["applied"])
        restored.begin(Action(kind="polish", current_action=instruction))
        self.assertTrue(restored.state["steering_requests"][-1]["applied"])
        self.assertEqual(restored.state["current_action"], instruction)
        self.assertEqual(restored.state["last_working_commit"], working)
        self.assertEqual(
            (restored.directory, restored.state["started_monotonic"], restored.state["head"]),
            identity,
        )

    def test_correctable_plan_error_can_be_resubmitted_in_same_run(self):
        bad = self.c.directory / "bad-plan.json"
        bad.write_text('{"deliverable":"missing checks"}')
        refused = self.cli("prepare", "--file", str(bad))
        self.assertEqual(refused.returncode, 1)
        self.assertIn("refused", json.loads(refused.stdout))
        restored = Cockpit(self.c.directory)
        self.assertEqual(restored.state["status"], "RUNNING")
        self.assertEqual(restored.state["phase"], "INSPECT")
        good = self.c.directory / "good-plan.json"
        good.write_text(self.plan.model_dump_json())
        accepted = self.cli("prepare", "--file", str(good))
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(Cockpit(self.c.directory).state["phase"], "BUILD")

    def test_controller_metadata_is_ignored_and_does_not_force_a_worktree(self):
        (self.repo / ".gitignore").write_text("__pycache__/\n")
        self.git("add", ".gitignore")
        self.git("commit", "-qm", "Stop ignoring controller metadata")
        previous = self.c.directory
        self.assertTrue((previous / "run.json").exists())
        another = Cockpit.start(self.repo, "Second run in the same repository", 5)
        self.assertNotEqual(another.directory, previous)
        self.assertEqual(another.state["status"], "RUNNING")

    def test_normal_git_commit_updates_head_and_becomes_checkpoint(self):
        self.prepare()
        self.edit()
        old_head = self.c.state["head"]
        self.git("add", "app.py")
        self.git("commit", "-qm", "Claude checkpoint")
        committed = self.git("rev-parse", "HEAD").strip()
        self.assertNotEqual(committed, old_head)
        self.c.verify(deliver=True)
        self.assertEqual(self.c.state["status"], "DELIVERED")
        self.assertEqual(self.c.state["head"], committed)
        self.assertEqual(self.c.state["last_working_commit"], committed)
        self.assertEqual(self.c.state["receipts"][-3]["kind"], "head_changed")

    def test_claude_can_delete_and_replace_existing_project_files(self):
        (self.repo / "obsolete.py").write_text("OLD = True\n")
        self.git("add", "obsolete.py")
        self.git("commit", "-qm", "Add obsolete implementation")
        self.prepare()
        (self.repo / "obsolete.py").unlink()
        (self.repo / "app.py").write_text("# replacement implementation\nVALUE = 42\n")
        self.c.verify(deliver=True)
        self.assertEqual(self.c.state["status"], "DELIVERED")
        self.assertIn("obsolete.py", self.c.state["files_changed"])
        self.assertIn("app.py", self.c.state["files_changed"])
        checkpoint = self.c.state["last_working_commit"]
        missing = subprocess.run(
            ["git", "cat-file", "-e", checkpoint + ":obsolete.py"], cwd=self.repo
        )
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("replacement implementation", self.git("show", checkpoint + ":app.py"))

    def test_operational_state_stays_compact_and_evidence_remains_separate(self):
        self.prepare()
        self.c.receipt("probe", {"text": "visible source evidence " * 5000})
        state = json.loads((self.c.directory / "run.json").read_text())
        for key in ("receipts", "reports", "baseline", "baseline_checks", "plan"):
            self.assertNotIn(key, state)
            self.assertNotIn(key, self.c.view())
        self.assertLess((self.c.directory / "run.json").stat().st_size, 10000)
        self.assertLessEqual(len(state["recent_evidence"]), 12)
        self.assertEqual(Cockpit(self.c.directory).state["receipts"][-1]["kind"], "probe")
        human = self.c.human()
        for label in ("DEADLINE:", "TIME REMAINING:", "CORE DEMO:", "SHIP:", "NEXT:"):
            self.assertIn(label, human)

    def test_long_budget_and_scaled_deadline_freezes(self):
        long_run = Cockpit.start(self.repo, "Weekend demo", 24 * 60)
        self.assertEqual(long_run.state["seconds"], 24 * 3600)
        self.prepare()
        self.c.state["seconds"] = 24 * 3600
        for remaining, expected in (
            (6000, "BUILD"),
            (5400, "FEATURE_FREEZE"),
            (3600, "POLISH_SHIP"),
            (1800, "FINAL_VERIFY"),
        ):
            with (
                self.subTest(remaining=remaining),
                patch.object(self.c, "remaining", return_value=remaining),
            ):
                self.assertEqual(self.c.deadline_phase(), expected)
        with patch.object(self.c, "remaining", return_value=5400):
            with self.assertRaisesRegex(Blocked, "Feature freeze"):
                self.c.begin(Action(kind="feature", current_action="Add speculative feature"))
            self.c.begin(Action(kind="core", current_action="Finish essential interaction"))
        with patch.object(self.c, "remaining", return_value=1800):
            with self.assertRaisesRegex(Blocked, "T-30"):
                self.c.begin(Action(kind="fix", risky=True, current_action="Risky late rewrite"))
            self.c.begin(Action(kind="ship", current_action="Finish submission copy"))
        self.c.state["seconds"] = 300
        with patch.object(self.c, "remaining", return_value=60):
            self.assertEqual(self.c.deadline_phase(), "FEATURE_FREEZE")

    def test_artifact_stall_forces_execution_instead_of_advice(self):
        self.prepare()
        self.c.state["seconds"] = 6 * 3600
        self.c.state["last_artifact_elapsed"] = 0
        provider = Adviser()
        with patch.object(self.c, "remaining", return_value=6 * 3600 - 1801):
            self.assertTrue(self.c.force_execution())
            self.c.advice(provider, question="Which physical stability invariant matters?")
        self.assertEqual(provider.requests, [])
        self.assertEqual(self.c.state["phase"], "BUILD")

    def test_risky_change_requires_current_working_checkpoint(self):
        self.prepare()
        with self.assertRaisesRegex(Blocked, "checkpoint"):
            self.c.begin(Action(kind="feature", risky=True, current_action="Risky change"))
        self.edit()
        self.c.verify()
        self.c.begin(Action(kind="feature", risky=True, current_action="Now safely preserved"))
        (self.repo / "app.py").write_text("VALUE = 43\n")
        with self.assertRaisesRegex(Blocked, "checkpoint"):
            self.c.begin(Action(kind="feature", risky=True, current_action="Unverified change"))

    def test_shipper_checks_assets_and_reports_url_failure_without_fake_deployment(self):
        self.prepare()
        with self.assertRaisesRegex(Blocked, "missing/empty"):
            self.c.ship(Shipping(readme="missing.md", deployment_note="Local demo"))
        with patch("institutional_workbench.cockpit.urlopen", side_effect=OSError("offline")):
            self.c.ship(Shipping(demo_url="https://demo.example.invalid"))
        self.assertEqual(self.c.state["url_status"], "UNVERIFIED")
        self.assertEqual(self.c.state["url_failure"], "offline")
        self.assertEqual(self.c.state["demo_url"], "https://demo.example.invalid")
        self.assertEqual(self.c.state["status"], "RUNNING")

    def test_required_shipping_assets_missing_produce_partial_definition_of_done_report(self):
        self.plan.ship_required = ["readme", "submission"]
        self.prepare()
        self.edit()
        self.c.verify(deliver=True)
        self.assertEqual(self.c.state["status"], "PARTIAL")
        report = self.c.state["final_report"]
        self.assertEqual(report["definition_of_done"], self.plan.acceptance)
        self.assertEqual(report["tests"], [{"name": "unit", "exit_status": 0}])
        self.assertIn("Shipping asset missing/stale: readme", report["remaining"])
        self.assertIn("Shipping asset missing/stale: submission", report["remaining"])
        self.assertTrue(report["last_working_commit"])

    def test_complete_shipping_assets_and_demo_are_delivered_with_evidence(self):
        self.plan.ship_required = ["readme", "submission", "pitch", "fallback"]
        self.plan.owned_paths.append("docs")
        self.plan.checks.append(
            Check(
                name="demo", kind="demo", argv=[sys.executable, "-c", "import app;print(app.VALUE)"]
            )
        )
        self.prepare()
        self.edit()
        (self.repo / "docs").mkdir()
        for name in self.plan.ship_required:
            (self.repo / "docs" / (name + ".md")).write_text("Run the verified local demo.\n")
        self.c.ship(
            Shipping(
                readme="docs/readme.md",
                submission="docs/submission.md",
                pitch="docs/pitch.md",
                fallback="docs/fallback.md",
                deployment_note="No account authorised; documented local demo is the fallback",
            )
        )
        self.c.verify(deliver=True)
        self.assertEqual(self.c.state["status"], "DELIVERED")
        self.assertEqual(self.c.state["demo_status"], "LOCAL ONLY")
        self.assertEqual(self.c.state["url_status"], "NOT APPLICABLE")
        self.assertEqual(self.c.state["final_report"]["remaining"], [])
        self.assertTrue(self.c.state["ship_checklist"]["readme"][0]["sha256"])

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
