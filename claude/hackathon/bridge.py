"""Foreground process owner only; all orchestration stays in Workbench."""

import argparse
import os
import signal
import subprocess
import sys
from types import FrameType


def run_child(argv: list[str]) -> int:
    def cancel(signum: int, frame: FrameType | None) -> None:
        raise KeyboardInterrupt

    old = {sig: signal.signal(sig, cancel) for sig in (signal.SIGINT, signal.SIGTERM)}
    child: subprocess.Popen[bytes] | None = None
    try:
        child = subprocess.Popen(argv, start_new_session=True)  # Stream inherited stdout/stderr.
        code = child.wait()  # No background return, task polling or detached continuation.
    except KeyboardInterrupt:
        code = 130
    finally:
        for sig, handler in old.items():
            signal.signal(sig, handler)
        if child is not None and child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
    print(f"BRIDGE_EXIT={code}", flush=True)  # Printed only after child exit/reaping.
    return code


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--task-file", required=True)
    parser.add_argument("--hard-deadline", type=float)
    args = parser.parse_args()
    sys.exit(
        run_child(
            [
                sys.executable,
                "-m",
                "institutional_workbench.cli",
                "hackathon",
                "--repo",
                args.repo,
                "--task-file",
                args.task_file,
                "--explain-routing",
            ]
            + (
                ["--hard-deadline", str(args.hard_deadline)]
                if args.hard_deadline is not None
                else []
            )
        )
    )
