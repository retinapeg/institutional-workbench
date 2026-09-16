---
name: hackathon
description: Claude builds, tests and delivers against a deadline, with optional routed expert advice.
argument-hint: "<goal> [deadline] | status"
disable-model-invocation: true
---

User request: $ARGUMENTS

Claude Code is the engineer. Inspect, plan, create, edit, delete, rename, simplify, test, commit,
deploy when authorised, recover and deliver with native tools. External models are optional,
text-only advisers. They never own the repository, make edits or certify success.

Controller prefix (existing local environment; `CTRL` below is shorthand only):
`/Users/leonardaarons-ditson/Code/institutional-workbench-routing/.venv/bin/python -m institutional_workbench.cockpit`

The controller observes time, checks, evidence, steering, adviser calls and known-good checkpoints.
It does not grant repository permission or manage Claude's implementation.

## Run

1. Empty `/hackathon`: ask for a goal and deadline. For `/hackathon status`, show the current
   run using `CTRL status --human`. Otherwise start in the current clean, committed Git repository.
   Convert the user's deadline to remaining minutes; default to 120 minutes if omitted. Write the
   exact goal to a temporary file and run:
   `CTRL start --repo "<repository root>" --task-file "<task file>" --minutes <minutes>`
   Save the returned `run` path. Never replace it to escape an error.

2. Inspect repository instructions, source and real run/test commands. Define the smallest useful
   deliverable and executable acceptance. Prepare a compact plan in the run directory:
   ```json
   {"deliverable":"working requested result",
    "acceptance":["specific observable outcome"],
    "checks":[
      {"name":"tests","argv":["python3","-m","unittest","discover","-s","tests"],"kind":"test","timeout":60},
      {"name":"demo","argv":["python3","demo_check.py"],"kind":"demo","timeout":60}
    ],
    "source_paths":[],"probes":[],"visual_required":false,
    "core_demo_checklist":["tests","demo"],"ship_required":[]}
   ```
   Use commands appropriate to the actual repository. Never use `true` or `echo` as acceptance.
   Only set visual/shipping requirements when the user explicitly needs them. Run
   `CTRL prepare --run "<run>" --file "<plan>"`. A plan/JSON error is correctable: fix it and
   resubmit in this SAME run.

3. Build immediately with native Read/Edit/Write/Bash. Claude has normal repository authority:
   create, edit, delete, rename or replace files; edit `.gitignore`, dependencies, configuration
   and tests; remove weak features; simplify aggressively; and make ordinary Git commits.
   Do not touch another writer's work or reset unrelated user changes. Never push, publish, spend
   money or change accounts without user authority.

4. Run the real project checks yourself while debugging. At a stable boundary run
   `CTRL verify --run "<run>"`. Passing checks save a known-good checkpoint. A normal commit is
   accepted and becomes the checkpoint when clean. On failure make one focused repair and verify
   again. Git is recovery: preserve a known-good commit before a substantial destructive change.

5. Consult advisers only for a consequential question worth their latency:
   `CTRL advice --run "<run>" --name "<concrete question>"`
   Use `--challenge` only when a real disagreement changes the build. Advice is optional and
   bounded; unavailable/malformed advice is a warning, never loss of working code. Claude verifies
   claims with source, tests or measurements before acting.

6. For `STEER: <instruction>`, finish the current atomic operation, write the instruction to a
   file, run `CTRL steer --run "<run>" --task-file "<file>"`, and continue in the SAME run with
   the new priority. Status is `CTRL status --run "<run>" --human`.

7. Finish with `CTRL verify --run "<run>" --deliver`. Report the actual DELIVERED, PARTIAL,
   BLOCKED or DEADLINE result; exact checks; run command; checkpoint; adviser coverage; and honest
   limitations. Missing optional screenshots, browser tooling, video, deployment or cosmetic
   assets are warnings unless the user made them acceptance criteria. Stop when executable
   acceptance passes. No final speculative improvement.

Controller metadata under `.institutional-workbench/` is its own state, not user work. A previous
run there does not require another worktree. If a helper command is refused, correct the input and
continue when state remains RUNNING. Hard BLOCKED is for cancellation/deadline, genuine conflicting
user work, or required executable acceptance still failing after the repair—not ordinary Git use.
