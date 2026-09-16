Build a useful, deterministic support-queue briefing tool in this repository. Keep it stdlib-only, offline, and runnable as:

python3 board.py EVENTS.json --as-of ISO_TIMESTAMP --format json
python3 board.py EVENTS.json --as-of ISO_TIMESTAMP --format html

Each event has event_id, ticket_id, timestamp (timezone-aware ISO 8601), and action. Actions are opened (includes title and priority), priority (changes priority), resolved, reopened. Priorities are normal or urgent. Replay events chronologically up to and including --as-of; at equal timestamps use input order. An identical repeated event_id is a duplicate, not another transition. A conflicting repeated event_id is invalid. Malformed inputs, unknown actions/priorities, naive timestamps, and transitions before a ticket is opened must fail with nonzero exit and a useful stderr error, not a traceback. Do not silently report an invalid input as an empty queue.

Only currently unresolved tickets appear. Open/reopen starts the current waiting interval; changing priority does not reset it. A resolved ticket's old waiting interval must not leak into its reopened age. Age is whole elapsed minutes at --as-of. Urgent tickets breach at age >= 30 minutes, normal at >= 120 minutes. Future events must not affect the snapshot.

JSON output must contain summary {active_count, breached_count} and tickets, each with ticket_id, title, priority, age_minutes, breached. Order tickets by breached first, then urgent before normal, then earliest current waiting start, then ticket_id lexicographically. Additional fields are fine.

HTML should be a readable standalone briefing with visible active/breached totals and ticket titles; escape untrusted titles. No web server or external assets required. Choose a small usable presentation and implementation structure. Add meaningful deterministic tests, preserve existing tests, and document the two run commands. Do not commit, install packages, access other projects, or change global configuration. Use the supplied hard time budget to prioritise a working path and verification.
