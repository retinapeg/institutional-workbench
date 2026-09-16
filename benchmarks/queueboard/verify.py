"""Frozen external acceptance/held-out checks. Never copied into contender repositories."""

import argparse
import html
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def event(number, ticket="A", hour="10:00", action="opened", **fields):
    result = {
        "event_id": str(number),
        "ticket_id": ticket,
        "timestamp": f"2026-01-02T{hour}:00Z",
        "action": action,
    }
    if action == "opened":
        result.update(title="Question", priority="normal")
    result.update(fields)
    return result


def cases():
    return [
        ("empty", "acceptance", [], [], None),
        (
            "boundary-and-order",
            "acceptance",
            [event(1), event(2, "B", "11:30", priority="urgent")],
            [("B", 30, True), ("A", 120, True)],
            None,
        ),
        (
            "resolved-absent",
            "acceptance",
            [event(1), event(2, hour="11:00", action="resolved")],
            [],
            None,
        ),
        (
            "reopened-clock",
            "heldout",
            [
                event(1, hour="08:00", priority="urgent"),
                event(2, hour="10:00", action="resolved"),
                event(3, hour="11:50", action="reopened"),
            ],
            [("A", 10, False)],
            None,
        ),
        (
            "future-priority-ignored",
            "heldout",
            [event(1, hour="11:00"), event(2, hour="12:01", action="priority", priority="urgent")],
            [("A", 60, False)],
            None,
        ),
        (
            "priority-keeps-age",
            "heldout",
            [event(1, hour="11:00"), event(2, hour="11:59", action="priority", priority="urgent")],
            [("A", 60, True)],
            None,
        ),
        (
            "unordered-offset-duplicate",
            "heldout",
            [
                event(2, action="priority", hour="11:59", priority="urgent"),
                event(1, timestamp="2026-01-02T12:00:00+01:00"),
                event(1, timestamp="2026-01-02T12:00:00+01:00"),
            ],
            [("A", 60, True)],
            None,
        ),
        (
            "conflicting-duplicate",
            "heldout",
            [event(1), event(1, priority="urgent")],
            None,
            "error",
        ),
        ("unknown-transition", "heldout", [event(1, action="reopened")], None, "error"),
        ("naive-time", "heldout", [event(1, timestamp="2026-01-02T10:00:00")], None, "error"),
        ("html-escaping", "heldout", [event(1, title='<script>alert("x")</script>')], None, "html"),
    ]


def verify(repo, scratch):
    checks = []
    for name, suite, events, expected, special in cases():
        path = scratch / f"{name}.json"
        path.write_text(json.dumps(events))
        command = [
            sys.executable,
            str(repo / "board.py"),
            str(path),
            "--as-of",
            "2026-01-02T12:00:00Z",
            "--format",
            "html" if special == "html" else "json",
        ]
        try:
            result = subprocess.run(command, cwd=repo, capture_output=True, text=True, timeout=3)
            if special == "error":
                assert result.returncode != 0 and result.stderr.strip(), "invalid input accepted"
                assert "Traceback" not in result.stderr, "traceback instead of useful error"
            else:
                assert result.returncode == 0, result.stderr[-1000:]
                if special == "html":
                    assert html.escape(events[0]["title"]) in result.stdout, "title not escaped"
                    assert "<script>" not in result.stdout, "unsafe title markup"
                    assert (
                        "active" in result.stdout.lower() and "breached" in result.stdout.lower()
                    ), "missing visible totals"
                else:
                    answer = json.loads(result.stdout)
                    rows = answer["tickets"]
                    assert [
                        (r["ticket_id"], r["age_minutes"], r["breached"]) for r in rows
                    ] == expected, f"wrong snapshot: {rows}"
                    assert answer["summary"] == {
                        "active_count": len(expected),
                        "breached_count": sum(r[2] for r in expected),
                    }, "wrong totals"
                    assert all(
                        isinstance(r["title"], str) and r["priority"] in {"normal", "urgent"}
                        for r in rows
                    ), "missing ticket details"
            checks.append({"name": name, "suite": suite, "passed": True, "error": None})
        except (
            AssertionError,
            ValueError,
            KeyError,
            TypeError,
            OSError,
            subprocess.TimeoutExpired,
        ) as exc:
            checks.append({"name": name, "suite": suite, "passed": False, "error": str(exc)[:1500]})
    return {
        "checks": checks,
        "application_runs": any(c["name"] == "empty" and c["passed"] for c in checks),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        print(json.dumps(verify(args.repo.resolve(), Path(directory))))
