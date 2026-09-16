# One A/B/C engineering benchmark

From the Workbench checkout:

```sh
uv run python benchmarks/run.py queueboard --budget 5m
```

This launches **three real, serial model runs**, each with five minutes of agent wall time:
plain Claude Code, plain Codex, and the current isolated Institutional cockpit plugin. It is not
a mock/demo switch. Use `--budget 20m` for twenty minutes **per contender**, not for the whole batch.
Use `--output /tmp/my-new-benchmark` for a specific **new** output directory; existing output is
never overwritten. Defaults go under `/tmp/institutional-benchmark-*/run/`.

Requirements: macOS `sandbox-exec`, `git`, `ps`, working local Claude/Codex authentication, and the
existing project environment. No packages, global tools, skills or settings are installed/changed.
This first harness deliberately refuses an unisolated fallback on other operating systems.

Default explicit models: Claude `sonnet` for both A and C, Codex `gpt-5.6-sol` for B. Override with
`--claude-model` / `--codex-model` when making a deliberate comparison. C's existing internal
adviser router is unchanged. Model capability and workflow are therefore not fully separated in
this engineering comparison; it is not a causal role-intervention study. Cost has no scoring weight.

## Challenge

Queueboard is an offline, stdlib-only support-queue briefing application. It must replay timestamped
events, account for resolution/reopening and priority changes, respect an as-of cutoff and SLA
boundaries, return ordered JSON, and render an escaped standalone HTML briefing. Architecture,
presentation and added tests are the contender's decisions. No external API or FleetCast data.

The starting stub passes its two basic tests but fails semantic checks. `task.md` predeclares the
full contract. `verify.py` is the external grader, with 3 acceptance and 8 held-out checks. Held-out
means withheld from contenders during execution, **not secret from humans reading this repository**.
All checks are frozen and hashed before inference. Grading does not depend on agent claims.

The harness copies the fixture bytes to one committed seed, then makes three independent Git clones
with the exact same commit and tracked/untracked source bytes. It passes identical brief/budget
bytes; C alone gets the existing `/institutional-cockpit:hackathon` invocation prefix. The plugin is
session-local, not promoted to `/hackathon`. The source checkout and current cockpit code are unedited.

## Safety and timing

- A macOS filesystem profile makes each contestant writable only in its own repository and scratch
  directory. Reads of peers' directories, the seed, held-out grader and benchmark source/tests are
  denied. Writes outside the allowlist—including source checkout, FleetCast and global settings—are
  denied. Claude runs under the harness profile; Codex uses its native named permission profile
  extending `:workspace` with equivalent path restrictions. macOS cannot nest `sandbox_apply`, so
  Codex is not wrapped in a second sandbox. No `danger-full-access` or bypass flag is used. Both
  real sandbox backends have deterministic allowed-write/denied-read/denied-write tests.
- Plain Claude uses safe mode, with no Institutional prompts. Both Claude runs restrict tools and
  disable external MCPs; C loads only the explicit preview plugin. Codex ignores user configuration
  and skips user skill discovery. Codex's supported per-process `CODEX_HOME` points at a private
  runtime directory, avoiding global SQLite/cache writes. Its auth file is a read-only reference
  to existing login data, never printed/copied; a provider refresh can create local auth state.
  The runtime directory is private (0700) and must never be published.
- The outer hard clock includes CLI startup, inspection, calls, tools and implementation. On expiry,
  TERM then KILL targets the owned process group and observed descendants (including new sessions).
  Cleanup has a separate bounded grace period. No retries, parallel contestants, or human prompts.
- Process ancestry is sampled. This contains ordinary CLI children; it is not a hostile daemon or
  network-isolation system, and does not promise containment of deliberately evasive processes.
- After each agent stops, the **same** frozen external verifier runs with a separate 45-second cap
  and a read-only candidate. Existing fixture tests must be unchanged for delivery. Candidate
  symlinks are recorded but not executed. All candidate files and timeout output remain available.
- Runtime/auth/permission failure is an observation, not grounds to relax the sandbox or retry.
  If a runtime needs a prohibited global write, fix/approve its integration separately; do not turn
  off these guards to obtain a nicer benchmark result.

