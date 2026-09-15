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

1. If the task is empty, ask for it. Otherwise run pwd and remember that absolute current directory.
2. Run mktemp /tmp/inst-hackathon-task.XXXXXX. With Write, put ONLY the task text above into that
   file, unchanged: no paraphrase, extra instructions, markup, escaping or shell interpolation.
3. Run the following once, substituting only the two absolute paths, quoted:

   uv run --project /Users/leonardaarons-ditson/Documents/Codex/institutional-workbench-routing inst hackathon --repo "<current-directory>" --task-file "<temporary-task-file>" --explain-routing

4. Wait for this SAME process through the native task-output mechanism until it exits. Do not
   launch another run, silently change provider/model flags, fix code yourself, or report a started
   run as delivered. If permissions are needed, ask normally; never bypass them.
5. Return its final DELIVERED/BLOCKED status, changes, tests, run command, limitations and evidence
   path concisely. If blocked, report the concrete blocker and STOP. Never automatically retry.

The target must be a Git repository with a commit and a detectable test command. The engine checks
dirty work and bounds execution. No automatic push, merge, deployment or account-setting changes.
