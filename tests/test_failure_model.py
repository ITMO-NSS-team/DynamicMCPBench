"""E4.5: RQ3 trace-property failure model.

Covers feature extraction, pure-Python IRLS logistic regression with ridge,
drop-column permutation importance, degenerate single-class input, and
JSON/Markdown rendering. Synthetic data with a known structure is used so
the recovered coefficient signs and importance ranking can be asserted.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dmcp.baselines.failure_model import (
    FEATURE_NAMES,
    FailureModelError,
    Sample,
    extract_features,
    fit_failure_model,
    fit_per_model_and_pooled,
    load_features_by_task,
    load_samples_for_model,
    render_markdown,
    report_to_json,
)

# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------


def test_extract_features_orders_match_feature_names():
    complexity = {
        "trace_depth": 3,
        "runtime_branching": True,
        "state_coupling": False,
        "cross_server": True,
    }
    feats = extract_features(complexity, "live_read")
    assert len(feats) == len(FEATURE_NAMES)
    assert feats[0] == 3.0  # trace_depth
    assert feats[1] == 1.0  # runtime_branching
    assert feats[2] == 0.0  # state_coupling
    assert feats[3] == 1.0  # cross_server
    assert feats[4] == 1.0  # dynamism_live
    assert feats[5] == 0.0  # dynamism_stateful


def test_extract_features_static_reference_level_is_both_zero():
    feats = extract_features({"trace_depth": 1}, "static")
    assert feats[4] == 0.0 and feats[5] == 0.0


def test_extract_features_stateful_dynamism():
    feats = extract_features({"trace_depth": 1}, "stateful_write")
    assert feats[4] == 0.0 and feats[5] == 1.0


# ---------------------------------------------------------------------------
# Logistic regression — sign + importance recovery
# ---------------------------------------------------------------------------


def _mk_sample(task_id: str, model: str, passed: bool, feats: tuple) -> Sample:
    return Sample(task_id=task_id, model=model, pass_flag=int(passed), features=feats)


def _synthetic_dataset(driver_index: int, n: int = 80) -> list[Sample]:
    """Synthesize a dataset where one feature deterministically drives pass/fail.

    pass = 1 iff feature[driver_index] >= 1.0; other features are noise drawn
    deterministically from a small lookup, so no RNG is needed.
    """
    samples: list[Sample] = []
    for i in range(n):
        feats = list((0.0,) * len(FEATURE_NAMES))
        # Pseudo-noise: each feature flips by a known modulus pattern.
        feats[0] = float((i % 3) + 1)  # trace_depth ∈ {1,2,3}
        feats[1] = float(i % 2)
        feats[2] = float((i // 4) % 2)
        feats[3] = float((i // 5) % 2)
        # dynamism: cycle through (static, live, stateful).
        cycle = i % 3
        feats[4] = 1.0 if cycle == 1 else 0.0
        feats[5] = 1.0 if cycle == 2 else 0.0
        # Force the driver feature to control the outcome.
        passed = feats[driver_index] >= 1.0 if driver_index >= 0 else (i % 2 == 0)
        if driver_index == 0:
            passed = feats[0] >= 2.0
        samples.append(_mk_sample(f"t{i}", "modelX", passed, tuple(feats)))
    return samples


def test_fit_recovers_positive_coefficient_for_pass_driving_feature():
    """When `cross_server` deterministically drives pass, its coefficient is +ve
    and its drop-loglik loss is the largest among features."""
    samples = _synthetic_dataset(driver_index=3, n=80)  # cross_server drives pass
    fit = fit_failure_model(samples, label="modelX")
    cross = next(i for i in fit.importances if i.name == "cross_server")
    assert cross.coefficient > 0
    # Cross-server should be the top driver.
    top = max(fit.importances, key=lambda i: i.drop_loglik_loss)
    assert top.name == "cross_server"


def test_fit_recovers_negative_coefficient_when_driver_predicts_fail():
    """If state_coupling deterministically predicts FAIL, its coefficient is -ve."""
    samples = []
    for i in range(60):
        state_coupling = float(i % 2)
        feats = (1.0, 0.0, state_coupling, 0.0, 1.0, 0.0)
        passed = state_coupling == 0.0  # state_coupling=1 → fail
        samples.append(_mk_sample(f"t{i}", "modelX", passed, feats))
    fit = fit_failure_model(samples, label="modelX")
    sc = next(i for i in fit.importances if i.name == "state_coupling")
    assert sc.coefficient < 0
    assert sc.odds_ratio < 1.0


def test_fit_degenerate_all_pass_returns_noted_result():
    feats = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
    samples = [_mk_sample(f"t{i}", "m", True, feats) for i in range(10)]
    fit = fit_failure_model(samples, label="m")
    assert fit.note is not None
    assert "all samples pass" in fit.note
    assert fit.pass_rate == 1.0
    assert all(i.coefficient == 0.0 for i in fit.importances)


def test_fit_degenerate_all_fail_returns_noted_result():
    feats = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
    samples = [_mk_sample(f"t{i}", "m", False, feats) for i in range(10)]
    fit = fit_failure_model(samples, label="m")
    assert fit.note is not None
    assert "all samples fail" in fit.note


def test_fit_empty_samples_raises():
    with pytest.raises(FailureModelError):
        fit_failure_model([], label="m")


# ---------------------------------------------------------------------------
# Per-model + pooled
# ---------------------------------------------------------------------------


def test_fit_per_model_and_pooled_produces_one_fit_per_model_plus_pooled():
    a = _synthetic_dataset(driver_index=3, n=60)
    b = _synthetic_dataset(driver_index=2, n=60)
    report = fit_per_model_and_pooled({"A": a, "B": b})
    labels = [f.label for f in report.fits]
    assert labels == ["A", "B", "pooled"]
    # The pooled fit converges and has non-trivial coefficients.
    pooled = report.fits[-1]
    assert pooled.converged
    assert any(abs(i.coefficient) > 0.1 for i in pooled.importances)


# ---------------------------------------------------------------------------
# Rendering + JSON
# ---------------------------------------------------------------------------


def test_render_markdown_contains_per_model_sections():
    a = _synthetic_dataset(driver_index=3, n=40)
    report = fit_per_model_and_pooled({"A": a})
    md = render_markdown(report, title="rq3 unit test")
    assert "rq3 unit test" in md
    assert "`A`" in md
    assert "`pooled`" in md
    assert "drop-loglik loss" in md
    for name in FEATURE_NAMES:
        assert name in md


def test_report_to_json_serializes_all_fits():
    a = _synthetic_dataset(driver_index=3, n=40)
    report = fit_per_model_and_pooled({"A": a})
    j = report_to_json(report)
    labels = [f["label"] for f in j["fits"]]
    assert labels == ["A", "pooled"]
    assert j["feature_names"] == list(FEATURE_NAMES)
    # Json round-trips through json.dumps (no inf/nan).
    blob = json.dumps(j)
    assert blob


# ---------------------------------------------------------------------------
# I/O: load specs + evals and join on task_id
# ---------------------------------------------------------------------------


def test_load_features_and_samples_end_to_end(tmp_path: Path):
    spec_obj = {
        "task_id": "t1",
        "complexity": {
            "trace_depth": 2,
            "runtime_branching": True,
            "state_coupling": False,
            "cross_server": True,
            "distinct_servers": 2,
            "recovery_required": False,
        },
        "dynamism": "live_read",
    }
    specs_path = tmp_path / "specs.jsonl"
    specs_path.write_text(json.dumps(spec_obj) + "\n")
    ev_obj = {
        "task_id": "t1",
        "candidate_trace_id": "tr-1",
        "passed": True,
    }
    evals_path = tmp_path / "evals.jsonl"
    evals_path.write_text(json.dumps(ev_obj) + "\n")

    features = load_features_by_task(specs_path)
    assert "t1" in features
    samples = load_samples_for_model(evals_path, features, model_label="m")
    assert len(samples) == 1
    assert samples[0].task_id == "t1"
    assert samples[0].pass_flag == 1
    # Trace depth surfaced into the first feature column.
    assert samples[0].features[0] == 2.0


def test_load_samples_drops_tasks_missing_from_specs(tmp_path: Path):
    specs_path = tmp_path / "specs.jsonl"
    specs_path.write_text("")
    evals_path = tmp_path / "evals.jsonl"
    evals_path.write_text(json.dumps({"task_id": "missing", "passed": True}) + "\n")
    features = load_features_by_task(specs_path)
    samples = load_samples_for_model(evals_path, features, model_label="m")
    assert samples == []


# ---------------------------------------------------------------------------
# Orthogonality guard
# ---------------------------------------------------------------------------


def test_failure_model_module_is_not_imported_by_evaluator_or_judge():
    """RQ3 is an analysis tool, not part of scoring. The headline path must
    not depend on it."""
    import inspect

    import dmcp.evaluator
    import dmcp.judge

    for module in (dmcp.evaluator, dmcp.judge):
        src = inspect.getsource(module)
        assert "failure_model" not in src, f"{module.__name__} must not import dmcp.baselines.failure_model"
