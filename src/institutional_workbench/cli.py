import argparse
import fcntl
import json
import re
import signal
import subprocess
import time
from pathlib import Path

from .orchestrator import Workbench
from .providers import CliProviders
from .routing import ALIASES, Router
from .runner import Blocked, Runner


def task_minutes(task: str) -> float:
    match = re.search(
        r"\b(?:in|within|budget(?: of)?)\s+(\d+(?:\.\d+)?)\s*(minutes?|mins?)\b", task, re.I
    )
    return float(match.group(1)) if match else 15


def main() -> int:
    parser = argparse.ArgumentParser(description="Decide, build, test, deliver, stop.")
    parser.add_argument(
        "command",
        choices=[
            "engineering",
            "hackathon",
            "economy",
            "dev",
            "hack",
            "status",
            "cancel",
            "crunch",
        ],
    )
    parser.add_argument("task", nargs="?")
    parser.add_argument("--task-file", type=Path, help="Read the exact task from a UTF-8 file")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--builder", choices=["claude", "codex"])
    parser.add_argument("--reviewer", choices=["claude", "codex"])
    parser.add_argument("--claude-model")
    parser.add_argument("--codex-model")
    parser.add_argument(
        "--no-routing", action="store_true", help="Use the v0.1 fixed-provider path"
    )
    parser.add_argument(
        "--explain-routing", action="store_true", help="Show specialist/model selection reasons"
    )
    parser.add_argument(
        "--quick", action="store_true", help="Routine task: builder only, no expert roundtable"
    )
    parser.add_argument(
        "--test",
        action="append",
        help="Approved acceptance command; repeat for lint/build/demo checks",
    )
    parser.add_argument(
        "--minutes", type=float, help="Time budget; overrides an explicit deadline in task text"
    )
    parser.add_argument(
        "--hard-deadline",
        type=float,
        metavar="MINUTES",
        help="Explicit hard run deadline; Hackathon otherwise uses a soft budget",
    )
    args = parser.parse_args()
    if args.task_file:
        if args.task is not None:
            parser.error("Use a task argument or --task-file, not both")
        args.task = args.task_file.read_text(encoding="utf-8")
    if args.minutes is None:
        args.minutes = (
            task_minutes(args.task or "") if args.command in {"hack", "hackathon"} else 15
        )
    if not 0 < args.minutes <= 60:
        parser.error("--minutes must be between 0 and 60")
    if args.hard_deadline is not None and not 0 < args.hard_deadline <= 60:
        parser.error("--hard-deadline must be between 0 and 60")
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=args.repo,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        repo = Path(result.stdout.strip()).resolve()
        root = repo / ".institutional-workbench"
        root.mkdir(exist_ok=True)
        active = root / "active.json"
        if args.command in {"status", "cancel", "crunch"}:
            if not active.exists():
                raise Blocked("No previous run in this repository")
            state_path = Path(json.loads(active.read_text())["run_dir"]) / "run.json"
            state = (
                json.loads(state_path.read_text())
                if state_path.exists()
                else {"status": "STARTING"}
            )
            if args.command in {"cancel", "crunch"}:
                if state["status"] in {"DELIVERED", "BLOCKED", "PAUSED", "DEADLINE", "CANCELLED"}:
                    print("Run has already stopped.")
                elif args.command == "crunch":
                    if state.get("mode") not in {"hack", "hackathon"}:
                        raise Blocked("Crunch control applies only to Hackathon")
                    (state_path.parent / "crunch").touch()
                    print(
                        "CRUNCH requested: finish the atomic operation, verify a checkpoint, then pause."
                    )
                else:
                    (state_path.parent / "cancel").touch()
                    print(
                        "Cancellation requested; the child process will stop and isolated work is retained."
                    )
            else:
                print(json.dumps(state, indent=2))
            return 0
        if not args.task or not args.task.strip():
            parser.error("engineering/hackathon/economy require a task")
        with (root / "run.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise Blocked(
                    "Another workbench run is active; use inst status or inst cancel"
                ) from exc
            run_dir = root / time.strftime("%Y%m%d-%H%M%S")
            run_dir.mkdir(exist_ok=False)
            active.write_text(json.dumps({"run_dir": str(run_dir)}))
            runner = Runner(
                run_dir / "cancel",
                (args.hard_deadline or args.minutes) * 60,
                hard_deadline=args.hard_deadline is not None
                or args.command not in {"hack", "hackathon"},
            )
            signal.signal(signal.SIGINT, lambda *_: runner.cancel_file.touch())
            signal.signal(signal.SIGTERM, lambda *_: runner.cancel_file.touch())
            providers = CliProviders(
                runner, args.claude_model or "sonnet", args.codex_model or "gpt-5.6-terra"
            )
            state = Workbench(
                repo,
                run_dir,
                runner,
                providers,
                mode=args.command,
                objective=args.task,
                builder=args.builder or "claude",
                reviewer=args.reviewer or "codex",
                quick=args.quick,
                tests=args.test,
                routing=not args.no_routing,
                router=Router(
                    ALIASES.get(args.command, args.command),
                    overrides={
                        key: value
                        for key, value in (
                            ("claude", args.claude_model),
                            ("codex", args.codex_model),
                        )
                        if value
                    },
                ),
                pinned_builder=args.builder is not None,
                pinned_reviewer=args.reviewer is not None,
                explain_routing=args.explain_routing,
            ).run()
            print("\n" + state["status"])
            if state["status"] == "PAUSED":
                for heading, value in state["checkpoint"].items():
                    print(heading + ": " + str(value))
            elif state["status"] == "DELIVERED":
                print("What changed: " + state["deliverable"])
                print(
                    "Tests: "
                    + "; ".join(" ".join(t["command"]) + " — passed" for t in state["tests"])
                )
                print("Run: " + state["run_command"])
                print("Files changed: " + ", ".join(state["files_changed"]))
                print("Known limitations: " + ("; ".join(state["limitations"]) or "None reported"))
                if args.command in {"hack", "hackathon"}:
                    print("Pitch: " + " → ".join(state["pitch_outline"]))
                    print("Fallback: " + state["fallback"])
            else:
                print("Concrete blocker: " + state["current_blocker"])
                print("Best next action: resolve that blocker, then run the command again.")
            print("Evidence: " + str(run_dir))
            return 0 if state["status"] in {"DELIVERED", "PAUSED"} else 1
    except (Blocked, OSError, subprocess.SubprocessError) as exc:
        print(f"BLOCKED\n{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
