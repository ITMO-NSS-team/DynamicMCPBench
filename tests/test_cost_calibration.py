"""E8.0a: live-price fetch + cost calibration aggregator tests.

The `dmcp eval` dispatch in `scripts/cost_calibration.py` is paid LLM compute
— only the pure-Python halves (price parsing, per-model aggregation,
extrapolation, Pareto picker) are unit-tested here. End-to-end smoke uses
--skip-eval + --no-live-prices against fixtures so no subprocess or network.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import cost_calibration  # noqa: E402

from dmcp.openrouter_prices import (  # noqa: E402
    LivePrice,
    compute_cost_usd,
    get_effective_price,
    load_cache,
    parse_prices,
    save_cache,
)

# ---------------------------------------------------------------------------
# Live-price parsing
# ---------------------------------------------------------------------------


def test_parse_prices_converts_per_token_to_per_mtok():
    """OpenRouter's `pricing.prompt` is per-token USD as string. We multiply
    by 1e6 so the result matches `dmcp/pricing.py::ModelPrice` units."""
    payload = {
        "data": [
            {"id": "openai/gpt-5.5", "pricing": {"prompt": "0.000005", "completion": "0.00003"}},
            {"id": "minimax/minimax-m3", "pricing": {"prompt": "0.0000003", "completion": "0.0000012"}},
        ]
    }
    prices = parse_prices(payload)
    assert abs(prices["openai/gpt-5.5"].input_per_mtok - 5.0) < 1e-9
    assert abs(prices["openai/gpt-5.5"].output_per_mtok - 30.0) < 1e-9
    assert abs(prices["minimax/minimax-m3"].input_per_mtok - 0.30) < 1e-9
    assert abs(prices["minimax/minimax-m3"].output_per_mtok - 1.20) < 1e-9


def test_parse_prices_skips_partial_entries():
    """A model missing one pricing leg should be dropped, not crash the whole
    parse — OpenRouter's listing carries a long tail of preview tags."""
    payload = {
        "data": [
            {"id": "x/full", "pricing": {"prompt": "0.000001", "completion": "0.000003"}},
            {"id": "x/no-completion", "pricing": {"prompt": "0.000001"}},
            {"id": "x/non-numeric", "pricing": {"prompt": "free", "completion": "free"}},
            {"id": "x/missing-pricing"},
            {"pricing": {"prompt": "0.000001", "completion": "0.000003"}},  # no id
        ]
    }
    prices = parse_prices(payload)
    assert set(prices) == {"x/full"}


def test_parse_prices_handles_empty_payload():
    assert parse_prices({}) == {}
    assert parse_prices({"data": []}) == {}


# ---------------------------------------------------------------------------
# Cache round-trip
# ---------------------------------------------------------------------------


def test_save_then_load_cache_roundtrips(tmp_path: Path):
    prices = {"openai/gpt-5.5": LivePrice(5.0, 30.0), "minimax/minimax-m3": LivePrice(0.30, 1.20)}
    path = tmp_path / "prices.json"
    save_cache(prices, path)
    loaded = load_cache(path)
    assert loaded == prices


def test_load_cache_missing_file_is_empty(tmp_path: Path):
    assert load_cache(tmp_path / "no.json") == {}


# ---------------------------------------------------------------------------
# Effective-price fallback chain (live → static → None)
# ---------------------------------------------------------------------------


def test_get_effective_price_prefers_live_over_static():
    """When OR rotates a price the live table must win — the static `dmcp/pricing.py`
    table is for offline reproducibility, not as the source of truth at run time."""
    live = {"anthropic/claude-haiku-4.5": LivePrice(0.50, 2.50)}  # different from static 0.80/4.0
    p = get_effective_price("anthropic/claude-haiku-4.5", live)
    assert p.input_per_mtok == 0.50
    assert p.output_per_mtok == 2.50


def test_get_effective_price_falls_back_to_static_table():
    p = get_effective_price("anthropic/claude-haiku-4.5", {})
    # static entry: 0.80 / 4.0
    assert p.input_per_mtok == 0.80
    assert p.output_per_mtok == 4.0


