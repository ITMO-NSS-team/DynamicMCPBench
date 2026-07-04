"""Tests for Benchmark Advisor planning statistics (BA2.3 / T04)."""

from __future__ import annotations

from benchmark_advisor.stats import (
    BASELINE_SENSITIVITY_RATES,
    COVERAGE_THRESHOLDS,
    DEFAULT_BASELINE_RATE,
    HEURISTIC_LABEL,
    budget_mde_curve,
    ci_width_pp,
    coverage_diagnostic,
    coverage_status,
    diagnostic_slice_ci_width_pp,
    leaderboard_rank_resolution_pp,
    plan_statistics,
    planned_mde_pp,
    planned_mde_pp_for_unique_tasks,
    required_tasks_for_mde,
    slice_task_count,
)


def test_mde_decreases_as_task_count_increases():
    assert planned_mde_pp(40) > planned_mde_pp(100) > planned_mde_pp(400)


def test_ci_width_decreases_as_task_count_increases():
    assert ci_width_pp(40) > ci_width_pp(100) > ci_width_pp(400)


def test_mde_and_ci_are_deterministic():
    assert planned_mde_pp(120) == planned_mde_pp(120)
    assert ci_width_pp(120) == ci_width_pp(120)


def test_mde_is_capped_and_handles_degenerate_n():
    assert planned_mde_pp(0) == 100.0
    assert planned_mde_pp(-5) == 100.0
    assert 0.0 < planned_mde_pp(1000) < 100.0


def test_unique_task_mde_caps_effective_sample_size():
    assert planned_mde_pp_for_unique_tasks(100) == planned_mde_pp(100)
    assert planned_mde_pp_for_unique_tasks(100, effective_sample_size=300) == planned_mde_pp(100)
    assert planned_mde_pp_for_unique_tasks(100, effective_sample_size=50) == planned_mde_pp(50)


def test_ba54_sensitivity_and_mode_helpers_use_unique_tasks():
    assert BASELINE_SENSITIVITY_RATES == (0.2, 0.5, 0.8)
    assert slice_task_count(100, 0.4) == 40
    assert diagnostic_slice_ci_width_pp(100, 0.4) == ci_width_pp(40)
    assert leaderboard_rank_resolution_pp(100, DEFAULT_BASELINE_RATE) == planned_mde_pp_for_unique_tasks(100)


def test_required_tasks_roundtrips_monotonically():
    # A smaller detectable effect needs more tasks.
    assert required_tasks_for_mde(2.0) > required_tasks_for_mde(10.0)


def test_required_tasks_reuses_power_n_scale():
    # Sanity: detecting a 10pp gap around 0.5 needs a few hundred tasks per group.
    n = required_tasks_for_mde(10.0, baseline=0.5)
    assert 300 <= n <= 450


def test_budget_mde_curve_is_monotone_decreasing():
    curve = budget_mde_curve([40, 80, 160, 320])
    mdes = [mde for _, mde in curve]
    assert mdes == sorted(mdes, reverse=True)
    assert [b for b, _ in curve] == [40, 80, 160, 320]


def test_coverage_status_bands_match_interfaces():
    # cross_server: approved >= 0.25, warning 0.10..0.249, refused < 0.10
    assert coverage_status(0.30, "cross_server") == "approved"
    assert coverage_status(0.25, "cross_server") == "approved"
    assert coverage_status(0.15, "cross_server") == "warning"
    assert coverage_status(0.10, "cross_server") == "warning"
    assert coverage_status(0.09, "cross_server") == "refused"


def test_coverage_status_long_chain_and_recovery():
    assert coverage_status(0.30, "long_chain") == "approved"
    assert coverage_status(0.20, "long_chain") == "warning"
    assert coverage_status(0.10, "long_chain") == "refused"
    assert coverage_status(0.10, "recovery") == "approved"
    assert coverage_status(0.06, "recovery") == "warning"
    assert coverage_status(0.04, "recovery") == "refused"


def test_coverage_diagnostic_carries_thresholds_and_label():
    d = coverage_diagnostic("cross_server", 0.15)
    assert d.status == "warning"
    assert (d.approved_floor, d.warning_floor) == COVERAGE_THRESHOLDS["cross_server"]
    assert d.label == HEURISTIC_LABEL


def test_plan_statistics_aggregates_and_labels_as_heuristic():
    stats = plan_statistics(
        task_budget=120,
        attempts_per_task=3,
        coverage_claims={"cross_server": 0.15, "long_chain": 0.35},
    )
    assert stats.label == HEURISTIC_LABEL
    assert stats.planned_mde_pp == planned_mde_pp(120)
    assert stats.ci_width_pp == ci_width_pp(120)
    statuses = {c.dimension: c.status for c in stats.coverage}
    assert statuses == {"cross_server": "warning", "long_chain": "approved"}
    # Round-trips to a plain dict for API serialization.
    d = stats.to_dict()
    assert d["label"] == HEURISTIC_LABEL
    assert d["coverage"][0]["dimension"] in {"cross_server", "long_chain"}


def test_plan_statistics_is_deterministic():
    a = plan_statistics(task_budget=80, attempts_per_task=3, coverage_claims={"recovery": 0.06})
    b = plan_statistics(task_budget=80, attempts_per_task=3, coverage_claims={"recovery": 0.06})
    assert a == b
