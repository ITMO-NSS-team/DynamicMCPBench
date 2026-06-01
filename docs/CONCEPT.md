# Concept, lineage, and plan

This is the canonical "why" behind DynamicMCPBench, distilled so that any
contributor — human or Claude — has the full context without access to the
original private planning documents. Read this once; it explains why the code
looks the way it does and which directions are dead ends.

`CLAUDE.md` holds the operational rules; this file holds the reasoning.

---

## 1. The problem we measure

LLM agents increasingly run over **many MCP servers at once**. Two empirical
facts motivate the project:

- **Tool selection breaks at scale.** Clients cap concurrent tools (Cursor ≈ 40,
  Copilot 128); registries list ~15–16k public servers. Agents must pick the
  right tool among many semantically overlapping ones.
- **Server attribution error (SAE).** When GitHub and GitLab both expose
  `search_issues`, an agent often calls the *right kind* of tool on the *wrong
  server*. No mainstream benchmark isolates this from plain wrong-tool error.

A second, deeper problem is **how you grade**. Most benchmarks compare a final
answer string or a ground-truth tool list. On live, stateful tools (weather,
prices, wikis, databases) the "right answer" changes between runs, and
ground-truth tool lists are ~50% noise (AGB's own finding). Answer-matching
therefore mis-ranks agents on exactly the tools agents actually use.

## 2. Three revisions of the idea (and why we are where we are)

The design went through three conceptual revisions. **Only rev.3 is
implemented. Do not reintroduce rev.1 or rev.2 mechanics.**

### rev.1 — graph-based (superseded)
Build a *tool dependency graph* from connected servers (alternative / dependency
/ sibling edges), mine structural patterns (cliques, paths, dependency stars),
and generate questions from those patterns. Central metric: SAE. Elegant, but
graph construction from real servers is hard (≥99% of servers expose no
`outputSchema`), and — decisively — a sister NeurIPS submission,
**AgentGraphBench (AGB)**, now *owns the graph lane*. Competing there is a losing
position.

### rev.2 — sampling-based MVP (superseded)
Drop the full graph; instead sample distractors around a target tool with six
strategies (random, hard-negative, cross-domain, same-name collision, sibling,
stratified) and build accuracy-vs-distractor-density curves. Simpler, but still
imposes structure onto invented questions and still leans on answer/plan
matching. Dropped in favor of letting structure *emerge* from real execution.

### rev.3 — trace-native (CURRENT — this is what we build)
Abandon both graph and sampling. **Explore live servers forward, record
successful execution traces, and treat the trace as ground truth.** Each trace is
distilled into a path-agnostic `TaskSpec`:

- **prompt** — fuzzy natural-language goal, tool names stripped but concrete
  context (paths, URLs, ids) preserved.
- **checkpoints** — effects that must hold (`tool_effect` with an
  `equivalence_set` of acceptable tools + optional `ArgPredicate`;
  `value_produced` substring/regex over a result or the final message).
- **minefields** — effects that must NOT occur (immediate fail).
- **ordering** — partial order, only where one effect truly depends on a prior one.
- **complexity** — emergent features (depth, cross-server, runtime branching,
  state coupling, recovery) for stratification.
- **dynamism** — `static / live_read / stateful_write`.

Agents are scored on **effect alignment**, never the final answer — which is what
makes the benchmark robust to live/changing data and sidesteps the
ground-truth-tool-noise problem by construction (every tool in a trace was
actually invoked).

## 3. The four orthogonality pillars

Every design choice must keep these true (full rule set:
`memory/feedback_agb_orthogonality.md`):

1. **Trace, not graph** — the primitive is a recorded trajectory.
2. **Forward, not backward** — explore → distill, never sample-subgraph → back-instruct.
3. **Effect, not answer** — grade reproduced effects, never a final-answer string.
4. **Live, not static cache** — substrate is live/stateful servers; a refresh
   protocol measures decay instead of freezing the world.

## 4. Phase map: plan → code → status

| Plan phase | Code | Status (see README roadmap) |
|---|---|---|
| 1A live corpus | `discovery/`, `install.py`, `vet.py`, `manifest.py` | done; 16-server substrate |
| 1B dual-mode env | `recorder.py`, `replay.py` | done; Tier-1 + Tier-2 replay; Tier-3 LLM simulator TODO |
| 2A forward exploration | `explorer.py`, `goal_gen.py` | done; persona library TODO |
| 2B distillation | `distiller.py`, `spec.py` | done |
| 3 evaluation | `evaluator.py`, `judge.py`, `report.py` | Tier-1/2 done; Tier-3 capability profile + pass^k TODO |
| 4 living benchmark | `refresh.py` | refresh done; decay metrics over time TODO |
| 5 paper + release | — | corpus scale-up + HF release + human validation TODO |

## 5. Research questions (drive the paper, target EMNLP 2026 Industry Track)

- **RQ1 (headline):** Does answer-matching mis-rank agents on dynamic-data tasks,
  and does trace alignment fix it?
- **RQ2:** Does forward exploration yield more realistic / diverse / executable
  tasks than backward graph-sampling (AGB) or direct generation (MCPEval)?
- **RQ3:** Which emergent trace properties (depth, branching, state-coupling,
  cross-server, dynamism) predict agent failure?
- **RQ4:** How reliable is trace-based scoring versus human judgment?

## 6. Source documents

The essence above is distilled from the team's private planning set: the
graph-based technical description (rev.1 PDF), the sampling MVP spec (rev.2), the
field survey of 50+ MCP/tool benchmarks, and the rev.3 trace-native research
plan. Those originals are not in the repo; this file is their in-repo successor.
Keep it in sync when the direction changes.
