"""RQ4 validation: deterministic stratified subset selection (E4.6).

RQ4 asks whether the Tier-1 deterministic scorer (`evaluator.py`) and the
Tier-2 LLM judge (`judge.py`) agree with a *human* consensus on a fixed
**200-task validation subset**. The subset must be balanced — never
oversample static or shallow tasks — so this module emits a deterministic
stratified sample over the `(dynamism, complexity_bin)` grid.

Outputs an `AnnotationRow` JSONL schema that human annotators fill in
(one row per (task_id, candidate_trace_id, rater_id)). A separate
`HumanConsensus` aggregate is computed from the row file: majority-vote
verdict + vote split + n_raters. The agreement statistics
(`dmcp/baselines/rq4_agreement.py`) consume both.

Per `memory/feedback_agb_orthogonality.md` and the CLAUDE.md hard
invariants: this module is read-only with respect to the headline scoring
path. It does NOT alter the evaluator/judge. Its only job is to put a
ground-truth-like signal next to the scorer outputs.
"""

from __future__ import annotations

import json
import random
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dmcp.curves import COMPLEXITY_BINS, complexity_bin
from dmcp.spec import TaskSpec

# Pre-registered subset target (research_plan RQ4 / simple_approach §5.6).
DEFAULT_SUBSET_N = 200

VALID_DYNAMISM = ("static", "live_read", "stateful_write")
VALID_VERDICT = ("pass", "fail")


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SubsetRow:
    """One row of the stratified validation subset."""

    task_id: str
    prompt: str
    dynamism: str
    complexity_bin: str
    trace_depth: int
    servers_used: tuple[str, ...]
    stratum_key: str  # f"{dynamism}|{complexity_bin}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "prompt": self.prompt,
            "dynamism": self.dynamism,
            "complexity_bin": self.complexity_bin,
            "trace_depth": self.trace_depth,
            "servers_used": list(self.servers_used),
            "stratum_key": self.stratum_key,
        }


