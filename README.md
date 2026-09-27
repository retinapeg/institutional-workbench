# Institutional Workbench

I wanted Claude and Codex to take a small change to a repository from assessment to tested patch, without me coordinating them by hand.

**Result:** In a predeclared 96-call experiment, expert-role prompts showed no role-specific benefit, and about a third of calls (33/96) failed on timeouts or badly formatted output rather than on the task.

**Status:** Prototype; the follow-up to [institutional-ai](https://github.com/retinapeg/institutional-ai).

- Two specialists assess the task blind and challenge each other once. A builder writes the change and QA red-teams it, then plain Python runs the tests and applies the patch.
- 14 of the 16 malformed answers were JSON wrapped in Markdown fences. Most score differences came from output format and completion, not from the role prompt.
- The experiment is small (eight synthetic tasks, two models) and lives on the [`v0.3-benchmark-lab`](https://github.com/retinapeg/institutional-workbench/tree/v0.3-benchmark-lab/benchmarks/results) branch. `main` has one recorded live run.

[Technical details →](docs/GUIDE.md)
