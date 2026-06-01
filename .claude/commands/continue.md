---
description: Pick up the next unclaimed step in docs/PLAN.md and drive it to a merged PR (the autonomous dev loop).
---

You are advancing DynamicMCPBench autonomously. Follow this loop **exactly**.
Read `CLAUDE.md`, `docs/CONCEPT.md`, `docs/AUTONOMY.md`, and every `memory/*.md`
first — the hard invariants there are non-negotiable. The goal is to realize the
ideas from **all** the docs and reach a finished paper.

**Cadence (strict):** do **exactly one** step per `/continue`. Announce your plan
*before* you start, and at the end report what you did, say what you'd do next, and
**ask the human before continuing** — never auto-advance to the next step. Stop and
report immediately if you hit a blocker.

**Plan changes need a human.** The plan may evolve, but if the work suggests new,
split, or re-sequenced steps (or promoting an Idea from the backlog), **propose it
and wait for confirmation** before editing the step set in `docs/PLAN.md`. Atomic
status updates via `claim.py`/`mark.py` are not plan changes.

### 0. Sync & bootstrap
```
export PATH="$HOME/.local/bin:$PATH"
git switch main && git pull --rebase origin main
bash scripts/bootstrap.sh        # idempotent: uv, venv, deps; warns on missing node/gh/.env
```
If `bootstrap.sh` warns that `gh` is unauthenticated, stop and ask the human to
run `gh auth login` (the loop needs it to open/merge PRs).

### 1. Claim the next step (race-safe)
```
python3 scripts/claim.py
```
- Prints `CLAIMED <id>` + the step block, or `NONE` (then stop — nothing eligible).
- `claim.py` already handles the parallel-agent race: it commits the claim to
  `main` and pushes; if another agent won the race it re-syncs and re-picks. Trust
  its output — the step it printed is yours.
- **Then announce** (before any code): post 2–4 lines — the claimed step id and how
  you'll satisfy its `done-when`.

### 2. Branch & implement
```
git switch -c feat/<id>-<short-slug>
```
- Implement **exactly** the step's `done-when`, nothing more. Keep the diff small
  and in scope. Match the codebase style in `CLAUDE.md`.
- **Add or extend tests** under `tests/` for any code change.
- Never violate the hard invariants (no final-answer grading; trace is the
  primitive; deterministic replay; sandboxed stateful_write; no secrets/artifacts
  committed). Graph/sampling work is allowed only as a **labeled baseline**, never
  as the headline path (`memory/feedback_agb_orthogonality.md`).

### 3. Gate
```
bash scripts/check.sh            # ruff check + pytest -q (ruff format advisory until PLAN CC.3)
```
Fix until green. Run `uv run ruff format <your changed files>` so new code stays
formatted (a repo-wide format baseline is its own step, CC.3).

### 4. Commit, PR, auto-merge
```
git add -A && git commit -m "<imperative subject>"   # + Claude Co-Authored-By trailer
git push -u origin feat/<id>-<short-slug>
gh pr create --fill --base main
python3 scripts/mark.py <id> "in_review (#<pr-number>)"
gh pr merge --squash --delete-branch <pr-number>
```
- **Auto-merge only when the gate is green.**
- **If the merge reports a conflict:** `git fetch origin main && git rebase origin/main`,
  resolve the conflict, re-run the gate, `git push --force-with-lease`, retry the merge.
- **If genuinely stuck** (unresolvable conflict, failing upstream, ambiguous spec):
  `python3 scripts/mark.py <id> blocked "<one-line reason>"` and **stop, reporting
  to the human**. Do not force or hack around a blocker.

### 5. Close out
```
git switch main && git pull --rebase origin main
python3 scripts/mark.py <id> done
```
Optionally refine `docs/PLAN.md` (new/again-sequenced steps, promoted ideas) — use
the same claim-style commit-and-push so concurrent agents stay consistent.

### 6. Report & ask
Summarize what merged (step id, PR #, what changed), state what you'd do next (the
next eligible step), and **ask whether to continue. Do not auto-proceed** to the
next step — wait for the human's «продолжи».
