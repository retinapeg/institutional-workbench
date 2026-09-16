"""Native Claude owns edits; this foreground helper owns bounded evidence and gates.

Not a sandbox: the cockpit authorises argv lists. Advisers can request only named
probes, never execute commands or mark implementation complete.
"""

import argparse
import csv
import fcntl
import hashlib
import json
import tempfile
import time
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse
from urllib.request import urlopen

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
    core_demo_checklist: list[str] = Field(default_factory=list, max_length=12)
    ship_required: list[Literal["readme", "pitch", "submission", "fallback", "screenshots"]] = (
        Field(default_factory=list)
    )
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


class Action(Record):
    kind: Literal["feature", "core", "fix", "polish", "ship", "verify"]
    risky: bool = False
    current_action: str = Field(min_length=1, max_length=500)
    next_action: str = Field(default="", max_length=500)


class Shipping(Record):
    readme: str = ""
    pitch: str = ""
    submission: str = ""
    fallback: str = ""
    screenshots: list[str] = Field(default_factory=list, max_length=8)
    demo_url: str = ""
    deployment_note: str = Field(default="", max_length=1000)


# Keep the operational state small. Detailed evidence is a separate local artifact,
# not a transcript fed back into every model call or status view.
EVIDENCE_KEYS = {
    "receipts",
    "reports",
    "baseline",
    "baseline_checks",
    "verification",
    "plan",
    "decision",
    "checkpoint_version",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Cockpit:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.state: dict[str, Any] = json.loads((directory / "run.json").read_text())
        if (directory / "evidence.json").exists():
            self.state.update(json.loads((directory / "evidence.json").read_text()))
        self.repo = Path(self.state["repo"])
        self.runner = Runner(directory / "cancel", max(0, self.remaining()))

    @classmethod
    def start(cls, repo: Path, task: str, minutes: float = 120) -> "Cockpit":
        repo = repo.resolve()
        if not task.strip() or not 0 < minutes <= 10080:
            raise Blocked("Supply a goal and budget, 0 < minutes <= 10080 (one week)")
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
            "deadline": datetime.fromtimestamp(time.time() + minutes * 60, UTC).isoformat(),
            "phase": "INSPECT",
            "status": "RUNNING",
            "receipts": [],
            "reports": [],
            "calls": 0,
            "repairs": 0,
            "visual": {"status": "UNVERIFIED"},
            "iteration": 0,
            "repair_used": False,
            "current_action": "Inspect and get the smallest demo running",
            "next_action": "Build",
            "last_working_commit": "",
            "steering_requests": [],
            "recent_evidence": [],
            "last_artifact_elapsed": 0.0,
            "top_risks": [],
            "demo_status": "UNVERIFIED",
            "demo_url": "",
            "url_status": "UNVERIFIED",
            "ship_checklist": {},
            "breaker_findings": [],
        }
        (directory / "run.json").write_text(json.dumps(state, indent=2))
        return cls(directory)

    def remaining(self) -> float:
        elapsed = time.monotonic() - float(self.state["started_monotonic"])
        if elapsed < 0:
            return 0  # Reboot/clock discontinuity: never silently extend a deadline.
        return max(
            0,
            min(
                float(self.state["seconds"]) - elapsed,
                float(self.state["started_at"]) + float(self.state["seconds"]) - time.time(),
            ),
        )

    def save(self) -> None:
        self.state["time_remaining"] = self.remaining()
        for name, value in (
            ("evidence", {k: v for k, v in self.state.items() if k in EVIDENCE_KEYS}),
            ("run", {k: v for k, v in self.state.items() if k not in EVIDENCE_KEYS}),
        ):
            temporary = self.directory / (name + ".tmp")
            temporary.write_text(json.dumps(value, indent=2) + "\n")
            temporary.replace(self.directory / (name + ".json"))

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
        self.state["recent_evidence"] = (
            self.state.get("recent_evidence", [])
            + [
                {
                    "kind": kind,
                    "elapsed": record["elapsed"],
                    "receipt": len(self.state["receipts"]) - 1,
                }
            ]
        )[-12:]
        if kind in {"checkpoint", "shipping", "files_observed"} or (
            kind == "execution" and details.get("exit_status") == 0
        ):
            self.state["last_artifact_elapsed"] = record["elapsed"]
            self.state.setdefault("milestones", {}).setdefault(kind, record["elapsed"])
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
        self,
        argv: list[str],
        cwd: Path,
        *,
        timeout: float = 90,
        require_success: bool = True,
        text: str = "",
    ) -> tuple[int, str, str]:
        try:
            return self.runner.run(
                argv,
                cwd,
                text=text,
                timeout=min(timeout, self.remaining()),
                require_success=require_success,
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
        self.state["definition_of_done"] = plan.acceptance
        self.state["core_demo_checklist"] = {
            item: "UNVERIFIED" for item in plan.core_demo_checklist
        }
        self.state["phase"] = "BUILD"
        self.breaker(self.state["baseline_checks"])
        if all(r["exit_status"] == 0 and r["unchanged"] for r in self.state["baseline_checks"]):
            self.checkpoint()
        self.save()

    def deadline_phase(self) -> str:
        remaining = self.remaining()
        seconds = float(self.state["seconds"])
        if remaining <= min(1800, seconds / 12):
            return "FINAL_VERIFY"
        if remaining <= min(3600, seconds / 6):
            return "POLISH_SHIP"
        if remaining <= min(5400, seconds / 4):
            return "FEATURE_FREEZE"
        return "BUILD"

    def begin(self, action: Action) -> None:
        self.gate("BUILD", "REPAIR")
        phase = self.deadline_phase()
        if phase != "BUILD" and action.kind == "feature":
            raise Blocked("Feature freeze: only essential core work, fixes or shipping remain")
        if phase in {"POLISH_SHIP", "FINAL_VERIFY"} and action.kind == "core":
            raise Blocked("No new core features this close to the deadline")
        if phase == "FINAL_VERIFY" and (action.risky or action.kind not in {"verify", "ship"}):
            raise Blocked("T-30: no risky/code changes; verify the demo/fallback and ship")
        if action.risky and self.state.get("checkpoint_version") != self.version():
            raise Blocked("Verify and checkpoint the current working demo before a risky change")
        if self.state["phase"] == "REPAIR" and action.kind != "fix":
            raise Blocked("Repair and verify this iteration before starting another")
        if self.state.get("verification") and self.state["phase"] != "REPAIR":
            if not all(
                r["exit_status"] == 0 and r["unchanged"] for r in self.state["verification"]
            ):
                raise Blocked("Previous checks failed; do not reset the repair allowance")
            self.state["iteration"] += 1
            self.state["repair_used"] = False
            self.state.pop("verification", None)
            self.state.pop("advice_started", None)
            self.state["reports"] = []
        self.state["iteration_started"] = time.monotonic()
        self.state["current_action"] = action.current_action
        self.state["next_action"] = action.next_action
        self.state["phase"] = "BUILD"
        for request in self.state["steering_requests"]:
            request["applied"] = True
        self.save()

    def steer(self, instruction: str) -> None:
        self.gate("INSPECT", "BUILD", "REPAIR", "REVIEW")
        if not instruction.strip() or len(instruction) > 2000:
            raise Blocked("Supply a concise steering instruction (1–2000 characters)")
        # Same process/run/clock/checks. Claude interprets this at its next safe boundary.
        self.state["steering_requests"] = (
            self.state["steering_requests"]
            + [
                {
                    "instruction": instruction,
                    "elapsed": self.state["seconds"] - self.remaining(),
                    "applied": False,
                }
            ]
        )[-20:]
        self.state["next_action"] = instruction
        self.receipt("steering", {"instruction": instruction})

    def breaker(self, results: list[dict[str, Any]]) -> None:
        for result in results:
            if result["exit_status"] != 0 or not result["unchanged"]:
                self.state["breaker_findings"] = (
                    self.state["breaker_findings"]
                    + [
                        {
                            "check": result["name"],
                            "exit_status": result["exit_status"],
                            "evidence": (result["stderr"] or result["stdout"])[-1500:],
                            "source_unchanged": result["unchanged"],
                        }
                    ]
                )[-10:]
        demos = [r for r in results if r["kind"] == "demo"]
        self.state["demo_status"] = (
            "LOCAL ONLY"
            if demos and all(r["exit_status"] == 0 and r["unchanged"] for r in demos)
            else "BROKEN"
            if demos
            else "UNVERIFIED"
        )
        for item in self.state.get("core_demo_checklist", {}):
            match = next((r for r in results if r["name"] == item), None)
            if match:
                self.state["core_demo_checklist"][item] = (
                    "PASS" if match["exit_status"] == 0 and match["unchanged"] else "FAIL"
                )
        for kind in ("test", "demo"):
            if any(r["kind"] == kind and r["exit_status"] == 0 and r["unchanged"] for r in results):
                self.state.setdefault("milestones", {}).setdefault(
                    kind, self.state["seconds"] - self.remaining()
                )

    def checkpoint(self) -> None:
        version = self.version()
        if self.state.get("checkpoint_version") == version:
            return
        # A private Git ref/temporary index preserves bytes without moving HEAD,
        # changing the user's index, firing commit hooks or discarding dirty work.
        with tempfile.TemporaryDirectory(dir=self.directory, prefix="checkpoint-") as folder:
            prefix = ["env", "GIT_INDEX_FILE=" + str(Path(folder) / "index"), "git"]
            self.run(prefix + ["read-tree", self.state["head"]], self.repo)
            paths = sorted(set(version) | set(self.state["baseline"]))
            self.run(prefix + ["add", "-A", "--", *paths], self.repo)
            _, tree, _ = self.run(prefix + ["write-tree"], self.repo)
            parent = self.state["last_working_commit"] or self.state["head"]
            _, commit, _ = self.run(
                [
                    "git",
                    "-c",
                    "user.name=Institutional Cockpit",
                    "-c",
                    "user.email=cockpit@localhost",
                    "commit-tree",
                    tree.strip(),
                    "-p",
                    parent,
                    "-m",
                    "Verified hackathon working checkpoint",
                ],
                self.repo,
            )
            if self.version() != version:
                raise Blocked("Candidate changed during checkpoint; previous checkpoint preserved")
            ref = "refs/institutional-cockpit/" + self.directory.name
            self.run(
                [
                    "git",
                    "update-ref",
                    ref,
                    commit.strip(),
                    self.state["last_working_commit"] or "0" * 40,
                ],
                self.repo,
            )
        self.state["last_working_commit"] = commit.strip()
        self.state["checkpoint_version"] = version
        self.receipt("checkpoint", {"commit": commit.strip(), "ref": ref})

    def ship(self, shipping: Shipping) -> None:
        self.gate("BUILD", "REPAIR")
        items: dict[str, Any] = {}
        for kind in ("readme", "pitch", "submission", "fallback", "screenshots"):
            value = getattr(shipping, kind)
            names = value if isinstance(value, list) else [value] if value else []
            files = []
            for name in names:
                path = self.path(name)
                if not path.is_file() or not path.stat().st_size:
                    raise Blocked(f"Shipping asset missing/empty: {name}")
                files.append({"path": name, "sha256": digest(path)})
            items[kind] = files
        self.state["ship_checklist"] = items
        self.state["demo_url"] = shipping.demo_url
        self.state["url_status"] = "UNVERIFIED" if shipping.demo_url else "NOT APPLICABLE"
        self.state["deployment_note"] = shipping.deployment_note
        if not shipping.demo_url and not shipping.deployment_note:
            raise Blocked("Explain why public deployment is not applicable/unavailable")
        if shipping.demo_url:
            url = urlparse(shipping.demo_url)
            if (
                url.scheme not in {"https", "http"}
                or not url.hostname
                or url.username
                or url.password
            ):
                raise Blocked("Use an HTTP(S) demo URL without credentials")
            try:
                with urlopen(shipping.demo_url, timeout=min(10, self.remaining())) as response:
                    response.read(1024)
                    self.state["url_status"] = (
                        "VERIFIED" if response.status == 200 else "UNVERIFIED"
                    )
                    self.state["url_checked_at"] = datetime.now(UTC).isoformat()
            except (OSError, ValueError) as exc:
                self.state["url_failure"] = str(exc)
            # HTTP availability is not proof of interactive behaviour or public reachability.
            self.state["url_evidence_scope"] = (
                "HTTP reachability from this laptop only; demo checks separate"
            )
        self.receipt("shipping", {"assets": items, "url_status": self.state["url_status"]})

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

    def advice(
        self, provider: Provider | None = None, *, question: str = "", challenge: bool = False
    ) -> None:
        self.gate("REVIEW", "BUILD")
        if self.state.get("advice_started"):
            raise Blocked("One independent assessment/challenge round only")
        if not question.strip() or self.deadline_phase() != "BUILD" or self.force_execution():
            self.receipt(
                "advice_skipped",
                {"reason": "No consequential question, time allowance, or recent artifact"},
            )
            return
        self.state["advice_started"] = True
        self.save()
        plan = Plan.model_validate(self.state["plan"])
        profile = profile_task(
            question, "hackathon", has_tests=True, remaining_seconds=self.remaining()
        )
        roles = (
            []
            if profile.difficulty in {"trivial", "low"}
            else select_specialists(profile, "hackathon", maximum=2)
        )
        self.state["roles"] = [role.model_dump() for role in roles]
        cutoff = self.state.get("iteration_started", self.state["started_monotonic"]) + min(
            600, self.state["seconds"] * plan.deliberation_fraction
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
            "question": question,
            "source": source,
            "receipts": list(self.state["receipts"])[-4:],
            "allowed_probe_names": [p.name for p in plan.probes],
        }
        router = Router("hackathon")
        for phase in ("INDEPENDENT", "CHALLENGE") if challenge else ("INDEPENDENT",):
            initial = list(self.state["reports"])
            if phase == "CHALLENGE" and not initial:
                break
            for role in roles[:1] if phase == "CHALLENGE" else roles:
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
        self.gate("REVIEW", "BUILD")
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

    def verify(self, *, deliver: bool = False) -> None:
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
        self.breaker(results)
        if before != self.version():
            raise Blocked("Verification changed the candidate; no success receipt issued")
        if not changed and not all(r["exit_status"] == 0 for r in self.state["baseline_checks"]):
            passed = False  # Narrative completion cannot turn a failing baseline into a no-op.
        visual = self.state["visual"]
        if visual.get("version") != before:
            visual["status"] = "UNVERIFIED"
        if not passed:
            if not self.state["repair_used"]:
                self.state["repair_used"] = True
                self.state["repairs"] += 1
                self.state["phase"] = "REPAIR"
            else:
                self.state["status"] = "BLOCKED"
                self.state["limitation"] = "Frozen checks still fail after one repair"
        elif passed:
            self.checkpoint()
            self.state["phase"] = "BUILD"
            self.state["build"] = "CHANGED" if changed else "NO CHANGES REQUIRED"
            missing: list[str] = []
            missing.extend(
                "Core demo unverified: " + name
                for name, status in self.state.get("core_demo_checklist", {}).items()
                if status != "PASS"
            )
            if plan.visual_required and visual["status"] == "UNVERIFIED":
                missing.append("Required render unavailable/stale; UI is not visually verified")
            for kind in plan.ship_required:
                assets = self.state["ship_checklist"].get(kind, [])
                if not assets or any(
                    not self.path(a["path"]).is_file()
                    or digest(self.path(a["path"])) != a["sha256"]
                    for a in assets
                ):
                    missing.append("Shipping asset missing/stale: " + kind)
            self.state["top_risks"] = missing[:5]
            if deliver:
                self.state["status"] = "PARTIAL" if missing else "DELIVERED"
                self.state["limitation"] = "; ".join(missing)
                self.state["final_report"] = {
                    "working_now": plan.deliverable,
                    "definition_of_done": plan.acceptance,
                    "tests": [
                        {"name": r["name"], "exit_status": r["exit_status"]} for r in results
                    ],
                    "demo_status": self.state["demo_status"],
                    "public_url": self.state["demo_url"],
                    "url_status": self.state["url_status"],
                    "remaining": missing,
                    "last_working_commit": self.state["last_working_commit"],
                }
        self.state["files_changed"] = sorted(changed)
        self.save()

    def force_execution(self) -> bool:
        return (
            float(self.state["seconds"])
            - self.remaining()
            - float(self.state.get("last_artifact_elapsed", 0))
            >= 1800
        )

    def view(self) -> dict[str, Any]:
        return {
            **{k: v for k, v in self.state.items() if k not in EVIDENCE_KEYS},
            "run": str(self.directory),
            "remaining_seconds": self.remaining(),
            "deadline_phase": self.deadline_phase(),
            "force_execution": self.force_execution(),
            "native_tool_timeout_ms": max(1, int(min(60, self.remaining()) * 1000)),
        }

    def human(self) -> str:
        s = self.view()
        return "\n".join(
            [
                f"DEADLINE: {s['deadline']} | TIME REMAINING: {s['remaining_seconds'] / 60:.1f} min",
                f"STATUS: {s['status']} | PHASE: {s['deadline_phase']}",
                f"DEMO URL: {s['demo_url'] or 'none'} ({s['url_status']}) | DEMO: {s['demo_status']}",
                "CORE DEMO: " + json.dumps(s.get("core_demo_checklist", {})),
                "SHIP: "
                + ", ".join(
                    f"{key}: {'present' if value else 'missing'}"
                    for key, value in s["ship_checklist"].items()
                ),
                "TOP RISKS: " + "; ".join(s["top_risks"]),
                "CURRENT: " + s["current_action"],
                "NEXT: " + s["next_action"],
                "LAST WORKING: " + (s["last_working_commit"] or "not yet verified"),
            ]
        )


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
            "begin",
            "steer",
            "ship",
        ],
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--run", type=Path)
    parser.add_argument("--task-file", type=Path)
    parser.add_argument("--minutes", type=float)
    parser.add_argument("--file", type=Path, help="Cockpit-authored plan/decision JSON")
    parser.add_argument("--name")
    parser.add_argument("--challenge", action="store_true")
    parser.add_argument("--deliver", action="store_true")
    parser.add_argument("--human", action="store_true")
    args = parser.parse_args()
    cockpit = None
    if args.action in {"prepare", "freeze", "visual", "begin", "ship"} and args.file is None:
        parser.error("--file is required")
    if args.action == "probe" and not args.name:
        parser.error("--name is required")
    with ExitStack() as stack:
        try:
            if args.action == "start":
                if args.task_file is None:
                    parser.error("start requires --task-file")
                cockpit = Cockpit.start(
                    args.repo,
                    args.task_file.read_text(),
                    args.minutes if args.minutes is not None else 120,
                )
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
                    cockpit.advice(question=args.name or "", challenge=args.challenge)
                elif args.action == "verify":
                    cockpit.verify(deliver=args.deliver)
                elif args.action == "begin":
                    cockpit.begin(Action.model_validate_json(args.file.read_text()))
                elif args.action == "steer":
                    if args.task_file is None:
                        parser.error("steer requires --task-file")
                    cockpit.steer(args.task_file.read_text())
                elif args.action == "ship":
                    cockpit.ship(Shipping.model_validate_json(args.file.read_text()))
                elif args.action == "visual":
                    data = json.loads(args.file.read_text())
                    cockpit.visual(data["screenshot"], data["viewport"], data["argv"])
                elif cockpit.state["status"] == "RUNNING":
                    cockpit.runner.check()
                    if (
                        cockpit.state.get("baseline")
                        and cockpit.version() != cockpit.state["baseline"]
                        and "files_observed" not in cockpit.state.get("milestones", {})
                    ):
                        cockpit.receipt(
                            "files_observed", {"note": "Project bytes changed since baseline"}
                        )
        except (Blocked, OSError, ValueError) as exc:
            if cockpit:
                if cockpit.state["status"] == "RUNNING":
                    # A refused optional action is a control boundary, not lost work.
                    if (
                        args.action in {"begin", "ship", "steer", "visual"}
                        and not isinstance(exc, Deadline)
                        and not (cockpit.directory / "cancel").exists()
                    ):
                        print(json.dumps({"refused": str(exc), **cockpit.view()}))
                        return 1
                    cockpit.state["status"] = "DEADLINE" if isinstance(exc, Deadline) else "BLOCKED"
                    cockpit.state["limitation"] = str(exc)
                    cockpit.save()
            else:
                print(json.dumps({"status": "BLOCKED", "error": str(exc)}))
                return 1
    assert cockpit is not None
    result = cockpit.view()
    if args.action == "advice":
        result["advice"] = cockpit.state["reports"]
    print(cockpit.human() if args.human else json.dumps(result, indent=2))
    return 0 if cockpit.state["status"] in {"RUNNING", "DELIVERED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
