# Queueboard starter

A dependency-free support-queue briefing prototype. `board.py` is an intentionally incomplete
stub: it handles the command interface and empty input only. Implement the task supplied by the
benchmark; architecture and HTML presentation are yours to choose.

Run existing checks: `python3 -m unittest discover -s tests -v`

Demo: `python3 board.py sample.json --as-of 2026-01-02T12:00:00Z --format json`

The two basic tests are intentionally insufficient: passing them does not establish the task's
semantics. Preserve them and add useful coverage. Do not read other benchmark contestants or graders.
