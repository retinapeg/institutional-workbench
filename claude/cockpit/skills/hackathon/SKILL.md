---
name: hackathon
description: Claude builds, tests and ships a demo against a deadline, with optional specialist advice.
argument-hint: "<goal> [deadline] | status"
disable-model-invocation: true
---

User request: $ARGUMENTS

You are the repository owner, inspector, sole builder, tester and deployment operator. Use your
native tools. Models ADVISE; Claude BUILDS. Do not invoke the legacy Workbench bridge/build engine,
spawn another builder, or stage a mandatory roundtable. Normal permissions and repository rules
apply. Never touch another writer's worktree, reset user work, install dependencies or change
accounts without approval. Start from a clean committed repository or an agreed isolated worktree.

Four responsibilities, not four agents:

- **Director:** deadline, observable definition of done, priorities, feature cuts, next useful action.
- **Builder:** native edits, implementation and debugging. Get the core interaction running early.
- **Breaker:** execute tests and exercise the current demo; record only concrete failures with
  reproduction/evidence. A hypothetical architecture concern is not a defect.
- **Shipper:** early deployment where authorised, verified URL, first-run instructions, screenshots,
  submission copy, 45–90 second pitch, limitations and an honest fallback demo.

Controller prefix (already installed locally; `CTRL` below is shorthand, not an alias to install):
`/Users/leonardaarons-ditson/Code/institutional-workbench-routing/.venv/bin/python -m institutional_workbench.cockpit`
Run controller actions in the foreground, inspect the result and keep the returned `run` path.
Every action after `start` takes `--run "<run>"`. It is an evidence/deadline helper, not a builder.

## Start and build

1. Empty `/hackathon`: ask for the goal and deadline; do not start a build. `status` or
   `/hackathon status`: show the current run with `CTRL status --human`, do not create a new run.
   Claude's built-in `/status` belongs to Claude itself; do not replace it.
2. For a goal, interpret the supplied deadline into remaining minutes (hours/dates are fine; check
   the local time). If omitted, state the default **120 minutes**. Write the user's full goal to a
   temporary task file, then immediately run:
   `CTRL start --repo "<repository root>" --task-file "<task file>" --minutes <remaining minutes>`
   The clock starts before inspection. Never silently extend it or create a replacement run.
3. Inspect repository instructions, relevant files, actual test/demo commands and cheap facts.
   Define the judge's visible experience and smallest working path. Write a compact plan in the
   run directory, adapting this example to the real project:
   ```json
   {"deliverable":"working interactive demo", "acceptance":["core behaviour and first run work"],
    "owned_paths":["app","tests/new_test.py","README.md","submission.md","pitch.md","fallback.md","screenshots"],
    "checks":[{"name":"tests","argv":["python3","-m","unittest","discover","-s","tests"],"kind":"test","timeout":60},
              {"name":"demo","argv":["python3","demo_check.py"],"kind":"demo","timeout":60}],
    "source_paths":[], "visual_required":true,
    "core_demo_checklist":["tests","demo"],
    "ship_required":["readme","pitch","submission","fallback","screenshots"]}
   ```
   Match core checklist labels to check names for executable verification; unmatched visual/user
   judgements remain UNVERIFIED. Own only needed files/directories, including shipping assets.
   Existing tests are protected.
   Checks must exercise the task, never `echo`/`true`. Write argv yourself from authorised project
   commands; never execute an adviser's shell string. `CTRL prepare --file "<plan.json>"` freezes
   checks and records baseline failures. It moves directly to BUILD: no advice/freeze prerequisite.
4. Start editing now. Before each atomic work group, `CTRL status --human`, then record an action:
   ```json
   {"kind":"core","risky":false,"current_action":"implement main interaction",
    "next_action":"run frozen tests and launch demo"}
   ```
   `CTRL begin --file "<action.json>"` authorises the next boundary. Kinds: `feature`, `core`, `fix`,
   `polish`, `ship`, `verify`. Mark risk honestly. Do not use `core` to smuggle in optional features.
   Use native Edit/Write/Bash to implement, with command timeouts within the status allowance.

## Small, artifact-first iterations

Build → test/exercise demo → preserve working checkpoint → identify the most important visible
weakness → improve → test/redeploy. No ceremony between steps. Keep scope aimed at the user/rubric.

- `CTRL verify` runs frozen host-side checks, records concrete Breaker failures and preserves a
  passing last-working Git checkpoint without moving the branch or altering the index. It keeps
  the run active. If it returns REPAIR, make **one** focused repair and retest; do not begin another
  iteration to reset a failing repair budget. Never weaken acceptance to obtain a pass.
