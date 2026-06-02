"""E4.4: answer-match scorer + RQ1 aggregator + Kendall's τ + over-time stability."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from dmcp.baselines.answer_match import DEFAULT_THRESHOLD, score_answer
from dmcp.baselines.rq1_compare import (
    PerSpecDecision,
    RQ1Error,
    aggregate_rq1,
    build_decisions,
    kendall_tau,
    load_candidate_final_messages,
    load_evals,
    load_reference_final_messages_by_trace_id,
    load_spec_to_reference_trace,
    render_markdown,
    report_to_json,
)
from dmcp.evaluator import CheckpointResult, EvaluationResult

# ---------------------------------------------------------------------------
# answer_match
# ---------------------------------------------------------------------------


def test_answer_match_passes_on_high_jaccard():
    r = score_answer("the time is 15 04 utc", "current time is 15 04 utc", threshold=0.5)
    assert r.passed is True
    assert r.jaccard >= 0.5


def test_answer_match_fails_on_disjoint_inputs():
    r = score_answer("apples and bananas", "neutrinos detect tomorrow", threshold=0.5)
    assert r.passed is False
    assert r.jaccard == 0.0
    assert r.substring_hit is False


def test_answer_match_substring_fallback_passes_under_threshold():
    # Jaccard would be ~0.16 — well under 0.5; substring fallback catches
    # the canonical short answer (`boston` is >= 5 chars).
    r = score_answer(
        "the answer to your question is boston",
        "boston",
        threshold=0.5,
    )
    assert r.passed is True
    assert r.substring_hit is True
    assert r.jaccard < 0.5


def test_answer_match_handles_none_and_empty():
    assert score_answer(None, "abc").passed is False
    assert score_answer("abc", None).passed is False
    assert score_answer("", "abc").passed is False


def test_answer_match_normalization_is_punctuation_insensitive():
    r = score_answer("Hello, World!!!", "hello world", threshold=0.99)
    assert r.jaccard == pytest.approx(1.0)
    assert r.passed is True


# ---------------------------------------------------------------------------
# kendall_tau
# ---------------------------------------------------------------------------


def test_kendall_tau_identical_rankings_is_one():
    assert kendall_tau([1.0, 2.0, 3.0], [10.0, 20.0, 30.0]) == pytest.approx(1.0)


def test_kendall_tau_fully_reversed_rankings_is_minus_one():
    assert kendall_tau([1.0, 2.0, 3.0], [30.0, 20.0, 10.0]) == pytest.approx(-1.0)


def test_kendall_tau_undefined_for_short_input():
    assert kendall_tau([], []) is None
    assert kendall_tau([0.5], [0.5]) is None


def test_kendall_tau_rejects_misaligned_inputs():
    with pytest.raises(RQ1Error):
        kendall_tau([1.0], [1.0, 2.0])


def test_kendall_tau_tau_b_handles_ties():
    # All ties in `a` → τ undefined (denom_a == 0) → None.
    assert kendall_tau([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None


# ---------------------------------------------------------------------------
# aggregate_rq1 / build_decisions
# ---------------------------------------------------------------------------


def _mk_decisions(model: str, pairs: list[tuple[bool, bool]]) -> list[PerSpecDecision]:
    return [
        PerSpecDecision(
            model=model,
            task_id=f"t{i}",
            trace_pass=t,
            answer_pass=a,
            jaccard=1.0 if a else 0.0,
            substring_hit=False,
        )
        for i, (t, a) in enumerate(pairs)
    ]


def test_aggregate_rq1_per_model_disagreement_rates():
    decisions = {
        # 10 tasks, both scorers agree on 6, false-fail on 2, false-pass on 2.
        "A": _mk_decisions(
            "A",
            [
                (True, True),
                (True, True),
                (False, False),
                (False, False),
                (False, False),
                (False, False),
                (True, False),  # false-fail
                (True, False),  # false-fail
                (False, True),  # false-pass
                (False, True),  # false-pass
            ],
        ),
    }
    report = aggregate_rq1(decisions, threshold=0.5)
    summary = report.models[0]
    assert summary.trace_accuracy == 0.4
    assert summary.answer_accuracy == 0.4
    assert summary.false_fail_rate == 0.2
    assert summary.false_pass_rate == 0.2
    assert summary.agreement_rate == 0.6
    # Single model → no τ.
    assert report.kendall_tau_rankings is None
    assert report.overall_false_fail_rate == 0.2


def test_aggregate_rq1_kendall_between_rankings():
    # Models rank A > B > C by trace, but A > C > B by answer → not identical.
    decisions = {
        "A": _mk_decisions("A", [(True, True)] * 3),
        "B": _mk_decisions("B", [(True, True), (True, False), (False, False)]),
        "C": _mk_decisions("C", [(True, True), (False, True), (False, False)]),
    }
    report = aggregate_rq1(decisions, threshold=0.5)
    # Both rankings are NOT identical → τ < 1.
    tau = report.kendall_tau_rankings
    assert tau is not None
    assert tau < 1.0


def test_aggregate_rq1_over_time_stability():
    run1 = _mk_decisions("M", [(True, True), (True, True), (False, False), (True, True)])
    # 1 spec flipped between runs → τ is not perfect 1.0.
    run2 = _mk_decisions("M", [(True, True), (False, True), (False, False), (True, True)])
    report = aggregate_rq1(
        {"M": run1},
        threshold=0.5,
        over_time_runs={"M": [run1, run2]},
    )
    assert "M" in report.over_time_stability
    assert report.over_time_stability["M"] < 1.0


# ---------------------------------------------------------------------------
# Rendering + JSON
# ---------------------------------------------------------------------------


def test_render_markdown_includes_headline():
    decisions = {"A": _mk_decisions("A", [(True, False), (False, True)])}
    report = aggregate_rq1(decisions, threshold=0.5)
    md = render_markdown(report, title="unit-test rq1")
    assert "unit-test rq1" in md
    assert "Kendall" in md
    assert "false-fail" in md
    assert "false-pass" in md


def test_report_to_json_round_trips_models():
    decisions = {
        "A": _mk_decisions("A", [(True, True), (False, False)]),
        "B": _mk_decisions("B", [(True, False), (False, True)]),
    }
    report = aggregate_rq1(decisions, threshold=0.5)
    j = report_to_json(report)
    assert sorted(m["model"] for m in j["models"]) == ["A", "B"]
    assert j["threshold"] == 0.5
    assert j["summary_stats"]["n_cells"] == 4


# ---------------------------------------------------------------------------
# I/O helpers + end-to-end build_decisions
# ---------------------------------------------------------------------------


def _mk_eval(task_id, cand_trace_id, *, passed: bool) -> EvaluationResult:
    return EvaluationResult(
        task_id=task_id,
        candidate_trace_id=cand_trace_id,
        candidate_model="modelX",
        evaluation_mode="replay",
        passed=passed,
        checkpoint_results=[
            CheckpointResult(checkpoint_id="cp-0", kind="tool_effect", passed=passed, reason="ok")
        ],
        minefield_results=[],
        ordering_ok=True,
        summary={
            "checkpoints_passed": int(passed),
            "checkpoints_total": 1,
            "minefields_hit": 0,
            "minefields_total": 0,
        },
    )


def test_build_decisions_end_to_end():
    task_id = uuid4()
    cand_trace_id = uuid4()
    ev = _mk_eval(task_id, cand_trace_id, passed=True)
    cand_msgs = {str(cand_trace_id): "the answer is paris"}
    ref_msgs = {"ref-trace-1": "paris"}
    spec_to_src = {str(task_id): "ref-trace-1"}
    decisions = build_decisions(
        model="modelX",
        evals=[ev],
        candidate_final_messages=cand_msgs,
        reference_final_messages_by_trace_id=ref_msgs,
        spec_to_source_trace=spec_to_src,
        threshold=0.5,
    )
    assert len(decisions) == 1
    d = decisions[0]
    assert d.trace_pass is True
    assert d.answer_pass is True  # substring fallback on "paris"
    assert d.substring_hit is True


def test_build_decisions_marks_false_fail_when_phrasing_diverges():
    task_id = uuid4()
    cand_trace_id = uuid4()
    ev = _mk_eval(task_id, cand_trace_id, passed=True)
    # Same content, totally different wording, no shared long tokens.
    cand_msgs = {str(cand_trace_id): "the temporal coordinate sits at fifteen oh four"}
    ref_msgs = {"ref-trace-1": "current time 15 04 utc"}
    spec_to_src = {str(task_id): "ref-trace-1"}
    decisions = build_decisions(
        model="modelX",
        evals=[ev],
        candidate_final_messages=cand_msgs,
        reference_final_messages_by_trace_id=ref_msgs,
        spec_to_source_trace=spec_to_src,
        threshold=0.5,
    )
    d = decisions[0]
    assert d.trace_pass is True
    assert d.answer_pass is False  # false-fail of answer-match


def test_load_helpers_handle_jsonl(tmp_path: Path):
    evals_path = tmp_path / "evals.jsonl"
    cand_path = tmp_path / "cand.jsonl"
    ref_path = tmp_path / "ref.jsonl"
    specs_path = tmp_path / "specs.jsonl"

    tid = uuid4()
    cand_tid = uuid4()
    src_tid = "ref-1"

    ev = _mk_eval(tid, cand_tid, passed=False)
    evals_path.write_text(ev.to_jsonl() + "\n")

    cand_trace = {
        "trace_id": str(cand_tid),
        "seed_metadata": {"exploration": {"final_message": "candidate said this"}},
    }
    cand_path.write_text(json.dumps(cand_trace) + "\n")

    ref_trace = {
        "trace_id": src_tid,
        "seed_metadata": {"exploration": {"final_message": "reference said this"}},
    }
    ref_path.write_text(json.dumps(ref_trace) + "\n")

    spec_obj = {"task_id": str(tid), "source_trace_id": src_tid}
    specs_path.write_text(json.dumps(spec_obj) + "\n")

    evs = load_evals(evals_path)
    assert len(evs) == 1
    cand_msgs = load_candidate_final_messages(cand_path)
    assert cand_msgs == {str(cand_tid): "candidate said this"}
    ref_msgs = load_reference_final_messages_by_trace_id(ref_path)
    assert ref_msgs == {src_tid: "reference said this"}
    assert load_spec_to_reference_trace(specs_path) == {str(tid): src_tid}


# ---------------------------------------------------------------------------
# Orthogonality guard
# ---------------------------------------------------------------------------


def test_answer_match_module_is_not_imported_by_evaluator_or_judge():
    """The hard invariant: the answer-match scorer must NEVER be imported by
    the headline scoring path. This test guards that contract by reading the
    source of those modules directly.
    """
    import inspect

    import dmcp.evaluator
    import dmcp.judge

    for module in (dmcp.evaluator, dmcp.judge):
        src = inspect.getsource(module)
        assert "answer_match" not in src, f"{module.__name__} must not import dmcp.baselines.answer_match"
        assert "rq1_compare" not in src, f"{module.__name__} must not import dmcp.baselines.rq1_compare"


def test_default_threshold_is_half():
    assert DEFAULT_THRESHOLD == 0.5
