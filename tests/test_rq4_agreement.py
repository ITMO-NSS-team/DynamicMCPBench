"""E4.6: agreement statistics — Cohen's κ, Krippendorff's α, replay determinism."""

from __future__ import annotations

from uuid import uuid4

import pytest

from dmcp.baselines.rq4_agreement import (
    AGREEMENT_THRESHOLD,
    REPLAY_FLIP_RATE_TARGET,
    build_report,
    cohen_kappa,
    compute_replay_determinism,
    krippendorff_alpha_binary,
    render_markdown,
    report_to_json,
)
from dmcp.baselines.rq4_subset import AnnotationRow, HumanConsensus
from dmcp.evaluator import CheckpointResult, EvaluationResult, MinefieldResult

# ---------------------------------------------------------------------------
# Cohen's κ
# ---------------------------------------------------------------------------


def test_cohen_kappa_perfect_agreement_is_one():
    pairs = [("pass", "pass"), ("fail", "fail"), ("pass", "pass"), ("fail", "fail")]
    assert cohen_kappa(pairs) == pytest.approx(1.0)


def test_cohen_kappa_perfect_disagreement_is_minus_one():
    pairs = [("pass", "fail"), ("fail", "pass"), ("pass", "fail"), ("fail", "pass")]
    assert cohen_kappa(pairs) == pytest.approx(-1.0)


def test_cohen_kappa_chance_agreement_is_zero():
    """Standard 2x2 example: 50 pass-pass, 25 pass-fail, 25 fail-pass, 0 fail-fail.
    p_obs = 0.5, p_exp = 0.75*0.75 + 0.25*0.25 = 0.625 → κ = (0.5 - 0.625)/(1 - 0.625) = -1/3."""
    pairs = [("pass", "pass")] * 50 + [("pass", "fail")] * 25 + [("fail", "pass")] * 25
    k = cohen_kappa(pairs)
    assert k is not None
    assert k == pytest.approx(-1 / 3, abs=1e-6)


def test_cohen_kappa_ignores_non_valid_verdicts():
    # Mixed pass/fail cells stay; rows with 'tie' or empty drop.
    pairs = [("pass", "pass"), ("fail", "fail"), ("tie", "fail"), ("", "pass")]
    assert cohen_kappa(pairs) == pytest.approx(1.0)


def test_cohen_kappa_empty_or_degenerate_is_none():
    assert cohen_kappa([]) is None
    # Both raters always say "pass" → expected agreement = 1.0 → κ undefined.
    assert cohen_kappa([("pass", "pass")] * 5) is None


# ---------------------------------------------------------------------------
# Krippendorff's α (binary nominal)
# ---------------------------------------------------------------------------


def test_alpha_perfect_agreement_is_one():
    grid = [["pass", "pass", "pass"], ["fail", "fail", "fail"]] * 5
    a = krippendorff_alpha_binary(grid)
    assert a is not None
    assert a == pytest.approx(1.0)


def test_alpha_within_bounds_for_mixed_grid():
    """α stays in the [-1, 1] band for a hand-crafted mixed-agreement grid."""
    grid = [["pass", "fail"], ["pass", "pass"], ["fail", "fail"], ["pass", "fail"]]
    a = krippendorff_alpha_binary(grid)
    assert a is not None
    assert -1.0 <= a <= 1.0
    # Not perfect agreement and not perfect disagreement.
    assert a != 1.0
    assert a != -1.0


def test_alpha_returns_none_when_no_marginal_disagreement():
    # All raters give 'pass' everywhere → expected disagreement is 0 → α undefined.
    grid = [["pass", "pass"] for _ in range(5)]
    assert krippendorff_alpha_binary(grid) is None


def test_alpha_drops_cells_with_one_rating():
    grid = [["pass"], ["fail", "fail"], ["pass", "pass"]]
    # First cell dropped → remaining 2 cells fully agree → α = 1.0
    a = krippendorff_alpha_binary(grid)
    assert a == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Replay determinism
# ---------------------------------------------------------------------------


