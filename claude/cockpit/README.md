# Claude-owned Hackathon preview

This opt-in path changes implementation ownership, not the existing Python router or CLI modes.
Claude reads, edits, inspects renders and owns the final decision. The foreground Python helper
collects actual evidence and runs frozen checks. Tool-disabled model workers only advise.
The installed `/engineering` still reads `~/.claude/skills/hackathon/roundtable.md`; neither that
file nor the installed skills/settings are changed by development or preview activation.

## Preview without replacing anything

From a **clean, committed disposable Git repository**:

```sh
claude --plugin-dir /Users/leonardaarons-ditson/Code/institutional-workbench-routing/claude/cockpit
```

Then type:

```text
/institutional-cockpit:hackathon Add a rank_three(a,b,c) Python function returning descending values, with duplicate and negative-value tests, in 5 minutes.
```

The namespace avoids collision with the currently installed `/hackathon`. No permission grants
are bundled. Ordinary Claude permissions apply to edits and controller commands; respond to a
genuine permission request normally. No global tool install, settings change or restart required.

## Activate the short `/hackathon` name when YOU are ready

Do this only after the active interview-preparation Claude session is finished. Claude watches
personal skills live. Keep the existing sibling `roundtable.md` because `/engineering` uses it.

```sh
backup_dir=$(mktemp -d /tmp/institutional-hackathon-skill-backup.XXXXXX)
cp /Users/leonardaarons-ditson/.claude/skills/hackathon/SKILL.md "$backup_dir/SKILL.md"
cp /Users/leonardaarons-ditson/Code/institutional-workbench-routing/claude/cockpit/skills/hackathon/SKILL.md /Users/leonardaarons-ditson/.claude/skills/hackathon/SKILL.md
```

Start a new Claude session in the intended repository and type:

```text
/hackathon Add a rank_three(a,b,c) Python function returning descending values, with duplicate and negative-value tests, in 5 minutes.
```

To undo, copy the saved `SKILL.md` back. Do not replace the entire skill directory.

## Evidence and bounded control

- `start` begins a monotonic **explicit hard** budget before source inspection; no invented deadline
  for maintenance. Legacy Python CLI soft deadlines/CRUNCH remain unchanged.
- `prepare` freezes cockpit-authored ownership, tests/demo argv and named read/CSV probes. It runs
  baseline checks against real files. These argv lists require cockpit/user authority; they are not
  a sandbox and must never be copied blindly from adviser output.
- `advice` uses the existing task profiler, role selector (zero for trivial work, otherwise max two),
  model registry and cost-zero capability router. Independent calls see no peer reports; one
  challenge sees the completed first round. Total deliberation cutoff is 15% of the run, including
  inspection; each provider child is bounded to the remaining allowance, max 90 seconds. At most
  one local operational escalation per adviser call. EPERM is not retried. Optional adviser
  unavailability returns control to Claude. There is no model-builder phase in this path.
- `probe` resolves only configured names, max twice each. CSV header checks are stdlib-only. For
  Parquet use an already-available authorised native query and retain its result; this helper does
  not install a database or silently send private data to a provider.
- `freeze` retains decisions, disagreements and observed receipt quotations. It checks that quotes
  actually exist and evidence is current. Claude must still check whether the inference is valid;
  this is not an automatic semantic judge. Essential blockers stop execution; optional unknowns
  should narrow scope or be deferred.
- Claude is the only writer. `status` supplies remaining time and native command timeout; last 25%
  is validation-only. Native tools must obey these boundaries. The helper cannot forcibly interrupt
  an in-flight Claude Edit/Read. Its own commands are terminated via the existing process-group
  runner. User cancellation writes only this run's cancellation file, even during an active call.
- `verify` executes frozen checks. Original tests and out-of-scope files are protected; a check
  changing source invalidates its own evidence. Exactly one implementation repair. A no-op needs
  baseline and final acceptance to pass. Concurrent writes are unsupported: use one writer per
  physical worktree. No reset, checkout, commit, push or automatic merge occurs.
- `visual` executes an authorised render command, records a newly produced PNG, viewport, hash and
  source version. CAPTURED_NOT_INTERPRETED does **not** assert layout correctness. Claude must view
  the screenshot. Missing/stale required rendering means PARTIAL after executable checks pass.

`DELIVERED`: actual frozen checks passed against the candidate; separately inspect visual status.
`PARTIAL`: executable evidence exists but required visual verification is missing.
`DEADLINE`: budget expired; files and receipts retained, no verified-completion claim.
`BLOCKED`: a necessary operation/permission/check cannot proceed safely or one repair failed.
Provider prose, a proposed patch, and a model confidence score cannot create these test receipts.

Run evidence lives in `.institutional-workbench/cockpit-*/run.json`. Keep it local: authorised argv,
source excerpts and command output may be sensitive. No automatic publication or account metadata.

## EPERM: established versus inferred

The inherited `100145d` regression reproduces an EPERM during `os.killpg(pid, 0)` cleanup masking
a primary timeout, and preserves that timeout. The original field run had no syscall trace, so
its exact syscall is **not retrospectively established**. This preview does not claim otherwise.
New host-operation failures retain phase, attempted argv, cwd, errno, status (unknown when no
result), and error; successful/failed completed commands retain stderr. A broad `Runner.run`
failure alone still cannot distinguish launch from every cleanup syscall. No protection is disabled.

## Checks

```sh
uv run python -m unittest discover -s tests -q
uvx ruff format --check src tests claude/hackathon/bridge.py
uvx ruff check src tests claude/hackathon/bridge.py
uvx --with 'pydantic>=2.10,<3' mypy --strict src claude/hackathon/bridge.py
uv build
```

`test_cockpit.py` uses real temporary repositories, writes and subprocess tests, with mocked
advisers. That is not Claude-host proof; the separately recorded isolated smoke supplies that
integration layer when runtime credentials/permissions allow it.
