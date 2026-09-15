---
name: hackathon
description: Run the Python Institutional Workbench hackathon engine in the current repository and return its final result.
argument-hint: "<task>"
disable-model-invocation: true
---

You are only the cockpit. Do not inspect/plan/build the task yourself, spawn agents, or follow the
native roundtable procedure. The Python engine owns roles, routing, building, tests and QA.

The user's exact task is:
<workbench-task>
$ARGUMENTS
</workbench-task>

1. If the task is exactly "speed up" or "crunch", run the existing control once against cwd:
   /Users/leonardaarons-ditson/Documents/Codex/institutional-workbench-routing/.venv/bin/python -m institutional_workbench.cli crunch --repo "<current-directory>"
   Report that the request was queued for the next safe boundary, then STOP; do not cancel or launch another run.
   If the task is empty, ask for it. Otherwise run pwd and remember that absolute current directory.
2. Run mktemp /tmp/inst-hackathon-task.XXXXXX. With Write, put ONLY the task text above into that
   file, unchanged: no paraphrase, extra instructions, markup, escaping or shell interpolation.
3. Run the following ONCE with Bash timeout=3720000 and run_in_background=false (omit that
   field if unavailable). Never use &, nohup, a detached task, or a second launch.
   Substitute only the two absolute paths, quoted:

   /Users/leonardaarons-ditson/Documents/Codex/institutional-workbench-routing/.venv/bin/python /Users/leonardaarons-ditson/Documents/Codex/institutional-workbench-routing/claude/hackathon/bridge.py --repo "<current-directory>" --task-file "<temporary-task-file>"

4. This Bash call must remain foreground until it returns BRIDGE_EXIT=<code>, emitted AFTER
   the Workbench child exits. Do not produce a final response before that result. A progress
   message is not completion. Do not silently change provider/model flags or fix code yourself.
   If permissions are needed, ask normally; never bypass them.
5. Return its final DELIVERED/BLOCKED/DEADLINE/PAUSED status, changes, tests, run command, limitations and evidence
   path concisely. If blocked, report the concrete blocker and STOP. Never automatically retry.

The target must be a Git repository with a commit and a detectable test command. The engine checks
dirty work and bounds execution. No automatic push, merge, deployment or account-setting changes.

Installation requires Claude's CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 and
BASH_DEFAULT_TIMEOUT_MS=BASH_MAX_TIMEOUT_MS=3720000 in its startup environment/settings.
Restart Claude after installation. These keep the foreground tool attached beyond the engine's
configured deadline (up to 60 minutes); they do not extend the engine's budget.
The engine reads "in 25 minutes" as a SOFT advisory budget; otherwise its default is 15.
Only an explicit request for a hard deadline authorizes appending --hard-deadline <minutes>.
For PAUSED, return the checkpoint headings and stop for user direction. Do not auto-resume or apply
the checkpoint patch. While the foreground Bash call is attached, a second terminal can issue the
crunch control command above; queued chat text is not a reliable interrupt mechanism.
