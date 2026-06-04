"""E8.1 / B1: pricing + UsageAccumulator + cost_latency aggregator tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dmcp.llm import UsageAccumulator, delta_snapshot
from dmcp.pricing import compute_cost_usd, get_price

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import cost_latency  # noqa: E402  (script imported as a module for testing)

# ---------------------------------------------------------------------------
# pricing.py — math is the cheapest invariant to lock down.
# ---------------------------------------------------------------------------


def test_compute_cost_uses_per_mtok_rates():
    # Kimi K2.6: $0.68/M input, $3.42/M output → 1M each = $4.10
    assert abs(compute_cost_usd("moonshotai/kimi-k2.6", 1_000_000, 1_000_000) - 4.10) < 1e-9


def test_compute_cost_unknown_model_returns_zero():
    # Honest zero; the unknown_price flag rides separately on the accumulator.
    assert compute_cost_usd("acme/nonexistent-1.0", 1_000_000, 1_000_000) == 0.0


def test_compute_cost_fractional_tokens():
    p = get_price("openai/gpt-5.5")
    assert p is not None
    cost = compute_cost_usd("openai/gpt-5.5", 1_500, 750)
    expected = 1_500 / 1_000_000 * p.input_per_mtok + 750 / 1_000_000 * p.output_per_mtok
    assert abs(cost - expected) < 1e-12


# ---------------------------------------------------------------------------
# UsageAccumulator — additivity + unknown-price flag + delta semantics
# ---------------------------------------------------------------------------


def test_accumulator_sums_calls_tokens_wall_and_cost():
    acc = UsageAccumulator(model="qwen/qwen3.7-max")  # $1.25 / $3.75
    acc.add({"prompt_tokens": 1_000_000, "completion_tokens": 0}, wall_ms=12.5)
    acc.add({"prompt_tokens": 0, "completion_tokens": 1_000_000}, wall_ms=7.5)
    snap = acc.snapshot()
    assert snap["calls"] == 2
    assert snap["prompt_tokens"] == 1_000_000
    assert snap["completion_tokens"] == 1_000_000
    assert abs(snap["cost_usd"] - (1.25 + 3.75)) < 1e-9
    assert abs(snap["wall_ms_total"] - 20.0) < 1e-9
    assert snap["latencies_ms"] == [12.5, 7.5]
    assert snap["unknown_price"] is False


def test_accumulator_flips_unknown_price_for_unpinned_model():
    acc = UsageAccumulator(model="acme/nonexistent-1.0")
    acc.add({"prompt_tokens": 100, "completion_tokens": 50}, wall_ms=1.0)
    snap = acc.snapshot()
    assert snap["unknown_price"] is True
    assert snap["cost_usd"] == 0.0  # honest zero
    assert snap["calls"] == 1


def test_accumulator_unknown_price_only_flips_on_nonzero_tokens():
    # A chat call that returned a usage dict but with zero tokens shouldn't trip the flag.
    acc = UsageAccumulator(model="acme/nonexistent-1.0")
    acc.add({"prompt_tokens": 0, "completion_tokens": 0}, wall_ms=0.1)
    assert acc.snapshot()["unknown_price"] is False


def test_delta_snapshot_isolates_one_work_unit():
    # The candidate explorer accumulates across many specs on one client.
    # delta_snapshot lets us attribute cost to a single explore() call.
    acc = UsageAccumulator(model="qwen/qwen3.7-max")
    acc.add({"prompt_tokens": 100, "completion_tokens": 50}, wall_ms=10.0)
    before = acc.snapshot()
    acc.add({"prompt_tokens": 200, "completion_tokens": 80}, wall_ms=15.0)
    acc.add({"prompt_tokens": 50, "completion_tokens": 20}, wall_ms=5.0)
    after = acc.snapshot()
    d = delta_snapshot(before, after)
    assert d["calls"] == 2
    assert d["prompt_tokens"] == 250
    assert d["completion_tokens"] == 100
    assert abs(d["wall_ms_total"] - 20.0) < 1e-9
    assert d["latencies_ms"] == [15.0, 5.0]


# ---------------------------------------------------------------------------
# scripts/cost_latency.py — aggregator, Pareto, $ /correct, latency quantiles
# ---------------------------------------------------------------------------


def _eval_row(model: str, passed: bool, cost_usd: float, lat_ms: list[float]) -> dict:
    return {
        "candidate_model": model,
        "passed": passed,
        "summary": {
            "cost": {
                "prompt_tokens": 100 * len(lat_ms),
                "completion_tokens": 50 * len(lat_ms),
                "cost_usd": cost_usd,
                "wall_ms_total": sum(lat_ms),
                "latencies_ms": lat_ms,
                "unknown_price": False,
            }
        },
    }


def _write_jsonl(p: Path, rows: list[dict]) -> None:
    with p.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r))
            fh.write("\n")


def test_aggregate_groups_per_model_and_computes_cost_per_correct(tmp_path: Path):
    p = tmp_path / "evals.jsonl"
    _write_jsonl(
        p,
        [
            _eval_row("openai/gpt-5.5", True, 0.05, [100.0, 200.0]),
            _eval_row("openai/gpt-5.5", False, 0.04, [120.0]),
            _eval_row("qwen/qwen3.7-max", True, 0.01, [50.0]),
            _eval_row("qwen/qwen3.7-max", True, 0.01, [60.0]),
        ],
    )
    agg = cost_latency.aggregate([p])
    rows_by_model = {r["model"]: r for r in agg["models"]}
    gpt = rows_by_model["openai/gpt-5.5"]
    assert gpt["runs"] == 2
    assert gpt["passed"] == 1
    assert gpt["accuracy"] == 0.5
    assert abs(gpt["cost_usd"] - 0.09) < 1e-6
    assert abs(gpt["cost_per_correct_usd"] - 0.09) < 1e-6
    qwen = rows_by_model["qwen/qwen3.7-max"]
    assert qwen["runs"] == 2
    assert qwen["passed"] == 2
    assert qwen["accuracy"] == 1.0
    assert abs(qwen["cost_per_correct_usd"] - 0.01) < 1e-6
    # Sorted by $/correct ascending: cheap-per-correct first.
    assert agg["models"][0]["model"] == "qwen/qwen3.7-max"


def test_aggregate_handles_zero_correct_model_without_crash(tmp_path: Path):
    p = tmp_path / "evals.jsonl"
    _write_jsonl(p, [_eval_row("openai/gpt-5.5", False, 0.05, [100.0])])
    agg = cost_latency.aggregate([p])
    r = agg["models"][0]
    assert r["passed"] == 0
    assert r["cost_per_correct_usd"] is None  # honest "undefined", not infinity


def test_aggregate_skips_rows_without_cost_block(tmp_path: Path):
    # Older EvaluationResult rows (pre-E8.1) won't have summary.cost; they should
    # still count toward runs/passed but contribute 0 cost + empty latencies.
    p = tmp_path / "evals.jsonl"
    rows = [
        {
            "candidate_model": "openai/gpt-5.5",
            "passed": True,
            "summary": {"checkpoints_total": 1, "checkpoints_passed": 1},
        }
    ]
    _write_jsonl(p, rows)
    agg = cost_latency.aggregate([p])
    r = agg["models"][0]
    assert r["runs"] == 1 and r["passed"] == 1 and r["accuracy"] == 1.0
    assert r["cost_usd"] == 0.0
    assert r["latency_p50_ms"] == 0.0


def test_aggregate_latency_quantiles_use_per_call_latencies(tmp_path: Path):
    p = tmp_path / "evals.jsonl"
    # Latencies 10, 20, 30, 40, 50 → p50=30, p95=48.
    _write_jsonl(
        p,
        [
            _eval_row("openai/gpt-5.5", True, 0.01, [10.0, 20.0]),
            _eval_row("openai/gpt-5.5", True, 0.01, [30.0, 40.0, 50.0]),
        ],
    )
    agg = cost_latency.aggregate([p])
    r = agg["models"][0]
    assert r["latency_p50_ms"] == 30.0
    assert r["latency_p95_ms"] == 48.0


def test_pareto_frontier_drops_dominated_models():
    rows = [
        # (cost ↑, accuracy ↓ where dominated)
        {"model": "cheap-bad", "cost_usd": 0.01, "accuracy": 0.20},
        {"model": "cheap-mid", "cost_usd": 0.02, "accuracy": 0.50},  # dominates cheap-bad
        {"model": "mid-mid", "cost_usd": 0.05, "accuracy": 0.50},  # dominated by cheap-mid
        {"model": "expensive-best", "cost_usd": 0.10, "accuracy": 0.80},
    ]
    frontier = cost_latency._pareto_frontier(rows)
    assert frontier == ["cheap-bad", "cheap-mid", "expensive-best"]


# ---------------------------------------------------------------------------
# Evaluator surfaces cost from trace.seed_metadata into summary.cost
# ---------------------------------------------------------------------------


def test_evaluator_surfaces_cost_from_trace_seed_metadata():
    """E8.1: explorer stashes delta_snapshot under trace.seed_metadata['cost'];
    evaluator must lift it into EvaluationResult.summary['cost'] so the
    cost_latency aggregator can read directly from evals/*.jsonl rows."""
    import uuid as _uuid
    from datetime import UTC, datetime

    from dmcp.evaluator import evaluate
    from dmcp.manifest import Dynamism
    from dmcp.spec import ComplexityProfile, TaskSpec, ToolEffectCheckpoint, ToolReference
    from dmcp.trace import Step, StepKind, StepStatus, Trace

    spec = TaskSpec(
        source_trace_id=_uuid.uuid4(),
        prompt="ping",
        dynamism=Dynamism.live_read,
        servers_used=["s"],
        complexity=ComplexityProfile(
            trace_depth=1,
            distinct_servers=1,
            cross_server=False,
            runtime_branching=False,
            state_coupling=False,
            recovery_required=False,
        ),
        checkpoints=[
            ToolEffectCheckpoint(
                checkpoint_id="c0",
                description="x",
                equivalence_set=[ToolReference(server_id="s", tool_name="t")],
            )
        ],
    )
    tr = Trace(goal="g")
    now = datetime.now(UTC)
    tr.steps.append(
        Step.build(
            step_id=0,
            kind=StepKind.call_tool_agent,
            server_id="s",
            tool_name="t",
            started_at=now,
            ended_at=now,
            status=StepStatus.success,
        )
    )
    tr.seed_metadata["cost"] = {
        "model": "openai/gpt-5.5",
        "calls": 3,
        "prompt_tokens": 1234,
        "completion_tokens": 567,
        "cost_usd": 0.025,
        "wall_ms_total": 300.0,
        "latencies_ms": [80.0, 110.0, 110.0],
        "unknown_price": False,
    }
    ev = evaluate(spec, tr)
    assert "cost" in ev.summary
    assert ev.summary["cost"]["calls"] == 3
    assert ev.summary["cost"]["cost_usd"] == 0.025


def test_evaluator_omits_cost_key_when_trace_has_no_cost():
    import uuid as _uuid
    from datetime import UTC, datetime

    from dmcp.evaluator import evaluate
    from dmcp.manifest import Dynamism
    from dmcp.spec import ComplexityProfile, TaskSpec, ToolEffectCheckpoint, ToolReference
    from dmcp.trace import Step, StepKind, StepStatus, Trace

    spec = TaskSpec(
        source_trace_id=_uuid.uuid4(),
        prompt="ping",
        dynamism=Dynamism.live_read,
        servers_used=["s"],
        complexity=ComplexityProfile(
            trace_depth=1,
            distinct_servers=1,
            cross_server=False,
            runtime_branching=False,
            state_coupling=False,
            recovery_required=False,
        ),
        checkpoints=[
            ToolEffectCheckpoint(
                checkpoint_id="c0",
                description="x",
                equivalence_set=[ToolReference(server_id="s", tool_name="t")],
            )
        ],
    )
    tr = Trace(goal="g")
    now = datetime.now(UTC)
    tr.steps.append(
        Step.build(
            step_id=0,
            kind=StepKind.call_tool_agent,
            server_id="s",
            tool_name="t",
            started_at=now,
            ended_at=now,
            status=StepStatus.success,
        )
    )
    ev = evaluate(spec, tr)
    assert "cost" not in ev.summary  # nothing to surface; honest absence


def test_render_markdown_marks_frontier_and_unknown_price(tmp_path: Path):
    p = tmp_path / "evals.jsonl"
    rows = [
        _eval_row("openai/gpt-5.5", True, 0.05, [100.0]),
        _eval_row("acme/mystery-x", True, 0.0, [40.0]),  # zero cost, unknown price below
    ]
    rows[1]["summary"]["cost"]["unknown_price"] = True
    _write_jsonl(p, rows)
    md = cost_latency.render_markdown(cost_latency.aggregate([p]))
    assert "★" in md  # frontier marker present
    assert "price unknown" in md  # honest warning for unpinned model