## Read the results

```text
run/
  brief.txt, verify.py, seed/
  claude/        repo/, stdout.log, stderr.log, process.json, sandbox.sb, final.diff, verification/
  codex/         ...
  institutional/ ...
  report.json
  REPORT.md
```

Report fields include delivered/partial/failed, separate process timeout/exit status, execution and
cleanup elapsed time, acceptance and held-out counts, application-runs evidence, changed files and
diff size, exact failed checks, observable request IDs/models/Codex turns, and permission failures.
Human interventions are zero because permission prompts are disabled. Exact model-call totals and
time to first working implementation are **UNKNOWN**, not guessed from completion prose. Final
verification is the only harness-observed working-state measurement; no concurrent test monitor.

`delivered` requires process completion, all external checks and intact original tests. A timed-out
candidate can still have passing checks, but remains partial rather than a completed run. No
arbitrary quality score or automatic winner. One fixed-order short run is exploratory engineering
evidence, with model, startup/permission and temporal confounds—not a general superiority claim.

Keep raw logs local: CLI streams can contain account/runtime metadata. Nothing is auto-published.

## Tests and supported invocations

```sh
uv run python -m unittest discover -s tests -p test_benchmark.py -v
uv run python -m unittest discover -s tests -q
uvx ruff check src tests benchmarks claude/hackathon/bridge.py
uvx --with 'pydantic>=2.10,<3' mypy --strict src benchmarks/run.py claude/hackathon/bridge.py
uv build
```

Fake argv overrides are a test-only Python seam, not a live-run result. Tests exercise real local
Git copies, OS read/write denials, timeout cleanup including a detached child, failure continuation,
common grading and both known passing responses and semantic failures.

Runtime flags were checked against local help (`claude` 2.1.273, `codex-cli` 0.154.0) and official
[Codex non-interactive documentation](https://learn.chatgpt.com/docs/non-interactive-mode) and
[Codex permission profiles](https://learn.chatgpt.com/docs/permissions) and
[Claude plugin loading documentation](https://code.claude.com/docs/en/plugins).

## Recorded short smoke — 2026-09-16

The initial genuine serial A/B/C smoke used the same fixture/brief and **120 seconds each**:

| Contender | Observed process | Acceptance | Held-out | Result |
|---|---|---:|---:|---|
| Claude Sonnet (`claude-sonnet-5` observed) | completed, 110.707s | 3/3 | 8/8 | delivered |
| Codex `gpt-5.6-sol` | startup failed, 0.391s | 2/3 | 0/8 | failed |
| Cockpit / Claude Sonnet | timed out, 120.034s | 2/3 | 0/8 | failed; no implementation changes |

Original report: `/tmp/institutional-abc-smoke-20260916/REPORT.md`.
It is retained unchanged. Do **not** interpret it as proof that one workflow is generally superior.

Codex startup attempted a global SQLite write, correctly denied by the initial outer sandbox.
A separate private-storage validation then exposed macOS's inability to nest `sandbox_apply`:
the model ran but tools were denied. Evidence is retained separately at
`/tmp/institutional-codex-storage-smoke.rQ0M2Q/result.json` (84.719s; no implementation).

The final integration uses Codex's supported native permission profile instead of nested sandboxes.
A real no-inference test proved allowed workspace writes, denied peer reads and denied outside
writes. A final bounded **Codex-only** live validation successfully executed repository commands;
its patch attempt was invalid and it timed out at **120.026s**, preserving the original fixture
(2/3 acceptance, 0/8 held-out). Evidence:
`/tmp/institutional-codex-native-smoke.W0A5gI/result.json`.
This is a separate validation, not a replacement B score spliced into the original comparison.
No final full A/B/C rerun was made, and no candidate code was repaired by the harness author.

Final deterministic suite: **99 passed** (89 inherited, 10 benchmark). Ruff formatting/lint,
strict mypy for `src`, the harness and legacy bridge, and package build passed. Installed Claude
skills/settings and Codex settings hashes were unchanged. No FleetCast access or modifications.
Only benchmark code, synthetic fixtures, documentation and benchmark tests are added.
