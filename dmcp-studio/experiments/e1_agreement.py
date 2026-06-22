#!/usr/bin/env python3
"""E1 — studio-vs-batch verdict agreement (the credibility experiment).

The studio scores via ``backend.dmcp_adapter.score_pair`` →
``dmcp.evaluator.evaluate``; the batch pipeline scores via the real
``dmcp eval --candidate-traces`` CLI (a subprocess that reads JSONL from disk
and runs the same evaluator). E1 confirms the studio's wrapping + JSON
round-trip does not perturb the deterministic Tier-1 verdict.

Method: build the showcase TaskSpec and a deterministic battery of ~100
candidate traces (every subset of the five tool-effect checkpoints, both
price-history equivalence tools, value-checkpoint met/unmet, plus a few
wrong-arg / wrong-server perturbations). Score each pair both ways; compare the
overall ``passed`` verdict and every per-checkpoint pass/fail. No network, no
LLM, fully reproducible.

Run:  uv run python dmcp-studio/experiments/e1_agreement.py
Out:  experiments/results/e1_agreement.json  (+ a printed summary)
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
STUDIO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STUDIO))  # for `backend`
sys.path.insert(0, str(STUDIO / "experiments"))  # for `e3_curate`

import e3_curate as e3  # noqa: E402
from backend import dmcp_adapter as adapter  # noqa: E402

from dmcp.trace import Step, StepKind, StepStatus, Trace  # noqa: E402

DMCP = ROOT / ".venv" / "bin" / "dmcp"
MANIFEST = ROOT / "manifests" / "local.json"
RESULTS = STUDIO / "experiments" / "results"

SPEC = e3.make_spec()
TASK_ID = str(SPEC.task_id)

# Steps that satisfy each tool-effect checkpoint (cp1..cp5). cp3 has two
# equivalence members (download / get_price_history). _step(i, tool, args, text).
_SAT = {
    "cp1": ("get_tickers_info", {"symbols": ["AAPL", "MSFT", "GOOGL"]}),
    "cp2": ("get_earnings", {"symbol": "AAPL", "period": "quarterly"}),
    "cp4": ("get_financials", {"stmt": "balance", "period": "yearly"}),
    "cp5": ("get_financials", {"stmt": "income", "period": "yearly"}),
}
_CP3_DOWNLOAD = ("download", {"symbols": ["AAPL", "MSFT", "GOOGL"], "period": "1y"})
_CP3_GPH = ("get_price_history", {"symbol": "AAPL", "period": "1y"})

# cp6 is contains_all=["earnings","balance"] (case-sensitive) on the final message.
_VALUE_MET = "Quarterly earnings and the balance sheet are summarized per company."
_VALUE_UNMET = "Here is a brief comparison of the three companies."


def _wrong_server_step(i: int) -> Step:
    """cp3-shaped call on the WRONG server (SAE) — fails cp3 on both sides."""
    return Step.build(
        step_id=i,
        kind=StepKind.call_tool_agent,
        server_id="arxiv",  # not in cp3's equivalence set
        tool_name="get_price_history",
        arguments={"symbol": "AAPL", "period": "1y"},
        result={"content": [{"type": "text", "text": "x"}], "isError": False},
        started_at=e3._T0,
        ended_at=e3._T0,
        status=StepStatus.success,
    )


def _build_candidate(
    idx: int, *, cps: list[str], cp3_tool: str | None, value_met: bool, extra: Step | None = None
) -> Trace:
    steps: list[Step] = []
    for cp in ["cp1", "cp2"]:
        if cp in cps:
            tool, args = _SAT[cp]
            steps.append(e3._step(len(steps), tool, args, "ok"))
    if "cp3" in cps and cp3_tool:
        tool, args = _CP3_DOWNLOAD if cp3_tool == "download" else _CP3_GPH
        steps.append(e3._step(len(steps), tool, args, "ok"))
    for cp in ["cp4", "cp5"]:
        if cp in cps:
            tool, args = _SAT[cp]
            steps.append(e3._step(len(steps), tool, args, "ok"))
    if extra is not None:
        extra.step_id = len(steps)
        steps.append(extra)
    msg = _VALUE_MET if value_met else _VALUE_UNMET
    trace = e3._make_trace(UUID(int=0x5000 + idx), steps, msg)
    trace.seed_metadata["task_id"] = TASK_ID  # so `dmcp eval` matches it to the spec
    return trace


def build_battery() -> list[Trace]:
    """~100 deterministic candidate traces with broad verdict variety."""
    out: list[Trace] = []
    base = ["cp1", "cp2", "cp3", "cp4", "cp5"]
    idx = 0
    # all 32 subsets of cp1..cp5, cp3 via download, value {met, unmet}
    for mask in range(32):
        cps = [c for b, c in enumerate(base) if mask & (1 << b)]
        for value_met in (True, False):
            out.append(_build_candidate(idx, cps=cps, cp3_tool="download", value_met=value_met))
            idx += 1
    # subsets where cp3 is present, via the get_price_history equivalence tool
    for mask in range(32):
        if not (mask & (1 << 2)):
            continue
        cps = [c for b, c in enumerate(base) if mask & (1 << b)]
        for value_met in (True, False):
            out.append(_build_candidate(idx, cps=cps, cp3_tool="get_price_history", value_met=value_met))
            idx += 1
    # a few targeted perturbations (wrong server for cp3; wrong arg for cp3)
    out.append(
        _build_candidate(
            idx, cps=["cp1", "cp2", "cp4", "cp5"], cp3_tool=None, value_met=True, extra=_wrong_server_step(0)
        )
    )
    idx += 1
    bad_arg = e3._step(0, "download", {"symbols": ["AAPL"], "period": "5y"}, "ok")  # period != 1y → cp3 fails
    out.append(
        _build_candidate(idx, cps=["cp1", "cp2", "cp4", "cp5"], cp3_tool=None, value_met=True, extra=bad_arg)
    )
    idx += 1
    # passing variants: every checkpoint satisfied, with benign perturbations that
    # MUST NOT change the verdict (reordering, extra/duplicate calls, either
    # equivalence tool, extra args). These add pass-variety AND prove incidental
    # trace differences don't perturb agreement.
    out.extend(_passing_variants(idx))
    return out


def _passing_variants(start_idx: int) -> list[Trace]:
    variants: list[Trace] = []
    idx = start_idx
    full = ["cp1", "cp2", "cp3", "cp4", "cp5"]
    for cp3_tool in ("download", "get_price_history"):
        for perturb in range(10):
            cps = list(full)
            extra = None
            if perturb % 3 == 1:  # duplicate an earlier satisfying call
                tool, args = _SAT["cp1"]
                extra = e3._step(0, tool, args, "dup")
            elif perturb % 3 == 2:  # extra benign successful call
                extra = e3._step(0, "get_tickers_info", {"symbols": ["AAPL"]}, "extra")
            t = _build_candidate(idx, cps=cps, cp3_tool=cp3_tool, value_met=True, extra=extra)
            # reorder steps for some variants (no ordering constraints in the spec)
            if perturb % 2 == 0 and len(t.steps) > 2:
                t.steps = list(reversed(t.steps))
                for i, s in enumerate(t.steps):
                    s.step_id = i
            variants.append(t)
            idx += 1
    return variants


def studio_verdicts(traces: list[Trace]) -> dict[str, dict]:
    """Score each trace through the studio's own scoring core."""
    out: dict[str, dict] = {}
    for t in traces:
        done = adapter.score_pair(SPEC, t, answer_looks_right=False, candidate_model="e1")
        out[str(t.trace_id)] = {
            "passed": done.effect_pass,
            "checkpoints": {v.checkpoint_id: v.met for v in done.checkpoints},
        }
    return out


