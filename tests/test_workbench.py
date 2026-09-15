import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from institutional_workbench.models import (
    BuildTask,
    Challenge,
    Decision,
    ExpertReport,
    QAResult,
    RepairResult,
)
from institutional_workbench.orchestrator import POLICIES, Workbench
from institutional_workbench.providers import CliProviders
from institutional_workbench.runner import Blocked, Runner


class FakeProvider:
    def __init__(self, bad_build=False, repairs_fail=False, qa_fix=False):
        self.calls = []
        self.bad_build, self.repairs_fail, self.qa_fix = bad_build, repairs_fail, qa_fix

    def ask(self, provider, prompt, schema):
        data = json.loads(prompt)
        self.calls.append((provider, schema.__name__, data))
        if schema is ExpertReport:
            return ExpertReport(
                key_observation="value must be 42",
                proposed_approach="one edit",
                important_assumptions=[],
                biggest_risk="wrong value",
                evidence=["app.py"],
                recommended_action="build",
                confidence=0.8,
            )
        if schema is Challenge:
            return Challenge(major_flaw="none", disagreement="none", missing_fact="none")
        if schema is Decision:
            return Decision(
                deliverable="working answer",
                acceptance_criteria=["answer is 42"],
                agreed=["one edit"],
                disputed=[],
                unknown=[],
                decision="build",
                build_plan=["edit app.py"],
                scoring_opportunities=["working demo"],
                winning_demo_moment="show 42",
            )
        if schema in {BuildTask, RepairResult}:
            bad = self.repairs_fail if schema is RepairResult else self.bad_build
            value = dict(
                summary="Implemented answer",
                files=[{"path": "app.py", "content": f"VALUE = {0 if bad else 42}\n"}],
                run_command="python app.py",
                limitations=[],
                pitch_outline=["problem", "demo"],
                fallback="show fixture",
            )
            if schema is RepairResult:
                value["resolved_findings"] = ["answer must be 42"] if self.qa_fix else []
            return schema(**value)
        if schema is QAResult:
            return QAResult(
                verdict="FIX" if self.qa_fix else "PASS",
                critical_findings=["answer must be 42"] if self.qa_fix else [],
                evidence=["test execution"],
                acceptance_met=not self.qa_fix,
                limitations=[],
                regression_tests=[
                    {
                        "path": "tests/test_regression.py",
                        "content": "import unittest\nfrom app import VALUE\nclass Regression(unittest.TestCase):\n def test_value(self): self.assertEqual(VALUE, 42)\n",
                    }
                ]
                if self.qa_fix
                else [],
            )
        raise AssertionError(schema)