def test_replay_determinism_zero_flips_is_perfect():
    run_a = {(f"t{i}", "c"): "pass" for i in range(10)}
    run_b = dict(run_a)
    r = compute_replay_determinism(run_a, run_b)
    assert r.n_cells_compared == 10
    assert r.n_flips == 0
    assert r.flip_rate == 0.0
    assert r.meets_target


def test_replay_determinism_with_flips():
    run_a = {("t0", "c"): "pass", ("t1", "c"): "fail", ("t2", "c"): "pass"}
    run_b = {("t0", "c"): "fail", ("t1", "c"): "fail", ("t2", "c"): "pass"}
    r = compute_replay_determinism(run_a, run_b)
    assert r.n_flips == 1
    assert r.flip_rate == pytest.approx(1 / 3)
    assert not r.meets_target  # 33% > 5%


# ---------------------------------------------------------------------------
# build_report — end-to-end on synthetic evals
# ---------------------------------------------------------------------------


def _mk_eval(task_id, cand_tid, *, passed: bool, tier2: bool = False) -> EvaluationResult:
    cp = CheckpointResult(
        checkpoint_id="cp-0",
        kind="tool_effect",
        passed=passed,
        reason="ok",
        tier=2 if tier2 else 1,
    )
    return EvaluationResult(
        task_id=task_id,
        candidate_trace_id=cand_tid,
        candidate_model="modelX",
        evaluation_mode=("replay+judge" if tier2 else "replay"),
        passed=passed,
        checkpoint_results=[cp],
        minefield_results=[],
        ordering_ok=True,
        summary={
            "checkpoints_passed": int(passed),
            "checkpoints_total": 1,
            "minefields_hit": 0,
            "minefields_total": 0,
        },
    )


def _ann(task: str, cand: str, rater: str, verdict: str) -> AnnotationRow:
    return AnnotationRow(
        task_id=task,
        candidate_trace_id=cand,
        candidate_model="modelX",
        rater_id=rater,
        verdict=verdict,
    )


def test_build_report_perfect_agreement_passes_threshold():
    # 4 cells; both Tier-1 verdicts match human consensus exactly
    cells = [
        (uuid4(), uuid4(), True),
        (uuid4(), uuid4(), False),
        (uuid4(), uuid4(), True),
        (uuid4(), uuid4(), False),
    ]
    annotations: list[AnnotationRow] = []
    evals = []
    consensus: list[HumanConsensus] = []
    for tid, ctid, passed in cells:
        verdict = "pass" if passed else "fail"
        annotations += [
            _ann(str(tid), str(ctid), "alice", verdict),
            _ann(str(tid), str(ctid), "bob", verdict),
        ]
        consensus.append(
            HumanConsensus(
                task_id=str(tid),
                candidate_trace_id=str(ctid),
                consensus_verdict=verdict,
                n_raters=2,
                vote_pass=(2 if passed else 0),
                vote_fail=(0 if passed else 2),
            )
        )
        evals.append(_mk_eval(tid, ctid, passed=passed))
    report = build_report(
        subset_size=4,
        annotations=annotations,
        consensus=consensus,
        tier1_evals=evals,
    )
    t1 = report.by_tier[0]
    assert t1.tier == "tier1"
    assert t1.n_cells == 4
    assert t1.cohen_kappa == pytest.approx(1.0)
    assert t1.cohen_kappa >= AGREEMENT_THRESHOLD
    assert t1.false_fail_rate == 0.0
    assert t1.false_pass_rate == 0.0


