import subprocess
import sys
import time
import unittest
from pathlib import Path

BRIDGE = Path(__file__).parents[1] / "claude/hackathon/bridge.py"


class BridgeTests(unittest.TestCase):
    def launch(self, child):
        launcher = (
            f"import runpy,sys; run=runpy.run_path({str(BRIDGE)!r})['run_child']; "
            f"sys.exit(run([sys.executable, '-u', '-c', {child!r}]))"
        )
        return subprocess.Popen(
            [sys.executable, "-u", "-c", launcher],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

    def test_waits_streams_output_and_returns_child_status(self):
        for exit_code in (0, 7):
            with self.subTest(exit_code=exit_code):
                start = time.monotonic()
                with self.launch(
                    "import time,sys; print('START',flush=True); time.sleep(.25); "
                    f"print('PROGRESS'); print('FINAL'); sys.exit({exit_code})"
                ) as bridge:
                    self.assertEqual(bridge.stdout.readline().strip(), "START")
                    self.assertIsNone(bridge.poll())
                    output = bridge.communicate(timeout=5)[0]
                    self.assertGreaterEqual(time.monotonic() - start, 0.25)
                    self.assertEqual(bridge.returncode, exit_code)
                    self.assertEqual(
                        output.splitlines(), ["PROGRESS", "FINAL", f"BRIDGE_EXIT={exit_code}"]
                    )

    def test_user_cancellation_terminates_and_reaps_child(self):
        with self.launch(
            "import signal,time,sys; "
            "signal.signal(signal.SIGTERM, lambda *_: (print('CANCELLED',flush=True),sys.exit(0))); "
            "print('START',flush=True); time.sleep(30)"
        ) as bridge:
            self.assertEqual(bridge.stdout.readline().strip(), "START")
            bridge.terminate()
            output = bridge.communicate(timeout=8)[0]
            self.assertEqual(bridge.returncode, 130)
            self.assertEqual(output.splitlines(), ["CANCELLED", "BRIDGE_EXIT=130"])
