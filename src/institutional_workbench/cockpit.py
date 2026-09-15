"""Native Claude owns edits; this foreground helper owns bounded evidence and gates.

Not a sandbox: the cockpit authorises argv lists. Advisers can request only named
probes, never execute commands or mark implementation complete.
"""

import argparse
import csv
import fcntl
import hashlib
import json
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from .models import Record
from .providers import CliProviders, Provider
from .routing import Router, profile_task, select_specialists
from .runner import Blocked, Deadline, Runner


class Check(Record):
    name: str = Field(min_length=1)
    argv: list[str] = Field(min_length=1)
    kind: Literal["test", "demo"] = "test"
    timeout: float = Field(default=60, gt=0, le=300)


class Probe(Record):
    name: str = Field(min_length=1)
    kind: Literal["read", "csv_columns"]
    path: str


class Plan(Record):
    deliverable: str = Field(min_length=1)
    acceptance: list[str] = Field(min_length=1)
    owned_paths: list[str] = Field(min_length=1)
    checks: list[Check] = Field(min_length=1)
    probes: list[Probe] = Field(default_factory=list, max_length=8)
    source_paths: list[str] = Field(default_factory=list, max_length=20)
    visual_required: bool = False
    # ponytail: one policy per run, not an adaptive scheduler.
    deliberation_fraction: float = Field(default=0.15, ge=0, le=0.25)
    validation_fraction: float = Field(default=0.25, ge=0.1, le=0.5)


class Finding(Record):
    claim: str
    evidence: str
    matters_because: str
    correction: str
    status: Literal["hypothesis", "observed", "unresolved"]


class Advice(Record):
    findings: list[Finding] = Field(default_factory=list, max_length=3)
    requested_probes: list[str] = Field(default_factory=list, max_length=2)
    unresolved: list[str] = Field(default_factory=list, max_length=3)


