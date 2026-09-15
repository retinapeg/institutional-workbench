import json
import unittest

import test_workbench as fixtures
from test_workbench import FakeProvider

from institutional_workbench.models import Challenge, QAResult
from institutional_workbench.providers import CliProviders
from institutional_workbench.routing import (
    WEIGHTS,
    Router,
    model_registry,
    profile_task,
    select_specialists,
)
from institutional_workbench.runner import Blocked


class RoutingPolicyTests(unittest.TestCase):
    def test_hackathon_capability_floor_changes_selection(self):
        router = Router("hackathon")
        easy = profile_task("Rename a field", "hackathon", has_tests=True)
        normal = profile_task("Build a working search demo", "hackathon", has_tests=True)
        hard = profile_task("Research a novel numerical proof", "hackathon", has_tests=True)
        calls = [
            (easy, "CHECK", "Software Engineer", 1, "haiku"),
            (normal, "4/7 BUILD", "Builder", 3, "gpt-5.6-sol"),
            (normal, "2/7 INDEPENDENT", "Software Engineer", 3, "gpt-5.6-sol"),
            (hard, "2/7 INDEPENDENT", "Mathematician", 4, "gpt-6-astra"),
            (hard, "2/7 INDEPENDENT", "Product Engineer", 3, "gpt-5.6-sol"),
            (hard, "6/7 RED TEAM", "Security / Reliability", 3, "gpt-5.6-sol"),
            (normal, "6/7 RED TEAM", "Security / Reliability", 1, "haiku"),
        ]
        for profile, phase, role, tier, model in calls:
            with self.subTest(phase=phase, role=role, difficulty=profile.difficulty):
                route = router.choose(profile, phase, role)
                self.assertEqual((route.selected_tier, route.selected_model), (tier, model))
                self.assertIn("monetary cost weight exactly zero", route.rationale)

    def test_hackathon_cost_and_diversity_never_change_winner(self):
        for task, role in (
            ("Rename a field", "Software Engineer"),
            ("Build a demo", "Builder"),
            ("Research a novel numerical proof", "Mathematician"),
        ):
            profile = profile_task(task, "hackathon", has_tests=True)
            registry = model_registry()
            expected = Router("hackathon", registry).choose(profile, "ANALYSE", role)
            for cost in ("very_low", "low", "medium", "high", "premium"):
                for model in registry:
                    model.cost_class = (
                        cost if model.model == expected.selected_model else "very_low"
                    )
                for preference in (None, "claude", "codex"):
                    actual = Router("hackathon", registry).choose(
                        profile, "ANALYSE", role, preferred=preference
                    )
                    self.assertEqual(actual.selected_model, expected.selected_model)

    def test_hackathon_one_evidenced_escalation(self):
        router = Router("hackathon")
        profile = profile_task("Rename field", "hackathon", has_tests=True)
        first = router.choose(profile, "BUILD", "Builder")
        with self.assertRaises(Blocked):
            router.choose(profile, "FIX", "Builder", previous=first)
        with self.assertRaises(Blocked):
            router.choose(profile, "FIX", "Builder", previous=first, trigger="prefer diversity")
        second = router.choose(
            profile, "FIX", "Builder", previous=first, trigger="executable test failed"
        )
        self.assertEqual(second.selected_tier, 2)
        with self.assertRaises(Blocked):
            router.choose(profile, "FIX", "Builder", previous=second, trigger="test failed")

    def test_hackathon_uses_speed_and_reliability_not_model_name(self):
        registry = model_registry()
        for model in registry:
            if model.model == "opus":
                model.speed_class = 3
        profile = profile_task("Build a demo", "hackathon", has_tests=True)
        self.assertEqual(
            Router("hackathon", registry).choose(profile, "BUILD", "Builder").selected_model,
            "opus",
        )

    def test_domain_selection_cases(self):
        cases = [
            (
                "Add farewell(name), test it. No other features; preserve input validation.",
                "engineering",
                {"Software Engineer", "Product Engineer"},
                {"Data Scientist", "Statistician", "Physicist"},
            ),
            (
                "Implement responsive waitlist landing page",
                "engineering",
                {"UX / Human Factors", "Software Engineer"},
                {"Physicist", "Mathematician", "Statistician"},
            ),
            (
                "Build relativistic starfield rendering with Doppler shift and aberration",
                "engineering",
                {"Physicist", "Mathematician", "Software Engineer"},
                {"Statistician"},
            ),
            (
                "Evaluate whether this classifier improvement is genuine",
                "engineering",
                {"Statistician", "Data Scientist"},
                {"Physicist"},
            ),
            (
                "Fix distributed queue bug",
                "engineering",
                {"Systems Engineer", "Security / Reliability"},
                {"Physicist"},
            ),
            (
                "Three hours left. Demo is unstable; rubric rewards wow factor",
                "hackathon",
                {"Hackathon Strategist / Judge", "Software Engineer", "Security / Reliability"},
                {"Physicist"},
            ),
        ]
        for task, mode, required, excluded in cases:
            with self.subTest(task=task):
                selected = select_specialists(profile_task(task, mode, has_tests=True), mode)
                names = {item.role for item in selected}
                self.assertTrue(required <= names)
                self.assertFalse(excluded & names)
                self.assertLessEqual(len(selected), 4)
                self.assertTrue(all(item.jurisdiction and item.question for item in selected))

    def test_specialist_cap_and_economy_rename(self):
        profile = profile_task(
            "Rename API field across five files with exhaustive tests", "economy", has_tests=True
        )
        self.assertEqual(select_specialists(profile, "economy"), [])
        with self.assertRaises(ValueError):
            select_specialists(profile, "engineering", maximum=5)
        self.assertTrue(profile.explanation)

    def test_modes_differ_and_economy_is_cheapest_sufficient(self):
        self.assertEqual(len({json.dumps(w, sort_keys=True) for w in WEIGHTS.values()}), 3)
        profile = profile_task(
            "Rename an API field with exhaustive tests", "economy", has_tests=True
        )
        route = Router("economy").choose(profile, "BUILD", "Software Engineer")
        self.assertEqual(route.selected_tier, 1)
        self.assertEqual(route.relative_cost_class, "low")
        self.assertIn(route.selected_model, {"haiku", "gpt-5.6-luna"})

    def test_hackathon_ignores_cost_and_prefers_fast_reliable_route(self):
        profile = profile_task(
            "Build the strongest demo before the deadline", "hackathon", has_tests=True
        )
        registry = model_registry()
        first = Router("hackathon", registry).choose(profile, "DECIDE", "Hackathon Strategist")
        for model in registry:
            model.cost_class = "premium" if model.model == first.selected_model else "very_low"
        second = Router("hackathon", registry).choose(profile, "DECIDE", "Hackathon Strategist")
        self.assertEqual(first.selected_model, second.selected_model)
        self.assertEqual(WEIGHTS["hackathon"]["cost"], 0)

    def test_roles_and_models_independent_manual_override(self):
        profile = profile_task("Numerical solver stability", "engineering", has_tests=True)
        for provider, model in (("claude", "sonnet"), ("codex", "gpt-5.6-terra")):
            route = Router("engineering", overrides={provider: model}).choose(
                profile, "ANALYSE", "Mathematician", pinned_provider=provider
            )
            self.assertEqual(route.specialist_role, "Mathematician")
            self.assertEqual(route.selected_provider, provider)
            self.assertEqual(route.selected_model, model)
            self.assertFalse(route.escalation_allowed)
            self.assertIn("Manual", route.rationale)

    def test_escalation_one_level_no_cycles_and_no_unconfigured_tiers(self):
        registry = [m for m in model_registry() if m.tier in {1, 3}]
        router = Router("economy", registry)
        profile = profile_task("Rename field", "economy", has_tests=True)
        first = router.choose(profile, "BUILD", "Builder")
        second = router.choose(profile, "FIX", "Builder", previous=first, trigger="test failed")
        self.assertEqual((first.selected_tier, second.selected_tier), (1, 3))
        self.assertEqual(second.escalation_trigger, "test failed")
        with self.assertRaises(Blocked):
            router.choose(profile, "FIX", "Builder", previous=second)

    def test_adapter_passes_exact_overridden_model(self):
        class Runner:
            def __init__(self):
                self.args = []

            def run(self, argv, *args):
                self.args = argv
                return (
                    0,
                    json.dumps(
                        {
                            "subtype": "success",
                            "result": '{"major_flaw":"","disagreement":"","missing_fact":""}',
                        }
                    ),
                    "",
                )

        runner = Runner()
        CliProviders(runner).ask("claude", "question", Challenge, model="opus")
        self.assertEqual(runner.args[runner.args.index("--model") + 1], "opus")


