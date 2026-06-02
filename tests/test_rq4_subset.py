"""E4.6: stratified subset selector + annotation schema."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from dmcp.baselines.rq4_subset import (
    AnnotationRow,
    SubsetError,
    build_subset,
    compute_consensus,
    load_annotations,
    load_subset_jsonl,
    write_annotation_template,
    write_subset_jsonl,
)
from dmcp.manifest import Dynamism
from dmcp.spec import ComplexityProfile, TaskSpec, ToolEffectCheckpoint, ToolReference


def _mk_spec(*, dynamism: Dynamism = Dynamism.live_read, depth: int = 1, prompt: str = "x") -> TaskSpec:
    return TaskSpec(
        task_id=uuid4(),
        source_trace_id=uuid4(),
        prompt=prompt,
        dynamism=dynamism,
        servers_used=["s"],
        complexity=ComplexityProfile(
            trace_depth=depth,
            distinct_servers=1,
            cross_server=False,
            runtime_branching=False,
            state_coupling=dynamism is Dynamism.stateful_write,
            recovery_required=False,
        ),
        checkpoints=[
            ToolEffectCheckpoint(
                checkpoint_id="cp-0",
                description="x",
                equivalence_set=[ToolReference(server_id="s", tool_name="t")],
            )
        ],
    )


def _balanced_dataset(n_per_stratum: int = 6) -> list[TaskSpec]:
    """Six tasks per (dynamism, depth-bin) combination — 6 × 3 × 4 = 72 specs."""
    specs: list[TaskSpec] = []
    for dyn in (Dynamism.static, Dynamism.live_read, Dynamism.stateful_write):
        for depth in (1, 2, 3, 5):
            for _ in range(n_per_stratum):
                specs.append(_mk_spec(dynamism=dyn, depth=depth))
    return specs


# ---------------------------------------------------------------------------
# build_subset
# ---------------------------------------------------------------------------


def test_build_subset_is_deterministic():
    specs = _balanced_dataset(n_per_stratum=5)
    a = build_subset(specs, n=24, seed=42)
    b = build_subset(specs, n=24, seed=42)
    assert [r.task_id for r in a.rows] == [r.task_id for r in b.rows]
    assert a.achieved_n == 24


def test_build_subset_distinct_seeds_can_differ():
    specs = _balanced_dataset(n_per_stratum=8)
    a = build_subset(specs, n=24, seed=1)
    b = build_subset(specs, n=24, seed=2)
    # At least one row should differ — seeds shuffle within strata
    assert {r.task_id for r in a.rows} != {r.task_id for r in b.rows}


def test_build_subset_every_non_empty_stratum_represented():
    """Even at small N, every non-empty stratum gets ≥ 1 row."""
    specs = _balanced_dataset(n_per_stratum=3)  # 36 specs across 12 strata
    sub = build_subset(specs, n=12, seed=0)
    seen = {r.stratum_key for r in sub.rows}
    expected = {
        f"{d.value}|{b}"
        for d in (Dynamism.static, Dynamism.live_read, Dynamism.stateful_write)
        for b in ("1", "2", "3-4", "5+")
    }
    assert seen == expected
    assert sub.achieved_n == 12


def test_build_subset_caps_at_population_size():
    specs = _balanced_dataset(n_per_stratum=2)  # only 24 specs
    sub = build_subset(specs, n=200, seed=0)
    assert sub.achieved_n == 24
    assert sub.target_n == 200


def test_build_subset_rejects_empty_input():
    with pytest.raises(SubsetError):
        build_subset([], n=10, seed=0)


def test_build_subset_notes_missing_strata():
    """If the substrate is missing entire dynamism classes, that's noted."""
    specs = [_mk_spec(dynamism=Dynamism.live_read, depth=1) for _ in range(8)]
    sub = build_subset(specs, n=4, seed=0)
    note_blob = "\n".join(sub.notes)
    assert "static|1" in note_blob
    assert "stateful_write|1" in note_blob


# ---------------------------------------------------------------------------
# JSONL I/O
# ---------------------------------------------------------------------------


def test_subset_jsonl_round_trip(tmp_path: Path):
    sub = build_subset(_balanced_dataset(n_per_stratum=3), n=8, seed=0)
    p = tmp_path / "subset.jsonl"
    write_subset_jsonl(sub, p)
    rows = load_subset_jsonl(p)
    assert [r.task_id for r in rows] == [r.task_id for r in sub.rows]


def test_annotation_template_emits_one_row_per_rater_per_subset_task(tmp_path: Path):
    sub = build_subset(_balanced_dataset(n_per_stratum=2), n=6, seed=0)
    # Make 2 candidate runs for each task in the subset + 1 extraneous task.
    cands = []
    for r in sub.rows:
        for c in (0, 1):
            cands.append(
                {
                    "task_id": r.task_id,
                    "candidate_trace_id": f"{r.task_id}-c{c}",
                    "candidate_model": "modelX",
                }
            )
    cands.append({"task_id": "not-in-subset", "candidate_trace_id": "x", "candidate_model": "y"})
    p = tmp_path / "annotations.jsonl"
    n = write_annotation_template(sub.rows, cands, rater_ids=["alice", "bob"], path=p)
    # achieved_n tasks × 2 candidates × 2 raters; the extraneous task is dropped
    assert n == sub.achieved_n * 2 * 2
    raw_rows = [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
    assert all(r["task_id"] != "not-in-subset" for r in raw_rows)


def test_load_annotations_skips_unfilled_rows(tmp_path: Path):
    p = tmp_path / "a.jsonl"
    p.write_text(
        json.dumps(
            {
                "task_id": "t",
                "candidate_trace_id": "c",
                "candidate_model": "m",
                "rater_id": "alice",
                "verdict": "",  # empty — unfilled
            }
        )
        + "\n"
        + json.dumps(
            {
                "task_id": "t",
                "candidate_trace_id": "c",
                "candidate_model": "m",
                "rater_id": "bob",
                "verdict": "pass",
            }
        )
        + "\n"
    )
    rows = load_annotations(p)
    assert len(rows) == 1
    assert rows[0].verdict == "pass"


def test_annotation_row_from_dict_rejects_bad_verdict():
    with pytest.raises(SubsetError):
        AnnotationRow.from_dict(
            {
                "task_id": "t",
                "candidate_trace_id": "c",
                "candidate_model": "m",
                "rater_id": "alice",
                "verdict": "maybe",
            }
        )


# ---------------------------------------------------------------------------
# Consensus
# ---------------------------------------------------------------------------


def _ann(task: str, cand: str, rater: str, verdict: str) -> AnnotationRow:
    return AnnotationRow(
        task_id=task,
        candidate_trace_id=cand,
        candidate_model="m",
        rater_id=rater,
        verdict=verdict,
    )


def test_consensus_majority_vote():
    ann = [
        _ann("t1", "c1", "alice", "pass"),
        _ann("t1", "c1", "bob", "pass"),
        _ann("t1", "c1", "carol", "fail"),
    ]
    cs = compute_consensus(ann)
    assert len(cs) == 1
    assert cs[0].consensus_verdict == "pass"
    assert cs[0].vote_pass == 2
    assert cs[0].vote_fail == 1
    assert cs[0].n_raters == 3


def test_consensus_reports_tie():
    ann = [
        _ann("t1", "c1", "alice", "pass"),
        _ann("t1", "c1", "bob", "fail"),
    ]
    cs = compute_consensus(ann)
    assert cs[0].consensus_verdict == "tie"