class Ruling(Record):
    claim: str
    decision: Literal["accept", "reject", "defer"]
    receipt: int = Field(ge=0)
    evidence_quote: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class Freeze(Record):
    implementation: list[str] = Field(min_length=1, max_length=4)
    rulings: list[Ruling] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    blocker: str = ""


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Cockpit:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.state: dict[str, Any] = json.loads((directory / "run.json").read_text())
        self.repo = Path(self.state["repo"])
        self.runner = Runner(directory / "cancel", max(0, self.remaining()))

    @classmethod
    def start(cls, repo: Path, task: str, minutes: float) -> "Cockpit":
        repo = repo.resolve()
        if not task.strip() or not 0 < minutes <= 180:
            raise Blocked("Supply a goal and explicit hard budget, 0 < minutes <= 180")
        started = time.monotonic()
        runner = Runner(repo / ".institutional-workbench/nonexistent-cancel", minutes * 60)
        _, root, _ = runner.run(["git", "rev-parse", "--show-toplevel"], repo)
        if Path(root.strip()).resolve() != repo:
            raise Blocked("Start at the repository root")
        _, dirty, _ = runner.run(["git", "status", "--porcelain"], repo)
        if dirty.strip():
            raise Blocked("Repository has existing work; use a separate committed worktree")
        _, head, _ = runner.run(["git", "rev-parse", "HEAD"], repo)
        directory = repo / ".institutional-workbench" / ("cockpit-" + str(time.time_ns()))
        directory.mkdir(parents=True)
        state = {
            "repo": str(repo),
            "task": task,
            "head": head.strip(),
            "started_monotonic": started,
            "started_at": time.time(),
            "seconds": minutes * 60,
            "phase": "INSPECT",
            "status": "RUNNING",
            "receipts": [],
            "reports": [],
            "calls": 0,
            "repairs": 0,
            "visual": {"status": "UNVERIFIED"},
        }
        (directory / "run.json").write_text(json.dumps(state, indent=2))
        return cls(directory)

    def remaining(self) -> float:
        elapsed = time.monotonic() - float(self.state["started_monotonic"])
        if elapsed < 0:
            return 0  # Reboot/clock discontinuity: never silently extend a deadline.
        return max(0, float(self.state["seconds"]) - elapsed)

    def save(self) -> None:
        temporary = self.directory / "run.tmp"
        temporary.write_text(json.dumps(self.state, indent=2) + "\n")
        temporary.replace(self.directory / "run.json")

    def gate(self, *phases: str) -> None:
        self.runner.check()
        if self.state["status"] != "RUNNING" or self.state["phase"] not in phases:
            raise Blocked(f"Action invalid in {self.state['status']}/{self.state['phase']}")

    def path(self, name: str) -> Path:
        path = self.repo / name
        if (
            not name
            or Path(name).is_absolute()
            or ".." in Path(name).parts
            or any(part.startswith(".") for part in Path(name).parts)
            or path.resolve() == self.repo
            or not path.resolve().is_relative_to(self.repo)
            or any(parent.is_symlink() for parent in (path, *path.parents))
        ):
            raise Blocked(f"Not an authorised plain repository path: {name}")
        if path.suffix in {".key", ".pem"}:
            raise Blocked("Do not collect credentials as evidence")
        return path

    def version(self) -> dict[str, str]:
        _, names, _ = self.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], self.repo
        )
        return {
            name: digest(self.repo / name)
            if (self.repo / name).is_file() and not (self.repo / name).is_symlink()
            else "MISSING_OR_SYMLINK"
            for name in names.split("\0")
            if name and not name.startswith(".institutional-workbench/")
        }

    def receipt(self, kind: str, details: dict[str, Any]) -> int:
        record = {
            "kind": kind,
            "phase": self.state["phase"],
            "elapsed": self.state["seconds"] - self.remaining(),
            **details,
        }
        self.state["receipts"].append(record)
        self.save()
        return len(self.state["receipts"]) - 1

    def execute(self, check: Check) -> dict[str, Any]:
        before = self.version()
        code, out, err = self.run(
            check.argv, self.repo, timeout=check.timeout, require_success=False
        )
        result = {
            "name": check.name,
            "kind": check.kind,
            "argv": check.argv,
            "exit_status": code,
            "stdout": out,
            "stderr": err,
            "version": before,
            "unchanged": before == self.version(),
        }
        self.receipt("execution", result)
        return result

    def run(
        self, argv: list[str], cwd: Path, *, timeout: float = 90, require_success: bool = True
    ) -> tuple[int, str, str]:
        try:
            return self.runner.run(
                argv, cwd, timeout=min(timeout, self.remaining()), require_success=require_success
            )
        except (OSError, Blocked) as exc:
            self.receipt(
                "operation_failure",
                {
                    "operation": "Runner.run",
                    "argv": argv,
                    "cwd": str(cwd),
                    "adapter": "host subprocess",
                    "errno": getattr(exc, "errno", None),
                    "error": str(exc),
                    "exit_status": None,
                    "context": "normal host permissions; owned subprocess group only",
                },
            )
            raise

    def prepare(self, plan: Plan) -> None:
        self.gate("INSPECT")
        if not any(check.kind == "test" for check in plan.checks):
            raise Blocked("At least one executable test is required")
        if len({p.name for p in plan.probes}) != len(plan.probes):
            raise Blocked("Probe names must be unique")
        for name in plan.owned_paths + plan.source_paths + [p.path for p in plan.probes]:
            self.path(name)
        self.state["plan"] = plan.model_dump()
        self.state["baseline"] = self.version()
        self.state["baseline_checks"] = [self.execute(check) for check in plan.checks]
        if any(not result["unchanged"] for result in self.state["baseline_checks"]):
            raise Blocked("Baseline check modified tracked/source files; inspect before proceeding")
        self.state["phase"] = "REVIEW"
        self.save()

    def probe(self, name: str) -> int:
        self.gate("REVIEW", "BUILD", "REPAIR")
        plan = Plan.model_validate(self.state["plan"])
        probe = next((p for p in plan.probes if p.name == name), None)
        if probe is None:
            raise Blocked("Unknown probe; advisers cannot supply executable commands")
        if sum(r.get("probe") == name for r in self.state["receipts"]) >= 2:
            raise Blocked("Probe attempt limit reached")
        path = self.path(probe.path)
        try:
            if path.stat().st_size > 1_048_576:
                raise ValueError("Evidence file exceeds 1 MiB; narrow the authorised probe")
            if probe.kind == "csv_columns":
                with path.open(newline="") as source:
                    text = json.dumps(next(csv.reader(source), []))
            else:
                text = path.read_text()[:60000]
        except (OSError, ValueError) as exc:
            return self.receipt(
                "probe_unavailable",
                {
                    "probe": name,
                    "path": probe.path,
                    "error": str(exc),
                    "errno": getattr(exc, "errno", None),
                    "next_action": "Cockpit must defer, narrow scope, or declare an essential blocker",
                },
            )
        return self.receipt(
            "probe", {"probe": name, "path": probe.path, "sha256": digest(path), "text": text}
        )

    def advice(self, provider: Provider | None = None) -> None:
        self.gate("REVIEW")
        if self.state.get("advice_started"):
            raise Blocked("One independent assessment/challenge round only")
        self.state["advice_started"] = True
        self.save()
        plan = Plan.model_validate(self.state["plan"])
        profile = profile_task(
            self.state["task"], "hackathon", has_tests=True, remaining_seconds=self.remaining()
        )
        roles = (
            []
            if profile.difficulty in {"trivial", "low"}
            else select_specialists(profile, "hackathon", maximum=2)
        )
        self.state["roles"] = [role.model_dump() for role in roles]
        cutoff = (
            self.state["started_monotonic"] + self.state["seconds"] * plan.deliberation_fraction
        )
        source = {}
        for name in plan.source_paths:
            path = self.path(name)
            try:
                if path.stat().st_size > 60000:
                    raise ValueError("Source too large; narrow evidence before review")
                source[name] = {"sha256": digest(path), "text": path.read_text()}
            except (OSError, ValueError) as exc:
                source[name] = {"unavailable": str(exc)}
        evidence = {
            "task": self.state["task"],
            "source": source,
            "receipts": list(self.state["receipts"]),
            "allowed_probe_names": [p.name for p in plan.probes],
        }
        router = Router("hackathon")
        for phase in ("INDEPENDENT", "CHALLENGE"):
            initial = list(self.state["reports"])
            if phase == "CHALLENGE" and not initial:
                break
            for role in roles:
                if time.monotonic() >= cutoff:
                    self.state["advice_cutoff"] = "Deliberation allowance exhausted; cockpit builds"
                    self.save()
                    return
                request = {
                    **evidence,
                    "role": role.model_dump(),
                    "phase": phase,
                    "authority": "Advice only. No edits, execution or completion authority.",
                    "instruction": "Cite supplied evidence; request a named probe for missing facts. Challenge false fixes; separate facts from hypotheses. Do not claim tools were used.",
                }
                if phase == "CHALLENGE":
                    request["peer_reports"] = initial
                previous = None
                for attempt in range(2):
                    seconds = min(90, cutoff - time.monotonic(), self.remaining())
                    if seconds <= 0:
                        break
                    child_runner = Runner(self.directory / "cancel", seconds)
                    try:
                        route = router.choose(
                            profile,
                            phase,
                            role.role,
                            previous=previous,
                            model_failure=bool(attempt),
                            trigger="operational failure" if attempt else None,
                        )
                    except Blocked as exc:
                        self.receipt("adviser_unavailable", {"role": role.role, "error": str(exc)})
                        break
                    self.state["calls"] += 1
                    self.receipt("route", route.model_dump())
                    try:
                        answer = (provider or CliProviders(child_runner)).ask(
                            route.selected_provider,
                            json.dumps(request),
                            Advice,
                            model=route.selected_model,
                        )
                        self.state["reports"].append(
                            {"role": role.role, "phase": phase, "report": answer.model_dump()}
                        )
                        self.save()
                        break
                    except (OSError, Blocked, ValueError) as exc:
                        self.runner.check()  # Overall deadline/cancel is never optional.
                        self.receipt(
                            "adviser_unavailable",
                            {
                                "role": role.role,
                                "provider": route.selected_provider,
                                "model": route.selected_model,
                                "error": str(exc),
                                "errno": getattr(exc, "errno", None),
                            },
                        )
                        if isinstance(exc, PermissionError):
                            break  # Never retry a denied operation on a stronger model.
                        previous = route

    def freeze(self, decision: Freeze) -> None:
        self.gate("REVIEW")
        for ruling in decision.rulings:
            if ruling.receipt >= len(self.state["receipts"]):
                raise Blocked("Unknown supporting receipt")
            receipt = self.state["receipts"][ruling.receipt]
            if receipt["kind"] not in {"probe", "execution"}:
                raise Blocked("Model opinion is not executable/source evidence")
            if ruling.evidence_quote not in str(receipt.get("text", receipt.get("stdout", ""))):
                raise Blocked("Ruling quote is not present in observed evidence")
            if (
                receipt["kind"] == "probe"
                and digest(self.path(receipt["path"])) != receipt["sha256"]
            ):
                raise Blocked("Evidence changed; re-run the probe before a consequential edit")
            if receipt["kind"] == "execution" and receipt["version"] != self.version():
                raise Blocked("Execution evidence is stale")
        self.state["decision"] = decision.model_dump()
        if decision.blocker:
            raise Blocked(decision.blocker)
        self.state["phase"] = "BUILD"
        self.save()

    def visual(self, screenshot: str, viewport: str, command: list[str]) -> None:
        self.gate("BUILD", "REPAIR")
        path = self.path(screenshot)
        if not viewport or not command:
            raise Blocked("Supply viewport and actual render command")
        if path.exists():
            raise Blocked("Use a fresh screenshot path; do not reuse an old image")
        result = self.execute(Check(name="render", kind="demo", argv=command))
        if (
            result["exit_status"]
            or not path.is_file()
            or path.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n"
        ):
            raise Blocked("Render did not produce a new PNG")
        self.state["visual"] = {
            "status": "CAPTURED_NOT_INTERPRETED",
            "path": screenshot,
            "viewport": viewport,
            "sha256": digest(path),
            "version": self.version(),
        }
        self.save()

    def verify(self) -> None:
        self.gate("BUILD", "REPAIR")
        plan = Plan.model_validate(self.state["plan"])
        before = self.version()
        baseline = self.state["baseline"]
        changed = {p for p in baseline.keys() | before.keys() if baseline.get(p) != before.get(p)}
        for name in changed:
            self.path(name)
            if not any(
                name == owned or name.startswith(owned.rstrip("/") + "/")
                for owned in plan.owned_paths
            ):
                raise Blocked(f"Change outside frozen ownership: {name}")
            if name in baseline and (
                name.startswith("tests/") or Path(name).name.startswith("test")
            ):
                raise Blocked(f"Existing acceptance test changed: {name}")
        _, head, _ = self.run(["git", "rev-parse", "HEAD"], self.repo)
        if head.strip() != self.state["head"]:
            raise Blocked("Repository HEAD changed during cockpit run")
        results = [self.execute(check) for check in plan.checks]
        passed = all(r["exit_status"] == 0 and r["unchanged"] for r in results)
        self.state["verification"] = results
        if before != self.version():
            raise Blocked("Verification changed the candidate; no success receipt issued")
        if not changed and not all(r["exit_status"] == 0 for r in self.state["baseline_checks"]):
            passed = False  # Narrative completion cannot turn a failing baseline into a no-op.
        visual = self.state["visual"]
        if visual.get("version") != before:
            visual["status"] = "UNVERIFIED"
        if not passed:
            if self.state["repairs"] == 0:
                self.state["repairs"] = 1
                self.state["phase"] = "REPAIR"
            else:
                self.state["status"] = "BLOCKED"
                self.state["limitation"] = "Frozen checks still fail after one repair"
        elif plan.visual_required and visual["status"] == "UNVERIFIED":
            self.state["status"] = "PARTIAL"
            self.state["limitation"] = (
                "Required render unavailable/stale; UI is not visually verified"
            )
        elif passed:
            self.state["status"] = "DELIVERED"
            self.state["build"] = "CHANGED" if changed else "NO CHANGES REQUIRED"
        self.state["files_changed"] = sorted(changed)
        self.save()

    def view(self) -> dict[str, Any]:
        plan = self.state.get("plan", {})
        reserve = self.state["seconds"] * plan.get("validation_fraction", 0.25)
        return {
            **self.state,
            "run": str(self.directory),
            "remaining_seconds": self.remaining(),
            "next_action": "VALIDATE_ONLY" if self.remaining() <= reserve else self.state["phase"],
            "native_tool_timeout_ms": max(1, int(min(60, self.remaining()) * 1000)),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=[
            "start",
            "prepare",
            "probe",
            "advice",
            "freeze",
            "verify",
            "status",
            "cancel",
            "visual",
        ],
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--run", type=Path)
    parser.add_argument("--task-file", type=Path)
    parser.add_argument("--minutes", type=float)
    parser.add_argument("--file", type=Path, help="Cockpit-authored plan/decision JSON")
    parser.add_argument("--name")
    args = parser.parse_args()
    cockpit = None
    if args.action in {"prepare", "freeze", "visual"} and args.file is None:
        parser.error("--file is required")
    if args.action == "probe" and not args.name:
        parser.error("--name is required")
    with ExitStack() as stack:
        try:
            if args.action == "start":
                if args.task_file is None or args.minutes is None:
                    parser.error("start requires --task-file and explicit --minutes")
                cockpit = Cockpit.start(args.repo, args.task_file.read_text(), args.minutes)
            else:
                if args.run is None:
                    parser.error("--run is required")
                if args.action == "cancel":
                    (args.run / "cancel").touch()
                    print(json.dumps({"status": "CANCEL_REQUESTED", "run": str(args.run)}))
                    return 0
                # Acquire BEFORE loading, and retain the lock during error persistence.
                lock = stack.enter_context((args.run / "lock").open("a"))
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                cockpit = Cockpit(args.run)
                if args.action == "prepare":
                    cockpit.prepare(Plan.model_validate_json(args.file.read_text()))
                elif args.action == "freeze":
                    cockpit.freeze(Freeze.model_validate_json(args.file.read_text()))
                elif args.action == "probe":
                    cockpit.probe(args.name)
                elif args.action == "advice":
                    cockpit.advice()
                elif args.action == "verify":
                    cockpit.verify()
                elif args.action == "visual":
                    data = json.loads(args.file.read_text())
                    cockpit.visual(data["screenshot"], data["viewport"], data["argv"])
                elif cockpit.state["status"] == "RUNNING":
                    cockpit.runner.check()
        except (Blocked, OSError, ValueError) as exc:
            if cockpit:
                if cockpit.state["status"] == "RUNNING":
                    cockpit.state["status"] = "DEADLINE" if isinstance(exc, Deadline) else "BLOCKED"
                    cockpit.state["limitation"] = str(exc)
                    cockpit.save()
            else:
                print(json.dumps({"status": "BLOCKED", "error": str(exc)}))
                return 1
    assert cockpit is not None
    print(json.dumps(cockpit.view(), indent=2))
    return 0 if cockpit.state["status"] in {"RUNNING", "DELIVERED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
