"""Benchmark Advisor planning statistics (BA2.3 / T04).

Deterministic, pre-run planning heuristics: a rough Wilson CI width, a
two-proportion MDE/power heuristic, the budget->MDE curve, and coverage
diagnostics for a planned task distribution. These reuse the existing, tested
``dmcp`` primitives (decision D2):

- ``dmcp.curves.proportion_ci`` — Wilson score interval;
- ``dmcp.ablation.power_n`` — per-group sample size at alpha=0.05, power=0.80.

Every output is a *planning heuristic* (``HEURISTIC_LABEL``), not final inference:
there is no dependence on live benchmark outcomes, no network/model calls, and
nothing here implies Stage-2 outcome analytics. Same input -> same output.

Out of scope: the deterministic validator orchestration (T02), the Stage-2
post-run validation report, and any outcome-tensor analytics.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from dmcp.ablation import _Z_ALPHA_05, _Z_POWER_80, power_n
from dmcp.curves import proportion_ci

HEURISTIC_LABEL = "planning_heuristic"

# Coverage thresholds (approved_floor, warning_floor) from INTERFACES.md
# "Validator Thresholds". planned < warning_floor => refused. The validator (T02)
# imports these so the threshold table has a single source of truth.
COVERAGE_THRESHOLDS: dict[str, tuple[float, float]] = {
    "cross_server": (0.25, 0.10),
    "long_chain": (0.30, 0.15),
    "recovery": (0.10, 0.05),
}


def wilson_ci(n: int, p: float = 0.5, z: float = 1.96) -> tuple[float, float]:
    """Wilson interval for an assumed pass rate ``p`` over ``n`` tasks (heuristic)."""
    k = round(p * n)
    return proportion_ci(k, n, z)


def ci_width_pp(n: int, p: float = 0.5, z: float = 1.96) -> float:
    """Full Wilson CI width in percentage points; shrinks as ``n`` grows."""
    lo, hi = wilson_ci(n, p, z)
    return (hi - lo) * 100.0


def planned_mde_pp(n_per_group: int, baseline: float = 0.5) -> float:
    """Minimum detectable effect (pp) for a two-proportion test (alpha=0.05, power=0.80).

    Closed-form planning approximation ``delta = (z_a + z_b) * sqrt(2 p (1-p) / n)``,
    consistent with ``dmcp.ablation.power_n`` and monotonically decreasing in
    ``n_per_group``. Returned in percentage points and capped at 100.
    """
    if n_per_group <= 0:
        return 100.0
    delta = (_Z_ALPHA_05 + _Z_POWER_80) * math.sqrt(2 * baseline * (1 - baseline) / n_per_group)
    return min(100.0, delta * 100.0)


def required_tasks_for_mde(mde_pp: float, baseline: float = 0.5) -> int:
    """Per-group tasks to detect ``mde_pp`` at the baseline rate (reuses ``power_n``)."""
    p1 = baseline
    p2 = min(0.999, baseline + mde_pp / 100.0)
    return power_n(p1, p2)


def budget_mde_curve(budgets: list[int], baseline: float = 0.5, groups: int = 2) -> list[tuple[int, float]]:
    """``[(task_budget, planned_mde_pp)]`` — the budget->MDE planning curve."""
    return [(b, planned_mde_pp(b // groups, baseline)) for b in budgets]


def coverage_status(planned: float, dimension: str) -> str:
    """``approved`` / ``warning`` / ``refused`` for a planned coverage ratio."""
    approved_floor, warning_floor = COVERAGE_THRESHOLDS[dimension]
    if planned >= approved_floor:
        return "approved"
    if planned >= warning_floor:
        return "warning"
    return "refused"


@dataclass(frozen=True)
class CoverageDiagnostic:
    dimension: str
    planned: float
    approved_floor: float
    warning_floor: float
    status: str
    label: str = HEURISTIC_LABEL


def coverage_diagnostic(dimension: str, planned: float) -> CoverageDiagnostic:
    approved_floor, warning_floor = COVERAGE_THRESHOLDS[dimension]
    return CoverageDiagnostic(
        dimension=dimension,
        planned=planned,
        approved_floor=approved_floor,
        warning_floor=warning_floor,
        status=coverage_status(planned, dimension),
    )


@dataclass(frozen=True)
class PlanningStats:
    """Aggregated planning heuristics for one design (consumed by the API layer)."""

    task_budget: int
    attempts_per_task: int
    baseline_rate: float
    planned_mde_pp: float
    ci_width_pp: float
    coverage: list[CoverageDiagnostic] = field(default_factory=list)
    label: str = HEURISTIC_LABEL

    def to_dict(self) -> dict:
        return asdict(self)


def plan_statistics(
    *,
    task_budget: int,
    attempts_per_task: int,
    baseline_rate: float = 0.5,
    coverage_claims: dict[str, float] | None = None,
) -> PlanningStats:
    """Compute the planning heuristics for a design.

    ``coverage_claims`` maps a coverage dimension (``cross_server`` / ``long_chain``
    / ``recovery``) to the planned ratio; only the dimensions a design actually
    claims need to be passed.
    """
    coverage = [coverage_diagnostic(dim, ratio) for dim, ratio in (coverage_claims or {}).items()]
    return PlanningStats(
        task_budget=task_budget,
        attempts_per_task=attempts_per_task,
        baseline_rate=baseline_rate,
        planned_mde_pp=planned_mde_pp(task_budget, baseline_rate),
        ci_width_pp=ci_width_pp(task_budget, baseline_rate),
        coverage=coverage,
    )
