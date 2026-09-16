"""One serial A/B/C experiment; macOS filesystem isolation, frozen external checks."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, cast

from institutional_workbench.runner import Runner

ROOT = Path(__file__).resolve().parent
CONTENDERS = ("claude", "codex", "institutional")


def tree(path: Path) -> dict[str, str]:
    result = {}
    for file in sorted(path.rglob("*")):
        relative = file.relative_to(path)
        if any(
            part in {".git", "__pycache__", ".institutional-workbench"} for part in relative.parts
        ):
            continue
        if file.is_symlink():
            result[str(relative)] = "SYMLINK:" + os.readlink(file)
            continue
        if file.is_file():
            result[str(relative)] = hashlib.sha256(file.read_bytes()).hexdigest()
    return result


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def process_table() -> dict[int, tuple[int, str]]:
    text = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,lstart="], capture_output=True, text=True, check=True, timeout=2
    ).stdout
    return {
        int(parts[0]): (int(parts[1]), parts[2])
        for line in text.splitlines()
        if len(parts := line.strip().split(None, 2)) == 3
    }


def descendants(pid: int, owned: dict[int, str]) -> None:
    current = process_table()
    parents = {pid} | {p for p, start in owned.items() if current.get(p, (0, ""))[1] == start}
    for _ in range(len(current)):
        found = {p for p, (parent, _) in current.items() if parent in parents}
        if found <= parents:
            break
        parents |= found
    for p in parents:
        if p in current:
            owned[p] = current[p][1]


def run_process(
    argv: list[str],
    cwd: Path,
    seconds: float,
    output: Path,
    *,
    prompt: str = "",
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Preserve timeout output; reap owned descendants, including nested new sessions."""
    if len(prompt.encode()) > 4096:
        raise ValueError("Compact benchmark briefs must fit in 4096 bytes")
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    result: dict[str, Any] = {"status": "failed", "exit_code": None, "error": None}
    owned: dict[int, str] = {}
    process = None
    try:
        with (output / "stdout.log").open("wb") as out, (output / "stderr.log").open("wb") as err:
            process = subprocess.Popen(
                argv,
                cwd=cwd,
                stdin=subprocess.PIPE,
                stdout=out,
                stderr=err,
                env=env,
                start_new_session=True,
            )
            assert process.stdin is not None
            try:
                process.stdin.write(prompt.encode())
                process.stdin.close()
            except BrokenPipeError:
                pass
            while True:
                descendants(process.pid, owned)
                code = process.poll()
                if code is not None:
                    result.update(status="completed" if code == 0 else "failed", exit_code=code)
                    break
                if time.monotonic() - started >= seconds:
                    result["status"] = "timeout"
                    break
                if out.tell() + err.tell() > 32 * 1024 * 1024:
                    result["error"] = "Output exceeds 32 MiB safety limit"
                    break
                time.sleep(min(0.1, max(0, seconds - (time.monotonic() - started))))
    except (OSError, subprocess.SubprocessError) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        execution_elapsed = time.monotonic() - started
        if process is not None:
            # Track before signalling. Match start identity before targeting an individual PID.
            try:
                descendants(process.pid, owned)
                for sig in (signal.SIGTERM, signal.SIGKILL):
                    current = process_table()
                    for pid, start in owned.items():
                        if current.get(pid, (0, ""))[1] == start:
                            try:
                                os.kill(pid, sig)
                            except ProcessLookupError:
                                pass
                            except PermissionError as exc:
                                result.setdefault("cleanup_signal_warnings", []).append(str(exc))
                    # Do not signal a reaped leader's stale process-group ID: on macOS
                    # this can raise EPERM and hide the original timeout.
                    if process.poll() is None:
                        try:
                            os.killpg(process.pid, sig)
                        except ProcessLookupError:
                            pass
                        except PermissionError as exc:
                            result.setdefault("cleanup_signal_warnings", []).append(str(exc))
                    if sig == signal.SIGTERM:
                        until = time.monotonic() + 2
                        while time.monotonic() < until:
                            process.poll()
                            current = process_table()
                            if not any(current.get(p, (0, ""))[1] == s for p, s in owned.items()):
                                break
                            time.sleep(0.05)
                process.wait(timeout=2)
                result["exit_code"] = process.returncode
            except (OSError, subprocess.SubprocessError) as exc:
                result["cleanup_error"] = str(exc)
                result["status"] = "failed"
        result["elapsed_seconds"] = round(execution_elapsed, 3)
        result["cleanup_seconds"] = round(time.monotonic() - started - execution_elapsed, 3)
    write_json(output / "process.json", result)
    return result


