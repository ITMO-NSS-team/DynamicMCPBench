# A0 — Pipeline integration map (for DMCP Studio)

**Purpose.** The single map the studio backend is built against, so A1–A4 never
re-open "how do I call the pipeline?". Every entry point below was read from
source in `dmcp/` (no guessed signatures). The studio **wraps** these; it never
reimplements distillation or scoring (build plan §2, §10).

**Golden rule restated.** The pipeline computes **only the effect verdict**
(invariant #1: *never grade the final answer*). There is **no answer-matching
scorer anywhere in `dmcp/`** — see [§6](#6-scoring). The studio's
Effect⇄Answer toggle therefore computes `answer_pass` **studio-side, as a demo
foil only**, and it must never feed back into a benchmark verdict.

---

## 1. Data models — reuse directly, do not redefine

All are Pydantic v2 and importable. `models.py` should `import` these and add
only view-only fields (build plan §4).

| Model | Module | Notes |
|---|---|---|
| `TaskSpec` | `dmcp.spec` | `extra="forbid"`. Fields: `task_id: UUID`, `source_trace_id: UUID`, `prompt`, `dynamism`, `servers_used`, `complexity`, `checkpoints`, `minefields`, `ordering`, `notes`, `provenance`, `created_at`. `SPEC_SCHEMA_VERSION="0.2.0"`. |
| `Checkpoint` | `dmcp.spec` | Discriminated union on `kind`: `ToolEffectCheckpoint` \| `ValueProducedCheckpoint` \| `StateConditionCheckpoint`. |
| `ToolEffectCheckpoint` | `dmcp.spec` | `checkpoint_id`, `description`, `equivalence_set: list[ToolReference]`, `arg_predicate: ArgPredicate \| None`, `must_succeed=True`. **The `equivalence_set` is exactly the editable-chips UI.** |
| `ValueProducedCheckpoint` | `dmcp.spec` | `predicate: ValuePredicate`, `scope ∈ {any_tool_result, final_assistant_message}`. |
| `ToolReference`, `ArgPredicate`, `ArgValueMatch`, `ValuePredicate`, `Minefield`, `OrderConstraint`, `ComplexityProfile`, `CheckpointKind` | `dmcp.spec` | supporting types. |
| `Trace`, `Step` | `dmcp.trace` | `extra="allow"`. `Step.kind: StepKind`, `Step.server_id/tool_name/arguments/result/status`. `SCHEMA_VERSION="0.1.0"`. |
| `StepKind` | `dmcp.trace` | `list_tools` \| `call_tool_agent` \| `call_tool_server_internal`. **Checkpoint counting filters on `call_tool_agent`** (invariant #7) — never collapse. |
| `StepStatus` | `dmcp.trace` | `success` \| `error` \| `timeout`. Replay caches **only `success` `call_tool_agent`** steps. |
| `ServerFingerprint`, `ToolSpec`, `TransportKind` | `dmcp.trace` | tool surface + transport. |
| `Manifest`, `ServerEntry`, `Dynamism` | `dmcp.manifest` | `Dynamism ∈ {static, live_read, stateful_write}`. `ServerEntry.sandbox: bool`. |
| `EvaluationResult`, `CheckpointResult`, `MinefieldResult` | `dmcp.evaluator` | the score payload — see §6. |

---

## 2. Stage 1 — Collect

- **Load a manifest:** `Manifest.load(path: Path) -> Manifest`; iterate
  `m.servers` (`list[ServerEntry]`) for `ServerCard`s. Each entry carries
  `server_id`, `dynamism`, `sandbox`, `description`, `tags`, `tool_count`.
- **Dynamism tag for the UI:** `ServerEntry.dynamism` →
  `live-read` / `stateful-write` / `static`.
- **Live tool surface (LIVE only):**
  `dmcp.goal_gen._fetch_tool_specs(entry, *, timeout_s=25.0) -> list[ToolSpec]`
  (private but the CLI's collect path uses it).
- **Server→ServerConfig for live runs:** `m.configs(server_ids) -> list[ServerConfig]`
  (types in `dmcp.recorder`: `StdioServer`/`SseServer`/`StreamableHttpServer`).
- Adding *new* servers is `dmcp crawl` (`dmcp.discovery/`) — **out of scope for
  A1/A3**; the "bring your own server" stretch (A4) reuses the collector.

## 3. Stage 2 — Explore (forward generation)

- **Goal generation (LIVE):**
  `dmcp.goal_gen.generate_goals(*, manifest, server_ids, llm, single_per_server=2, cross_pairs=5, seed=0, use_personas=True) -> dmcp.goals.Goals`
  (a `Goals` object with `.entries`). Persona seeding is internal.
- **Explore:**
  `dmcp.explorer.explore(*, goal, servers=None, recorder=None, llm, system_prompt=DEFAULT_SYSTEM_PROMPT, budget=12, persona=None, tool_surface=None, ...) -> ExplorationResult`.
  **Exactly one** of `servers=` (live `TraceRecorder`) or `recorder=` (a
  pre-built recorder, e.g. `TraceReplayRecorder`).
  `ExplorationResult(trace, outcome, tool_call_count, successful_tool_calls, final_message, messages, cost)`.
  `outcome ∈ {completed, budget_exhausted, llm_error, no_tools_called}`.
- **Always call** `dmcp.explorer.stash_exploration_in_trace(result)` afterward —
  it writes `messages` + `final_message` into
  `trace.seed_metadata["exploration"]`, which `value_produced` /
  `final_assistant_message` checkpoints read at score time.
- **SSE streaming:** `explore()` runs a monolithic budget loop; there is no
  per-call callback hook. To stream call-by-call (build plan §4 `/api/explore`),
  the adapter wraps the recorder and intercepts `call_tool` to emit a `call`
  event per invocation — **wrap, don't patch `explore()`**.

## 4. Stage 3 — Distill

- `dmcp.distiller.distill(trace, *, llm, manifest=None, provenance=None) -> TaskSpec`.
- Raises `DistillationError` if the trace has **no successful agent tool calls**.
- Deterministic, temperature-0 tool-call schema (`emit_task_spec`),
  `max_tokens=16384`. `DISTILLER_VERSION="0.2.0"`.
- Output is a full `TaskSpec` — feed straight to the `/api/distill` response.

## 5. Stage 4 — Candidate run (the recipe to mirror)

The canonical wiring is `dmcp/cli.py::evaluate._single_run` (replay branch).
Reproduce exactly:

```python
ref = reference_index[str(spec.source_trace_id)]  # Trace
recorder = TraceReplayRecorder(  # dmcp.replay
    cache_traces=[ref],
    goal=spec.prompt,
    tier2_threshold=0.75,
    simulator_llm=None,  # Tier-3 OFF (determinism)
)
result = await explore(  # dmcp.explorer
    goal=spec.prompt,
    recorder=recorder,
    llm=OpenRouterClient(model=candidate_model),
    budget=12,
    tool_surface=optional_pool_surface,  # see §7
)
stash_exploration_in_trace(result)
ev = evaluate(
    spec,
    result.trace,  # dmcp.evaluator — §6
    candidate_model=candidate_model,
    evaluation_mode="replay",
    server_tags={e.server_id: e.tags for e in m.servers},
)
```

In REPLAY-only A1 the candidate trajectory comes from a **frozen fixture**, not
a live agent run — no LLM needed.

## 6. Scoring

- **Entry:** `dmcp.evaluator.evaluate(spec, candidate, *, candidate_model=None, evaluation_mode=None, server_tags=None) -> EvaluationResult`. **Fully deterministic** (invariant #3).
- **`EvaluationResult`:** `passed: bool` (the **effect** verdict),
  `checkpoint_results: list[CheckpointResult]` (`passed`, `reason`,
  `matched_step_id`, `tier`), `minefield_results`, `ordering_ok`,
  `summary` (carries `sae`, `iae`, `error_taxonomy`). This is the **only**
  verdict the pipeline produces.
- **There is NO `answer_pass` in the pipeline** — by design (invariant #1). The
  `/api/score` `done` event's `answer_pass` is **computed studio-side** as a
  contrast foil: a plain string check of the candidate's `final_message`
  against a stored reference answer, **for curated fixtures only**, clearly
  labelled demo-only. It must never reach an `EvaluationResult` or any committed
  benchmark number.
- **Tier-2 (optional, non-deterministic):**
  `dmcp.judge.upgrade_with_judge(checkpoints, trace, checkpoint_results, *, llm) -> list[CheckpointResult]`.
  Off the demo's critical path; headline verdict stays Tier-1.

## 7. Replay world + pools

- `TraceReplayRecorder(cache_traces: Iterable[Trace], *, goal=None, seed_metadata=None, tier2_threshold=0.75, simulator_llm=None)` — async ctx mgr with the live recorder's surface (`__aenter__/__aexit__/list_tools/call_tool/.trace`).
  Cache key = `(server_id, tool_name, canonical_args)` over **successful
  `call_tool_agent` steps only**. **In-memory, no disk/network** in the
  scoring path (invariant #3).
- Reference traces load from JSONL via `Trace.model_validate_json(line)`; specs
  link to their trace by `spec.source_trace_id`. The CLI helper is
  `_load_traces_by_id`.
- **Equivalence/distractor demo (A3/A4, optional):** `dmcp.pools.build_eval_pool`,
  `pool_to_tool_surface`, `ToolCatalog.from_traces` build the offered tool
  surface (gold/target/full, `p_alt`, `pool_size`). Toggling an equivalence-set
  member in the UI re-runs **Tier-1 `evaluate` only**.

## 8. Infra & safety

- **LLM:** `dmcp.llm.OpenRouterClient(model=...)`; `DEFAULT_MODEL="anthropic/claude-haiku-4.5"`. Needs `OPENROUTER_API_KEY` (`.env`). **LIVE stages only** — REPLAY touches no network.
- **Sandbox default-deny (build plan §10, invariant #4):** the `Manifest`
  validator already forces `stateful_write ⇒ sandbox=true`. The adapter adds a
  second gate: refuse to invoke any tool on a `stateful_write` server unless
  `ServerEntry.sandbox` is true. **A1 ships a test for this.**

---

## Assumptions / open questions

1. **`answer_pass` is studio-only.** Confirmed by absence of any answer scorer
   in `dmcp/` — recorded above as the design, not a guess.
2. **`dmcp.goals.Goals` shape** read only as `.entries`; revisit when wiring the
   LIVE `/api/goal` route (A3). REPLAY `/api/goal` serves a fixture goal.
3. **SSE granularity** comes from wrapping the recorder, since `explore()` has
   no per-call hook (§3). Confirmed by reading the explore loop.
4. **Studio location:** `dmcp-studio/` lives inside this repo (imports `dmcp`
   directly via the editable install); the demo *paper* stays in `paper_demo/`,
   so the build plan's `dmcp-studio/paper/` is intentionally omitted here.
