# CLAUDE.md — working agreement for Claude Code in DynamicMCPBench

This file is auto-loaded into every Claude Code session in this repo. It is the
single source of truth for how agents (and humans) work here. **Read it fully
before changing anything.** For the full conceptual story and the project plan,
read `docs/CONCEPT.md`. For team-shared lessons, read everything under `memory/`
at session start.

## What this project is (north star)

DynamicMCPBench is a **trace-grounded** benchmark for LLM agents over live MCP
servers. We build it by *observing successful agent trajectories* on real
servers, distilling each into path-agnostic **effect checkpoints**, and grading
candidate agents on whether they reproduce those effects — **never** on
string-matching a final answer. The organizing primitive is the **execution
trace**, not a dependency graph; generation is **forward** (explore → distill),
not backward (sample a subgraph → back-instruct a question). This is a
deliberate, defended pivot away from AgentGraphBench (AGB); the rules that keep
us orthogonal to it live in `memory/feedback_agb_orthogonality.md`.

## Hard invariants — do NOT break these

These protect the scientific validity of the benchmark. A change that violates
one is wrong even if it runs. If a task seems to require breaking one, **stop and
raise it in the PR** instead of working around it.

1. **Never grade the final answer.** Scoring is effect-based (checkpoints). A
   `value_produced` checkpoint matches *evidence the spec demands*, never "is the
   answer correct". Do not add candidate-answer-vs-reference-answer comparison.
2. **The trace is the primitive.** Tasks come from real successful trajectories
   via forward exploration. Never introduce a pre-built tool dependency graph or
   back-instruction-from-a-graph — that is AGB's lane and breaks our story.
3. **Replay is deterministic and machine-independent.** No wall-clock,
   randomness, or network in scoring/replay paths. Fair multi-agent comparison
   MUST use `dmcp eval --replay`. Tier-2 fuzzy matching stays deterministic
   (`difflib`); the only model in the loop is the explicit Tier-2 judge.
4. **`stateful_write` servers must be sandboxed.** The `Manifest` validator
   enforces `sandbox=true`; never relax it. Exploration/refresh must not cause
   real side effects. `dmcp refresh` skips stateful_write unless
   `--refresh-stateful` (dangerous — only for a server you know is sandboxed).
5. **Never commit secrets.** API keys live only in `.env` (git-ignored). Copy
   `.env.example` → `.env`. Never hardcode, echo, or paste a key into code,
   commits, or chat.
6. **Never commit generated artifacts.** `traces/ specs/ evals/ reports/
   crawled/ goals/auto*.json manifests/crawled*.json` are git-ignored. Only
   hand-authored manifests and `goals/{local,scaled,recovery}.json` are tracked.
   Released datasets go to HuggingFace (roadmap), not the repo.
7. **Preserve the step-kind distinction.** `call_tool_agent` vs
   `call_tool_server_internal` — checkpoint counting filters on it; never collapse them.
8. **Structured, deterministic LLM calls.** The distiller, judge, and goal-gen
   drive the model via OpenAI tool-call schemas at `temperature=0`.
9. **Schema discipline.** Pydantic models that define on-disk data use
   `ConfigDict(extra="forbid")`. Any schema/behavior change bumps the relevant
   `*_version` (`SCHEMA_VERSION`, `SPEC_SCHEMA_VERSION`, `DISTILLER_VERSION`, …).

## Architecture map

The package is `dmcp/`. Each module maps to a pipeline phase (full story in
`docs/CONCEPT.md`, status in `README.md` roadmap):

| Module | Phase | Role |
|---|---|---|
| `trace.py`, `spec.py` | data model | `Trace`/`Step` (the primitive) and `TaskSpec` (checkpoints/minefields/ordering) |
| `discovery/`, `install.py`, `vet.py`, `manifest.py` | 1A — substrate | crawl MCP Registry → install → smoke-vet → manifest (with dynamism + sandbox) |
| `recorder.py`, `replay.py` | 1B — execution | live capture (`TraceRecorder`) + deterministic replay (`TraceReplayRecorder`), shared async surface |
| `explorer.py`, `goal_gen.py`, `goals.py` | 2A — exploration | goal-seeded forward exploration → traces |
| `distiller.py` | 2B — distillation | trace → `TaskSpec` via LLM tool-call schema |
| `evaluator.py` (Tier-1), `judge.py` (Tier-2) | 3 — evaluation | deterministic effect scoring + LLM effect-equivalence |
| `refresh.py` | 4 — living bench | re-run reference traces live, classify drift/decay |
| `report.py` | reporting | markdown leaderboard, stratified |
| `llm.py` | infra | OpenRouter client (default `anthropic/claude-haiku-4.5`) |
| `cli.py` | entry | `dmcp crawl/goal-gen/explore/distill/generate/eval/refresh/report/record` |

