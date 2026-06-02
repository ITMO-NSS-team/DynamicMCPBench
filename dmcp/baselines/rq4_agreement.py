"""RQ4 scorer-vs-human agreement statistics (E4.6).

Given:

  - the **human consensus** verdict per (task_id, candidate_trace_id)
    cell (from `dmcp/baselines/rq4_subset.py::compute_consensus`),
  - per-tier scorer verdicts (Tier-1 deterministic, Tier-2 LLM judge)
    extracted from `EvaluationResult` JSONL,

this module computes:

  - **Cohen's κ** between each scorer tier and the human consensus,
  - **Krippendorff's α** (binary nominal) over the full rater × cell
    matrix (raters + Tier-1 + Tier-2 treated symmetrically — this is the
    inter-rater-agreement-including-the-scorer view),
  - **false-pass rate** (scorer = pass, human = fail) and **false-fail
    rate** (scorer = fail, human = pass), per tier,
  - **replay determinism** — given two scorer runs of the same set of
    (task_id, candidate_model) pairs, the fraction of cells whose verdict
    flipped between runs. The done-when target is < 5 %.

Tie cells (annotators split exactly evenly) are excluded from κ / α and
reported separately so they cannot silently inflate or deflate agreement.

Pure-Python; no scipy / numpy dependency. Per
`memory/feedback_agb_orthogonality.md` and CLAUDE.md, this module is
analysis-only — it does NOT plug into the headline scoring path.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dmcp.baselines.rq4_subset import (
    VALID_VERDICT,
    AnnotationRow,
    HumanConsensus,
)
from dmcp.evaluator import EvaluationResult

# Pre-registered agreement target (research_plan RQ4 / simple_approach §5.6).
AGREEMENT_THRESHOLD = 0.7
# Pre-registered replay-determinism target.
REPLAY_FLIP_RATE_TARGET = 0.05


# ---------------------------------------------------------------------------
# Cohen's κ (two raters, binary nominal)
# ---------------------------------------------------------------------------


def cohen_kappa(pairs: list[tuple[str, str]]) -> float | None:
    """Cohen's κ over (rater_a, rater_b) verdict pairs.

    Each entry must be a pair of verdicts in {'pass', 'fail'} — pairs
    containing anything else (e.g. 'tie' or '') are ignored. Returns None
    when the contingency table is empty or fully tied (κ undefined).
    """
    a: list[str] = []
    b: list[str] = []
    for av, bv in pairs:
        if av in VALID_VERDICT and bv in VALID_VERDICT:
            a.append(av)
            b.append(bv)
    n = len(a)
    if n == 0:
        return None
    p_obs = sum(1 for i in range(n) if a[i] == b[i]) / n
    p_pass_a = sum(1 for v in a if v == "pass") / n
    p_pass_b = sum(1 for v in b if v == "pass") / n
    p_fail_a = 1 - p_pass_a
    p_fail_b = 1 - p_pass_b
    p_exp = p_pass_a * p_pass_b + p_fail_a * p_fail_b
    if p_exp == 1.0:
        return None  # both raters degenerate to the same constant verdict
    return (p_obs - p_exp) / (1.0 - p_exp)


# ---------------------------------------------------------------------------
# Krippendorff's α (binary nominal, any number of raters)
# ---------------------------------------------------------------------------


def krippendorff_alpha_binary(
    rater_grid: list[list[str | None]],
) -> float | None:
    """Krippendorff's α for binary nominal data with possible missing values.

    `rater_grid[i]` is one cell's list of rater verdicts. Each entry is
    'pass', 'fail', or None (missing). Cells with fewer than two non-None
    verdicts are dropped before computing α. Returns None if there isn't
    enough data left or both categories collapse to one.
    """
    # Drop cells with <2 ratings.
    valid_cells: list[list[str]] = []
    for cell in rater_grid:
        ratings = [v for v in cell if v in VALID_VERDICT]
        if len(ratings) >= 2:
            valid_cells.append(ratings)
    if not valid_cells:
        return None
    # Disagreement metric: nominal — δ(p, q) = 0 if equal else 1.
    # Observed disagreement: sum over cells of pairwise mismatches /
    #                       sum over cells of m(m-1), where m = ratings per cell.
    num_obs = 0
    den_obs = 0
    for ratings in valid_cells:
        m = len(ratings)
        den_obs += m * (m - 1)
        for i in range(m):
            for j in range(m):
                if i == j:
                    continue
                if ratings[i] != ratings[j]:
                    num_obs += 1
    if den_obs == 0:
        return None
    d_obs = num_obs / den_obs
    # Expected disagreement: based on marginals across all valid ratings.
    n_pass = 0
    n_fail = 0
    for ratings in valid_cells:
        n_pass += sum(1 for v in ratings if v == "pass")
        n_fail += sum(1 for v in ratings if v == "fail")
    total = n_pass + n_fail
    if total < 2 or n_pass == 0 or n_fail == 0:
        # Marginal disagreement is zero — α undefined.
        return None
    # Pairwise nominal disagreement under independence:
    # for any two ratings drawn without replacement, P(mismatch) =
    #   2 * n_pass * n_fail / (total * (total - 1)).
    d_exp = 2 * n_pass * n_fail / (total * (total - 1))
    if d_exp == 0:
        return None
    return 1.0 - d_obs / d_exp


# ---------------------------------------------------------------------------
# Tier extraction from EvaluationResult
# ---------------------------------------------------------------------------


def _tier1_verdict(ev: EvaluationResult) -> str:
    """Tier-1 verdict (deterministic), restricted to Tier-1 checkpoint passes.

    `ev.passed` is the post-Tier-2 verdict (when judge was on). For Tier-1
    we recompute pass = all-Tier-1-cps-pass AND no minefield hit AND
    ordering ok — so the agreement column reflects the deterministic tier
    alone, even if the eval used the Tier-2 upgrade path.
    """
    tier1_ok = all(cr.passed for cr in ev.checkpoint_results if cr.tier == 1)
    if not ev.checkpoint_results:
        tier1_ok = True
    no_mines = not any(mr.hit for mr in ev.minefield_results)
    ordering_ok = ev.ordering_ok
    return "pass" if (tier1_ok and no_mines and ordering_ok) else "fail"


def _tier2_verdict(ev: EvaluationResult) -> str | None:
    """Tier-2 verdict — only meaningful when the LLM judge was actually run.

    Detect via `evaluation_mode` containing 'judge' or by any Tier-2 row in
    the checkpoint results. Returns None when no Tier-2 was applied.
    """
    mode = ev.evaluation_mode or ""
    has_tier2 = "judge" in mode or any(cr.tier == 2 for cr in ev.checkpoint_results)
    if not has_tier2:
        return None
    return "pass" if ev.passed else "fail"


def index_evals(evals: Iterable[EvaluationResult]) -> dict[tuple[str, str], EvaluationResult]:
    out: dict[tuple[str, str], EvaluationResult] = {}
    for ev in evals:
        out[(str(ev.task_id), str(ev.candidate_trace_id))] = ev
    return out


# ---------------------------------------------------------------------------
# Top-level aggregation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TierAgreement:
    tier: str  # "tier1" or "tier2"
    n_cells: int
    n_pass_human: int
    n_pass_scorer: int
    cohen_kappa: float | None
    false_fail_rate: float | None  # scorer=fail, human=pass
    false_pass_rate: float | None  # scorer=pass, human=fail
    agreement_rate: float | None


@dataclass(frozen=True)
class ReplayDeterminism:
    n_cells_compared: int
    n_flips: int
    flip_rate: float
    meets_target: bool


@dataclass
class AgreementReport:
    n_subset: int
    n_annotated_cells: int
    n_consensus_cells: int
    n_tie_cells: int
    by_tier: list[TierAgreement] = field(default_factory=list)
    krippendorff_alpha: float | None = None
    replay: ReplayDeterminism | None = None
    notes: list[str] = field(default_factory=list)


class AgreementError(ValueError):
    pass


def compute_tier_agreement(
    tier_name: str,
    consensus: dict[tuple[str, str], HumanConsensus],
    scorer_verdicts: dict[tuple[str, str], str],
) -> TierAgreement:
    """Score one tier against the human consensus over the shared cell set."""
    common: list[tuple[str, str]] = []
    for cell, cs in consensus.items():
        if cs.consensus_verdict not in VALID_VERDICT:
            continue
        if cell not in scorer_verdicts:
            continue
        common.append((scorer_verdicts[cell], cs.consensus_verdict))
    if not common:
        return TierAgreement(
            tier=tier_name,
            n_cells=0,
            n_pass_human=0,
            n_pass_scorer=0,
            cohen_kappa=None,
            false_fail_rate=None,
            false_pass_rate=None,
            agreement_rate=None,
        )
    n = len(common)
    n_pass_scorer = sum(1 for s, _ in common if s == "pass")
    n_pass_human = sum(1 for _, h in common if h == "pass")
    n_agree = sum(1 for s, h in common if s == h)
    n_false_fail = sum(1 for s, h in common if s == "fail" and h == "pass")
    n_false_pass = sum(1 for s, h in common if s == "pass" and h == "fail")
    return TierAgreement(
        tier=tier_name,
        n_cells=n,
        n_pass_scorer=n_pass_scorer,
        n_pass_human=n_pass_human,
        cohen_kappa=cohen_kappa(common),
        false_fail_rate=n_false_fail / n,
        false_pass_rate=n_false_pass / n,
        agreement_rate=n_agree / n,
    )


def compute_krippendorff_with_scorers(
    annotations: list[AnnotationRow],
    tier1_verdicts: dict[tuple[str, str], str],
    tier2_verdicts: dict[tuple[str, str], str] | None,
) -> float | None:
    """Treat each tier as one additional rater for the cell-level α computation."""
    by_cell: dict[tuple[str, str], list[str | None]] = {}
    for a in annotations:
        cell = (a.task_id, a.candidate_trace_id)
        by_cell.setdefault(cell, []).append(a.verdict)
    for cell in list(by_cell.keys()):
        by_cell[cell].append(tier1_verdicts.get(cell))
        if tier2_verdicts is not None:
            by_cell[cell].append(tier2_verdicts.get(cell))
    if not by_cell:
        return None
    return krippendorff_alpha_binary(list(by_cell.values()))


def compute_replay_determinism(
    run_a: dict[tuple[str, str], str],
    run_b: dict[tuple[str, str], str],
) -> ReplayDeterminism:
    """Flip rate between two scorer runs over the same (task, cand_trace) cells.

    Only cells present in BOTH runs and with verdicts in VALID_VERDICT are
    counted. The done-when target is `flip_rate < REPLAY_FLIP_RATE_TARGET`.
    """
    common = set(run_a) & set(run_b)
    n = 0
    flips = 0
    for cell in common:
        va = run_a[cell]
        vb = run_b[cell]
        if va not in VALID_VERDICT or vb not in VALID_VERDICT:
            continue
        n += 1
        if va != vb:
            flips += 1
    flip_rate = (flips / n) if n else 0.0
    return ReplayDeterminism(
        n_cells_compared=n,
        n_flips=flips,
        flip_rate=flip_rate,
        meets_target=flip_rate < REPLAY_FLIP_RATE_TARGET,
    )


def build_report(
    *,
    subset_size: int,
    annotations: list[AnnotationRow],
    consensus: list[HumanConsensus],
    tier1_evals: list[EvaluationResult],
    tier2_evals: list[EvaluationResult] | None = None,
    replay_run_b_evals: list[EvaluationResult] | None = None,
) -> AgreementReport:
    """Assemble the full RQ4 agreement report.

    `tier1_evals` are the deterministic-only evals (judge off); we re-derive
    Tier-1 verdicts even when these come from a judge-enabled run, so the
    column is always tier-1-only.

    `tier2_evals` are the same evals with the judge enabled — the Tier-2
    column reflects the post-judge verdict.

    `replay_run_b_evals` is an optional second Tier-1 run used only for the
    replay-determinism flip rate.
    """
    consensus_idx = {(c.task_id, c.candidate_trace_id): c for c in consensus}
    decisive = {k: v for k, v in consensus_idx.items() if v.consensus_verdict in VALID_VERDICT}
    n_ties = sum(1 for c in consensus if c.consensus_verdict == "tie")

    tier1_idx = index_evals(tier1_evals)
    tier1_verdicts: dict[tuple[str, str], str] = {cell: _tier1_verdict(ev) for cell, ev in tier1_idx.items()}

    tier2_verdicts: dict[tuple[str, str], str] = {}
    if tier2_evals is not None:
        for cell, ev in index_evals(tier2_evals).items():
            v2 = _tier2_verdict(ev)
            if v2 is not None:
                tier2_verdicts[cell] = v2

    tier_results: list[TierAgreement] = [
        compute_tier_agreement("tier1", decisive, tier1_verdicts),
    ]
    if tier2_verdicts:
        tier_results.append(compute_tier_agreement("tier2", decisive, tier2_verdicts))

    alpha = compute_krippendorff_with_scorers(
        annotations,
        tier1_verdicts,
        tier2_verdicts if tier2_verdicts else None,
    )

    replay = None
    if replay_run_b_evals is not None:
        run_b = {cell: _tier1_verdict(ev) for cell, ev in index_evals(replay_run_b_evals).items()}
        replay = compute_replay_determinism(tier1_verdicts, run_b)

    return AgreementReport(
        n_subset=subset_size,
        n_annotated_cells=len({(a.task_id, a.candidate_trace_id) for a in annotations}),
        n_consensus_cells=len(decisive),
        n_tie_cells=n_ties,
        by_tier=tier_results,
        krippendorff_alpha=alpha,
        replay=replay,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _fmt(x: float | None, digits: int = 3) -> str:
    if x is None:
        return "—"
    return f"{x:.{digits}f}"


def _fmt_pct(x: float | None, digits: int = 1) -> str:
    if x is None:
        return "—"
    return f"{x * 100:.{digits}f}%"


def render_markdown(report: AgreementReport, *, title: str | None = None) -> str:
    lines: list[str] = []
    lines.append(f"# {title or 'RQ4 scorer-vs-human agreement (E4.6)'}")
    lines.append("")
    lines.append(
        f"_subset_: **{report.n_subset}** tasks ・ "
        f"_annotated cells_: **{report.n_annotated_cells}** ・ "
        f"_consensus cells_ (non-tie): **{report.n_consensus_cells}** ・ "
        f"_ties_: **{report.n_tie_cells}**"
    )
    lines.append("")
    lines.append("## Per-tier agreement vs human consensus")
    lines.append("")
    lines.append(
        "| tier | n | Cohen's κ | meets ≥0.7 | scorer pass | human pass | agree | false-fail | false-pass |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for t in report.by_tier:
        meets = "✓" if (t.cohen_kappa is not None and t.cohen_kappa >= AGREEMENT_THRESHOLD) else "—"
        lines.append(
            f"| `{t.tier}` | {t.n_cells} | {_fmt(t.cohen_kappa)} | {meets} | "
            f"{t.n_pass_scorer} | {t.n_pass_human} | "
            f"{_fmt_pct(t.agreement_rate)} | {_fmt_pct(t.false_fail_rate)} | "
            f"{_fmt_pct(t.false_pass_rate)} |"
        )
    lines.append("")
    lines.append("## Krippendorff's α (raters + scorers, binary nominal)")
    lines.append("")
    alpha = report.krippendorff_alpha
    meets_a = "✓" if (alpha is not None and alpha >= AGREEMENT_THRESHOLD) else "—"
    lines.append(f"- α = **{_fmt(alpha)}** ・ meets ≥0.7: {meets_a}")
    lines.append("")
    if report.replay is not None:
        r = report.replay
        meets_r = "✓" if r.meets_target else "—"
        lines.append("## Replay determinism (Tier-1 verdict, run-A vs run-B)")
        lines.append("")
        lines.append(
            f"- compared **{r.n_cells_compared}** cells ・ "
            f"flips = **{r.n_flips}** ・ "
            f"flip rate = **{_fmt_pct(r.flip_rate)}** ・ "
            f"meets <{REPLAY_FLIP_RATE_TARGET * 100:.0f}%: {meets_r}"
        )
        lines.append("")
    if report.notes:
        lines.append("## Notes")
        for n in report.notes:
            lines.append(f"- {n}")
        lines.append("")
    return "\n".join(lines) + "\n"


def report_to_json(report: AgreementReport) -> dict[str, Any]:
    return {
        "n_subset": report.n_subset,
        "n_annotated_cells": report.n_annotated_cells,
        "n_consensus_cells": report.n_consensus_cells,
        "n_tie_cells": report.n_tie_cells,
        "krippendorff_alpha": report.krippendorff_alpha,
        "tiers": [
            {
                "tier": t.tier,
                "n_cells": t.n_cells,
                "n_pass_scorer": t.n_pass_scorer,
                "n_pass_human": t.n_pass_human,
                "cohen_kappa": t.cohen_kappa,
                "agreement_rate": t.agreement_rate,
                "false_fail_rate": t.false_fail_rate,
                "false_pass_rate": t.false_pass_rate,
            }
            for t in report.by_tier
        ],
        "replay": (
            None
            if report.replay is None
            else {
                "n_cells_compared": report.replay.n_cells_compared,
                "n_flips": report.replay.n_flips,
                "flip_rate": report.replay.flip_rate,
                "meets_target": report.replay.meets_target,
            }
        ),
        "agreement_threshold": AGREEMENT_THRESHOLD,
        "replay_flip_rate_target": REPLAY_FLIP_RATE_TARGET,
        "notes": list(report.notes),
    }


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def load_evals(path: Path) -> list[EvaluationResult]:
    out: list[EvaluationResult] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(EvaluationResult.model_validate_json(line))
    return out


def load_consensus(path: Path) -> list[HumanConsensus]:
    out: list[HumanConsensus] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            out.append(
                HumanConsensus(
                    task_id=str(d["task_id"]),
                    candidate_trace_id=str(d["candidate_trace_id"]),
                    consensus_verdict=str(d.get("consensus_verdict", "tie")),
                    n_raters=int(d.get("n_raters", 0)),
                    vote_pass=int(d.get("vote_pass", 0)),
                    vote_fail=int(d.get("vote_fail", 0)),
                )
            )
    return out


def write_consensus(consensus: list[HumanConsensus], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for c in consensus:
            f.write(
                json.dumps(
                    {
                        "task_id": c.task_id,
                        "candidate_trace_id": c.candidate_trace_id,
                        "consensus_verdict": c.consensus_verdict,
                        "n_raters": c.n_raters,
                        "vote_pass": c.vote_pass,
                        "vote_fail": c.vote_fail,
                    }
                )
                + "\n"
            )
