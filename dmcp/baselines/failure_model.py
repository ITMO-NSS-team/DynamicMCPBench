"""RQ3 trace-property failure model (E4.5).

Fits a ridge-regularized logistic regression of `pass/fail` on the trace
features:

  - trace_depth         int   (number of successful agent tool calls)
  - runtime_branching   {0,1} (later arg derived from earlier result)
  - state_coupling      {0,1} (any stateful_write server touched)
  - cross_server        {0,1} (uses ≥ 2 servers)
  - dynamism_live       {0,1} (task's max-server dynamism is live_read)
  - dynamism_stateful   {0,1} (... is stateful_write)
    (the static class is the reference level, encoded as both zero.)

Per candidate model and pooled across models. Reports per-feature
coefficients, odds ratios, and a **drop-column permutation importance**:
the log-likelihood drop when the column is removed and the model refit.

The fit is intentionally lightweight:

  - pure-Python — no new dep (numpy is transitively present but we keep
    this module dependency-free so the report can be regenerated even in
    a minimal environment);
  - **ridge** (Tikhonov, λ = 1e-3 by default) on the non-intercept
    coefficients to handle near-separability gracefully when a feature
    splits all-pass / all-fail in small N;
  - IRLS (Newton-Raphson) with up to 50 iterations and a 1e-6 tolerance
    on the change in coefficients.

This module is read-only with respect to the headline scoring path. The
hard CLAUDE.md invariants are untouched (no final-answer grading; trace
is the primitive; effect checkpoints unchanged). RQ3's role is purely
diagnostic — explaining *which* trace properties drive failure — and is
labeled a comparison/analysis tool, not part of the scorer.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Feature order is fixed so coefficients line up across runs / reports.
FEATURE_NAMES: tuple[str, ...] = (
    "trace_depth",
    "runtime_branching",
    "state_coupling",
    "cross_server",
    "dynamism_live",
    "dynamism_stateful",
)


# ---------------------------------------------------------------------------
# Tiny linear algebra (square solve via partial-pivot Gaussian elimination)
# ---------------------------------------------------------------------------


class _LinAlgError(RuntimeError):
    pass


def _solve(matrix_a: Sequence[Sequence[float]], rhs_b: Sequence[float]) -> list[float]:
    """Solve A @ x = b for a small square `A`. Partial pivoting, no deps."""
    n = len(matrix_a)
    if any(len(row) != n for row in matrix_a) or len(rhs_b) != n:
        raise _LinAlgError("solve: A must be square and match b in size")
    a = [list(row) + [rhs_b[i]] for i, row in enumerate(matrix_a)]
    for col in range(n):
        # Partial pivot: pick the row with max |a[*, col]| at or below `col`.
        pivot = col
        best = abs(a[col][col])
        for r in range(col + 1, n):
            v = abs(a[r][col])
            if v > best:
                best = v
                pivot = r
        if best == 0.0:
            raise _LinAlgError("solve: singular matrix")
        a[col], a[pivot] = a[pivot], a[col]
        diag = a[col][col]
        for k in range(col, n + 1):
            a[col][k] /= diag
        for r in range(n):
            if r == col:
                continue
            factor = a[r][col]
            if factor == 0.0:
                continue
            for k in range(col, n + 1):
                a[r][k] -= factor * a[col][k]
    return [row[-1] for row in a]


def _sigmoid(x: float) -> float:
    """Numerically stable logistic sigmoid."""
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Sample:
    """One row going into the regression."""

    task_id: str
    model: str
    pass_flag: int
    features: tuple[float, ...]  # aligned with FEATURE_NAMES


@dataclass(frozen=True)
class FeatureImportance:
    name: str
    coefficient: float
    odds_ratio: float
    drop_loglik_loss: float


@dataclass(frozen=True)
class FitResult:
    """One logistic fit."""

    label: str  # model name or "pooled"
    n_samples: int
    n_passes: int
    pass_rate: float
    converged: bool
    iterations: int
    loglik: float
    intercept: float
    importances: tuple[FeatureImportance, ...]
    note: str | None = None


@dataclass
class RQ3Report:
    ridge: float
    fits: list[FitResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class FailureModelError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------


def _dynamism_dummies(dyn: str) -> tuple[float, float]:
    if dyn == "live_read":
        return (1.0, 0.0)
    if dyn == "stateful_write":
        return (0.0, 1.0)
    return (0.0, 0.0)  # static (reference level)


def extract_features(complexity: dict[str, Any], dynamism: str) -> tuple[float, ...]:
    """Pull the RQ3 feature vector out of a ComplexityProfile dict + dynamism."""
    live, stateful = _dynamism_dummies(dynamism)
    return (
        float(complexity.get("trace_depth", 0) or 0),
        1.0 if complexity.get("runtime_branching") else 0.0,
        1.0 if complexity.get("state_coupling") else 0.0,
        1.0 if complexity.get("cross_server") else 0.0,
        live,
        stateful,
    )


# ---------------------------------------------------------------------------
# IRLS logistic regression with L2 ridge
# ---------------------------------------------------------------------------


def _fit_logistic(
    x: list[list[float]],
    y: list[int],
    *,
    ridge: float,
    max_iter: int = 50,
    tol: float = 1e-6,
) -> tuple[list[float], float, int, bool]:
    """Return (coefficients_incl_intercept, loglik, iters, converged).

    coefficients[0] is the intercept; coefficients[1:] are feature coefficients.
    The ridge penalty is applied to non-intercept coefficients only.
    """
    n = len(y)
    if n == 0:
        raise FailureModelError("cannot fit on zero samples")
    n_feat = len(x[0]) if x else 0
    # Design matrix with leading 1 column for the intercept.
    design = [[1.0, *row] for row in x]
    p = n_feat + 1
    beta = [0.0] * p
    iters = 0
    converged = False
    for it in range(max_iter):
        iters = it + 1
        # eta = design @ beta; mu = sigmoid(eta).
        eta = [sum(design[i][j] * beta[j] for j in range(p)) for i in range(n)]
        mu = [_sigmoid(e) for e in eta]
        w = [max(m * (1.0 - m), 1e-9) for m in mu]
        # Score vector: design.T @ (y - mu) - ridge * beta (no penalty on intercept).
        score = [0.0] * p
        for j in range(p):
            s = sum(design[i][j] * (y[i] - mu[i]) for i in range(n))
            if j > 0:
                s -= ridge * beta[j]
            score[j] = s
        # Information matrix: design.T @ W @ design + ridge * I (no ridge on intercept).
        info = [[0.0] * p for _ in range(p)]
        for j in range(p):
            for k in range(j, p):
                s = sum(w[i] * design[i][j] * design[i][k] for i in range(n))
                if j == k and j > 0:
                    s += ridge
                info[j][k] = s
                info[k][j] = s
        try:
            delta = _solve(info, score)
        except _LinAlgError as e:
            raise FailureModelError(f"IRLS solve failed: {e}") from e
        beta_new = [beta[j] + delta[j] for j in range(p)]
        max_step = max(abs(beta_new[j] - beta[j]) for j in range(p))
        beta = beta_new
        if max_step < tol:
            converged = True
            break
    # Final log-likelihood (without ridge — we report the data fit).
    eta = [sum(design[i][j] * beta[j] for j in range(p)) for i in range(n)]
    mu = [_sigmoid(e) for e in eta]
    loglik = 0.0
    for i in range(n):
        m = min(max(mu[i], 1e-12), 1.0 - 1e-12)
        loglik += y[i] * math.log(m) + (1 - y[i]) * math.log(1.0 - m)
    return beta, loglik, iters, converged


def _drop_column_loglik(
    x: list[list[float]],
    y: list[int],
    drop_index: int,
    *,
    ridge: float,
) -> float:
    """Refit with `drop_index` zeroed out; return data log-likelihood."""
    if not x:
        return 0.0
    x_reduced = [[v for j, v in enumerate(row) if j != drop_index] for row in x]
    if not x_reduced[0]:
        # Intercept-only model.
        p_hat = sum(y) / max(len(y), 1)
        p_hat = min(max(p_hat, 1e-12), 1.0 - 1e-12)
        return sum(yi * math.log(p_hat) + (1 - yi) * math.log(1.0 - p_hat) for yi in y)
    _, loglik, _, _ = _fit_logistic(x_reduced, y, ridge=ridge)
    return loglik


def fit_failure_model(
    samples: Sequence[Sample],
    *,
    label: str,
    ridge: float = 1e-3,
    compute_importance: bool = True,
) -> FitResult:
    """Fit a logistic regression of pass/fail on the trace features.

    If all `pass_flag` values are identical, the fit is undefined; we report
    a degenerate FitResult with a note rather than raising, so the CLI can
    still emit a comprehensible per-model row.
    """
    n = len(samples)
    if n == 0:
        raise FailureModelError(f"{label}: no samples to fit")
    y = [int(s.pass_flag) for s in samples]
    x = [list(s.features) for s in samples]
    n_pass = sum(y)
    if n_pass == 0 or n_pass == n:
        return FitResult(
            label=label,
            n_samples=n,
            n_passes=n_pass,
            pass_rate=n_pass / n,
            converged=True,
            iterations=0,
            loglik=0.0,
            intercept=0.0,
            importances=tuple(
                FeatureImportance(name=name, coefficient=0.0, odds_ratio=1.0, drop_loglik_loss=0.0)
                for name in FEATURE_NAMES
            ),
            note=("all samples pass" if n_pass == n else "all samples fail")
            + " — coefficients are not identifiable",
        )
    beta, loglik, iters, converged = _fit_logistic(x, y, ridge=ridge)
    importances: list[FeatureImportance] = []
    for j, name in enumerate(FEATURE_NAMES):
        coef = beta[j + 1]
        odds = math.exp(coef) if abs(coef) < 25 else float("inf") if coef > 0 else 0.0
        drop_loss = 0.0
        if compute_importance:
            try:
                reduced_loglik = _drop_column_loglik(x, y, j, ridge=ridge)
                drop_loss = loglik - reduced_loglik
            except FailureModelError:
                drop_loss = float("nan")
        importances.append(
            FeatureImportance(
                name=name,
                coefficient=coef,
                odds_ratio=odds,
                drop_loglik_loss=drop_loss,
            )
        )
    return FitResult(
        label=label,
        n_samples=n,
        n_passes=n_pass,
        pass_rate=n_pass / n,
        converged=converged,
        iterations=iters,
        loglik=loglik,
        intercept=beta[0],
        importances=tuple(importances),
    )


def fit_per_model_and_pooled(
    samples_by_model: dict[str, list[Sample]],
    *,
    ridge: float = 1e-3,
) -> RQ3Report:
    """Fit one model per candidate plus a pooled model across all candidates."""
    fits: list[FitResult] = []
    pooled: list[Sample] = []
    for model, samples in sorted(samples_by_model.items()):
        if not samples:
            continue
        fits.append(fit_failure_model(samples, label=model, ridge=ridge))
        pooled.extend(samples)
    if pooled:
        fits.append(fit_failure_model(pooled, label="pooled", ridge=ridge))
    return RQ3Report(ridge=ridge, fits=fits)


# ---------------------------------------------------------------------------
# I/O — join EvaluationResult JSONL × TaskSpec JSONL on task_id
# ---------------------------------------------------------------------------


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def load_features_by_task(specs_path: Path) -> dict[str, tuple[float, ...]]:
    """Map task_id → feature vector, derived from a TaskSpec JSONL."""
    out: dict[str, tuple[float, ...]] = {}
    for d in _iter_jsonl(specs_path):
        tid = d.get("task_id")
        if not isinstance(tid, str):
            continue
        complexity = d.get("complexity") or {}
        dynamism = d.get("dynamism") or "live_read"
        out[tid] = extract_features(complexity, dynamism)
    return out


def load_samples_for_model(
    evals_path: Path,
    features_by_task: dict[str, tuple[float, ...]],
    *,
    model_label: str,
) -> list[Sample]:
    samples: list[Sample] = []
    for d in _iter_jsonl(evals_path):
        tid = d.get("task_id")
        if not isinstance(tid, str):
            continue
        feats = features_by_task.get(tid)
        if feats is None:
            continue
        passed = bool(d.get("passed"))
        samples.append(
            Sample(
                task_id=tid,
                model=model_label,
                pass_flag=int(passed),
                features=feats,
            )
        )
    return samples


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _fmt_float(x: float | None, digits: int = 3) -> str:
    if x is None:
        return "—"
    if math.isnan(x):
        return "nan"
    if math.isinf(x):
        return "+∞" if x > 0 else "-∞"
    return f"{x:+.{digits}f}"


def _fmt_odds(x: float | None) -> str:
    if x is None or math.isnan(x):
        return "—"
    if math.isinf(x):
        return "+∞" if x > 0 else "0"
    return f"{x:.3f}"


def render_markdown(report: RQ3Report, *, title: str | None = None) -> str:
    lines: list[str] = []
    lines.append(f"# {title or 'RQ3 trace-property failure model (E4.5)'}")
    lines.append("")
    lines.append(
        f"_ridge λ_: **{report.ridge:.0e}** ・ "
        "ridge-regularized logistic regression of pass/fail on trace features"
    )
    lines.append("")
    if not report.fits:
        lines.append("_no fits produced_")
        return "\n".join(lines) + "\n"

    for fit in report.fits:
        lines.append(f"## `{fit.label}`")
        lines.append("")
        lines.append(
            f"n = **{fit.n_samples}** ・ pass rate = "
            f"**{fit.pass_rate * 100:.1f}%** ・ iters = {fit.iterations} ・ "
            f"converged = {fit.converged} ・ loglik = {fit.loglik:.3f}"
        )
        if fit.note:
            lines.append(f"_note_: {fit.note}")
            lines.append("")
            continue
        lines.append("")
        lines.append("| feature | coefficient | odds ratio | drop-loglik loss |")
        lines.append("|---|---|---|---|")
        for imp in sorted(fit.importances, key=lambda i: i.drop_loglik_loss, reverse=True):
            lines.append(
                f"| `{imp.name}` | {_fmt_float(imp.coefficient)} | "
                f"{_fmt_odds(imp.odds_ratio)} | {_fmt_float(imp.drop_loglik_loss)} |"
            )
        lines.append("")
        lines.append(f"_intercept_: {_fmt_float(fit.intercept)}")
        lines.append("")

    if report.notes:
        lines.append("## Notes")
        for n in report.notes:
            lines.append(f"- {n}")
        lines.append("")

    return "\n".join(lines) + "\n"


def report_to_json(report: RQ3Report) -> dict[str, Any]:
    def _imp(imp: FeatureImportance) -> dict[str, Any]:
        # JSON cannot encode inf/nan losslessly; coerce to string.
        coef = imp.coefficient if math.isfinite(imp.coefficient) else str(imp.coefficient)
        odds = imp.odds_ratio if math.isfinite(imp.odds_ratio) else str(imp.odds_ratio)
        drop = imp.drop_loglik_loss if math.isfinite(imp.drop_loglik_loss) else str(imp.drop_loglik_loss)
        return {
            "name": imp.name,
            "coefficient": coef,
            "odds_ratio": odds,
            "drop_loglik_loss": drop,
        }

    return {
        "ridge": report.ridge,
        "feature_names": list(FEATURE_NAMES),
        "fits": [
            {
                "label": fit.label,
                "n_samples": fit.n_samples,
                "n_passes": fit.n_passes,
                "pass_rate": fit.pass_rate,
                "converged": fit.converged,
                "iterations": fit.iterations,
                "loglik": fit.loglik,
                "intercept": fit.intercept,
                "note": fit.note,
                "importances": [_imp(i) for i in fit.importances],
            }
            for fit in report.fits
        ],
        "notes": list(report.notes),
    }