class RoutedFake(FakeProvider):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.models = []

    def ask(self, provider, prompt, schema, *, model=None):
        self.models.append(model)
        return super().ask(provider, prompt, schema)


class RoutedDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.WorkbenchTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def qa_failure_bench(self, failures, **options):
        class InvalidQA(RoutedFake):
            qa_attempts = 0

            def ask(self, provider, prompt, schema, *, model=None):
                if schema is QAResult:
                    self.qa_attempts += 1
                    if self.qa_attempts <= failures:
                        self.calls.append((provider, schema.__name__, json.loads(prompt)))
                        return QAResult.model_validate_json('{"verdict":"not-a-verdict"}')
                return super().ask(provider, prompt, schema, model=model)

        fake = InvalidQA(**options)
        return self.fixture.bench(fake, routing=True, mode="hackathon"), fake

    def test_invalid_haiku_qa_escalates_once_without_implementation_repair(self):
        bench, fake = self.qa_failure_bench(1)
        result = bench.run()
        self.assertEqual(result["status"], "DELIVERED")
        self.assertEqual(result["repairs"], 0)
        qa = [r for r in bench.invocations if r["task_or_phase"] == "6/7 RED TEAM"]
        self.assertEqual(len(qa), 2)
        self.assertEqual(qa[0]["selected_model"], "haiku")
        self.assertFalse(qa[0]["schema_success"])
        self.assertEqual(qa[1]["selected_tier"], qa[0]["selected_tier"] + 1)
        self.assertTrue(qa[1]["schema_success"])
        self.assertEqual([c[1] for c in fake.calls].count("BuildTask"), 1)
        self.assertEqual([c[1] for c in fake.calls].count("ExpertReport"), 3)
        self.assertEqual([c[1] for c in fake.calls].count("Challenge"), 3)

    def test_second_invalid_qa_blocks_without_repair_or_third_model_call(self):
        bench, fake = self.qa_failure_bench(2)
        result = bench.run()
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual((fake.qa_attempts, result["repairs"]), (2, 0))
        self.assertEqual((self.fixture.repo / "app.py").read_text(), "VALUE = 0\n")

    def test_successful_haiku_qa_does_not_escalate(self):
        bench, fake = self.qa_failure_bench(0)
        result = bench.run()
        self.assertEqual(result["status"], "DELIVERED")
        self.assertEqual((fake.qa_attempts, result["repairs"]), (1, 0))
        self.assertEqual(bench.invocations[-1]["selected_model"], "haiku")
        self.assertIsNone(bench.invocations[-1]["escalation_from"])

    def test_model_escalation_and_real_defect_use_separate_budgets(self):
        bench, fake = self.qa_failure_bench(1, bad_build=True, qa_fix=True)
        result = bench.run()
        self.assertEqual(result["status"], "DELIVERED")
        self.assertEqual((fake.qa_attempts, result["repairs"]), (2, 1))
        self.assertEqual([c[1] for c in fake.calls].count("RepairResult"), 1)
        self.assertEqual(WEIGHTS["hackathon"]["cost"], 0)

    def test_original_path_remains_available(self):
        fake = FakeProvider()
        result = self.fixture.bench(fake, routing=False).run()
        self.assertEqual(result["status"], "DELIVERED")
        self.assertEqual(
            [c[0] for c in fake.calls],
            ["codex", "claude", "codex", "claude", "codex", "claude", "codex"],
        )

    def test_routing_logged_and_independence_preserved(self):
        fake = RoutedFake()
        bench = self.fixture.bench(fake, routing=True, mode="engineering")
        result = bench.run()
        self.assertEqual(result["status"], "DELIVERED")
        self.assertEqual(result["calls"], 7)
        rows = json.loads((bench.run_dir / "invocations.json").read_text())
        self.assertEqual(len(rows), len(fake.calls))
        self.assertTrue(
            all(
                row["rationale"] and row["schema_success"] and row["wall_seconds"] >= 0
                for row in rows
            )
        )
        self.assertTrue(all("reports" not in call[2] for call in fake.calls[:2]))
        self.assertTrue(all(model for model in fake.models))
        self.assertTrue(all(row["actual_monetary_spend"] is None for row in rows))

    def test_failed_verification_escalates_only_builder(self):
        bench = self.fixture.bench(RoutedFake(bad_build=True), routing=True, mode="economy")
        result = bench.run()
        self.assertEqual(result["status"], "DELIVERED")
        builders = [r for r in bench.invocations if r["specialist_role"] == "Builder"]
        self.assertEqual(len(builders), 2)
        self.assertEqual(builders[1]["selected_tier"], builders[0]["selected_tier"] + 1)
        self.assertFalse(builders[0]["acceptance_result"])
        self.assertTrue(builders[1]["acceptance_result"])
        self.assertEqual(result["repairs"], 1)

    def test_failed_route_escalates_once_then_stops(self):
        class Failing(RoutedFake):
            def ask(self, *args, **kwargs):
                raise Blocked("Malformed response")

        bench = self.fixture.bench(Failing(), routing=True)
        result = bench.run()
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["calls"], 2)
        self.assertTrue(bench.invocations[1]["escalation_from"])

    def test_deterministic_tests_bypass_models_and_preserve_main_tag(self):
        (self.fixture.repo / "app.py").write_text("VALUE = 42\n")
        self.fixture.git("add", "app.py")
        self.fixture.git("commit", "-m", "passing fixture")
        self.fixture.git("tag", "v0.1.0")
        before = self.fixture.git("rev-parse", "main", "v0.1.0")
        fake = RoutedFake()
        bench = self.fixture.bench(fake, routing=True, mode="economy")
        bench.objective = "Run existing tests"
        result = bench.run()
        self.assertEqual(result["status"], "DELIVERED")
        self.assertEqual(result["calls"], 0)
        self.assertEqual(fake.calls, [])
        self.assertEqual(before, self.fixture.git("rev-parse", "main", "v0.1.0"))

    def test_hackathon_limits_survive_router(self):
        bench = self.fixture.bench(
            RoutedFake(bad_build=True, repairs_fail=True), routing=True, mode="hackathon"
        )
        result = bench.run()
        self.assertEqual(result["status"], "BLOCKED")
        self.assertLessEqual(result["calls"], 16)
        self.assertLessEqual(result["repairs"], 2)
        self.assertLessEqual(result["repairs"], 1)
        self.assertEqual(sum(r["task_or_phase"] == "6/7 RED TEAM" for r in bench.invocations), 1)

    def test_deadline_never_becomes_an_escalation(self):
        bench = self.fixture.bench(RoutedFake(), routing=True)
        bench.runner.deadline = 0
        self.assertEqual(bench.run()["status"], "BLOCKED")
        self.assertEqual(bench.state["calls"], 0)


if __name__ == "__main__":
    unittest.main()