def test_get_effective_price_returns_none_for_unknown_model():
    assert get_effective_price("acme/mystery-x", {}) is None


def test_compute_cost_usd_uses_live_then_static_then_zero():
    """Computed cost must respect the same fallback chain (math, not just lookup)."""
    live = {"alpha/x": LivePrice(2.0, 10.0)}
    # Live model.
    assert abs(compute_cost_usd("alpha/x", 1_000_000, 1_000_000, live) - 12.0) < 1e-9
    # Static fallback (haiku 0.80 / 4.0 → $4.80).
    assert abs(compute_cost_usd("anthropic/claude-haiku-4.5", 1_000_000, 1_000_000, live) - 4.80) < 1e-9
    # Honest zero on completely unknown.
    assert compute_cost_usd("acme/mystery-x", 1_000_000, 1_000_000, live) == 0.0


# ---------------------------------------------------------------------------
# Per-model aggregation
# ---------------------------------------------------------------------------


def _row(model: str, passed: bool, prompt: int, completion: int, latencies_ms: list[float]) -> dict:
    return {
        "candidate_model": model,
        "passed": passed,
        "summary": {
            "cost": {
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "cost_usd": 0.0,  # ignored — aggregator recomputes against live
                "wall_ms_total": sum(latencies_ms),
                "latencies_ms": latencies_ms,
                "unknown_price": False,
            }
        },
    }


def test_per_model_metrics_recomputes_cost_against_live_table():
    """Static `cost_usd` in the row is ignored — calibration must reflect
    today's prices, not the price at the original run's snapshot."""
    rows = [
        _row("alpha/x", True, 1_000_000, 0, [100.0]),
        _row("alpha/x", False, 1_000_000, 0, [120.0]),
    ]
    # Live: $2/Mtok input, $10/Mtok output → 1M input = $2 → mean = $2 per spec.
    live = {"alpha/x": LivePrice(2.0, 10.0)}
    m = cost_calibration._per_model_metrics(rows, live)
    assert m["runs"] == 2
    assert m["passed"] == 1 and m["accuracy"] == 0.5
    assert abs(m["mean_cost_usd"] - 2.0) < 1e-9
    # Token means are integer floor of the totals.
    assert m["mean_prompt_tokens"] == 1_000_000


def test_per_model_metrics_marks_unknown_price():
    rows = [_row("acme/mystery-x", True, 1_000, 500, [50.0])]
    m = cost_calibration._per_model_metrics(rows, live={})  # not in live and not in static
    assert m["unknown_price"] is True
    assert m["mean_cost_usd"] == 0.0


def test_per_model_metrics_empty_rows_returns_safe_zeros():
    m = cost_calibration._per_model_metrics([], live={})
    assert m["runs"] == 0
    assert m["accuracy"] == 0.0
    assert m["mean_cost_usd"] == 0.0


def test_per_model_metrics_latency_quantiles_use_per_call_data():
    rows = [
        _row("alpha/x", True, 100, 50, [10.0, 20.0]),
        _row("alpha/x", True, 100, 50, [30.0, 40.0, 50.0]),
    ]
    live = {"alpha/x": LivePrice(1.0, 1.0)}
    m = cost_calibration._per_model_metrics(rows, live)
    # Latencies: 10,20,30,40,50 → p50=30, p95=48.
    assert m["latency_p50_ms"] == 30.0
    assert m["latency_p95_ms"] == 48.0


# ---------------------------------------------------------------------------
# Extrapolation
# ---------------------------------------------------------------------------


def test_extrapolate_scales_cost_linearly_by_corpus_and_passk():
    metrics = {"mean_cost_usd": 0.05, "accuracy": 0.6}
    cells = cost_calibration.extrapolate(metrics, corpus_sizes=(600, 1100), pass_k=(1, 3))
    by = {(c["corpus_size"], c["pass_k"]): c for c in cells}
    # 600 × k1 = 600 × 0.05 = $30; 1100 × k3 = 1100 × 0.05 × 3 = $165.
    assert abs(by[(600, 1)]["projected_usd"] - 30.0) < 1e-9
    assert abs(by[(1100, 3)]["projected_usd"] - 165.0) < 1e-9
    # projected_correct holds at accuracy × corpus (single-axis, no k inflation).
    assert by[(600, 1)]["projected_correct"] == 360.0
    # $/correct: $30 / 360 = $0.0833...
    assert abs(by[(600, 1)]["projected_usd_per_correct"] - 30.0 / 360.0) < 1e-4


