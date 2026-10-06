# Institutional Workbench

Can Claude and Codex take a small change to a repository from assessment to tested patch without a person coordinating them, and does giving each model an expert role make it a better specialist?

**Result:** In a predeclared 96-call experiment (8 tasks × 2 CLI stacks × 3 role conditions × 2 repeats), 33 calls failed before the task was judged: 13 timeouts, 4 provider errors and 16 malformed outputs, all 33 on the Claude CLI side (Codex 0/48). 14 of the 16 malformed answers were JSON wrapped in Markdown fences, despite an explicit instruction not to. The matched-role condition had a higher raw mean score than the no-role baseline (0.71 vs 0.59), but almost all of that gap came from fewer format and completion failures; on schema-valid answers the three conditions were within 0.06 of each other.

**Why it matters:** Elaborate multi-agent role prompting did not by itself create better specialists. Whether a call completed, and whether its output parsed, mattered more than which role it was given. Model failures, protocol failures and infrastructure failures have to be counted separately before anything can be said about the role prompt, and that taxonomy carried into the later [agent_reliability_lab](https://github.com/retinapeg/agent_reliability_lab).

**Status:** Prototype; the follow-up to [institutional-ai](https://github.com/retinapeg/institutional-ai). `main` has one recorded live run. The experiment lives on the [`v0.3-benchmark-lab`](https://github.com/retinapeg/institutional-workbench/tree/v0.3-benchmark-lab/benchmarks/results) branch.

- Two specialists assess the task blind and challenge each other once. A reviewer freezes the deliverable and acceptance criteria, a builder writes the change, QA red-teams it with new tests only, and plain Python runs the frozen test commands and applies the patch. The run blocks if a decision erases a dissent that was raised.
- Each model call is one JSON object validated against a schema; a malformed answer blocks the run with no retry. Runs are capped at 16 calls, 15 minutes and 90 seconds per call.
- The experiment is small: eight synthetic tasks (two each in physics, mathematics, statistics and software), two CLI stacks, ceiling effects on many valid answers, and no claim of statistical significance.

## Evidence

| Claim | Where to check (branch `v0.3-benchmark-lab`) |
|---|---|
| Protocol committed before inference; fingerprint recorded 10 s later; nothing changed during the sweep | `benchmarks/README.md`, `benchmarks/results/manifest.json`, `benchmarks/results/INTERPRETATION.md` |
| 33 protocol failures: 13 timeout, 4 provider error, 16 malformed; 14/16 fenced | `benchmarks/results/INTERPRETATION.md`, `benchmarks/results/results.csv` |
| Condition means 0.5875 / 0.7148 / 0.6172 (baseline / matched / mismatched); schema-valid 20 / 23 / 20 of 32 | `benchmarks/results/summary.json`, `SUMMARY.md` |
| Per-stack: Codex `gpt-5.6-terra` 48/48 schema-valid; Claude `sonnet` 15/48 | `benchmarks/results/INTERPRETATION.md` |
| All 63 schema-valid responses regraded with the unchanged graders after the run; every stored score reproduced | `benchmarks/results/INTERPRETATION.md` |
| One live run on `main`: health endpoint delivered in 214 s, 7 provider calls, 0 repairs | [`VERIFICATION.md`](VERIFICATION.md) |

A predeclared secondary sweep with a third model was gated on a protocol-failure rate below 20% and was skipped at 34%.

## Reproduce the offline checks

```bash
uv sync --python 3.11
uv run python -m unittest discover -s tests -v      # fake providers; no model calls
```

A live run needs the Claude Code and Codex CLIs signed in: `uv run inst dev "add a /health endpoint"`. The benchmark records on the experiment branch are immutable; the 96 per-call records, the parsed CSV and the summary are all committed there.

## What this does not show

- That role prompts never help, or that Claude Sonnet cannot do the mathematics. All 12 Claude-side mathematics calls failed at the process layer, so their task scores are 0 by the predeclared rule, not measured.
- A fair intrinsic comparison of the two models. The surviving task mixes differ, and the comparison is between CLI stacks (Claude Code 2.1.272, Codex CLI 0.154.0), not bare models.
- Cost. Timed-out calls' token use is unknown, and the dollar figures are estimates, not subscription spend.

[Technical details →](docs/GUIDE.md)