class NoOpProvider(FakeProvider):
    def ask(self, provider, prompt, schema, *, model=None):
        if schema is BuildTask:
            self.calls.append((provider, schema.__name__, json.loads(prompt)))
            return BuildTask(
                summary="Existing repository already satisfies the objective",
                files=[],
                run_command="python demo.py",
                limitations=[],
                pitch_outline=["verified existing demo"],
                fallback="show passing tests",
            )
        return super().ask(provider, prompt, schema)


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        (self.repo / "app.py").write_text("VALUE = 0\n")
        (self.repo / "tests").mkdir()
        (self.repo / "tests/test_app.py").write_text(
            "import unittest\nfrom app import VALUE\nclass Test(unittest.TestCase):\n def test_value(self): self.assertEqual(VALUE, 42)\n"
        )
        self.git("add", ".")
        self.git("commit", "-m", "fixture")

    def git(self, *args):
        return subprocess.run(
            ["git", *args], cwd=self.repo, check=True, capture_output=True, text=True
        ).stdout

    def bench(self, fake=None, **options):
        directory = self.repo / ".institutional-workbench/run"
        runner = Runner(directory / "cancel", 30)
        return Workbench(
            self.repo,
            directory,
            runner,
            fake or FakeProvider(),
            mode=options.pop("mode", "dev"),
            objective="Make answer 42",
            tests=[f"{sys.executable} -m unittest discover -s tests -v"],
            **options,
        )

    def commit_passing_baseline(self, *, demo=False):
        (self.repo / "app.py").write_text("VALUE = 42\n")
        if demo:
            (self.repo / "demo.py").write_text("from app import VALUE\nprint(f'DEMO {VALUE}')\n")
        self.git("add", "app.py", *(["demo.py"] if demo else []))
        self.git("commit", "-m", "verified baseline")

    def test_hackathon_structured_noop_runs_tests_demo_qa_and_delivers_without_patch(self):
        self.commit_passing_baseline(demo=True)
        base = self.git("rev-parse", "HEAD")
        fake = NoOpProvider()
        bench = self.bench(fake, mode="hackathon")
        result = bench.run()
        self.assertEqual((result["status"], result["build_result"]), ("DELIVERED", "NO_OP"))
        self.assertEqual(result["qa_status"], "VERIFIED")
        self.assertEqual(result["files_changed"], [])
        self.assertIsNone(result["patch_sha256"])
        self.assertFalse((bench.run_dir / "output/delivery.patch").exists())
        self.assertEqual(result["tests"][0]["exit_code"], 0)
        self.assertEqual(result["demo"]["exit_code"], 0)
        self.assertIn("DEMO 42", result["demo"]["output"])
        self.assertEqual([c[1] for c in fake.calls].count("QAResult"), 1)
        phases = [
            json.loads(line)["phase"]
            for line in (bench.run_dir / "events.jsonl").read_text().splitlines()
        ]
        self.assertLess(phases.index("5/7 TEST"), phases.index("6/7 RED TEAM"))
        self.assertEqual(self.git("rev-parse", "HEAD"), base)
        self.assertEqual(self.git("diff", "--name-only", "HEAD"), "")

    def test_hackathon_noop_failed_tests_uses_existing_one_repair(self):
        fake = NoOpProvider()
        result = self.bench(fake, mode="hackathon").run()
        self.assertEqual(result["status"], "DELIVERED")
        self.assertEqual((result["repairs"], result["build_result"]), (1, "CHANGED"))
        self.assertEqual((self.repo / "app.py").read_text(), "VALUE = 42\n")
        self.assertEqual([c[1] for c in fake.calls].count("QAResult"), 1)

    def test_routed_hackathon_structured_noop_keeps_review_and_delivers(self):
        self.commit_passing_baseline()
        fake = NoOpProvider()
        bench = self.bench(fake, mode="hackathon", routing=True)
        result = bench.run()
        self.assertEqual((result["status"], result["build_result"]), ("DELIVERED", "NO_OP"))
        self.assertEqual(result["qa_status"], "VERIFIED")
        self.assertEqual(result["files_changed"], [])
        self.assertEqual([c[1] for c in fake.calls].count("BuildTask"), 1)
        self.assertEqual([c[1] for c in fake.calls].count("QAResult"), 1)
        self.assertTrue(
            any(row["specialist_role"] == "Builder" and row["success"] for row in bench.invocations)
        )

    def test_hackathon_noop_failed_tests_without_successful_repair_blocks(self):
        fake = NoOpProvider(repairs_fail=True)
        result = self.bench(fake, mode="hackathon").run()
        self.assertEqual((result["status"], result["repairs"]), ("BLOCKED", 1))
        self.assertEqual([c[1] for c in fake.calls].count("QAResult"), 0)
        self.assertEqual((self.repo / "app.py").read_text(), "VALUE = 0\n")

    def test_malformed_builder_still_blocks_before_tests_and_qa(self):
        class MalformedBuilder(NoOpProvider):
            def ask(self, provider, prompt, schema):
                if schema is BuildTask:
                    return BuildTask.model_validate({"files": []})
                return super().ask(provider, prompt, schema)

        self.commit_passing_baseline()
        fake = MalformedBuilder()
        bench = self.bench(fake, mode="hackathon")
        result = bench.run()
        self.assertEqual(result["status"], "BLOCKED")
        self.assertNotIn("build_result", result)
        self.assertEqual([c[1] for c in fake.calls].count("QAResult"), 0)
        self.assertFalse((bench.run_dir / "output/tests.json").exists())

    def test_delivery_independence_one_challenge_and_immediate_stop(self):
        fake = FakeProvider()
        result = self.bench(fake).run()
        self.assertEqual(result["status"], "DELIVERED")
        self.assertEqual((self.repo / "app.py").read_text(), "VALUE = 42\n")
        types = [call[1] for call in fake.calls]
        self.assertEqual(
            types,
            [
                "ExpertReport",
                "ExpertReport",
                "Challenge",
                "Challenge",
                "Decision",
                "BuildTask",
                "QAResult",
            ],
        )
        for _, _, data in fake.calls[:2]:
            self.assertNotIn("reports", data)
            self.assertNotIn("challenges", data)
        self.assertEqual(result["repairs"], 0)
        self.assertEqual(result["files_changed"], ["app.py"])
        self.assertFalse((self.repo / "__pycache__").exists())
        self.assertEqual(self.git("log", "-1", "--format=%s").strip(), "fixture")

    def test_specialist_cap(self):
        with self.assertRaisesRegex(Blocked, "four"):
            self.bench(experts=[("Expert", "codex", "question")] * 5)

    def test_quick_uses_only_one_provider(self):
        fake = FakeProvider()
        result = self.bench(fake, quick=True, builder="codex").run()
        self.assertEqual(result["status"], "DELIVERED")
        self.assertEqual({call[0] for call in fake.calls}, {"codex"})
        self.assertEqual(len(fake.calls), 3)

    def test_two_repairs_maximum_no_more_qa_or_analysis(self):
        fake = FakeProvider(bad_build=True, repairs_fail=True)
        result = self.bench(fake).run()
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["repairs"], 2)
        self.assertEqual([c[1] for c in fake.calls].count("QAResult"), 1)
        self.assertEqual((self.repo / "app.py").read_text(), "VALUE = 0\n")

    def test_one_repair_delivers_then_stops(self):
        result = self.bench(FakeProvider(bad_build=True, qa_fix=True)).run()
        self.assertEqual(result["status"], "DELIVERED")
        self.assertEqual(result["repairs"], 1)
        self.assertTrue((self.repo / "tests/test_regression.py").exists())

    def test_dirty_repository_preserved(self):
        (self.repo / "app.py").write_text("user work\n")
        fake = FakeProvider()
        result = self.bench(fake).run()
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("uncommitted", result["current_blocker"])
        self.assertEqual((self.repo / "app.py").read_text(), "user work\n")
        self.assertEqual(fake.calls, [])

    def test_provider_failure_is_visible(self):
        class Broken:
            def ask(self, *args):
                raise Blocked("login required")

        result = self.bench(Broken()).run()
        self.assertEqual(result["current_blocker"], "login required")
        self.assertEqual(result["status"], "BLOCKED")

    def test_concurrent_user_change_prevents_integration(self):
        fake = FakeProvider()
        original = fake.ask

        def ask(provider, prompt, schema):
            result = original(provider, prompt, schema)
            if schema is QAResult:
                (self.repo / "user-note.txt").write_text("new user work")
            return result

        fake.ask = ask
        result = self.bench(fake).run()
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("changed during", result["current_blocker"])
        self.assertEqual((self.repo / "app.py").read_text(), "VALUE = 0\n")

    def test_cancelled_run_preserves_original(self):
        fake = FakeProvider()
        bench = self.bench(fake)
        original = fake.ask

        def ask(provider, prompt, schema):
            result = original(provider, prompt, schema)
            if schema is BuildTask:
                bench.runner.cancel_file.touch()
            return result

        fake.ask = ask
        result = bench.run()
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("Cancelled", result["current_blocker"])
        self.assertEqual((self.repo / "app.py").read_text(), "VALUE = 0\n")

    def test_test_path_alias_cannot_bypass_protection(self):
        from institutional_workbench.models import FileChange

        bench = self.bench()
        bench.work.mkdir(parents=True)
        with self.assertRaisesRegex(Blocked, "Refusing"):
            bench.apply(
                [FileChange(path="tests//test_existing.py", content="pass")],
                protected={"tests/test_existing.py"},
            )

    def test_hack_policy_uses_same_engine_and_pitch(self):
        fake = FakeProvider()
        result = self.bench(fake, mode="hack").run()
        self.assertEqual(result["status"], "DELIVERED")
        self.assertNotEqual(POLICIES["dev"], POLICIES["hack"])
        self.assertIn("rubric", fake.calls[0][2]["policy"])
        self.assertTrue(result["pitch_outline"])

    def test_timeout_kills_child(self):
        marker = Path(self.tmp.name) / "late"
        runner = Runner(Path(self.tmp.name) / "cancel")
        with self.assertRaisesRegex(Blocked, "timed out"):
            runner.run(
                [
                    sys.executable,
                    "-c",
                    f"import time; from pathlib import Path; time.sleep(.5); Path({str(marker)!r}).touch()",
                ],
                self.repo,
                timeout=0.1,
            )
        time.sleep(0.55)
        self.assertFalse(marker.exists())

    def test_cancel_kills_child(self):
        cancel = Path(self.tmp.name) / "cancel"
        timer = threading.Timer(0.1, cancel.touch)
        timer.start()
        try:
            with self.assertRaisesRegex(Blocked, "Cancelled"):
                Runner(cancel).run([sys.executable, "-c", "import time; time.sleep(30)"], self.repo)
        finally:
            timer.join()

    def test_cli_dispatch_and_malformed_output(self):
        class FakeRunner:
            def __init__(self):
                self.calls = []

            def run(self, argv, *args):
                self.calls.append(argv)
                if argv[0] == "claude":
                    return (
                        0,
                        json.dumps(
                            {
                                "subtype": "success",
                                "result": '{"major_flaw":"none","disagreement":"none","missing_fact":"none"}',
                            }
                        ),
                        "",
                    )
                return (
                    0,
                    '{"type":"item.completed","item":{"type":"agent_message","text":"invalid"}}\n{"type":"turn.completed","usage":{}}',
                    "",
                )

        runner = FakeRunner()
        providers = CliProviders(runner)
        self.assertEqual(providers.ask("claude", "question", Challenge).major_flaw, "none")
        with self.assertRaisesRegex(Blocked, "Malformed codex"):
            providers.ask("codex", "question", Challenge)
        self.assertEqual([call[0] for call in runner.calls], ["claude", "codex"])


if __name__ == "__main__":
    unittest.main()
