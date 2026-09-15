---
name: hackathon
description: Build and verify a bounded demo with Claude as sole writer and optional routed advisers.
argument-hint: "<goal> in <minutes> minutes"
disable-model-invocation: true
---

Goal and explicit hard deadline: $ARGUMENTS

You are the cockpit AND sole implementation owner. Use your actual Read/Glob/Grep/Edit/Write/Bash
tools. Advisers are text-only, cannot edit, and never certify completion. Do not invoke the old
bridge, Python CLI build engine, builder agent, advisor model, or another interactive assistant.
Normal permissions and repository instructions apply; no bypasses, automatic commits or installs.
Do not touch another writer's worktree. If dirty, use an agreed isolated committed worktree or stop.

Controller (existing local environment; no global install):
`/Users/leonardaarons-ditson/Code/institutional-workbench-routing/.venv/bin/python -m institutional_workbench.cockpit`
Below, `CTRL` denotes this exact prefix, not a shell alias to install.
Use one foreground invocation per action. Never background it. Read each returned JSON/exit status.

1. **Start now.** If goal or minutes are missing ask only for that. Otherwise use pwd, create a
   temporary task file and Write the full goal into it verbatim. Immediately run:
   `CTRL start --repo "<cwd>" --task-file "<file>" --minutes <explicit minutes>`
   Save the returned `run` path. This starts a hard clock BEFORE source inspection or advisers.
   Every later action uses `--run "<run>"`. Run `CTRL status` before each group of native tool
   operations; obey `remaining_seconds`, `native_tool_timeout_ms` and `next_action`.
   Native Bash timeouts must not exceed this allowance. No hidden retries.
2. **Inspect with actual tools.** Read repository instructions, relevant source, test/demo commands
   and status. Confirm each needed capability by use. Do not launch a browser for nonvisual work.
   Resolve cheap facts directly (schema query, source search, calculation). No debate for a fact.
   Choose a small slice and explicit observable acceptance. Write a plan JSON in the run directory:
   ```json
   {"deliverable":"observable result", "acceptance":["specific outcome"],
    "owned_paths":["app.py","tests/new_test.py"],
    "checks":[{"name":"tests","argv":["python3","-m","unittest","discover","-s","tests","-v"],"kind":"test","timeout":60}],
    "source_paths":["app.py"],
    "probes":[{"name":"source","kind":"read","path":"app.py"}],
    "visual_required":false}
   ```
   These are examples, not acceptance for every task. Checks must actually exercise the requested
   behaviour, including a demo check (`kind: demo`) if needed. Include a failing regression for a
   real bug; never use echo/true as validation. Existing tests remain protected. Own narrow paths.
   Author argv yourself from repository/user-authorised commands; never execute advisers' shell
   strings. Plan/probes/checks freeze with `CTRL prepare --file "<plan.json>"`. This runs baseline
   checks, records source hashes and confirms real execution. Expected assertion failures are OK;
   missing capability/dependency must be resolved or explicitly blocked, not called success.
3. **Evidence and optional advice.** `CTRL probe --name source` reads only the configured file.
   `csv_columns` probes read a CSV header, without another model. Other authorised data methods
   (e.g. installed DuckDB on Parquet) use YOUR native tools; retain command/output, no installation
   or access widening. Select zero advisers for trivial work; otherwise call `CTRL advice` once.
   It reuses task-dependent roles (max 2), the capability router, independent reports and at most
   one challenge. It spends at most 15% of the TOTAL budget, including earlier inspection. A timed
   out/unavailable optional adviser falls back to cockpit-only. Never restart a roundtable.
   Fulfil named evidence requests with `probe` at most twice. Unavailable nonessential facts are
   deferred or narrow scope; only an essential missing permission/correctness input blocks work.
   Preserve hypotheses and dissent. Independently verify a consequential finding before editing.
4. **Freeze and build early.** Write decision JSON:
   ```json
   {"implementation":["small bounded change"],"rulings":[],"unresolved":[],"blocker":""}
   ```
   For review-driven corrections include rulings with `claim`, `decision` (accept/reject/defer),
   `receipt` (zero-based observed receipt index), `evidence_quote`, and `reason`. Quotations must
   exist in current source/execution evidence. Reject plausible fixes contradicted by a query/test.
   Receipt validation proves provenance, not logical entailment: YOU check the inference.
   `CTRL freeze --file "<decision.json>"` then YOU implement with Edit/Write. No text-only builder.
   An intentional no-op needs passing baseline AND final checks, not a worker claim.
5. **Validate/stabilise.** Check status between atomic edits. At `VALIDATE_ONLY` (last 25% budget),
   no new features or speculative changes; finish only a safe atomic edit, then verify. Run
   `CTRL verify`; it executes frozen tests/demo against actual files. If `REPAIR`, make ONE focused
   correction, then `verify` once. Never alter frozen acceptance to manufacture a pass.
   For visual work, use an available authorised renderer. `CTRL visual --file <render.json>` takes
   `{"screenshot":"new-shot.png","viewport":"1280x800","argv":[...actual render command...]}`.
   The command must create that new PNG. Inspect it with your image tool; record viewport and
   findings. Capture alone is not proof of no clipping. After changes capture/recheck again.
   Without rendering, explicitly report UI UNVERIFIED (required visual work yields PARTIAL).
6. **Stop.** DELIVERED requires actual frozen checks, unchanged acceptance and bounded ownership.
   Report build/no-op, exact checks, demo/render status, evidence path, unresolved risks and next
   action. PARTIAL/DEADLINE preserves files but is not verified completion. BLOCKED requires a
   concrete essential reason. Never claim advice did implementation. No final extra improvement.

Budget limitation: the controller kills ONLY its own timed-out children. It cannot interrupt a
native Claude Edit/Read already in flight; check time at each boundary and set native command
timeouts. At expiry, stop new edits, collect `status`, report partial evidence and do not auto-resume.
Use `CTRL cancel --run <run>` for user cancellation. Do not signal unrelated processes.
Keep brief progress: Inspect → Evidence → Frozen → Claude build → Real checks → Result.
