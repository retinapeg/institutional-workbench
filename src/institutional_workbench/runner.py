"""Small POSIX subprocess runner shared by models, git and acceptance commands."""

import os
import selectors
import signal
import subprocess
import time
from pathlib import Path


class Blocked(RuntimeError):
    pass


class Deadline(Blocked):
    pass


class Runner:
    def __init__(self, cancel_file: Path, seconds: float = 900, *, hard_deadline: bool = True):
        self.cancel_file = cancel_file
        self.advisory_deadline = time.monotonic() + seconds
        self.deadline = self.advisory_deadline if hard_deadline else float("inf")

    def check(self) -> None:
        if self.cancel_file.exists():
            raise Blocked("Cancelled by user; isolated work is preserved.")
        if time.monotonic() >= self.deadline:
            raise Deadline("Hard deadline exhausted; isolated work is preserved.")

    def run(
        self,
        argv: list[str],
        cwd: Path,
        text: str = "",
        timeout: float = 90,
        *,
        require_success: bool = True,
    ) -> tuple[int, str, str]:
        self.check()
        deadline = min(self.deadline, time.monotonic() + timeout)
        env = os.environ.copy()
        if Path(argv[0]).name == "claude":
            env.pop("CLAUDECODE", None)  # Allow the isolated, tools-disabled provider child.
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            env=env,
        )
        assert process.stdin and process.stdout and process.stderr
        output = {"out": bytearray(), "err": bytearray()}
        pending = memoryview(text.encode())
        try:
            with selectors.DefaultSelector() as selector:
                for pipe, label in ((process.stdout, "out"), (process.stderr, "err")):
                    os.set_blocking(pipe.fileno(), False)
                    selector.register(pipe, selectors.EVENT_READ, label)
                os.set_blocking(process.stdin.fileno(), False)
                if pending:
                    selector.register(process.stdin, selectors.EVENT_WRITE, "in")
                else:
                    process.stdin.close()
                while selector.get_map() or process.poll() is None:
                    self.check()
                    if time.monotonic() >= deadline:
                        raise Blocked(f"Command timed out after {timeout:g}s: {argv[0]}")
                    for key, _ in selector.select(0.05):
                        if key.data == "in":
                            try:
                                pending = pending[os.write(key.fd, pending[:8192]) :]
                            except BrokenPipeError:
                                pending = memoryview(b"")
                            if not pending:
                                selector.unregister(key.fileobj)
                                process.stdin.close()
                        else:
                            chunk = os.read(key.fd, 8192)
                            if not chunk:
                                selector.unregister(key.fileobj)
                            else:
                                output[key.data].extend(chunk)
                                if len(output[key.data]) > 1_048_576:
                                    raise Blocked("Command exceeded the 1 MiB output limit")
            code = process.returncode
            assert code is not None
            out, err = (output[key].decode(errors="replace") for key in ("out", "err"))
            if code and require_success:
                raise Blocked(f"{argv[0]} exited {code}: {err[-1500:]}")
            return code, out, err
        finally:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                until = time.monotonic() + 2
                while time.monotonic() < until:
                    process.poll()
                    try:
                        os.killpg(process.pid, 0)
                    except ProcessLookupError:
                        break
                    except PermissionError:
                        # macOS may deny a group probe while the leader is exiting.
                        if process.poll() is not None:
                            break
                    time.sleep(0.02)
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            except ProcessLookupError:
                pass
            process.wait()
            for pipe in (process.stdin, process.stdout, process.stderr):
                pipe.close()
