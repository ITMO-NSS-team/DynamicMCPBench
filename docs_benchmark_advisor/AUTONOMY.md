# Benchmark Advisor autonomous work protocol

This file mirrors the role of `docs/AUTONOMY.md` for the advisor module. It
describes how Codex, Claude Code, Cursor, and human contributors should advance
`docs_benchmark_advisor/PLAN.md` without constant coordination.

The advisor-local plan is intentionally compatible with the style of
`docs/PLAN.md`, but it is not currently wired into `scripts/claim.py` or the
global `/continue` loop. If the team wants full automation later, promote these
steps into the global ledger or extend the claim scripts after human approval.

## The UX

```text
read docs_benchmark_advisor/CONCEPT.md
read docs_benchmark_advisor/PLAN.md
read docs_benchmark_advisor/planning/INTERFACES.md
read your assigned docs_benchmark_advisor/planning/TASKS/*.md
implement exactly one step in one PR
```

Each contributor should be able to work from repository files, `AGENTS.md`,
`docs_benchmark_advisor/planning/INTERFACES.md`, and their own task packet.

## Source of truth

`docs_benchmark_advisor/PLAN.md` is the advisor roadmap and claim ledger. It
orders the work into epics and uses the same step fields as the main plan:

```text
status / owner / claimed_at / deps / source / done-when
```

Detailed implementation boundaries live in task packets under
`docs_benchmark_advisor/planning/TASKS/`. When a step and a task packet appear to
conflict, treat `planning/INTERFACES.md` and the task packet as the
implementation contract, then update `PLAN.md` in the same PR to remove
ambiguity.

## Cadence

One step equals one PR.

1. Announce which `BA*` step you are taking and which task packet it maps to.
2. Stay inside the allowed files/directories declared by that task.
3. Add the required tests from the task packet.
4. Run the smallest meaningful local checks, and the full gate before a merge PR
   when feasible.
5. Report what changed, what was verified, and which step should be next.

## Branch and PR policy

- Use short-lived branches such as `feat/ba1-1-core-schema` or
  `docs/ba0-advisor-plan`.
- Keep PRs single-purpose and aligned with one `BA*` step.
- Do not edit unrelated `dmcp`, Studio, script, or documentation files unless
  the assigned task explicitly allows it.
- Schema-breaking changes after the contract steps require an integration
  decision and updates to affected task packets.

## Local gate

For implementation PRs, follow the repo gate:

```bash
ruff check .
ruff format --check .
pytest -q
```

Documentation-only PRs should at minimum run:

```bash
git diff --check -- docs_benchmark_advisor
```

and manually verify links/paths with `rg` when paths are renamed.

## Parallelism rules

- Contract steps land first.
- Schema and statistical-guide work can proceed in parallel after the planning
  ledger is accepted.
- Fixtures start after statistical guide rule ids are stable.
- Planner, validator, planning statistics, and fixture-backed UI can proceed in
  parallel after their dependencies land.
- API/export integration waits for core components.
- Hardening waits for an end-to-end smoke.

## Safety and scope guardrails

- Do not launch generation or evaluation from advisor work.
- Do not add final-answer grading.
- Do not weaken DynamicMCPBench trace/effect scoring invariants.
- Do not make Stage 2 report implementation part of v1.
- Do not let UI invent fields outside `planning/INTERFACES.md`.
- Do not let the planner make unsupported statistical claims outside
  `planning/STATISTICAL_GUIDE.md`.
- Do not bypass deterministic validation.

## Blocking

If a task needs a schema-breaking change, a new v1 route, a new
statistical-guide rule family, or a change to launch behavior, stop and ask for
human approval. Blocked is better than quietly changing the scientific contract.