def batch_verdicts(traces: list[Trace], workdir: Path) -> dict[str, dict]:
    """Score the same traces through the real `dmcp eval --candidate-traces` CLI."""
    specs_p = workdir / "specs.jsonl"
    cands_p = workdir / "cands.jsonl"
    out_p = workdir / "evals.jsonl"
    specs_p.write_text(SPEC.to_jsonl() + "\n", encoding="utf-8")
    with cands_p.open("w", encoding="utf-8") as fh:
        for t in traces:
            fh.write(t.to_jsonl() + "\n")
    cmd = [
        str(DMCP), "eval", str(specs_p),
        "--candidate-traces", str(cands_p),
        "--manifest", str(MANIFEST),
        "--output", str(out_p),
        "--candidate-traces-out", str(workdir / "ctraces.jsonl"),
    ]  # fmt: skip
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    if res.returncode != 0:
        raise RuntimeError(f"dmcp eval failed:\n{res.stdout}\n{res.stderr}")
    out: dict[str, dict] = {}
    for line in out_p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        ev = json.loads(line)
        out[str(ev["candidate_trace_id"])] = {
            "passed": ev["passed"],
            "checkpoints": {cr["checkpoint_id"]: cr["passed"] for cr in ev["checkpoint_results"]},
        }
    return out


def main() -> int:
    traces = build_battery()
    studio = studio_verdicts(traces)
    with tempfile.TemporaryDirectory() as td:
        batch = batch_verdicts(traces, Path(td))

    n_pairs = len(traces)
    passed_match = 0
    cp_total = cp_match = 0
    disagreements: list[dict] = []
    for tid in studio:
        s, b = studio[tid], batch.get(tid)
        if b is None:
            disagreements.append({"trace_id": tid, "error": "missing in batch output"})
            continue
        if s["passed"] == b["passed"]:
            passed_match += 1
        for cp_id, s_met in s["checkpoints"].items():
            cp_total += 1
            b_met = b["checkpoints"].get(cp_id)
            if s_met == b_met:
                cp_match += 1
            else:
                disagreements.append({"trace_id": tid, "checkpoint": cp_id, "studio": s_met, "batch": b_met})

    # verdict variety (so reviewers see this isn't all-pass or all-fail)
    n_pass = sum(1 for v in studio.values() if v["passed"])
    summary = {
        "experiment": "E1",
        "n_pairs": n_pairs,
        "verdict_pass": n_pass,
        "verdict_fail": n_pairs - n_pass,
        "overall_verdict_agreement": round(passed_match / n_pairs, 4),
        "checkpoint_verdict_agreement": round(cp_match / cp_total, 4),
        "checkpoint_comparisons": cp_total,
        "disagreements": disagreements,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "e1_agreement.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    ov = summary["overall_verdict_agreement"] * 100
    cpa = summary["checkpoint_verdict_agreement"] * 100
    print("=== E1: studio-vs-batch agreement ===")
    print(f"pairs:                 {n_pairs}  ({n_pass} pass / {n_pairs - n_pass} fail)")
    print(f"overall verdict agree: {ov:.1f}%  ({passed_match}/{n_pairs})")
    print(f"checkpoint agree:      {cpa:.1f}%  ({cp_match}/{cp_total})")
    print(f"disagreements:         {len(disagreements)}")
    print(f"wrote {RESULTS / 'e1_agreement.json'}")
    return 0 if not disagreements else 1


if __name__ == "__main__":
    raise SystemExit(main())
