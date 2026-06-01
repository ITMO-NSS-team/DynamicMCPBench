"""E1.3: unit test for candidate-trace ingestion indexing (dmcp.cli.index_candidate_traces)."""

from __future__ import annotations

from dmcp.cli import index_candidate_traces
from dmcp.trace import Trace


def test_index_candidate_traces_by_task_and_prompt(tmp_path):
    t1 = Trace(goal="do X")
    t1.seed_metadata["task_id"] = "task-abc"
    t2 = Trace(goal="do Y")  # no task_id → matched only by prompt

    p = tmp_path / "cand.jsonl"
    p.write_text(t1.to_jsonl() + "\n" + t2.to_jsonl() + "\n", encoding="utf-8")

    by_task, by_prompt = index_candidate_traces(p)

    # task-tagged trace is indexed by its task_id ...
    assert "task-abc" in by_task
    assert by_task["task-abc"][0].goal == "do X"
    # ... and also by prompt (fallback path)
    assert by_prompt["do X"][0].trace_id == t1.trace_id
    # the untagged trace is reachable only by prompt
    assert set(by_task) == {"task-abc"}  # t2 (no task_id) contributes no task key
    assert by_prompt["do Y"][0].trace_id == t2.trace_id


def test_index_candidate_traces_multiple_per_task(tmp_path):
    a, b = Trace(goal="g"), Trace(goal="g")
    a.seed_metadata["task_id"] = "t1"
    b.seed_metadata["task_id"] = "t1"
    p = tmp_path / "cand.jsonl"
    p.write_text(a.to_jsonl() + "\n" + b.to_jsonl() + "\n", encoding="utf-8")
    by_task, _ = index_candidate_traces(p)
    # two traces for one task → kept for pass^k aggregation
    assert len(by_task["t1"]) == 2
