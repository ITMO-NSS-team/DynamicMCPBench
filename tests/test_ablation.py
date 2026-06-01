"""E2.8: ablation statistics (chi-square / Fisher / Holm / power-n / contrasts)."""

from __future__ import annotations

from dmcp.ablation import (
    chi2_2x2,
    compare_strategies,
    fisher_exact_2x2,
    holm,
    power_n,
)


def test_chi2_association_and_degenerate():
    chi2, p = chi2_2x2(20, 5, 5, 20)
    assert chi2 > 15 and p < 0.001
    assert chi2_2x2(10, 10, 10, 10) == (0.0, 1.0)  # no association
    assert chi2_2x2(0, 0, 0, 0) == (0.0, 1.0)
    assert chi2_2x2(5, 0, 5, 0) == (0.0, 1.0)  # empty column


def test_fisher_separated_vs_balanced():
    assert fisher_exact_2x2(9, 1, 1, 9) < 0.05
    assert fisher_exact_2x2(5, 5, 5, 5) > 0.5


def test_holm_monotone_and_capped():
    adj = holm([0.01, 0.04, 0.03])
    assert all(0.0 <= x <= 1.0 for x in adj)
    assert adj[0] >= 0.01 * 3 - 1e-9  # smallest raw scaled by m
    assert all(x == 1.0 for x in holm([0.9, 0.95]))


def test_power_n_matches_doc():
    assert 160 <= power_n(0.5, 0.65) <= 175  # doc ~167
    assert 145 <= power_n(0.25, 0.40) <= 162  # doc ~152
    assert power_n(0.5, 0.5) == 0


def test_compare_strategies_runs_contrasts_with_holm():
    stats = {
        "random": (2, 20),
        "hard_neg": (15, 20),
        "cross_domain": (8, 20),
        "same_name": (16, 20),
        "sibling": (3, 20),
        "stratified": (10, 20),
    }
    rows = compare_strategies(stats)
    assert len(rows) == 5  # all default contrasts runnable
    assert all("p_holm" in r and "significant" in r for r in rows)
    rh = next(r for r in rows if r["a"] == "random" and r["b"] == "hard_neg")
    assert rh["p_holm"] < 0.05  # 2/20 vs 15/20 is a strong, significant contrast
