# Cockpit preview verification — 2026-09-15

Base: `100145d1d561896eede01988b0b3299820d6c352`, branch
`codex/hackathon-capability-routing`. No legacy engine/provider/router/bridge edits.

## Automated gates

- `uv run python -m unittest discover -s tests -q`: **89 passed** (70 inherited + 19 cockpit).
- `uvx ruff format --check src tests claude/hackathon/bridge.py`: **passed**.
- `uvx ruff check src tests claude/hackathon/bridge.py`: **passed**.
- `uvx --with 'pydantic>=2.10,<3' mypy --strict src claude/hackathon/bridge.py`: **passed**, 9 source files.
- `uv build`: **passed**, wheel and sdist.

The 19 new tests distinguish real temporary-repository writes/subprocess executions from mocked
advisers. Coverage: delivered host edit; narrative-only failure; genuine no-op; CSV schema probe;
optional missing evidence; false all-rows claim; stale/fabricated evidence; independent reports and
one challenge; trivial zero-adviser route; exhausted optional routing; injected EPERM diagnostics;
real slow-process deadline; deliberation cutoff/reserve; unavailable visual evidence; synthetic
render receipt without claiming visual interpretation; owned-path protection; terminal status;
lock/cancellation safety; dirty repository preservation.

One independent read-only review found four issues: lock/cancellation races, exhausted optional
route blocking, terminal-status expiry mutation, and visual-partial bypass of repair. All repaired
and covered by tests. No second review loop or extra live worker benchmark.

## Genuine Claude-host smoke

Loaded only the local preview plugin with `--plugin-dir`, invoked
`/institutional-cockpit:hackathon`, in a disposable repository. Claude Auto Mode, permission prompts
disabled for this noninteractive test, **no added allow rules or bypass flags**. Existing global
permissions remained in force. The inherited outer model reported `claude-opus-5`; no outer model
override was supplied. This is cockpit execution, not a live routed-adviser test.

- Full outer process: **107.380 seconds**, exit **0**, successful final Claude result.
- `permission_denials`: **[]**.
- Baseline: both frozen checks failed because `ranking.py` did not exist.
- Claude directly wrote `ranking.py` and `tests/test_rank_three_extra.py` using its host tools.
- Controller `verify`: **9 tests passed**, demo exit 0, output **`9, 5, 2`**.
- Final status: **DELIVERED**, build **CHANGED**, **0 repairs**, **0 optional adviser calls**.
- Existing README, demo and acceptance tests: baseline hashes unchanged; Git HEAD unchanged.
- Root agent independently reran the nine tests and demo successfully.
- No browser/render required or attempted. Visual status remains **UNVERIFIED**.

Local evidence (not committed: full Claude streams may include runtime/account metadata):

```text
/tmp/inst-cockpit-smoke.Rt5uaZ/timing.json
/tmp/inst-cockpit-smoke.Rt5uaZ/claude-stream.jsonl
/tmp/inst-cockpit-smoke.Rt5uaZ/repo/.institutional-workbench/cockpit-1789508164979660000/run.json
```

This proves the namespaced preview/native cockpit path, not replacement of the globally installed
short command. The latter is intentionally a user-controlled activation step in README.md.
Dynamic advisers/challenge were exercised with mocks, not additional live paid calls. Existing
native `/engineering` was not re-run live; its installed files and inherited Python tests are preserved.

## Preservation receipts

Personal file SHA256 values matched before/after the live run:

| File under `~/.claude/` | SHA256 |
|---|---|
| `skills/hackathon/SKILL.md` | `fc131f44d5076f778e476eed2eba40be0c897d45043f872182bd31bf8e4683b2` |
| `skills/hackathon/roundtable.md` | `576da3f153bdc255f2b4d1491b14611beb24fb97a99c2a0f8f2d0c15c5cc2bf1` |
| `skills/engineering/SKILL.md` | `95955fd908f6a2257c3fc5ff65da3184cbd8483013357b383a8fbd0017cd5bd6` |
| `settings.json` | `c31d6a51a4a89f0afe1a21489933d73e87b9bf3904b54ae05d2346f204f53360` |

FleetCast was not accessed as a sandbox or modified. No active session/server was restarted.

## Limits on the claim

The historical EPERM syscall remains unproven for the original field run. The inherited cleanup
regression and new injected-launch diagnostic test are deterministic evidence, not retroactive
tracing. The helper supervises its children; native Claude tools observe deadlines at operation
boundaries, not through a global process supervisor. Frozen checks are authored by the cockpit:
their substantive adequacy still requires judgment. Source quotes prove provenance, not entailment.
