# Decision: the autonomous /continue dev loop

**Type:** decision. **Audience:** every Claude in this repo.

The project advances via a single mechanism: **`docs/PLAN.md` (the living plan +
claim ledger) driven by the `/continue` runbook** (`.claude/commands/continue.md`)
and the helpers in `scripts/`. Full spec: `docs/AUTONOMY.md`.

**Key rules to remember:**
- Saying «продолжи» / `/continue` = claim the next eligible step, implement its
  `done-when`, gate (`scripts/check.sh`), open a PR, **auto-merge only when green**,
  then `mark.py <id> done`. **Exactly one step per invocation**, with human
  checkpoints: **announce the plan before starting**, and at the end **report +
  ask before continuing** (never auto-advance).
- **Never hand-edit step statuses** while working — `scripts/claim.py` /
  `scripts/mark.py` do it atomically (git push is the lock; losers re-pick). This is
  what makes parallel agents safe.
- **Plan changes need a human.** Adding/splitting/re-sequencing steps or promoting an
  Idea must be *proposed and confirmed* before editing `docs/PLAN.md`'s step set; the
  loop only updates statuses automatically. Aim: realize ideas from *all* docs → a paper.
- **Blocked > forced.** Unresolvable conflict / failing upstream / ambiguous spec →
  `mark.py <id> blocked "<reason>"` and stop for a human. Never force a merge.
- Graph/sampling are **baselines only**, never the headline — see
  [[feedback_agb_orthogonality]].

**How to apply:** when the user wants progress, run `/continue`. When you finish a
step, leave `docs/PLAN.md` accurate so the next agent (or you) resumes cleanly.
