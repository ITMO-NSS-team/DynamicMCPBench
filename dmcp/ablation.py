"""Ablation statistics for the sampling-strategy study (E2.8, simple_approach §8).

Pure-Python (no SciPy/statsmodels) significance tests for comparing distractor
strategies on SAE rate:

  chi2_2x2 / fisher_exact_2x2  — per-contrast 2x2 association tests
  holm                          — Holm-Bonferroni multiple-comparison correction
  power_n                       — two-proportion sample size (α=0.05 two-sided,
                                  power=0.80) — reproduces the doc's ~167 for
                                  0.50 vs 0.65
  compare_strategies            — runs the documented pairwise contrasts and
                                  Holm-adjusts across them

The mixed-effects logistic regression `correct ~ strategy + P_alt + level +
(1|task) + (1|model)` from the plan needs statsmodels and is intentionally
DEFERRED (lean-deps rule) — the per-contrast tests below are the v0 substitute.
"""

from __future__ import annotations

import math

# Default pairwise contrasts (simple_approach §8.1), on SAE rate.
DEFAULT_CONTRASTS: tuple[tuple[str, str], ...] = (
    ("random", "hard_neg"),
    ("hard_neg", "cross_domain"),
    ("same_name", "hard_neg"),
    ("sibling", "cross_domain"),
    ("stratified", "random"),
)

_Z_ALPHA_05 = 1.959963984540054  # z_{0.025}
_Z_POWER_80 = 0.8416212335729143  # z_{0.20}


def chi2_2x2(a: int, b: int, c: int, d: int) -> tuple[float, float]:
    """Pearson chi-square for a 2x2 table [[a,b],[c,d]]; returns (chi2, p) (1 dof)."""
    n = a + b + c + d
    row1, row2, col1, col2 = a + b, c + d, a + c, b + d
    if n == 0 or min(row1, row2, col1, col2) == 0:
        return (0.0, 1.0)
    chi2 = n * (a * d - b * c) ** 2 / (row1 * row2 * col1 * col2)
    p = math.erfc(math.sqrt(chi2 / 2.0))  # survival fn of chi-square, 1 dof
    return (chi2, p)


def fisher_exact_2x2(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p-value for the 2x2 table [[a,b],[c,d]]."""
    n = a + b + c + d
    if n == 0:
        return 1.0
    row1 = a + b
    col1 = a + c

    def hyp(k: int) -> float:
        return math.comb(col1, k) * math.comb(n - col1, row1 - k) / math.comb(n, row1)

    p_obs = hyp(a)
    lo = max(0, row1 - (n - col1))
    hi = min(row1, col1)
    p = sum(hyp(k) for k in range(lo, hi + 1) if hyp(k) <= p_obs + 1e-12)
    return min(1.0, p)


def holm(pvals: list[float]) -> list[float]:
    """Holm-Bonferroni adjusted p-values (same order as input)."""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    adj = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, (m - rank) * pvals[i])
        adj[i] = min(1.0, running)
    return adj


def power_n(p1: float, p2: float) -> int:
    """Per-group n to detect p1 vs p2 (two-sided α=0.05, power=0.80)."""
    if p1 == p2:
        return 0
    num = (_Z_ALPHA_05 + _Z_POWER_80) ** 2 * (p1 * (1 - p1) + p2 * (1 - p2))
    return math.ceil(num / (p1 - p2) ** 2)


def compare_strategies(
    stats: dict[str, tuple[int, int]],
    contrasts: tuple[tuple[str, str], ...] = DEFAULT_CONTRASTS,
    *,
    small_cell: int = 5,
    alpha: float = 0.05,
) -> list[dict]:
    """Run pairwise SAE-rate contrasts with Holm correction.

    stats: strategy -> (sae_count, n). Each present contrast becomes a 2x2 test
    (Fisher when any cell < `small_cell`, else chi-square). Returns one dict per
    runnable contrast with raw + Holm-adjusted p and a significance flag.
    """
    runnable = [(x, y) for (x, y) in contrasts if x in stats and y in stats]
    rows: list[dict] = []
    raw_p: list[float] = []
    for x, y in runnable:
        sx, nx = stats[x]
        sy, ny = stats[y]
        a, b, c, d = sx, nx - sx, sy, ny - sy
        if min(a, b, c, d) < small_cell:
            test, p = "fisher", fisher_exact_2x2(a, b, c, d)
            stat = float("nan")
        else:
            test, (stat, p) = "chi2", chi2_2x2(a, b, c, d)
        rows.append(
            {
                "a": x,
                "b": y,
                "sae_rate_a": sx / nx if nx else 0.0,
                "sae_rate_b": sy / ny if ny else 0.0,
                "test": test,
                "stat": stat,
                "p": p,
            }
        )
        raw_p.append(p)
    adj = holm(raw_p)
    for r, pa in zip(rows, adj, strict=True):
        r["p_holm"] = pa
        r["significant"] = pa < alpha
    return rows
