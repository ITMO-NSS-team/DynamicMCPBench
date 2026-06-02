# Autonomous development loop

This repo can drive itself toward the finished paper, one reviewed step at a time,
with several Claude Code agents working in parallel without colliding. This is the
human-readable spec; the executable runbook is the `/continue` slash command
(`.claude/commands/continue.md`), and the mechanics live in `scripts/`.

## The UX

```
git clone …/DynamicMCPBench && cd DynamicMCPBench
claude                       # start Claude Code
> продолжи        (or: /continue)
```

Claude picks the next unclaimed step from `docs/PLAN.md`, implements it, opens a
PR, and **auto-merges when the gate is green**, then stops (or loops if you ask).

## Source of truth: `docs/PLAN.md`

`docs/PLAN.md` is both the roadmap and the **claim ledger**. Each step is a block
with `status / owner / claimed_at / deps / source / done-when`. The
`status/owner/claimed_at` fields are the «плашка» that marks who is working on
what. **Don't hand-edit statuses while the loop runs** — `scripts/claim.py` and
`scripts/mark.py` update them atomically.

The plan may evolve toward realizing the ideas from **all** the planning docs
(`docs/CONCEPT.md`), but **changes to the step set need a human**: the loop
*proposes* new / split / re-sequenced steps (or promoting an Idea) and applies
them only after confirmation. The loop never self-edits the plan's structure — it
only updates step **statuses** atomically (claim / in_review / done / blocked).

## Cadence & human checkpoints

`/continue` runs **exactly one step**, with a human checkpoint on each side:

1. **Announce first.** After claiming, the agent states (2–4 lines) which step it
   took and how it will satisfy the `done-when` — *before* writing code.
2. **Implement → gate → PR → auto-merge** (below).
3. **Report & ask.** The agent summarizes what merged, says what it would do next,
   and **asks whether to continue** — it does not auto-advance. Progress resumes
   only when a human says «продолжи».

## How parallel agents stay out of each other's way

Git is the arbiter (an atomic ref update wins). To claim a step, `claim.py`:

1. `git fetch origin main && git reset --hard origin/main` (sync to the truth),
2. picks the first `todo` step whose `deps` are all `done`,
3. flips it to `claimed` (with owner + timestamp), commits, and **pushes to main**,
4. if the push is **rejected** (someone else pushed first), discards the local
   claim, re-syncs, and re-picks — looping until its push lands or nothing is left.

So two agents that grab the same step at the same moment can't both win: exactly
one push lands; the other re-picks the next eligible step. The claim is visible to
everyone on the next `git pull`.

## Merge policy

- Work happens on a per-step branch `feat/<id>-<slug>`; **never commit to `main`**
  except the tiny claim/mark ledger commits the scripts make.
- **Auto-merge requires the gate to be green:** `ruff check .` + `ruff format --check .`
  + `pytest -q` (`scripts/check.sh`). Format your changed files with
  `uv run ruff format <paths>` before committing.
- Merge is a squash via `gh pr merge --squash --delete-branch`.
- **Conflicts:** rebase the branch on `origin/main`, resolve, re-gate, re-merge.
- **Blocked:** anything unresolvable (bad conflict, failing upstream, ambiguous
  spec) → `scripts/mark.py <id> blocked "<reason>"` and **stop for a human**. The
  loop never forces a merge or hacks around a blocker.

## Prerequisites (per machine)

`scripts/bootstrap.sh` is idempotent and sets up most of it:

- **uv** — installed if missing; creates `.venv`; `uv pip install -e ".[servers,dev]"`.
- **gh** — must be authenticated (`gh auth login`) for PR + auto-merge. Bootstrap
  warns if not.
- **node/npx** — needed only for npm-based MCP servers (fs, memory, cyanheads).
- **`.env`** — `OPENROUTER_API_KEY` is required for pipeline steps (explore /
  distill / eval / generate). Code/test steps don't need it. Copy `.env.example`.

## Safety / guardrails

- One claimed step per agent at a time; stay within the step's `done-when` scope.
- Never force-push `main`; never commit secrets or generated artifacts (enforced by
  `.gitignore` + the `.env` deny in `.claude/settings.json`).
- Every code change ships tests; the gate is mandatory before any merge.
- Respect the hard invariants in `CLAUDE.md` and `memory/`. Graph/sampling work is
  permitted only as a clearly-labeled comparison **baseline**, never as the headline.

## Scripts

| Script | Does |
|---|---|
| `scripts/bootstrap.sh` | idempotent env setup; warns on missing prereqs |
| `scripts/agent_id.sh` | stable claim owner id (`name@host`) |
| `scripts/check.sh` | the gate: ruff check + ruff format --check + pytest |
| `scripts/claim.py` | atomically claim the next eligible step (race-safe) |
| `scripts/mark.py` | set a step's status on main (`in_review` / `done` / `blocked`) |

## Results rule

Experiments commit their findings. Any experiment / RQ / validation step writes a
report under `docs/experiments/<id>-<slug>.md` and commits it — **negative and
failed results included** (a fail is a finding, never silently dropped). Each
report states the question, method + reproduce command, a **pre-registered
decision rule**, the data, a `positive | neutral | negative` result, and the
conclusion. Raw artifacts stay git-ignored; only the report + distilled numbers
are committed. An empirical-claim step is not `done` until its report exists. Full
convention: `docs/experiments/README.md`.
