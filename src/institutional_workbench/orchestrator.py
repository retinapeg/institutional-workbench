"""One roundtable, one decision, one builder, one QA pass, at most two repairs."""

import hashlib
import json
import os
import re
import shlex
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, TypeVar, cast

from pydantic import BaseModel

from .models import BuildTask, Challenge, Decision, ExpertReport, FileChange, QAResult, RepairResult
from .providers import CliProviders, Provider
from .routing import (
    ALIASES,
    MODE_TEXT,
    Mode,
    Router,
    RoutingDecision,
    profile_task,
    select_specialists,
)
from .runner import Blocked, Deadline, Runner

T = TypeVar("T", bound=BaseModel)


class DeliberationClosed(Blocked):
    pass


class QAUnavailable(Blocked):
    """The reviewer failed operationally, not a verdict about the implementation."""


POLICIES = {
    **MODE_TEXT,
    "dev": MODE_TEXT["engineering"],
    "hack": MODE_TEXT["hackathon"],
}
REASONING = "Identify objective and constraints. Reduce the problem; look for invariants, symmetry and the highest-leverage change where relevant. Make claims testable. Evidence outranks confidence. Do not imitate or automatically agree with the user. Build a vertical slice and stop."


class Workbench:
    def __init__(
        self,
        repo: Path,
        run_dir: Path,
        runner: Runner,
        provider: Provider,
        *,
        mode: str,
        objective: str,
        builder: str = "claude",
        reviewer: str = "codex",
        quick: bool = False,
        tests: list[str] | None = None,
        experts: list[tuple[str, str, str]] | None = None,
        routing: bool = False,
        router: Router | None = None,
        pinned_builder: bool = False,
        pinned_reviewer: bool = False,
        explain_routing: bool = False,
    ):
        self.repo, self.run_dir, self.runner, self.provider = repo, run_dir, runner, provider
        self.lock = threading.RLock()
        self.clock_start = time.monotonic()
        self.budget_seconds = max(0.0, runner.advisory_deadline - self.clock_start)
        self.build_deadline = self.clock_start + self.budget_seconds * 0.20
        self.demo_command: list[str] = []
        self.mode, self.objective = cast(Mode, ALIASES.get(mode, mode)), objective
        self.routing = routing
        self.router = router or Router(self.mode)
        self.pinned_builder, self.pinned_reviewer = pinned_builder, pinned_reviewer
        self.explain_routing = explain_routing
        self.explicit_experts = experts is not None
        self.profile = profile_task(objective, self.mode)
        self.last_routes: dict[str, RoutingDecision] = {}
        self.invocations: list[dict[str, Any]] = []
        self.builder, self.reviewer, self.quick = builder, reviewer, quick
        self.commands = [shlex.split(command) for command in (tests or [])]
        self.experts = experts if experts is not None else self.select_experts()
        if len(self.experts) > 4 or any(not question.strip() for _, _, question in self.experts):
            raise Blocked("At most four specialists, each with a concrete question")
        self.work = run_dir / "workspace"
        self.state: dict[str, Any] = {
            "objective": objective,
            "deliverable": "",
            "acceptance_criteria": [],
            "current_phase": "UNDERSTAND",
            "current_blocker": None,
            "next_build_action": "Inspect repository",
            "calls": 0,
            "max_calls": 16,
            "repairs": 0,
            "mode": mode,
            "status": "RUNNING",
            "started": time.time(),
            "run_dir": str(run_dir),
            "repository": str(repo),
            "budget_seconds": self.budget_seconds,
            "hard_deadline": runner.deadline != float("inf"),
            "time_to_build_start": None,
            "time_to_first_passing_test": None,
            "time_to_working_demo": None,
            "experts": [
                {"role": role, "provider": provider, "question": question}
                for role, provider, question in self.experts
            ],
        }
        self.test_results: list[dict[str, Any]] = []
        self.changed: set[str] = set()

    def select_experts(self) -> list[tuple[str, str, str]]:
        if self.quick:
            return []
        roles = [
            (
                "Software Engineer",
                "codex",
                "What is the smallest correct change and its failure test?",
            )
        ]
        if self.mode == "hackathon":
            roles.append(
                (
                    "Hackathon Strategist",
                    "claude",
                    "Which one demo moment earns the most rubric value within the stated deadline and sponsor stack?",
                )
            )
        else:
            roles.append(
                (
                    "Product Engineer",
                    "claude",
                    "What observable user outcome matters, and what should remain out of scope?",
                )
            )
        return roles

    def save(self) -> None:
        with self.lock:
            target = self.run_dir / "run.json"
            temporary = target.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.state, indent=2) + "\n")
            os.replace(temporary, target)

    def crunch(self) -> bool:
        return self.mode == "hackathon" and (self.run_dir / "crunch").exists()

    def pause_checkpoint(
        self, remaining: str = "Awaiting your direction; no further autonomous work"
    ) -> None:
        self.state.update(
            status="PAUSED",
            checkpoint={
                "WORKING NOW": f"Candidate retained in {self.work}",
                "WHAT REMAINS": remaining,
                "TEST STATUS": self.test_results,
                "DEMO STATUS": self.state.get("demo", "Not separately verified"),
                "CURRENT RISKS": self.state.get("limitations", [])
                + (
                    [str(self.state["current_blocker"])]
                    if self.state.get("current_blocker")
                    else []
                ),
                "BEST NEXT ACTION": "Inspect the checkpoint, then choose continue, redirect, specific repair, or delivery. Nothing was auto-applied.",
            },
        )
        self.event("PAUSED", "Crunch checkpoint ready; waiting for user direction")

    def event(self, phase: str, action: str, **details: Any) -> None:
        with self.lock:
            self.state.update(current_phase=phase, next_build_action=action)
            self.save()
            with (self.run_dir / "events.jsonl").open("a") as output:
                output.write(
                    json.dumps({"time": time.time(), "phase": phase, "action": action, **details})
                    + "\n"
                )
                output.flush()
            print(f"[{phase}] {action}", flush=True)

    def git(self, *args: str, cwd: Path | None = None) -> str:
        return self.runner.run(["git", *args], cwd or self.repo)[1].strip()

    def dirty(self) -> str:
        return self.git(
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            ".",
            ":!.institutional-workbench",
        )

    def ask(self, phase: str, provider: str, context: dict[str, Any], schema: type[T]) -> T:
        if self.routing:
            return self.ask_routed(phase, provider, context, schema)
        self.runner.check()
        if self.state["calls"] >= self.state["max_calls"]:
            raise Blocked("Model-call cap reached; no further consultation")
        self.state["calls"] += 1
        self.event(phase, f"{context.get('role', schema.__name__)} · {provider}", provider=provider)
        prompt = json.dumps(
            {
                "objective": self.objective,
                "policy": POLICIES[self.mode],
                "reasoning": REASONING,
                **context,
            }
        )
        try:
            result = self.provider.ask(provider, prompt, schema)
        except (Blocked, OSError, ValueError) as exc:
            self.runner.check()
            if schema is QAResult:
                raise QAUnavailable(str(exc)) from exc
            raise
        (self.run_dir / "reports" / f"{self.state['calls']:02d}-{schema.__name__}.json").write_text(
            result.model_dump_json(indent=2)
        )
        self.event(phase, f"{provider} finished", usage=getattr(self.provider, "last_usage", {}))
        return result

    def ask_routed(
        self,
        phase: str,
        preferred: str,
        context: dict[str, Any],
        schema: type[T],
        *,
        deadline: float | None = None,
    ) -> T:
        runner, client = self.runner, self.provider
        if deadline is not None:
            if isinstance(client, CliProviders):
                client = CliProviders(self.runner, client.models["claude"], client.models["codex"])
        role = str(
            context.get(
                "role",
                "Builder"
                if schema in {BuildTask, RepairResult}
                else "Decision Authority"
                if schema is Decision
                else "Security / Reliability",
            )
        )
        pinned = (
            self.builder
            if role == "Builder" and (self.pinned_builder or self.quick)
            else self.reviewer
            if (schema in {Decision, QAResult} and self.pinned_reviewer)
            else self.builder
            if self.quick
            else None
        )
        previous = self.last_routes.get("Builder") if schema is RepairResult else None
        trigger = "failed executable verification or QA finding" if previous else None
        if previous and not previous.escalation_allowed:
            raise Blocked("Builder route cannot escalate; refusing to repeat a failed model")
        local_profile = (
            self.profile.model_copy(update={"latency_sensitivity": "critical"})
            if self.runner.advisory_deadline - time.monotonic() < 180 or self.crunch()
            else self.profile
        )
        model_failure = False
        for attempt in range(
            2
        ):  # At most one local escalation; separate from implementation repair.
            runner.check()
            if deadline is not None and (time.monotonic() >= deadline or self.crunch()):
                raise DeliberationClosed("Optional deliberation closed; freeze available evidence")
            with self.lock:
                if self.state["calls"] >= self.state["max_calls"]:
                    raise Blocked("Model-call cap reached; no further routing")
                self.state["calls"] += 1
                call_id = self.state["calls"]
            route = self.router.choose(
                local_profile,
                phase,
                role,
                preferred=preferred,
                pinned_provider=pinned,
                previous=previous,
                trigger=trigger,
                model_failure=model_failure,
            )
            self.event(
                phase,
                f"{role} · {route.selected_provider}/{route.selected_model}",
                routing=route.model_dump(),
            )
            if self.explain_routing:
                print("  " + route.rationale, flush=True)
            started = time.time()
            record: dict[str, Any] = {
                "run_id": self.run_dir.name,
                "call_id": call_id,
                **route.model_dump(),
                "started": started,
                "ended": None,
                "wall_seconds": None,
                "success": False,
                "schema_success": False,
                "acceptance_result": None,
                "repair_required": None,
                "input_tokens": None,
                "output_tokens": None,
                "reported_cost_usd": None,
                "actual_monetary_spend": None,
            }
            with self.lock:
                self.invocations.append(record)
            self.write_telemetry()
            prompt = json.dumps(
                {
                    "objective": self.objective,
                    "policy": POLICIES[self.mode],
                    "reasoning": REASONING,
                    **context,
                }
            )
            try:
                result = client.ask(
                    route.selected_provider, prompt, schema, model=route.selected_model
                )
                record["schema_success"] = True
                if (
                    isinstance(result, ExpertReport)
                    and local_profile.verification_strength == "weak"
                    and (result.confidence < 0.55 or not result.evidence)
                ):
                    raise Blocked(
                        "Insufficient independent evidence/confidence under weak verification"
                    )
                record["success"] = True
                self.last_routes[role] = route
                (self.run_dir / "reports" / f"{call_id:02d}-{schema.__name__}.json").write_text(
                    result.model_dump_json(indent=2)
                )
                return result
            except (Blocked, OSError, ValueError) as exc:
                record["failure"] = str(exc)
                runner.check()  # Cancellation/deadline never becomes a model escalation.
                if attempt or not route.escalation_allowed:
                    if schema is QAResult and not record["schema_success"]:
                        failures = [
                            f"{row['selected_provider']}/{row['selected_model']}: {row['failure']}"
                            for row in self.invocations
                            if row["task_or_phase"] == phase and "failure" in row
                        ]
                        raise QAUnavailable("; ".join(failures)) from exc
                    raise
                previous, trigger = route, str(exc)
                model_failure = not record["schema_success"]
            finally:
                record.update(ended=time.time(), wall_seconds=round(time.time() - started, 3))
                usage = getattr(client, "last_usage", {})
                tokens = usage.get("usage", {})
                record.update(
                    input_tokens=tokens.get("input_tokens"),
                    output_tokens=tokens.get("output_tokens"),
                    reported_cost_usd=usage.get("reported_cost_usd"),
                    provider_metadata=usage,
                )
                self.write_telemetry()
        raise Blocked("Bounded route exhausted")

    def write_telemetry(self) -> None:
        with self.lock:
            target = self.run_dir / "invocations.json"
            temporary = target.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.invocations, indent=2) + "\n")
            os.replace(temporary, target)

    def consult(
        self, phase: str, contexts: list[dict[str, Any]], schema: type[T], deadline: float
    ) -> list[dict[str, Any]]:
        """One bounded parallel round; only the coordinator owns files/code."""

        def one(item: tuple[tuple[str, str, str], dict[str, Any]]) -> dict[str, Any] | None:
            expert, context = item
            try:
                return self.ask_routed(
                    phase, expert[1], context, schema, deadline=deadline
                ).model_dump()
            except DeliberationClosed:
                self.runner.check()
                if time.monotonic() < deadline and not self.crunch():
                    raise
                self.event(
                    "DELIBERATION CUTOFF", f"{expert[0]} unfinished; build with available evidence"
                )
                return None

        with ThreadPoolExecutor(max_workers=min(4, max(1, len(contexts)))) as pool:
            return [
                report
                for report in pool.map(one, zip(self.experts, contexts))
                if report is not None
            ]

    def deadline_decision(
        self, reports: list[dict[str, Any]], challenges: list[dict[str, Any]]
    ) -> Decision:
        return Decision(
            deliverable=self.objective,
            acceptance_criteria=[
                "Requested behaviour implemented",
                "Frozen tests and demo checks pass",
            ],
            agreed=[],
            disputed=[str(c["disagreement"]) for c in challenges if c["disagreement"]],
            unknown=[
                "Deliberation deadline reached; incomplete specialist evidence is not consensus"
            ],
            decision="Build the smallest requested vertical slice now; no further deliberation.",
            build_plan=[str(r["recommended_action"]) for r in reports[:4]]
            or ["Implement the stated objective and its deterministic acceptance tests"],
            winning_demo_moment=self.objective,
        )

    def snapshot(self, directory: Path) -> dict[str, str]:
        paths = self.git(
            "ls-files", "--cached", "--others", "--exclude-standard", cwd=directory
        ).splitlines()
        snapshot: dict[str, str] = {}
        size = 0
        for name in paths:
            path = directory / name
            if path.is_symlink() or not path.is_file():
                continue
            if any(part.startswith(".") for part in Path(name).parts) or path.suffix in {
                ".pem",
                ".key",
                ".lock",
            }:
                continue
            if path.stat().st_size > 60_000:
                continue
            try:
                content = path.read_text()
            except (UnicodeError, OSError):
                continue
            if "\x00" in content:
                continue
            size += len(content)
            if size > 180_000:
                raise Blocked(
                    "Repository snapshot exceeds 180k characters; use a smaller target repository"
                )
            snapshot[name] = content
        return snapshot

    def test_commands(self) -> None:
        if self.commands:
            return
        python = self.repo / ".venv/bin/python"
        executable = str(python) if python.is_file() else sys.executable
        if (self.work / "tests").is_dir():
            contents = "\n".join(
                path.read_text() for path in (self.work / "tests").glob("test*.py")
            )
            self.commands = (
                [[executable, "-m", "pytest", "-q"]]
                if "pytest" in contents
                else [[executable, "-m", "unittest", "discover", "-s", "tests", "-v"]]
            )
        elif (self.work / "package.json").is_file():
            package = json.loads((self.work / "package.json").read_text())
            if "test" in package.get("scripts", {}):
                self.commands = [["npm", "test"]]
        if not self.commands:
            raise Blocked('No test command detected. Retry with --test "your acceptance command"')

    def freeze_demo_command(self) -> None:
        if self.mode != "hackathon":
            return
        python = self.repo / ".venv/bin/python"
        executable = str(python) if python.is_file() else sys.executable
        if (self.work / "DEMO_COMMAND").is_file():
            self.demo_command = shlex.split((self.work / "DEMO_COMMAND").read_text())
        elif (self.work / "demo.py").is_file():
            self.demo_command = [executable, "demo.py"]
        self.state["demo_command"] = self.demo_command

    def test(self) -> bool:
        self.event("5/7 TEST", "Running frozen acceptance commands")
        self.test_results = []
        for command in self.commands:
            code, out, err = self.runner.run(command, self.work, timeout=120, require_success=False)
            result = {"command": command, "exit_code": code, "output": (out + err)[-20000:]}
            self.test_results.append(result)
        (self.run_dir / "output/tests.json").write_text(json.dumps(self.test_results, indent=2))
        passed = all(
            item["exit_code"] == 0 and "Ran 0 tests" not in item["output"]
            for item in self.test_results
        )
        if passed and self.state["time_to_first_passing_test"] is None:
            self.state["time_to_first_passing_test"] = round(time.monotonic() - self.clock_start, 3)
        if self.demo_command:
            code, out, err = self.runner.run(
                self.demo_command, self.work, timeout=60, require_success=False
            )
            demo = {"command": self.demo_command, "exit_code": code, "output": (out + err)[-20000:]}
            (self.run_dir / "output/demo.json").write_text(json.dumps(demo, indent=2))
            self.state["demo"] = demo
            passed = passed and code == 0
            if code == 0 and self.state["time_to_working_demo"] is None:
                self.state["time_to_working_demo"] = round(time.monotonic() - self.clock_start, 3)
        if self.routing:
            for record in reversed(self.invocations):
                if record["specialist_role"] == "Builder" and record["success"]:
                    record.update(acceptance_result=passed, repair_required=not passed)
                    break
            self.write_telemetry()
        return passed

    def apply(self, files: list[FileChange], *, protected: set[str] | None = None) -> None:
        names = [change.path for change in files]
        if len(names) != len(set(names)):
            raise Blocked("Duplicate paths in builder output")
        for change in files:
            path = Path(change.path)
            target = self.work / path
            if (
                path.is_absolute()
                or path.as_posix() != change.path
                or ".." in path.parts
                or not path.parts
                or any(part.startswith(".") for part in path.parts)
                or path.suffix in {".pem", ".key"}
                or target.is_symlink()
                or any(
                    parent.is_symlink() for parent in target.parents if self.work in parent.parents
                )
                or self.work.resolve() not in target.resolve().parents
                or change.path in (protected or set())
            ):
                raise Blocked(f"Refusing protected or escaping file path: {change.path}")
        for change in files:
            target = self.work / change.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(change.content)
            self.changed.add(change.path)

    def repair_candidate(
        self, decision: Decision, protected: set[str], qa: QAResult | None
    ) -> RepairResult:
        self.state["repairs"] += 1
        fix = self.ask(
            "FIX",
            self.builder,
            {
                "decision": decision.model_dump(),
                "snapshot": self.snapshot(self.work),
                "test_results": self.test_results,
                "qa": qa.model_dump() if qa is not None else None,
                "demo": self.state.get("demo"),
                "instruction": "Fix only the listed blockers. Existing and QA tests are immutable. Return full changed file contents; no architecture reopening.",
            },
            RepairResult,
        )
        self.apply(fix.files, protected=protected)
        return fix

    def run(self) -> dict[str, Any]:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "reports").mkdir(exist_ok=True)
        (self.run_dir / "output").mkdir(exist_ok=True)
        try:
            self.event("1/7 INSPECT", "Inspecting repository")
            if self.dirty():
                raise Blocked(
                    "Target repository has uncommitted work. Commit or stash it yourself before running; no files changed."
                )
            base = self.git("rev-parse", "HEAD")
            self.state["base_commit"] = base
            self.git("worktree", "add", "--detach", str(self.work), base)
            self.test_commands()
            self.freeze_demo_command()
            before = self.snapshot(self.work)
            if self.routing:
                self.profile = profile_task(
                    self.objective,
                    self.mode,
                    context_chars=sum(map(len, before.values())),
                    has_tests=bool(self.commands),
                    remaining_seconds=self.runner.advisory_deadline - time.monotonic(),
                )
                self.state["task_profile"] = self.profile.model_dump()
                if not self.explicit_experts:
                    selected = [] if self.quick else select_specialists(self.profile, self.mode)
                    self.experts = [
                        (s.role, "claude" if i % 2 else "codex", s.jurisdiction + ". " + s.question)
                        for i, s in enumerate(selected)
                    ]
                self.state["experts"] = [
                    {"role": role, "preferred_provider": pref, "question": question}
                    for role, pref, question in self.experts
                ]
                self.event("PROFILE", "; ".join(self.profile.explanation))
                if self.profile.deterministic_action == "test":
                    self.state.update(
                        deliverable="Verified existing tests",
                        acceptance_criteria=["Existing frozen test commands pass"],
                    )
                    if not self.test():
                        raise Blocked(
                            "Existing tests failed; deterministic verification does not authorise code repair"
                        )
                    self.state.update(
                        status="DELIVERED",
                        files_changed=[],
                        tests=self.test_results,
                        run_command=shlex.join(self.commands[0]),
                        limitations=[],
                        pitch_outline=[],
                        fallback="",
                    )
                    self.event("7/7 DELIVERED", "Tier 0: existing tests verified; zero model calls")
                    self.state["elapsed_seconds"] = round(time.time() - self.state["started"], 1)
                    self.save()
                    return self.state
            early_build = self.mode == "hackathon" and self.routing
            contexts: list[dict[str, Any]] = [
                {
                    "role": role,
                    "jurisdiction": question,
                    "snapshot": before,
                    "instruction": "Brief independent assessment, <=150 words. No peer conclusions.",
                }
                for role, _, question in self.experts
            ]
            if early_build:
                reports = self.consult(
                    "2/7 INDEPENDENT",
                    contexts,
                    ExpertReport,
                    self.clock_start + self.budget_seconds * 0.12,
                )
            else:
                reports = [
                    self.ask("2/7 INDEPENDENT", expert[1], context, ExpertReport).model_dump()
                    for expert, context in zip(self.experts, contexts)
                ]
            # Reveal only after the independent round has finished.
            contexts = [
                {
                    "role": role,
                    "jurisdiction": question,
                    "reports": reports,
                    "instruction": "One flaw/disagreement/missing fact only; <=60 words. No new round.",
                }
                for role, _, question in self.experts
            ]
            if early_build:
                challenge_deadline = self.clock_start + self.budget_seconds * 0.16
                challenges = (
                    self.consult("2/7 CHALLENGE", contexts, Challenge, challenge_deadline)
                    if self.profile.difficulty not in {"trivial", "low"}
                    and time.monotonic() < challenge_deadline
                    and not self.crunch()
                    and reports
                    else []
                )
            else:
                challenges = [
                    self.ask("2/7 CHALLENGE", expert[1], context, Challenge).model_dump()
                    for expert, context in zip(self.experts, contexts)
                ]
            decision_context = {
                "snapshot": before,
                "reports": reports,
                "challenges": challenges,
                "acceptance_commands": self.commands,
                "demo_command": self.demo_command,
                "instruction": "Freeze deliverable, scope and testable acceptance now. Preserve disagreement. Build next; no more analysis.",
            }
            if early_build:
                try:
                    decision = self.ask_routed(
                        "3/7 DECIDE",
                        self.reviewer,
                        decision_context,
                        Decision,
                        deadline=self.build_deadline,
                    )
                except DeliberationClosed:
                    self.runner.check()
                    if time.monotonic() < self.build_deadline and not self.crunch():
                        raise
                    decision = self.deadline_decision(reports, challenges)
                    self.event(
                        "3/7 DECIDE", "Deliberation cutoff: freeze available evidence and BUILD"
                    )
            else:
                decision = self.ask(
                    "3/7 DECIDE",
                    self.builder if self.quick else self.reviewer,
                    decision_context,
                    Decision,
                )
            if (
                challenges
                and any(
                    c["disagreement"].strip().lower() not in {"", "none", "no disagreement"}
                    for c in challenges
                )
                and not decision.disputed
            ):
                raise Blocked("Decision erased specialist disagreement")
            self.state.update(
                deliverable=decision.deliverable,
                acceptance_criteria=decision.acceptance_criteria,
                decision=decision.model_dump(),
            )
            context = {
                "snapshot": before,
                "decision": decision.model_dump(),
                "acceptance_commands": self.commands,
                "demo_command": self.demo_command,
                "instruction": "BUILD NOW. Return complete contents of only changed files, plus relevant tests. No deletions, hidden files, new dependencies or unrelated features. Existing test files are IMMUTABLE: do not include them in files, even to add tests. Add coverage in NEW test files. No prose-only deliverable.",
            }
            self.state["time_to_build_start"] = round(time.monotonic() - self.clock_start, 3)
            build = self.ask("4/7 BUILD", self.builder, context, BuildTask)
            if build.question:
                if self.crunch():
                    raise Blocked(
                        "Builder needs user direction at crunch checkpoint: " + build.question
                    )
                answer = self.ask(
                    "4/7 FOCUSED HELP",
                    self.reviewer,
                    {
                        "question": build.question,
                        "snapshot": before,
                        "decision": decision.model_dump(),
                    },
                    ExpertReport,
                )
                build = self.ask(
                    "4/7 BUILD", self.builder, {**context, "answer": answer.model_dump()}, BuildTask
                )
                if build.question:
                    raise Blocked("Builder still blocked after its one focused question")
            if not build.files:
                raise Blocked("Builder returned no implementation")
            # Existing tests are coordinator-owned acceptance evidence; builder may add tests.
            protected = {
                name
                for name in before
                if Path(name).name.startswith("test") or "/tests/" in f"/{name}"
            }
            self.apply(build.files, protected=protected)
            passed = self.test()
            # Hackathon spends its existing repair before asking QA about failing software.
            if self.mode == "hackathon" and not passed:
                build = self.repair_candidate(decision, protected, None)
                passed = self.test()
                if not passed:
                    raise Blocked("Executable/demo acceptance still fails after 1 repair cycle")
            qa: QAResult | None = None
            self.state.update(qa_status="UNVERIFIED", qa_failure=None)
            try:
                qa = self.ask(
                    "6/7 RED TEAM",
                    self.builder if self.quick else self.reviewer,
                    {
                        "decision": decision.model_dump(),
                        "snapshot": self.snapshot(self.work),
                        "diff": self.git("diff", cwd=self.work),
                        "test_results": self.test_results,
                        "demo": self.state.get("demo"),
                        "instruction": "Review ACTUAL implementation against acceptance. test_results and demo are host-executed receipts, not model claims; you need not execute them yourself. One pass. Only critical/high-value blockers. If critical findings require repairs, supply independent regression test files runnable by the frozen commands. Do not reopen architecture.",
                    },
                    QAResult,
                )
            except QAUnavailable as exc:
                self.runner.check()  # User cancellation and explicit deadlines still win.
                self.state["qa_failure"] = str(exc)
                safety_required = re.search(
                    r"\b(safety|security)\b",
                    self.objective + " " + " ".join(decision.acceptance_criteria),
                    re.IGNORECASE,
                )
                if self.mode != "hackathon" or not passed or safety_required:
                    raise
                self.event("6/7 RED TEAM", "QA_STATUS=UNVERIFIED; QA_FAILURE=" + str(exc))
            if qa is not None:
                self.state["qa_status"] = (
                    "VERIFIED"
                    if qa.verdict == "PASS" and qa.acceptance_met and not qa.critical_findings
                    else "FINDINGS"
                )
            qa_limitations = (
                qa.limitations
                if qa is not None
                else [
                    "QA_STATUS=UNVERIFIED: model QA did not complete. QA_FAILURE="
                    + str(self.state["qa_failure"])
                ]
            )
            if qa is not None and qa.verdict == "BLOCKED":
                raise Blocked("QA blocker: " + "; ".join(qa.critical_findings))
            if qa is not None and not qa.acceptance_met and not qa.regression_tests:
                raise Blocked(
                    "QA could not establish acceptance; no executable regression evidence was supplied"
                )
            if qa is not None and qa.regression_tests:
                if any(not change.path.startswith("tests/test") for change in qa.regression_tests):
                    raise Blocked("QA may add only tests/test* regression files")
                self.apply(qa.regression_tests, protected=set(self.snapshot(self.work)))
                protected.update(change.path for change in qa.regression_tests)
                passed = self.test()
            if qa is not None and qa.critical_findings and not qa.regression_tests:
                raise Blocked(
                    "QA found critical issues without executable regression evidence: "
                    + "; ".join(qa.critical_findings)
                )
            needs_fix = not passed or (
                qa is not None and (qa.verdict == "FIX" or not qa.acceptance_met)
            )
            if self.routing and needs_fix:
                for record in reversed(self.invocations):
                    if record["specialist_role"] == "Builder" and record["success"]:
                        record["repair_required"] = True
                        break
                self.write_telemetry()
            repair_limit = 1 if self.mode == "hackathon" else 2
            for _ in range(repair_limit - self.state["repairs"]):
                if not needs_fix:
                    break
                fix = self.repair_candidate(decision, protected, qa)
                build = fix
                passed = self.test()
                needs_fix = not passed or not set(
                    qa.critical_findings if qa is not None else []
                ) <= set(fix.resolved_findings)
            if needs_fix:
                raise Blocked(
                    f"Acceptance still fails after {repair_limit} repair cycles. See output/tests.json"
                )
            self.runner.check()
            if self.dirty() or self.git("rev-parse", "HEAD") != base:
                raise Blocked(
                    "Original repository changed during the run; verified result remains in isolated workspace"
                )
            self.git("add", "--intent-to-add", "--", *sorted(self.changed), cwd=self.work)
            if (
                set(self.git("diff", "--name-only", "HEAD", cwd=self.work).splitlines())
                - self.changed
            ):
                raise Blocked(
                    "Acceptance commands changed unrelated tracked files; refusing delivery"
                )
            patch = self.runner.run(["git", "diff", "--binary", "HEAD"], self.work)[1]
            if not patch.strip():
                raise Blocked("No deliverable diff exists")
            patch_path = self.run_dir / "output/delivery.patch"
            patch_path.write_text(patch)
            if self.crunch():
                self.state.update(
                    tests=self.test_results,
                    run_command=build.run_command,
                    limitations=build.limitations + qa_limitations,
                    files_changed=sorted(self.changed),
                    delivery_patch=str(patch_path),
                )
                self.pause_checkpoint()
                self.state["elapsed_seconds"] = round(time.time() - self.state["started"], 1)
                self.save()
                return self.state
            self.runner.run(["git", "apply", "--check", str(patch_path)], self.repo)
            self.runner.run(["git", "apply", str(patch_path)], self.repo)
            changed = self.git("diff", "--name-only", "HEAD", cwd=self.work).splitlines()
            self.state.update(
                status="DELIVERED",
                files_changed=changed,
                tests=self.test_results,
                run_command=build.run_command,
                limitations=build.limitations + qa_limitations,
                pitch_outline=build.pitch_outline,
                fallback=build.fallback,
                patch_sha256=hashlib.sha256(patch.encode()).hexdigest(),
            )
            if self.mode == "hackathon" and not self.demo_command:
                self.state["limitations"].append(
                    "No repository-owned demo command detected; only tests verified."
                )
            self.event("7/7 DELIVERED", build.summary)
        except (Blocked, OSError, ValueError) as exc:
            self.state.update(
                status="DEADLINE" if isinstance(exc, Deadline) else "BLOCKED",
                current_blocker=str(exc),
            )
            if (
                self.crunch()
                and not isinstance(exc, Deadline)
                and not self.runner.cancel_file.exists()
            ):
                self.pause_checkpoint("Checkpoint is incomplete; resolve the recorded blocker")
            else:
                self.event(
                    self.state["status"],
                    "Resolve the concrete blocker, then start a fresh bounded run",
                )
        self.state["elapsed_seconds"] = round(time.time() - self.state["started"], 1)
        self.save()
        return self.state
