# `memory/` — team-shared Claude knowledge

This directory is **committed, PR-reviewed agent memory**: durable lessons,
constraints, and feedback that every contributor's Claude Code session should
load. It exists because per-user Claude memory (under `~/.claude/...`) is private
to one machine — when a colleague's Claude learns something important, the rest
of the team's agents never see it. Committing it here fixes that.

## Protocol

- **Read everything in `memory/*.md` at session start.** `CLAUDE.md` instructs
  agents to do this.
- **One fact per file.** Use a kebab-case name and a short type tag in the body
  (`feedback`, `lesson`, `reference`, `decision`).
- **Promote, don't hoard.** When you learn a durable, generalizable lesson in a
  session, write it here and include it in your PR so the team inherits it.
  Volatile, task-local notes stay in your private `~/.claude` memory.
- **Changes go through PR review** like any other repo content — these files
  steer every agent, so they deserve scrutiny.

## Current entries

- `feedback_agb_orthogonality.md` — the hard rule set keeping this project
  orthogonal to AgentGraphBench (trace not graph; forward not backward; effect
  not answer; live not static cache). Referenced from `README.md` and `CLAUDE.md`.
- `lesson_zero_score_is_not_a_score.md` — a complete cell scoring 0% can be a
  model that never ran. Check `agent_call_count` and cost before believing any
  low number; exclude-and-explain beats relaxing determinism to get a number.