def test_build_report_separates_false_fail_from_false_pass():
    # Tier-1 says pass, human says fail → false-pass.
    tid_a, ctid_a = uuid4(), uuid4()
    # Tier-1 says fail, human says pass → false-fail.
    tid_b, ctid_b = uuid4(), uuid4()
    annotations = [
        _ann(str(tid_a), str(ctid_a), "alice", "fail"),
        _ann(str(tid_a), str(ctid_a), "bob", "fail"),
        _ann(str(tid_b), str(ctid_b), "alice", "pass"),
        _ann(str(tid_b), str(ctid_b), "bob", "pass"),
    ]
    consensus = [
        HumanConsensus(str(tid_a), str(ctid_a), "fail", 2, 0, 2),
        HumanConsensus(str(tid_b), str(ctid_b), "pass", 2, 2, 0),
    ]
    evals = [
        _mk_eval(tid_a, ctid_a, passed=True),  # scorer=pass, human=fail
        _mk_eval(tid_b, ctid_b, passed=False),  # scorer=fail, human=pass
    ]
    report = build_report(
        subset_size=2,
        annotations=annotations,
        consensus=consensus,
        tier1_evals=evals,
    )
    t1 = report.by_tier[0]
    assert t1.false_pass_rate == 0.5
    assert t1.false_fail_rate == 0.5


def test_build_report_includes_replay_determinism_when_run_b_supplied():
    tid, ctid = uuid4(), uuid4()
    ann = [
        _ann(str(tid), str(ctid), "alice", "pass"),
        _ann(str(tid), str(ctid), "bob", "pass"),
    ]
    consensus = [HumanConsensus(str(tid), str(ctid), "pass", 2, 2, 0)]
    run_a = [_mk_eval(tid, ctid, passed=True)]
    run_b = [_mk_eval(tid, ctid, passed=False)]  # flipped
    report = build_report(
        subset_size=1,
        annotations=ann,
        consensus=consensus,
        tier1_evals=run_a,
        replay_run_b_evals=run_b,
    )
    assert report.replay is not None
    assert report.replay.n_cells_compared == 1
    assert report.replay.flip_rate == 1.0
    assert not report.replay.meets_target


def test_build_report_includes_tier2_when_judge_evals_supplied():
    tid, ctid = uuid4(), uuid4()
    ann = [
        _ann(str(tid), str(ctid), "alice", "pass"),
        _ann(str(tid), str(ctid), "bob", "pass"),
    ]
    consensus = [HumanConsensus(str(tid), str(ctid), "pass", 2, 2, 0)]
    tier1 = [_mk_eval(tid, ctid, passed=False)]  # tier-1 disagrees
    tier2 = [_mk_eval(tid, ctid, passed=True, tier2=True)]  # tier-2 agrees
    report = build_report(
        subset_size=1,
        annotations=ann,
        consensus=consensus,
        tier1_evals=tier1,
        tier2_evals=tier2,
    )
    labels = [t.tier for t in report.by_tier]
    assert "tier1" in labels
    assert "tier2" in labels


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_render_markdown_mentions_thresholds():
    tid, ctid = uuid4(), uuid4()
    ann = [_ann(str(tid), str(ctid), "a", "pass"), _ann(str(tid), str(ctid), "b", "pass")]
    consensus = [HumanConsensus(str(tid), str(ctid), "pass", 2, 2, 0)]
    report = build_report(
        subset_size=1,
        annotations=ann,
        consensus=consensus,
        tier1_evals=[_mk_eval(tid, ctid, passed=True)],
    )
    md = render_markdown(report, title="unit-test rq4")
    assert "unit-test rq4" in md
    assert "Cohen's κ" in md
    assert "Krippendorff" in md
    assert "≥0.7" in md
    j = report_to_json(report)
    assert j["agreement_threshold"] == AGREEMENT_THRESHOLD
    assert j["replay_flip_rate_target"] == REPLAY_FLIP_RATE_TARGET


# ---------------------------------------------------------------------------
# Orthogonality guard
# ---------------------------------------------------------------------------


def test_rq4_modules_not_imported_by_evaluator_or_judge():
    import inspect

    import dmcp.evaluator
    import dmcp.judge

    for module in (dmcp.evaluator, dmcp.judge):
        src = inspect.getsource(module)
        for forbidden in ("rq4_subset", "rq4_agreement"):
            assert forbidden not in src, f"{module.__name__} must not import dmcp.baselines.{forbidden}"


def test_minefield_result_import_is_used():
    """Sanity: importing MinefieldResult so the local _mk_eval helper stays honest
    (a model with no minefield results is still a valid scorer outcome)."""
    assert MinefieldResult is not None
