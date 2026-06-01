"""E2.7: P_alt degradation-curve aggregation + complexity bins."""

from __future__ import annotations

from dmcp.curves import aggregate_curve, complexity_bin, proportion_ci


def test_complexity_bin():
    assert complexity_bin(1) == "1"
    assert complexity_bin(2) == "2"
    assert complexity_bin(3) == "3-4"
    assert complexity_bin(4) == "3-4"
    assert complexity_bin(7) == "5+"


def test_proportion_ci_edges():
    assert proportion_ci(0, 0) == (0.0, 0.0)
    lo, hi = proportion_ci(10, 10)
    assert hi == 1.0 or hi > 0.6  # all-pass → upper near 1
    assert lo > 0.6
    lo0, hi0 = proportion_ci(0, 10)
    assert lo0 == 0.0
    lo_mid, hi_mid = proportion_ci(5, 10)
    assert lo_mid < 0.5 < hi_mid  # CI straddles the point estimate


def test_aggregate_curve_micro_and_macro():
    samples = [
        # p=0.0: 2 passed / 2 (bin 1), no SAE
        {"p_alt": 0.0, "passed": True, "had_sae": False, "bin": "1"},
        {"p_alt": 0.0, "passed": True, "had_sae": False, "bin": "2"},
        # p=1.0: 0 passed / 2, both SAE
        {"p_alt": 1.0, "passed": False, "had_sae": True, "bin": "1"},
        {"p_alt": 1.0, "passed": False, "had_sae": True, "bin": "2"},
    ]
    pts = aggregate_curve(samples)["points"]
    assert [p["p_alt"] for p in pts] == [0.0, 1.0]  # sorted
    assert pts[0]["accuracy"] == 1.0 and pts[0]["sae_rate"] == 0.0
    assert pts[1]["accuracy"] == 0.0 and pts[1]["sae_rate"] == 1.0
    # macro = mean over bins (each bin has 1 sample here)
    assert pts[0]["macro_accuracy"] == 1.0
    assert pts[1]["macro_sae_rate"] == 1.0
    assert set(pts[0]["by_bin"]) == {"1", "2"}


def test_aggregate_curve_macro_differs_from_micro():
    # bin "1" has 3 samples (all pass), bin "3-4" has 1 (fail).
    # micro accuracy = 3/4 = 0.75; macro = mean(1.0, 0.0) = 0.5.
    samples = [
        {"p_alt": 0.5, "passed": True, "had_sae": False, "bin": "1"},
        {"p_alt": 0.5, "passed": True, "had_sae": False, "bin": "1"},
        {"p_alt": 0.5, "passed": True, "had_sae": False, "bin": "1"},
        {"p_alt": 0.5, "passed": False, "had_sae": False, "bin": "3-4"},
    ]
    pt = aggregate_curve(samples)["points"][0]
    assert pt["accuracy"] == 0.75
    assert pt["macro_accuracy"] == 0.5