def test_extrapolate_handles_zero_accuracy_without_div_zero():
    metrics = {"mean_cost_usd": 0.05, "accuracy": 0.0}
    cells = cost_calibration.extrapolate(metrics, corpus_sizes=(100,), pass_k=(1,))
    assert cells[0]["projected_usd_per_correct"] is None  # honest "undefined"


# ---------------------------------------------------------------------------
# Pareto frontier (the recommended subset)
# ---------------------------------------------------------------------------


def test_pareto_frontier_keeps_each_step_up_in_accuracy():
    per_model = [
        {"model": "cheap-bad", "mean_cost_usd": 0.01, "accuracy": 0.20},
        {"model": "cheap-mid", "mean_cost_usd": 0.02, "accuracy": 0.50},  # beats cheap-bad
        {"model": "mid-mid", "mean_cost_usd": 0.05, "accuracy": 0.50},  # dominated
        {"model": "exp-best", "mean_cost_usd": 0.10, "accuracy": 0.80},  # beats cheap-mid
    ]
    frontier = cost_calibration._pareto_frontier(per_model)
    assert frontier == ["cheap-bad", "cheap-mid", "exp-best"]


def test_pareto_frontier_handles_empty_pool():
    assert cost_calibration._pareto_frontier([]) == []


# ---------------------------------------------------------------------------
# End-to-end smoke: --skip-eval + --no-live-prices over fixture
# ---------------------------------------------------------------------------


def test_skip_eval_end_to_end_smoke(tmp_path: Path):
    """Aggregator wired correctly through the script entry point — no LLM,
    no network, no subprocess to dmcp eval."""
    out = tmp_path / "calib"
    out.mkdir()
    # Two cells: cheap+low-acc, mid+high-acc → frontier = [both].
    with (out / "eval_alpha_x.jsonl").open("w", encoding="utf-8") as fh:
        for r in [
            _row("alpha/x", True, 1_000_000, 0, [100.0]),
            _row("alpha/x", False, 1_000_000, 0, [120.0]),
        ]:
            fh.write(json.dumps(r))
            fh.write("\n")
    with (out / "eval_beta_y.jsonl").open("w", encoding="utf-8") as fh:
        for r in [
            _row("beta/y", True, 1_000_000, 0, [50.0]),
            _row("beta/y", True, 1_000_000, 0, [55.0]),
        ]:
            fh.write(json.dumps(r))
            fh.write("\n")
    # Pre-cache a price table so --no-live-prices skips the network.
    save_cache(
        {"alpha/x": LivePrice(2.0, 10.0), "beta/y": LivePrice(5.0, 25.0)},
        out / "prices.json",
    )
    json_path = tmp_path / "numbers.json"
    script = Path(__file__).resolve().parent.parent / "scripts" / "cost_calibration.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--models",
            "alpha/x,beta/y",
            "--n",
            "2",
            "--specs",
            "/dev/null",
            "--reference-traces",
            "/dev/null",
            "--manifest",
            "/dev/null",
            "--out",
            str(out),
            "--json",
            str(json_path),
            "--prices-cache",
            str(out / "prices.json"),
            "--no-live-prices",
            "--corpus-sizes",
            "100",
            "--pass-k",
            "1",
            "--skip-eval",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "cost_calibration.md" in proc.stdout
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    by_model = {m["model"]: m for m in payload["models"]}
    # alpha/x: 1M input × $2/M = $2/spec → projected 100 specs × k1 = $200.
    cell_a = next(c for c in by_model["alpha/x"]["extrapolation"] if c["corpus_size"] == 100)
    assert abs(cell_a["projected_usd"] - 200.0) < 1e-6
    # Frontier: cheaper-and-correct beta beats alpha (50% < 100% acc, but at higher cost — so both stay).
    assert "alpha/x" in payload["recommended_subset"]
    assert "beta/y" in payload["recommended_subset"]
