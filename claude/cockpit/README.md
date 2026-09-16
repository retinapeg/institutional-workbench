# Claude-native Hackathon

Claude inspects, builds, tests and ships. External models optionally advise on a concrete question;
there is no mandatory roundtable or external patch-writing builder. Director, Builder, Breaker and
Shipper are four responsibilities of the same cockpit, not four persistent agents.

## Use

In a clean, committed project, after activation:

```text
/hackathon Build a compelling interactive demo for this judging rubric in 8 hours: ...
```

No deadline means a stated 120-minute default. Empty `/hackathon` asks for a goal; it does not build.
During the same run:

```text
STEER: The backend is good enough. Make the main interaction clearer and more impressive.
/hackathon status
deliver
```

Plain `status` also requests the operational view. Claude's reserved `/status` remains unchanged.

## Isolated preview and activation

Before replacing any installed skill, launch from a disposable clean repository:

```sh
claude --plugin-dir /Users/leonardaarons-ditson/Code/institutional-workbench-routing/claude/cockpit
```

Use `/institutional-cockpit:hackathon <goal> in <minutes> minutes` there. No permission grants or
global settings changes are bundled. Activate only after the realistic isolated smoke passes:
back up `~/.claude/skills/hackathon/SKILL.md`, replace **only that file** with
`claude/cockpit/skills/hackathon/SKILL.md`, then test empty `/hackathon` in a fresh Claude session.
Restore the saved file to roll back. Keep the sibling `roundtable.md`: `/engineering` uses it.
Do not replace a skill underneath another active user's run.

## The loop and its limits

Inspect briefly → define observable acceptance → build → run real tests/demo → checkpoint → improve
the most visible weakness → ship. `prepare` begins BUILD immediately. No freeze or adviser call is
required. Per iteration, at most two advisers and one optional challenge; one focused implementation
repair before a failing iteration blocks. Adviser failure never erases a working demo.

The foreground helper maintains `.institutional-workbench/cockpit-*/run.json`: deadline, phase,
checklists, risks, current/next action, steering, evidence and last-working checkpoint. No hidden
reasoning is stored. `status --human` is the readable view; keep evidence local if it includes
private source or output. `steer` records priorities for the next safe operation boundary without a
new run. Thirty minutes without an artifact forces execution, not another conference.

Frozen checks run on actual files. Existing tests and ownership stay protected. `verify` saves a
working Git checkpoint without moving the current branch/index and continues; `verify --deliver`
finishes with an evidence-based result. New risky work requires a working checkpoint. Failed later
changes do not erase it. There are no destructive resets, automatic merges or pushes.
Inspect/recover a saved checkpoint in a separate Git worktree at its recorded SHA, never by resetting
the active checkout. Complete all source/document edits before final screenshot capture; later file
changes correctly invalidate that screenshot. Recording an existing shipping manifest is read-only.

Deadline policy: T−90 feature freeze, T−60 stabilise/present, T−30 no risky changes. Short runs scale
these to 25%, 16.7% and 8.3%. Checks happen at native operation boundaries; this is **not a sandbox**
and cannot interrupt Claude's in-flight Edit/Read. Helper subprocesses and native commands retain
bounded timeouts. Budget expiry preserves work rather than pretending the definition of done passed.

Shipper records README, pitch, submission, fallback, screenshots and public-URL status. It checks a
provided URL's HTTP reachability; Claude still exercises the real interaction. Screenshot capture
is evidence, not a layout judgement. Missing required assets/visual proof stay explicit. Deployment
uses only authorised destinations; no account changes, purchases, secrets or fabricated integrations.

`DELIVERED` means the frozen checks and required shipping evidence pass. `PARTIAL`, `BLOCKED` and
`DEADLINE` preserve useful work and name what is unverified. Native permissions still apply.

## Verify development changes

```sh
uv run python -m unittest discover -s tests -q
uvx ruff format --check src tests benchmarks claude/hackathon/bridge.py
uvx ruff check src tests benchmarks claude/hackathon/bridge.py
uvx --with 'pydantic>=2.10,<3' mypy --strict src benchmarks/run.py claude/hackathon/bridge.py
uv build
```

Deterministic temporary-repository tests are not live Claude proof. Keep the separate realistic
smoke evidence, registration result and limitations explicit; do not rerun a user project to test
this integration. The legacy Python CLI and `/engineering` are separate, unchanged paths.

### Current verification — 16 September 2026

115 deterministic tests, lint, strict typing and package build pass. The one live disposable
Sonnet cockpit attempt repaired the seeded budget-conservation bug: first source edit at 37.9s,
passing core/browser checks and working checkpoint by 51.2s. One injected steering instruction
was read and followed with visible-interaction edits (Claude redundantly recorded it twice).
Zero advisers were used. Original acceptance files and global settings/skills stayed unchanged.

That attempt **did not complete**: an existing screenshot filename caused a fatal helper refusal;
the run was stopped at 218.6s before shipping assets were produced. Its evidence remains at
`/tmp/inst-hackathon-web-smoke.mGihG3/metrics.json`. The refusal is now nonterminal and regression
tested; the skill explains fresh captures and safe stopping. A post-fix live recheck still needs
approval. Global `/hackathon` has **not** been replaced; do not call this activated or live-proven.
