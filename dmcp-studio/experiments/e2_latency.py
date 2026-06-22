#!/usr/bin/env python3
"""E2 — per-stage latency budget for the booth (which stages run live vs replay).

The booth runs in REPLAY (the default, graded path; live-explore is blocked by an
upstream dependency regression — see docs/experiments/studio-e2-latency.md and the
A3 blocker note). E2 measures the REPLAY studio path the booth actually exhibits:
per-stage request compute through the real FastAPI routes (SSE pacing disabled so
we time compute, not the cosmetic inter-event delay), the deterministic evaluator
compute distribution over the 118-pair battery, and the cold fixture load. All
deterministic, no network, no LLM.

Run:  uv run python dmcp-studio/experiments/e2_latency.py
Out:  experiments/results/e2_latency.json  (+ a printed summary)
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

STUDIO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STUDIO))
sys.path.insert(0, str(STUDIO / "experiments"))

import e1_agreement as e1  # noqa: E402  (reuse the deterministic candidate battery)
from backend import dmcp_adapter as adapter  # noqa: E402
from backend import replay_store  # noqa: E402
from backend.app import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

RESULTS = STUDIO / "experiments" / "results"
N = 200  # iterations per stage
INTERACTIVE_MS = 2000.0  # per-action compute bar
COLD_START_MS = 30_000.0  # cold-start-to-first-verdict bar (A5)

client = TestClient(app)


def _pct(xs: list[float], p: float) -> float:
    s = sorted(xs)
    k = max(0, min(len(s) - 1, round((p / 100) * (len(s) - 1))))
    return s[k]


def _bench(label: str, fn, n: int = N) -> dict:
    fn()  # warm
    samples = []
    for _ in range(n):
        t0 = time.perf_counter_ns()
        fn()
        samples.append((time.perf_counter_ns() - t0) / 1e6)  # ms
    return {
        "stage": label,
        "median_ms": round(_pct(samples, 50), 3),
        "p95_ms": round(_pct(samples, 95), 3),
        "n": n,
    }


def stage_benches() -> list[dict]:
    """Per-stage REPLAY request compute through the real routes (delay=0)."""
    return [
        _bench("servers", lambda: client.get("/api/servers?mode=replay")),
        _bench("goal", lambda: client.post("/api/goal?mode=replay", json={"server_ids": ["yfinance"]})),
        _bench("explore (SSE)", lambda: client.get("/api/explore?mode=replay&delay=0")),
        _bench("distill", lambda: client.post("/api/distill?mode=replay", json={"trace_id": None})),
        _bench("score (SSE)", lambda: client.get("/api/score?candidate=hermes3-8b&delay=0")),
        _bench("leaderboard", lambda: client.get("/api/leaderboard?mode=replay")),
    ]


def evaluator_distribution() -> dict:
    """Deterministic evaluator compute over the 118-pair battery (the graded path)."""
    spec = e1.SPEC
    traces = e1.build_battery()
    samples = []
    for t in traces:
        t0 = time.perf_counter_ns()
        adapter.score_pair(spec, t, answer_looks_right=False)
        samples.append((time.perf_counter_ns() - t0) / 1e6)
    return {
        "pairs": len(traces),
        "median_ms": round(_pct(samples, 50), 3),
        "p95_ms": round(_pct(samples, 95), 3),
        "max_ms": round(max(samples), 3),
    }


def cold_fixture_load() -> float:
    """Cold fixture parse (cleared lru_cache) — the one-time studio warm-up cost."""
    replay_store.load_showcase.cache_clear()
    replay_store.load_leaderboard.cache_clear()
    t0 = time.perf_counter_ns()
    replay_store.load_showcase()
    return (time.perf_counter_ns() - t0) / 1e6


def main() -> int:
    cold_ms = cold_fixture_load()
    stages = stage_benches()
    ev = evaluator_distribution()

    by = {s["stage"]: s for s in stages}
    # cold-start to first verdict ≈ cold fixture load + one full score request
    first_verdict_ms = round(cold_ms + by["score (SSE)"]["median_ms"], 3)
    slowest_action = max(s["p95_ms"] for s in stages)

    summary = {
        "experiment": "E2",
        "mode": "replay (booth path; live-explore blocked — see A3 blocker)",
        "iterations_per_stage": N,
        "stages": stages,
        "evaluator_over_battery": ev,
        "cold_fixture_load_ms": round(cold_ms, 3),
        "cold_start_to_first_verdict_ms": first_verdict_ms,
        "interactive_bar_ms": INTERACTIVE_MS,
        "cold_start_bar_ms": COLD_START_MS,
        "passes_interactive_bar": bool(slowest_action < INTERACTIVE_MS),
        "passes_cold_start_bar": bool(first_verdict_ms < COLD_START_MS),
        "note": (
            "Reported times are request COMPUTE (SSE inter-event pacing disabled). "
            "The booth UI adds a cosmetic ~0.45s/call pacing delay (configurable). "
            "LIVE goal/explore are not timed: live-explore is blocked upstream and "
            "the booth runs REPLAY for every stage."
        ),
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "e2_latency.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("=== E2: REPLAY booth-path latency (compute; pacing disabled) ===")
    for s in stages:
        print(f"  {s['stage']:16} median {s['median_ms']:8.3f} ms   p95 {s['p95_ms']:8.3f} ms")
    print(
        f"  evaluator/pair    median {ev['median_ms']:8.3f} ms   p95 {ev['p95_ms']:8.3f} ms"
        f"  (n={ev['pairs']})"
    )
    print(f"  cold fixture load        {cold_ms:8.3f} ms")
    print(
        f"  cold→first verdict       {first_verdict_ms:8.3f} ms  (bar {COLD_START_MS:.0f} ms → "
        f"{'PASS' if summary['passes_cold_start_bar'] else 'FAIL'})"
    )
    print(
        f"  slowest action p95       {slowest_action:8.3f} ms  (bar {INTERACTIVE_MS:.0f} ms → "
        f"{'PASS' if summary['passes_interactive_bar'] else 'FAIL'})"
    )
    print(f"wrote {RESULTS / 'e2_latency.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
