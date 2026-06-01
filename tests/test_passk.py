"""E1.1: unit tests for the pass^k aggregation (dmcp.report.passk_stats)."""

from __future__ import annotations

import uuid

from dmcp.report import passk_stats


def test_passk_basic_and_pass1():
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    runs = {a: [True, True, True], b: [True, False, True], c: [True]}
    st = passk_stats(runs)
    # only a and c have all-passing runs → pass^k = 2/3
    assert abs(st["passk"] - 2 / 3) < 1e-9
    # 6 of 7 individual runs passed → pass@1 = 6/7
    assert abs(st["pass1"] - 6 / 7) < 1e-9
    assert st["tasks"] == 3
    assert st["runs"] == 7
    assert st["max_runs"] == 3


def test_passk_no_sae_excludes_flagged_tasks():
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    runs = {a: [True, True], b: [True, False], c: [True, True]}
    # b is the only failing task and also the SAE-flagged one → no-SAE subset {a,c} all pass
    st = passk_stats(runs, sae_tasks={b})
    assert abs(st["passk"] - 2 / 3) < 1e-9
    assert abs(st["passk_no_sae"] - 1.0) < 1e-9


def test_passk_empty():
    st = passk_stats({})
    assert st == {
        "passk": 0.0,
        "passk_no_sae": 0.0,
        "pass1": 0.0,
        "tasks": 0,
        "runs": 0,
        "max_runs": 0,
    }


def test_passk_single_run_equals_pass1():
    a, b = uuid.uuid4(), uuid.uuid4()
    st = passk_stats({a: [True], b: [False]})
    assert st["passk"] == 0.5
    assert st["pass1"] == 0.5
    assert st["max_runs"] == 1