@dataclass(frozen=True)
class AnnotationRow:
    """One human-rater annotation for one (task_id, candidate_trace_id) cell.

    Rater fills `verdict`, `justification`, `minutes_spent`. The other
    fields are pre-populated when the annotation file is generated from a
    subset + a set of candidate traces.
    """

    task_id: str
    candidate_trace_id: str
    candidate_model: str
    rater_id: str
    verdict: str  # "pass" | "fail"
    justification: str = ""
    minutes_spent: float = 0.0
    annotated_at: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AnnotationRow:
        verdict = str(d.get("verdict", "")).strip().lower()
        if verdict not in VALID_VERDICT:
            raise SubsetError(f"verdict must be in {VALID_VERDICT}; got {verdict!r}")
        return cls(
            task_id=str(d["task_id"]),
            candidate_trace_id=str(d["candidate_trace_id"]),
            candidate_model=str(d.get("candidate_model", "")),
            rater_id=str(d["rater_id"]),
            verdict=verdict,
            justification=str(d.get("justification", "")),
            minutes_spent=float(d.get("minutes_spent", 0.0)),
            annotated_at=d.get("annotated_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "candidate_trace_id": self.candidate_trace_id,
            "candidate_model": self.candidate_model,
            "rater_id": self.rater_id,
            "verdict": self.verdict,
            "justification": self.justification,
            "minutes_spent": self.minutes_spent,
            "annotated_at": self.annotated_at,
        }


@dataclass(frozen=True)
class HumanConsensus:
    """Aggregated human verdict for one (task_id, candidate_trace_id) cell."""

    task_id: str
    candidate_trace_id: str
    consensus_verdict: str  # "pass" | "fail" | "tie"
    n_raters: int
    vote_pass: int
    vote_fail: int


@dataclass
class SubsetManifest:
    rows: list[SubsetRow] = field(default_factory=list)
    target_n: int = DEFAULT_SUBSET_N
    achieved_n: int = 0
    seed: int = 0
    stratum_counts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    generated_at: str = ""


class SubsetError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Stratified sampling
# ---------------------------------------------------------------------------


def _spec_dynamism(spec: TaskSpec) -> str:
    return spec.dynamism.value if hasattr(spec.dynamism, "value") else str(spec.dynamism)


def _to_subset_row(spec: TaskSpec) -> SubsetRow:
    depth = int(getattr(spec.complexity, "trace_depth", 0) or 0)
    dyn = _spec_dynamism(spec)
    cbin = complexity_bin(depth)
    return SubsetRow(
        task_id=str(spec.task_id),
        prompt=spec.prompt,
        dynamism=dyn,
        complexity_bin=cbin,
        trace_depth=depth,
        servers_used=tuple(spec.servers_used),
        stratum_key=f"{dyn}|{cbin}",
    )


def _expected_strata() -> list[str]:
    return [f"{d}|{b}" for d in VALID_DYNAMISM for b in COMPLEXITY_BINS]


def build_subset(
    specs: Iterable[TaskSpec],
    *,
    n: int = DEFAULT_SUBSET_N,
    seed: int = 0,
) -> SubsetManifest:
    """Deterministic stratified sample of `n` tasks from `specs`.

    Stratification is over the (dynamism × complexity_bin) grid. Within
    each non-empty stratum the population is sorted by task_id for
    stability, then shuffled with a seed derived from the parent seed and
    the stratum key. Quotas are computed by quasi-proportional rounding
    with a floor of 1 per non-empty stratum so the corners of the grid
    don't get dropped at small N.
    """
    by_stratum: dict[str, list[SubsetRow]] = {}
    total = 0
    for spec in specs:
        row = _to_subset_row(spec)
        by_stratum.setdefault(row.stratum_key, []).append(row)
        total += 1
    if total == 0:
        raise SubsetError("no specs available to subset")

    non_empty = {k: rows for k, rows in by_stratum.items() if rows}
    # Quotas: proportional to stratum size, but every non-empty stratum gets ≥ 1.
    pop_total = sum(len(rs) for rs in non_empty.values())
    target = min(n, pop_total)
    quotas: dict[str, int] = {}
    leftover: list[tuple[float, str]] = []
    assigned = 0
    for key, rows in non_empty.items():
        ideal = target * len(rows) / pop_total
        floor = max(1, int(ideal))
        # Don't allocate more than the stratum can supply.
        floor = min(floor, len(rows))
        quotas[key] = floor
        assigned += floor
        leftover.append((ideal - floor, key))
    # Adjust to hit `target`: top up by fractional leftover, then drop if over.
    if assigned < target:
        leftover.sort(key=lambda x: (-x[0], x[1]))
        i = 0
        while assigned < target and leftover:
            frac, key = leftover[i]
            if quotas[key] < len(non_empty[key]):
                quotas[key] += 1
                assigned += 1
            i = (i + 1) % len(leftover)
            # Safety: if every stratum is at its cap, stop.
            if all(quotas[k] >= len(non_empty[k]) for k in quotas):
                break
    elif assigned > target:
        # Trim from largest quotas first to keep small-stratum representation.
        order = sorted(quotas.keys(), key=lambda k: (-quotas[k], k))
        i = 0
        while assigned > target:
            key = order[i % len(order)]
            if quotas[key] > 1:
                quotas[key] -= 1
                assigned -= 1
            i += 1
            if i > len(order) * 10:
                break  # paranoia: should never need this

    rows_out: list[SubsetRow] = []
    notes: list[str] = []
    stratum_counts: dict[str, int] = {}
    for key in sorted(non_empty.keys()):
        rows = sorted(non_empty[key], key=lambda r: r.task_id)
        rng = random.Random(seed * 1_000_003 + (hash(key) & 0xFFFF))
        rng.shuffle(rows)
        take = min(quotas.get(key, 0), len(rows))
        rows_out.extend(rows[:take])
        stratum_counts[key] = take
    for expected in _expected_strata():
        if expected not in stratum_counts:
            notes.append(f"stratum {expected} is empty in the substrate")

    return SubsetManifest(
        rows=rows_out,
        target_n=n,
        achieved_n=len(rows_out),
        seed=seed,
        stratum_counts=stratum_counts,
        notes=notes,
        generated_at=datetime.now(UTC).isoformat(),
    )


# ---------------------------------------------------------------------------
# Annotation schema & consensus
# ---------------------------------------------------------------------------


def write_subset_jsonl(manifest: SubsetManifest, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in manifest.rows:
            f.write(json.dumps(row.to_dict()) + "\n")


def load_subset_jsonl(path: Path) -> list[SubsetRow]:
    out: list[SubsetRow] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            out.append(
                SubsetRow(
                    task_id=str(d["task_id"]),
                    prompt=str(d.get("prompt", "")),
                    dynamism=str(d.get("dynamism", "")),
                    complexity_bin=str(d.get("complexity_bin", "")),
                    trace_depth=int(d.get("trace_depth", 0)),
                    servers_used=tuple(d.get("servers_used") or ()),
                    stratum_key=str(d.get("stratum_key", "")),
                )
            )
    return out


def write_annotation_template(
    subset: list[SubsetRow],
    candidate_rows: Iterable[dict[str, Any]],
    *,
    rater_ids: list[str],
    path: Path,
) -> int:
    """Emit a starter annotation JSONL — one row per (task, cand_trace, rater).

    `candidate_rows` is an iterable of dicts with at minimum
    `{"task_id": str, "candidate_trace_id": str, "candidate_model": str}`
    (the schema emitted by `dmcp eval --candidate-traces-out`). Verdicts are
    left empty for the rater to fill.
    """
    subset_index = {r.task_id for r in subset}
    written = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for cand in candidate_rows:
            task_id = str(cand.get("task_id") or "")
            if task_id not in subset_index:
                continue
            cand_tid = str(cand.get("candidate_trace_id") or "")
            model = str(cand.get("candidate_model") or "")
            for rater in rater_ids:
                row = {
                    "task_id": task_id,
                    "candidate_trace_id": cand_tid,
                    "candidate_model": model,
                    "rater_id": rater,
                    "verdict": "",  # rater fills "pass" or "fail"
                    "justification": "",
                    "minutes_spent": 0.0,
                    "annotated_at": None,
                }
                f.write(json.dumps(row) + "\n")
                written += 1
    return written


def load_annotations(path: Path) -> list[AnnotationRow]:
    out: list[AnnotationRow] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            verdict = str(d.get("verdict", "")).strip().lower()
            if verdict not in VALID_VERDICT:
                # Skip un-annotated rows silently — the human hasn't filled them yet.
                continue
            out.append(AnnotationRow.from_dict({**d, "verdict": verdict}))
    return out


def compute_consensus(annotations: Iterable[AnnotationRow]) -> list[HumanConsensus]:
    """Majority-vote consensus per (task_id, candidate_trace_id).

    Ties are reported as `consensus_verdict = "tie"` rather than being
    silently broken — the agreement statistics treat ties as inconclusive.
    """
    by_cell: dict[tuple[str, str], list[AnnotationRow]] = {}
    for a in annotations:
        by_cell.setdefault((a.task_id, a.candidate_trace_id), []).append(a)
    out: list[HumanConsensus] = []
    for (tid, ctid), rows in sorted(by_cell.items()):
        passes = sum(1 for r in rows if r.verdict == "pass")
        fails = sum(1 for r in rows if r.verdict == "fail")
        if passes > fails:
            verdict = "pass"
        elif fails > passes:
            verdict = "fail"
        else:
            verdict = "tie"
        out.append(
            HumanConsensus(
                task_id=tid,
                candidate_trace_id=ctid,
                consensus_verdict=verdict,
                n_raters=len(rows),
                vote_pass=passes,
                vote_fail=fails,
            )
        )
    return out