Live and replay recorders must stay drop-in interchangeable
(`__aenter__/__aexit__/list_tools/call_tool/.trace`).

## Code style

- Python ≥ 3.11; `from __future__ import annotations`; modern typing (`X | None`,
  `list[...]`, no `Optional`/`List`).
- **Ruff is the single source of truth.** Run `ruff check .` and
  `ruff format .`. Config in `pyproject.toml` (line-length 110; rules
  `E,F,I,UP,B,SIM`). Honor the documented ignores; don't silently widen them.
- Pydantic v2 for on-disk schemas: `ConfigDict(extra="forbid")`; discriminated
  unions via `Field(discriminator=...)` (see `spec.py` checkpoints).
- Async via `asyncio`/`anyio`; recorders are async context managers.
- **Docstring discipline (existing convention — match it):** every module
  docstring states its purpose *and* an explicit "Scope of v0 / out of scope"
  note. New modules follow suit.
- Keep dependencies lean — no new heavy dependency without discussion in the PR.
- Naming: `snake_case`; `server_id` slugs; namespaced tool names `server__tool`.

## Collaboration workflow (multiple Claudes, one repo)

- **One task → one short-lived branch** off the latest `main`
  (`feat/… | fix/… | docs/… | chore/…`). **Never commit to `main`.**
- `git pull --rebase origin main` before starting and before pushing.
- **Keep PRs small and single-purpose** so parallel agents don't collide. Don't
  refactor unrelated code in a feature PR.
- **Before every commit, this local gate is mandatory** (there is no CI yet):
  `ruff check . && ruff format --check . && pytest -q`.
- Imperative commit subjects (match the log: "Add …", "Expose …", "Tighten …").
  Include the Claude `Co-Authored-By:` trailer on agent-made commits.
- Update the `README.md` roadmap checkbox(es) and any touched docs in the **same** PR.
- If two agents need the same area, the open PR owns it — coordinate, don't double-edit.

## Shared memory protocol

- `memory/*.md` is **team-shared, committed, PR-reviewed** agent knowledge
  (invariants, hard-won lessons, the AGB orthogonality rule set). **Read it at
  session start.**
- When you learn a durable, generalizable lesson, **promote it to `memory/` via a
  PR** so every teammate's Claude inherits it. Per-user `~/.claude` memory is
  private scratch, not a substitute for committed team memory.

## Running & verifying

```bash
uv pip install -e ".[servers,dev]"     # dmcp + the substrate MCP servers + dev tools
cp .env.example .env                    # then set OPENROUTER_API_KEY (see .env.example)
ruff check . && ruff format --check . && pytest -q

# Smoke a single server (no benchmark run):
uv run dmcp record .venv/bin/python -t stdio -s time \
  --stdio-arg -m --stdio-arg mcp_server_time --stdio-arg --local-timezone --stdio-arg UTC \
  --tool get_current_time --args '{"timezone":"UTC"}'
```

`dmcp eval/explore/generate/crawl` make paid LLM/network calls — run them
deliberately, not as casual checks.

## Plan-first discipline

For any non-trivial change (3+ steps or an architectural decision), plan before
editing and keep the diff reviewable. Prefer the smallest change that satisfies
the task. When something goes sideways, stop and re-plan rather than pushing on.

## Autonomous development

This repo advances via a self-driving loop. The plan and claim ledger is
`docs/PLAN.md`; the runbook is the `/continue` slash command; the full protocol is
`docs/AUTONOMY.md`. To make progress, run `/continue` (or say «продолжи»): Claude
claims the next eligible step, implements its `done-when`, runs the gate, opens a
PR, and **auto-merges when green**, then marks the step done.

Conventions that keep parallel agents safe:
- **Never hand-edit step statuses** in `docs/PLAN.md` — `scripts/claim.py` and
  `scripts/mark.py` update them atomically (git push is the lock; the loser re-picks).
- One claimed step per agent; stay within its scope; the plan is dynamic (you may
  append/split/promote steps).
- **Blocked > forced**: unresolvable conflicts or ambiguity → `scripts/mark.py <id>
  blocked` and stop for a human. Never force a merge.