def sandbox(work: Path, runtime: Path, denied_reads: list[Path], *, writable: bool = True) -> str:
    def quote(path: Path) -> str:
        return json.dumps(str(path.resolve()))

    lines = [
        "(version 1)",
        "(allow default)",
        "(deny file-write*)",
        f"(allow file-write* (subpath {quote(runtime)}))",
        '(allow file-write* (literal "/dev/null") (literal "/dev/tty"))',
    ]
    if writable:
        lines.append(f"(allow file-write* (subpath {quote(work)}))")
    lines += [f"(deny file-read* (subpath {quote(path)}))" for path in denied_reads]
    return "\n".join(lines)


def git(repo: Path, *args: str) -> str:
    return Runner(repo / ".never-cancel", 30).run(["git", *args], repo)[1]


def prepare(source: Path, destination: Path) -> tuple[dict[str, str], str]:
    if not any(
        destination.resolve().is_relative_to(root.resolve())
        for root in (Path("/tmp"), Path(tempfile.gettempdir()))
    ):
        raise ValueError("Benchmark output must be in /tmp or the OS temporary directory")
    if not source.is_dir() or destination.exists():
        raise ValueError("Source must exist and output must be a new directory")
    baseline = tree(source)
    if any(value.startswith("SYMLINK:") for value in baseline.values()):
        raise ValueError("Symlinks are not supported in starting fixtures")
    destination.mkdir(parents=True)
    seed = destination / "seed"
    seed.mkdir()
    for name in baseline:
        target = seed / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    git(seed, "init", "-q")
    git(seed, "add", ".")
    git(
        seed,
        "-c",
        "user.name=Benchmark Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "Frozen benchmark starting state",
    )
    head = git(seed, "rev-parse", "HEAD").strip()
    for contender in CONTENDERS:
        directory = destination / contender
        directory.mkdir()
        git(destination, "clone", "--quiet", "--no-hardlinks", str(seed), str(directory / "repo"))
        if tree(directory / "repo") != baseline:
            raise ValueError("Starting states differ")
    return baseline, head


def commands(contender: str, plugin: Path, claude_model: str, codex_model: str) -> list[str]:
    if contender == "codex":
        return [
            "codex",
            "exec",
            "--ignore-user-config",
            "--ephemeral",
            "--json",
            "-c",
            'approval_policy="never"',
            "-c",
            "project_doc_max_bytes=0",
            "--disable",
            "memories",
            "--disable",
            "plugins",
            "--enable",
            "skip_host_skill_discovery",
            "--model",
            codex_model,
            "-",
        ]
    command = [
        "claude",
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--no-session-persistence",
        "--permission-mode",
        "auto",
        "--permission-prompts",
        "none",
        "--restricted",
        "--tools",
        "Read,Glob,Grep,Write,Edit,Bash,Skill",
        "--setting-sources",
        "",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--model",
        claude_model,
    ]
    return command + (["--safe-mode"] if contender == "claude" else ["--plugin-dir", str(plugin)])


def codex_permissions(runtime: Path, denied: list[Path]) -> list[str]:
    """Use Codex's native sandbox once; macOS cannot nest sandbox_apply calls."""
    args = [
        "-c",
        'default_permissions="benchmark"',
        "-c",
        'permissions.benchmark.extends=":workspace"',
    ]
    rules = {
        ":root": "read",
        ":slash_tmp": "read",
        ":tmpdir": "read",
        str(runtime.resolve()): "write",
        **{str(path.resolve()): "deny" for path in denied},
    }
    table = ", ".join(f"{json.dumps(path)}={json.dumps(access)}" for path, access in rules.items())
    args += ["-c", "permissions.benchmark.filesystem={" + table + "}"]
    return args


