"""P_alt degradation-curve aggregation + complexity bins (E2.7).

The `dmcp curve` driver sweeps P_alt over a grid in Target-pool replay and, at
each point, records per-spec pass/fail + whether SAE occurred. This module turns
those samples into the paper's degradation curves: accuracy and SAE rate vs P_alt
with 95% confidence intervals, normalized by complexity bin (micro within a bin,
macro across bins) so models with different complexity mixes compare fairly
(simple_approach §7.3/§7.5, PDF §4.3).
"""

from __future__ import annotations

import math

COMPLEXITY_BINS = ("1", "2", "3-4", "5+")


def complexity_bin(trace_depth: int) -> str:
    """Bin a task by required-tool / trace depth (simple_approach §7.5)."""
    if trace_depth <= 1:
        return "1"
    if trace_depth == 2:
        return "2"
    if trace_depth <= 4:
        return "3-4"
    return "5+"


def proportion_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion k/n (no SciPy needed)."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def aggregate_curve(samples: list[dict]) -> dict:
    """Aggregate sweep samples into a degradation curve.

    samples: [{"p_alt": float, "passed": bool, "had_sae": bool, "bin": str}].
    Returns {"points": [...]} sorted by p_alt; each point has micro accuracy /
    SAE rate with Wilson CIs, plus macro (mean over complexity bins) and a
    per-bin breakdown.
    """
    by_p: dict[float, list[dict]] = {}
    for s in samples:
        by_p.setdefault(s["p_alt"], []).append(s)

    points: list[dict] = []
    for p in sorted(by_p):
        rows = by_p[p]
        n = len(rows)
        acc_k = sum(1 for r in rows if r["passed"])
        sae_k = sum(1 for r in rows if r["had_sae"])

        per_bin: dict[str, dict] = {}
        for r in rows:
            per_bin.setdefault(r["bin"], []).append(r)
        bin_stats = {
            b: {
                "n": len(br),
                "accuracy": sum(1 for r in br if r["passed"]) / len(br),
                "sae_rate": sum(1 for r in br if r["had_sae"]) / len(br),
            }
            for b, br in per_bin.items()
        }
        macro_acc = sum(v["accuracy"] for v in bin_stats.values()) / len(bin_stats) if bin_stats else 0.0
        macro_sae = sum(v["sae_rate"] for v in bin_stats.values()) / len(bin_stats) if bin_stats else 0.0

        points.append(
            {
                "p_alt": p,
                "n": n,
                "accuracy": acc_k / n if n else 0.0,
                "accuracy_ci": proportion_ci(acc_k, n),
                "sae_rate": sae_k / n if n else 0.0,
                "sae_ci": proportion_ci(sae_k, n),
                "macro_accuracy": round(macro_acc, 4),
                "macro_sae_rate": round(macro_sae, 4),
                "by_bin": bin_stats,
            }
        )
    return {"points": points}