- Before risky changes, obtain a passing checkpoint. Retain `last_working_commit`; do not erase or
  overwrite it when later work fails. Recovery must preserve current useful changes, not reset them.
  To inspect/recover a checkpoint, use a separate Git worktree at that SHA; never reset this checkout.
- Zero advisers is normal. Only for a consequential concrete question use
  `CTRL advice --name "<question this specialist uniquely resolves>"` (at most two advisers in an
  iteration). Existing role/capability routing handles selection; do not demand diversity. Only if
  an actual disagreement changes the next build action, add `--challenge` for one short challenge.
  Advice is optional and time-bounded. Unavailable/malformed advice cannot erase a working build.
  Use native repository inspection/tests first. Never spend 10–15 minutes debating an ordinary choice.
- `CTRL freeze --file <decision.json>` remains optional for evidence-backed consequential choices;
  it is not a required gate. Claude decides; advisers do not own code or certify success.
- Every 30–60 minutes produce real evidence: a change, passing test, measured interaction, screenshot,
  deployment or shipping asset. At 30 minutes without evidence, stop consultation and execute the
  smallest useful build/test/ship action. A progress paragraph is not an artifact.

## Steering and deadline

At the next safe boundary, handle `STEER: <instruction>` without restarting: Write the instruction
verbatim to a file, `CTRL steer --task-file "<file>"`, inspect status, and update the next action.
If the request is already listed in state, do not record it again: use `begin` to apply its priority.
Preserve working progress. `status` shows deadline, demo, core/ship checklists, risks and next action.
`deliver` means freeze improvements, verify and hand back the current result; it is not permission to
declare missing work complete. User cancellation uses `CTRL cancel`; signal only owned processes.

Obey the controller's deadline phases at every operation boundary:

- Before T−90: build/improve/test/deploy.
- T−90: freeze optional features; only missing core-demo work may still be added.
- T−60: fixes, deployment verification, UX clarity and presentation/submission assets.
- T−30: **no risky changes**; final tests, fallback, screenshots/video, README, submission and pitch.

For short runs the helper scales those thresholds to 25%, 16.7% and 8.3% of total time. At expiry,
stop new work and report the preserved state. This is boundary enforcement, not a security sandbox:
it cannot interrupt an already-running native Edit/Read. Set native command timeouts accordingly.

## Ship and finish

Deploy early when practical using an authorised existing destination. Do not create accounts,
purchase anything, expose secrets or invent a public target. Ask if publication/credentials need new
authority. If public deployment is inappropriate/unavailable, provide runnable configuration and
label the public URL UNVERIFIED / NOT APPLICABLE with the concrete reason, never a claimed deploy.

Create useful README/setup/run instructions, submission copy, a 45–90 second pitch and honest
fallback instructions. Prepare video only if practical. Finish code and document edits BEFORE the
final screenshot: later repository edits invalidate visual evidence.

For visible UI, launch the actual app and exercise the interaction. Use an available authorised
renderer, then `CTRL visual --file <render.json>` with
`{"screenshot":"screenshots/demo.png","viewport":"1280x800","argv":["actual","render","command"]}`.
It must create a new PNG. Inspect the image yourself; capture alone does not prove clear UX. Refresh
after changes. Missing/stale required visual evidence is PARTIAL, never a fake visual pass.
Do not pre-render into the same filename before `visual`; the helper runs the renderer itself.
A refused optional action does not end the run: use a fresh filename once or report the missing
asset. Never debug/modify the controller source or edit its state to bypass a gate. On an actual
BLOCKED/DEADLINE terminal state, stop and return the concrete reason and saved checkpoint.

After capture, record the existing shipping files via `CTRL ship --file`:
```json
{"readme":"README.md","pitch":"pitch.md","submission":"submission.md","fallback":"fallback.md",
 "screenshots":["screenshots/demo.png"],"demo_url":"","deployment_note":"Local only; no authorised public destination."}
```
A supplied public URL gets an HTTP probe; successful HTTP is reachability evidence, not proof of the
entire interaction. Verify the real demo flow too. Fallbacks must be labelled honestly, never faked
integrations or sponsor claims.

When done or asked to deliver, `CTRL verify --deliver`. Report its actual terminal state, what works,
tests/demo and public-URL status, shipping file paths, checkpoint, remaining risks and one next action.
Keep it concise. No optional improvements after delivery. Do not push/merge/submit to an event
without the user's authority. Preserve files/evidence on PARTIAL, BLOCKED or DEADLINE; do not start over.