def observations(log: Path) -> dict[str, Any]:
    requests: set[str] = set()
    models: set[str] = set()
    failures: list[Any] = []
    turns = 0
    for line in log.read_text(errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("request_id"):
            requests.add(event["request_id"])
        message = event.get("message", {})
        if isinstance(message, dict) and message.get("model"):
            models.add(message["model"])
        if event.get("type") == "turn.completed":
            turns += 1
        if event.get("permission_denials"):
            failures.extend(event["permission_denials"])
        if event.get("type") in {"error", "turn.failed"}:
            failures.append(event)
    return {
        "model_calls": None,
        "request_ids_observed": len(requests) or None,
        "codex_turns_completed": turns or None,
        "resolved_models_observed": sorted(models),
        "permission_or_provider_failures": failures,
    }


def verify(repo: Path, grader: Path, output: Path, denied: list[Path]) -> dict[str, Any]:
    runtime = output / "runtime"
    runtime.mkdir(parents=True)
    profile = sandbox(repo, runtime, denied, writable=False)
    env = {**os.environ, "TMPDIR": str(runtime), "PYTHONDONTWRITEBYTECODE": "1"}
    before = tree(repo)
    process = run_process(
        ["/usr/bin/sandbox-exec", "-p", profile, sys.executable, "-I", str(grader), str(repo)],
        repo,
        45,
        output,
        env=env,
    )
    try:
        result = json.loads((output / "stdout.log").read_text())
        assert isinstance(result["checks"], list)
        assert process["status"] == "completed"
        assert tree(repo) == before
    except (ValueError, KeyError, AssertionError) as exc:
        result = {
            "checks": [],
            "application_runs": False,
            "verification_error": str(exc),
            "verification_process": process,
        }
    return cast(dict[str, Any], result)


def benchmark(
    challenge: Path,
    destination: Path,
    seconds: float,
    *,
    claude_model: str = "sonnet",
    codex_model: str = "gpt-5.6-sol",
    overrides: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").exists():
        raise ValueError("This first harness requires macOS sandbox-exec; no unisolated fallback")
    source = challenge / "repo"
    task = (challenge / "task.md").read_text()
    baseline, head = prepare(source, destination)
    # Same task/budget bytes; only C's invocation prefix differs.
    brief = f"{task.rstrip()}\n\nHard elapsed-time budget: {seconds / 60:g} minutes.\n"
    (destination / "brief.txt").write_text(brief)
    grader = destination / "verify.py"
    shutil.copyfile(challenge / "verify.py", grader)
    report: dict[str, Any] = {
        "challenge": challenge.name,
        "budget_seconds": seconds,
        "starting_commit": head,
        "starting_files": baseline,
        "brief_sha256": hashlib.sha256(brief.encode()).hexdigest(),
        "grader_sha256": hashlib.sha256(grader.read_bytes()).hexdigest(),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "order": list(CONTENDERS),
        "results": {},
        "winner": None,
        "runtime_versions": {
            name: subprocess.run(
                [name, "--version"], capture_output=True, text=True, timeout=10
            ).stdout.strip()
            if shutil.which(name)
            else "UNAVAILABLE"
            for name in ("claude", "codex")
        },
        "limitations": [
            "Single fixed-order run, not a causal or statistical comparison",
            "Time to first working implementation is not observed; final checks only",
            "Filesystem isolation is not a hostile-agent network security boundary",
        ],
    }
    plugin = ROOT.parent / "claude/cockpit"
    for contender in CONTENDERS:
        directory = destination / contender
        repo = directory / "repo"
        runtime = directory / "runtime"
        runtime.mkdir(mode=0o700)
        # Use Codex's supported per-process storage setting, never its global state DB.
        # Auth is referenced read-only, not printed/copied; atomic refresh stays local.
        codex_storage = runtime / "codex"
        codex_storage.mkdir(mode=0o700)
        existing_auth = (
            Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "auth.json"
        )
        if existing_auth.is_file():
            (codex_storage / "auth.json").symlink_to(existing_auth.resolve())
        denied = [destination / other for other in CONTENDERS if other != contender]
        denied += [
            ROOT,
            ROOT.parent / "tests",
            ROOT.parent / ".git",
            destination / "seed",
            grader,
            destination / "report.json",
            destination / "REPORT.md",
            Path.home() / ".claude/skills",
        ]
        profile = sandbox(repo, runtime, denied)
        (directory / "sandbox.sb").write_text(profile)
        command = (overrides or {}).get(contender) or commands(
            contender, plugin, claude_model, codex_model
        )
        launch = ["/usr/bin/sandbox-exec", "-p", profile, *command]
        if contender == "codex" and contender not in (overrides or {}):
            command = command[:-1] + codex_permissions(runtime, denied) + command[-1:]
            launch = command
        prompt = (
            "/institutional-cockpit:hackathon " if contender == "institutional" else ""
        ) + brief
        env = {
            **os.environ,
            "TMPDIR": str(runtime),
            "PYTHONDONTWRITEBYTECODE": "1",
            "CLAUDE_CODE_TMPDIR": str(runtime),
            "XDG_CACHE_HOME": str(runtime / "cache"),
            "CODEX_HOME": str(codex_storage),
        }
        env.pop("CLAUDECODE", None)
        print(f"{contender}: starting ({seconds:g}s)", flush=True)
        result = run_process(
            launch,
            repo,
            seconds,
            directory,
            prompt=prompt,
            env=env,
        )
        result.update(observations(directory / "stdout.log"))
        result["command"] = command
        final = tree(repo)
        result["changed_files"] = sorted(
            p for p in baseline.keys() | final.keys() if baseline.get(p) != final.get(p)
        )
        # Include untracked files without modifying the candidate's Git index.
        # .git/runtime metadata is not a product diff: store a source-only comparison.
        parts: list[str] = []
        for name in result["changed_files"]:
            left = (
                (destination / "seed" / name).read_text(errors="replace").splitlines(True)
                if name in baseline
                else []
            )
            right = (
                [final[name] + "\n"]
                if final.get(name, "").startswith("SYMLINK:")
                else (repo / name).read_text(errors="replace").splitlines(True)
                if name in final
                else []
            )
            parts.extend(
                difflib.unified_diff(left, right, fromfile=f"a/{name}", tofile=f"b/{name}")
            )
        patch = "".join(parts).encode()
        (directory / "final.diff").write_bytes(patch)
        result["diff_bytes"] = len(patch)
        result["diff_added_lines"] = sum(
            line.startswith("+") and not line.startswith("+++") for line in parts
        )
        result["diff_removed_lines"] = sum(
            line.startswith("-") and not line.startswith("---") for line in parts
        )
        verified: dict[str, Any] = (
            {
                "checks": [],
                "application_runs": False,
                "verification_error": "Candidate contains symlinks; not executed",
            }
            if any(value.startswith("SYMLINK:") for value in final.values())
            else verify(
                repo,
                grader,
                directory / "verification",
                [ROOT, *[destination / other for other in CONTENDERS if other != contender]],
            )
        )
        result["verification"] = verified
        checks = verified["checks"]
        protected_tests = [name for name in baseline if name.startswith("tests/")]
        result["original_tests_preserved"] = all(
            final.get(name) == baseline[name] for name in protected_tests
        )
        result["acceptance"] = {
            "passed": sum(c["passed"] for c in checks if c["suite"] == "acceptance"),
            "total": sum(c["suite"] == "acceptance" for c in checks),
        }
        result["heldout"] = {
            "passed": sum(c["passed"] for c in checks if c["suite"] == "heldout"),
            "total": sum(c["suite"] == "heldout" for c in checks),
        }
        result["outcome"] = (
            "delivered"
            if checks
            and all(c["passed"] for c in checks)
            and result["status"] == "completed"
            and result["original_tests_preserved"]
            else "partial"
            if result["changed_files"] and verified["application_runs"]
            else "failed"
        )
        result["time_to_first_working_seconds"] = None
        result["human_interventions"] = 0
        result["requested_model"] = codex_model if contender == "codex" else claude_model
        result["unresolved_defects"] = [c for c in checks if not c["passed"]]
        if not result["original_tests_preserved"]:
            result["unresolved_defects"].append({"error": "Existing tests modified or removed"})
        report["results"][contender] = result
        write_json(destination / "report.json", report)
        print(f"{contender}: {result['outcome']} ({result['status']})", flush=True)
    rows = [
        "# A/B/C benchmark",
        "",
        "No automatic winner. Same starting commit, brief and budget.",
        "",
        "| Contender | Outcome | Process | Seconds | Acceptance | Held-out | Diff bytes |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for name, result in report["results"].items():
        a, h = result["acceptance"], result["heldout"]
        rows.append(
            f"| {name} | {result['outcome']} | {result['status']} | {result['elapsed_seconds']} | {a['passed']}/{a['total']} | {h['passed']}/{h['total']} | {result['diff_bytes']} |"
        )
    rows += [
        "",
        "See report.json for exact failed checks, provider/process errors and observable call counts.",
        "Time to first working version and exact model-call totals: UNKNOWN. Human interventions: 0.",
        "Budget covers agent execution; external frozen verification runs afterward with its own 45s cap.",
        "Runtime logs remain local and may contain account metadata. Do not publish them blindly.",
    ]
    (destination / "REPORT.md").write_text("\n".join(rows) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("challenge", nargs="?", default="queueboard")
    parser.add_argument("--budget", default="5m", help="Equal hard agent budget, e.g. 2m or 90s")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--claude-model", default="sonnet")
    parser.add_argument("--codex-model", default="gpt-5.6-sol")
    args = parser.parse_args()
    try:
        seconds = float(args.budget[:-1]) * {"s": 1, "m": 60}[args.budget[-1]]
    except (ValueError, KeyError, IndexError):
        parser.error("budget must look like 90s or 5m")
    if not 0 < seconds <= 3600:
        parser.error("budget must be positive and at most 60m per contender")
    challenge = ROOT / args.challenge
    if not challenge.resolve().is_relative_to(ROOT) or not (challenge / "verify.py").is_file():
        parser.error("Use an included challenge directory")
    destination = args.output or Path(tempfile.mkdtemp(prefix="institutional-benchmark-")) / "run"
    benchmark(
        challenge,
        destination.resolve(),
        seconds,
        claude_model=args.claude_model,
        codex_model=args.codex_model,
    )
    print(destination / "REPORT.md")


if __name__ == "__main__":
    main()
