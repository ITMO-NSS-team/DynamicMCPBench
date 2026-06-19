#!/usr/bin/env python3
"""E3 — curate & freeze the showcase REPLAY fixture for DMCP Studio.

Builds the AAPL/MSFT/GOOGL worked example (the paper's default) as *real*
``dmcp`` objects — a reference ``Trace``, a distilled ``TaskSpec``, and three
candidate ``Trace``s — then **asserts** that the deterministic ``evaluate()``
produces the three showcase verdicts before writing the frozen fixture:

  1. clean pass via an equivalence-set tool (``get_price_history``);
  2. answer-pass / effect-fail (skips the income statement — incomplete
     aggregation);
  3. answer-fail / effect-pass (correct run; live numbers drifted).

The fixture is loaded at request time by the backend, which runs the SAME
``evaluate()`` on it — so REPLAY exercises the real scorer deterministically.
``answer_pass`` is a studio-side demo foil only (see INTEGRATION_NOTES §6); it
is carried per-candidate as ``answer_looks_right`` and never scored by ``dmcp``.

Run:  uv run python dmcp-studio/experiments/e3_curate.py
Output: dmcp-studio/backend/fixtures/showcase_aapl.json  (+ leaderboard.json)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from dmcp.evaluator import evaluate
from dmcp.spec import (
    ArgPredicate,
    ComplexityProfile,
    TaskSpec,
    ToolEffectCheckpoint,
    ToolReference,
    ValuePredicate,
    ValueProducedCheckpoint,
)
from dmcp.trace import (
    ServerFingerprint,
    Step,
    StepKind,
    StepStatus,
    ToolSpec,
    Trace,
    TransportKind,
)

FIXTURES = Path(__file__).resolve().parent.parent / "backend" / "fixtures"

# Deterministic clock — no wall-clock in the fixture (invariant #3).
_T0 = datetime(2026, 1, 2, 15, 0, 0, tzinfo=UTC)
SERVER = "yfinance"
REF_TRACE_ID = UUID("11111111-1111-1111-1111-111111111111")
TASK_ID = UUID("22222222-2222-2222-2222-222222222222")

YF_TOOLS = [
    ("get_tickers_info", "Latest quote/ticker info for symbols."),
    ("get_earnings", "Quarterly or annual earnings for a symbol."),
    ("download", "Download OHLCV price history for symbols over a period."),
    ("get_price_history", "Price history for a symbol over a period."),
    ("get_financials", "Balance-sheet / income-statement financials."),
]


def _result(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": False}


def _step(i: int, tool: str, args: dict, text: str) -> Step:
    return Step.build(
        step_id=i,
        kind=StepKind.call_tool_agent,
        server_id=SERVER,
        tool_name=tool,
        arguments=args,
        result=_result(text),
        started_at=_T0,
        ended_at=_T0,
        status=StepStatus.success,
    )


def _fingerprint() -> ServerFingerprint:
    return ServerFingerprint(
        server_id=SERVER,
        transport=TransportKind.stdio,
        endpoint="stdio:yfinance",
        tool_count=len(YF_TOOLS),
    )


def _tool_specs() -> dict[str, list[ToolSpec]]:
    return {SERVER: [ToolSpec(name=n, description=d) for n, d in YF_TOOLS]}


def _make_trace(trace_id: UUID, steps: list[Step], final_message: str) -> Trace:
    t = Trace(
        trace_id=trace_id,
        goal=GOAL,
        servers=[_fingerprint()],
        tool_specs=_tool_specs(),
        steps=steps,
        started_at=_T0,
        ended_at=_T0,
    )
    # value_produced/final_assistant_message reads this (stash_exploration_in_trace shape).
    t.seed_metadata["exploration"] = {
        "outcome": "completed",
        "final_message": final_message,
        "successful_tool_calls": sum(1 for s in steps if s.kind is StepKind.call_tool_agent),
    }
    return t


GOAL = (
    "Compare the financial health and recent performance of Apple (AAPL), "
    "Microsoft (MSFT), and Google (GOOGL): latest ticker information, most "
    "recent quarterly earnings, and one year of price history."
)
PERSONA = "A retail investor comparing three large-cap tech stocks before rebalancing."


def reference_steps() -> list[Step]:
    return [
        _step(
            0,
            "get_tickers_info",
            {"symbols": ["AAPL", "MSFT", "GOOGL"]},
            "AAPL 201.5; MSFT 430.1; GOOGL 178.2",
        ),
        _step(
            1, "get_earnings", {"symbol": "AAPL", "period": "quarterly"}, "AAPL Q earnings: EPS 1.53, beat"
        ),
        _step(
            2, "get_earnings", {"symbol": "MSFT", "period": "quarterly"}, "MSFT Q earnings: EPS 3.05, beat"
        ),
        _step(
            3, "get_earnings", {"symbol": "GOOGL", "period": "quarterly"}, "GOOGL Q earnings: EPS 2.12, beat"
        ),
        _step(
            4, "download", {"symbols": ["AAPL", "MSFT", "GOOGL"], "period": "1y"}, "1y OHLCV for 3 symbols"
        ),
        _step(
            5,
            "get_financials",
            {"stmt": "balance", "period": "yearly"},
            "Balance sheets: cash, debt, equity per company",
        ),
        _step(
            6,
            "get_financials",
            {"stmt": "income", "period": "yearly"},
            "Income statements: revenue, net income per company",
        ),
    ]


def make_spec() -> TaskSpec:
    cps = [
        ToolEffectCheckpoint(
            checkpoint_id="cp1",
            description="Look up latest ticker info for the three symbols.",
            equivalence_set=[ToolReference(server_id=SERVER, tool_name="get_tickers_info")],
        ),
        ToolEffectCheckpoint(
            checkpoint_id="cp2",
            description="Pull the most recent quarterly earnings.",
            equivalence_set=[ToolReference(server_id=SERVER, tool_name="get_earnings")],
            arg_predicate=ArgPredicate(must_include={"period": "quarterly"}),
        ),
        ToolEffectCheckpoint(
            checkpoint_id="cp3",
            description="Retrieve one year of price history (any equivalent tool).",
            equivalence_set=[
                ToolReference(server_id=SERVER, tool_name="download"),
                ToolReference(server_id=SERVER, tool_name="get_price_history"),
            ],
            arg_predicate=ArgPredicate(must_include={"period": "1y"}),
        ),
        ToolEffectCheckpoint(
            checkpoint_id="cp4",
            description="Read the balance sheet.",
            equivalence_set=[ToolReference(server_id=SERVER, tool_name="get_financials")],
            arg_predicate=ArgPredicate(must_include={"stmt": "balance"}),
        ),
        ToolEffectCheckpoint(
            checkpoint_id="cp5",
            description="Read the income statement.",
            equivalence_set=[ToolReference(server_id=SERVER, tool_name="get_financials")],
            arg_predicate=ArgPredicate(must_include={"stmt": "income"}),
        ),
        ValueProducedCheckpoint(
            checkpoint_id="cp6",
            description="Final answer surfaces earnings and balance-sheet evidence.",
            predicate=ValuePredicate(contains_all=["earnings", "balance"]),
            scope="final_assistant_message",
        ),
    ]
    return TaskSpec(
        task_id=TASK_ID,
        source_trace_id=REF_TRACE_ID,
        prompt=GOAL,
        dynamism="live_read",
        servers_used=[SERVER],
        complexity=ComplexityProfile(
            trace_depth=7,
            distinct_servers=1,
            cross_server=False,
            runtime_branching=False,
            state_coupling=False,
            recovery_required=False,
        ),
        checkpoints=cps,
    )


def candidate_clean() -> Trace:
    """qwen3.7-max — clean pass, reaches cp3 via get_price_history (equivalence set)."""
    steps = [
        _step(0, "get_tickers_info", {"symbols": ["AAPL", "MSFT", "GOOGL"]}, "AAPL 201; MSFT 430; GOOGL 178"),
        _step(1, "get_earnings", {"symbol": "AAPL", "period": "quarterly"}, "AAPL EPS 1.53"),
        _step(2, "get_earnings", {"symbol": "MSFT", "period": "quarterly"}, "MSFT EPS 3.05"),
        _step(3, "get_earnings", {"symbol": "GOOGL", "period": "quarterly"}, "GOOGL EPS 2.12"),
        _step(4, "get_price_history", {"symbol": "AAPL", "period": "1y"}, "1y price history"),
        _step(5, "get_financials", {"stmt": "balance", "period": "yearly"}, "balance sheets"),
        _step(6, "get_financials", {"stmt": "income", "period": "yearly"}, "income statements"),
    ]
    return _make_trace(
        UUID("33333333-3333-3333-3333-333333333333"),
        steps,
        "Across AAPL, MSFT and GOOGL: Microsoft leads on quarterly earnings growth, "
        "Apple shows the strongest balance sheet, and Google trails on 1-year price return. "
        "Fundamentals, earnings and balance-sheet evidence are summarized per company.",
    )


def candidate_incomplete() -> Trace:
    """hermes3-8b — incomplete aggregation: never reads the income statement (cp5)."""
    steps = [
        _step(0, "get_tickers_info", {"symbols": ["AAPL", "MSFT", "GOOGL"]}, "quotes"),
        _step(1, "get_earnings", {"symbol": "AAPL", "period": "quarterly"}, "AAPL EPS"),
        _step(2, "get_earnings", {"symbol": "MSFT", "period": "quarterly"}, "MSFT EPS"),
        _step(3, "get_earnings", {"symbol": "GOOGL", "period": "quarterly"}, "GOOGL EPS"),
        _step(4, "download", {"symbols": ["AAPL", "MSFT", "GOOGL"], "period": "1y"}, "1y prices"),
        _step(5, "get_financials", {"stmt": "balance", "period": "yearly"}, "balance sheets"),
        # NOTE: no income-statement call — cp5 stays unmet.
    ]
    return _make_trace(
        UUID("44444444-4444-4444-4444-444444444444"),
        steps,
        "Comparing Apple, Microsoft and Google: all three show solid fundamentals and "
        "steady earnings, with healthy balance sheets and positive one-year price trends. "
        "Microsoft looks strongest overall on financial health.",
    )


def candidate_stale() -> Trace:
    """grok-4.3 (stale) — correct path, every effect met; only the live numbers moved."""
    steps = [
        _step(0, "get_tickers_info", {"symbols": ["AAPL", "MSFT", "GOOGL"]}, "quotes"),
        _step(1, "get_earnings", {"symbol": "AAPL", "period": "quarterly"}, "AAPL EPS"),
        _step(2, "get_earnings", {"symbol": "MSFT", "period": "quarterly"}, "MSFT EPS"),
        _step(3, "get_earnings", {"symbol": "GOOGL", "period": "quarterly"}, "GOOGL EPS"),
        _step(4, "download", {"symbols": ["AAPL", "MSFT", "GOOGL"], "period": "1y"}, "1y prices"),
        _step(5, "get_financials", {"stmt": "balance", "period": "yearly"}, "balance sheets"),
        _step(6, "get_financials", {"stmt": "income", "period": "yearly"}, "income statements"),
    ]
    return _make_trace(
        UUID("55555555-5555-5555-5555-555555555555"),
        steps,
        "AAPL 1-year return +18.4%, MSFT +12.1%, GOOGL +9.7% (as of today). Full "
        "fundamentals, quarterly earnings and balance-sheet + income-statement evidence "
        "reported per company.",
    )


SERVERS_VIEW = [
    {
        "server_id": "yfinance",
        "dynamism": "live_read",
        "sandbox": False,
        "description": "Live market data: quotes, earnings, fundamentals, and price history for tickers.",
        "tools": [n for n, _ in YF_TOOLS],
    },
    {
        "server_id": "arxiv",
        "dynamism": "live_read",
        "sandbox": False,
        "description": "Scholarly metadata and full-text search over arXiv preprints.",
        "tools": ["search", "get_paper", "list_authors", "get_citations"],
    },
    {
        "server_id": "wikipedia",
        "dynamism": "live_read",
        "sandbox": False,
        "description": "Encyclopedic lookups; mostly stable content with occasional edits.",
        "tools": ["search", "get_summary", "get_page", "get_links"],
    },
    {
        "server_id": "github-sandbox",
        "dynamism": "stateful_write",
        "sandbox": True,
        "description": "Developer platform in a sandbox. State-changing tools run isolated.",
        "tools": ["create_issue", "list_repos", "get_file", "delete_branch"],
    },
]

CANDIDATES = [
    ("qwen3.7-max", "clean run · different tool", candidate_clean, True),
    ("hermes3-8b", "incomplete aggregation", candidate_incomplete, True),
    ("grok-4.3 (stale)", "correct path · live data moved", candidate_stale, False),
]


def build() -> dict:
    ref = _make_trace(
        REF_TRACE_ID,
        reference_steps(),
        "Compared AAPL, MSFT and GOOGL on quotes, quarterly earnings, 1-year price history, "
        "and balance-sheet + income-statement evidence.",
    )
    spec = make_spec()

    # Self-consistency: the reference trace must pass its own spec.
    ref_ev = evaluate(spec, ref)
    assert ref_ev.passed, f"reference trace fails its own spec: {ref_ev.summary}"

    candidates = []
    for name, note, fn, answer_ok in CANDIDATES:
        ctrace = fn()
        ev = evaluate(spec, ctrace, candidate_model=name, evaluation_mode="replay")
        candidates.append(
            {
                "name": name,
                "note": note,
                "answer_looks_right": answer_ok,  # studio-side demo foil only
                "trace": json.loads(ctrace.to_jsonl()),
            }
        )
        print(f"  {name:18} effect_pass={ev.passed!s:5} answer_looks_right={answer_ok}")

    # Assert the three showcase verdicts (effect side, from the real evaluator).
    verdicts = {c["name"]: evaluate(spec, Trace.model_validate(c["trace"])).passed for c in candidates}
    assert verdicts["qwen3.7-max"] is True, "case 1 (clean equivalence pass) must effect-PASS"
    assert verdicts["hermes3-8b"] is False, "case 2 (incomplete aggregation) must effect-FAIL"
    assert verdicts["grok-4.3 (stale)"] is True, "case 3 (stale answer) must effect-PASS"

    return {
        "id": "showcase_aapl",
        "servers": SERVERS_VIEW,
        "goal": {"goal": GOAL, "persona": PERSONA},
        "reference_trace": json.loads(ref.to_jsonl()),
        "task_spec": json.loads(spec.to_jsonl()),
        "candidates": candidates,
    }


# Parent-study leaderboard for the peek panel. PLACEHOLDER until a real export
# from the parent study is wired (build plan §10: never present invented numbers
# as real). Marked so the UI/route can label it.
LEADERBOARD = {
    "_placeholder": True,
    "_note": "Replace with a real export from the parent study before any public demo.",
    "rows": [
        {"model": "qwen3.7-max", "group": "API", "pass3": 51.2},
        {"model": "glm-5.1", "group": "API", "pass3": 50.3},
        {"model": "qwen3.6-35b-a3b", "group": "local", "pass3": 48.5},
        {"model": "deepseek-v4-pro", "group": "API", "pass3": 46.4},
        {"model": "gemma-4-31b-it", "group": "local", "pass3": 42.5},
        {"model": "claude-haiku-4.5", "group": "API", "pass3": 41.1},
        {"model": "hermes3-8b", "group": "local", "pass3": 13.2},
    ],
}


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    print("Building showcase fixture (asserting verdicts)…")
    fixture = build()
    (FIXTURES / "showcase_aapl.json").write_text(json.dumps(fixture, indent=2), encoding="utf-8")
    (FIXTURES / "leaderboard.json").write_text(json.dumps(LEADERBOARD, indent=2), encoding="utf-8")
    print(f"Wrote {FIXTURES / 'showcase_aapl.json'} and leaderboard.json")


if __name__ == "__main__":
    main()
