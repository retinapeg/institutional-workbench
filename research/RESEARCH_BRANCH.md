# Long-lived research branch

Repository: `retinapeg/institutional-workbench`.
Branch: `research/institutional-engineering`.
Worktree: `~/Documents/Codex/institutional-workbench-research`.
Base: `v0.3-benchmark-lab`, commit `2400aa4e35bb908f272afb0baca10d588590be43`.

- Put all new research-only benchmarks, protocols, papers and datasets under `research/`.
- Reuse the existing product/provider/router code; do not maintain copied implementations.
- The inherited `benchmarks/` snapshot is retained unchanged for historical reproducibility;
  do not relocate it or rewrite its results as part of this branch setup.
- Product/provider/router improvements may flow from product branches into this research
  branch after review and testing. No such merge is performed by this setup.
- Never merge the research branch wholesale into product. Research-only code or data may
  enter product only through an explicitly approved, scoped promotion with its own review.
- Use this separate physical worktree for research; leave `main`, `v0.1.0`, and
  `v0.2-dynamic-routing` untouched. Do not force-push shared history or move release tags.

This branch setup changes documentation only. It does not change runtime behaviour,
installed commands, or the separate `retinapeg/institutional-engineering` repository.
