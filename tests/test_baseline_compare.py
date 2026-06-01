"""E4.3: RQ2 generation-quality comparison harness."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from dmcp.baselines.compare import (
    BASELINE_VERSION_PREFIX,
    CompareError,
    compare_methods,
    load_catalog,
    render_markdown,
    report_to_json,
    summarize_method,
)
from dmcp.manifest import Dynamism
from dmcp.spec import (
    ArgPredicate,
    ComplexityProfile,
    TaskSpec,
    ToolEffectCheckpoint,
    ToolReference,
)


def _mk_spec(
    *,
    method: str,
    tools: list[tuple[str, str]],
    eq_set_for_first: list[tuple[str, str]] | None = None,
    arg_predicate: bool = True,
    prompt: str = "do the thing",
) -> TaskSpec:
    """Synthesize a TaskSpec with `len(tools)` tool_effect checkpoints.

    The first checkpoint optionally gets a wider `equivalence_set` (so we can
    exercise the "multi-tool equivalence_set" axis for the forward arm)."""
    cps: list[ToolEffectCheckpoint] = []
    for i, (sid, tname) in enumerate(tools):
        eq = [ToolReference(server_id=sid, tool_name=tname)]
        if i == 0 and eq_set_for_first:
            eq = [ToolReference(server_id=s, tool_name=t) for s, t in eq_set_for_first]
        cps.append(
            ToolEffectCheckpoint(
                checkpoint_id=f"cp-{i}",
                description="x",
                equivalence_set=eq,
                arg_predicate=(ArgPredicate(must_include={"x": 1}) if arg_predicate else None),
                must_succeed=True,
            )
        )
    if method == "forward":
        version = "0.1.0"
        notes = None
    elif method == "graph":
        version = "baseline-graph-sampling-0.1.0"
        notes = "[BASELINE:graph_sampling motif=chain seed=0]"
    elif method == "direct":
        version = "baseline-direct-generation-0.1.0"
        notes = "[BASELINE:direct_generation]"
    else:
        raise AssertionError(method)
    server_ids = sorted({s for s, _ in tools})
    return TaskSpec(
        task_id=uuid4(),
        distiller_version=version,
        source_trace_id=uuid4(),
        prompt=prompt,
        dynamism=Dynamism.live_read,
        servers_used=server_ids,
        complexity=ComplexityProfile(
            trace_depth=len(tools),
            distinct_servers=len(server_ids),
            cross_server=len(server_ids) > 1,
            runtime_branching=False,
            state_coupling=False,
            recovery_required=False,
        ),
        checkpoints=list(cps),
        notes=notes,
    )


def _write_jsonl(path: Path, specs: list[TaskSpec]) -> None:
    path.write_text(
        "\n".join(s.to_jsonl() for s in specs) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# summarize_method
# ---------------------------------------------------------------------------


def test_forward_arm_records_multi_tool_equivalence_sets():
    """The headline axis: forward eq_sets can be >1; baselines are 1.0 by build."""
    specs = [
        _mk_spec(
            method="forward",
            tools=[("s", "a"), ("s", "b")],
            eq_set_for_first=[("s", "a"), ("t", "a_alt"), ("u", "a_alt2")],
        ),
        _mk_spec(method="forward", tools=[("s", "c")]),
    ]
    summary = summarize_method(
        "forward",
        specs,
        catalog={("s", "a"), ("s", "b"), ("s", "c"), ("t", "a_alt"), ("z", "unused")},
        has_reference_traces=True,
    )
    # 3 tool_effect cps total; first has 3 equiv-tools, others have 1.
    assert summary.n_tool_effect_checkpoints == 3
    assert summary.max_eq_set_size == 3
    assert summary.fraction_singleton_eq_set == pytest.approx(2 / 3)
    assert summary.mean_eq_set_size == pytest.approx((3 + 1 + 1) / 3)
    # referenced = {s.a, s.b, s.c, t.a_alt, u.a_alt2}; catalog = 5 entries
    # of which {s.a, s.b, s.c, t.a_alt} = 4 also appear in referenced → 4/5
    assert summary.coverage == pytest.approx(4 / 5)
    # Executable-by-construction set for forward
    assert summary.executable_by_construction == 1.0
    assert summary.marker_violations == ()


def test_baseline_arms_are_singletons_by_construction():
    specs = [
        _mk_spec(method="graph", tools=[("s", "a"), ("s", "b")]),
        _mk_spec(method="graph", tools=[("s", "c")]),
    ]
    summary = summarize_method("graph", specs)
    assert summary.fraction_singleton_eq_set == 1.0
    assert summary.max_eq_set_size == 1
    assert summary.executable_by_construction is None  # baselines need a live re-run
    assert summary.marker_violations == ()


def test_marker_violation_flagged_when_arms_mixed():
    # A forward-versioned spec smuggled into the graph arm — verify it's flagged.
    specs = [
        _mk_spec(method="forward", tools=[("s", "a")]),
        _mk_spec(method="graph", tools=[("s", "b")]),
    ]
    summary = summarize_method("graph", specs)
    assert any("0.1.0" in v for v in summary.marker_violations)
    summary_fwd = summarize_method("forward", [_mk_spec(method="graph", tools=[("s", "x")])])
    assert any("baseline-" in v for v in summary_fwd.marker_violations)


def test_missing_arg_predicate_rate_proxies_unnecessary_tool_upper_bound():
    """Direct gen with no args → 100% missing arg_predicate (upper bound)."""
    specs = [
        _mk_spec(method="direct", tools=[("s", "a"), ("s", "b")], arg_predicate=False),
    ]
    summary = summarize_method("direct", specs)
    assert summary.fraction_missing_arg_predicate == 1.0


def test_filter_pass_rate_computed_only_when_proposals_supplied():
    specs = [_mk_spec(method="direct", tools=[("s", "a")])]
    no_meta = summarize_method("direct", specs)
    with_meta = summarize_method("direct", specs, proposals_attempted=4)
    assert no_meta.filter_pass_rate is None
    assert with_meta.filter_pass_rate == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# compare_methods + rendering + JSON
# ---------------------------------------------------------------------------


def test_compare_methods_rejects_unknown_label(tmp_path: Path):
    path = tmp_path / "x.jsonl"
    path.write_text("")
    with pytest.raises(CompareError):
        compare_methods({"forward": path, "bogus": path})


def test_compare_methods_end_to_end(tmp_path: Path):
    forward = tmp_path / "forward.jsonl"
    graph = tmp_path / "graph.jsonl"
    direct = tmp_path / "direct.jsonl"
    _write_jsonl(
        forward,
        [
            _mk_spec(
                method="forward",
                tools=[("s", "a"), ("s", "b")],
                eq_set_for_first=[("s", "a"), ("t", "a_alt")],
            )
        ],
    )
    _write_jsonl(
        graph,
        [_mk_spec(method="graph", tools=[("s", "a"), ("s", "b")])],
    )
    _write_jsonl(
        direct,
        [_mk_spec(method="direct", tools=[("s", "a")], arg_predicate=False)],
    )
    catalog = {("s", "a"), ("s", "b"), ("t", "a_alt"), ("z", "unused")}
    report = compare_methods(
        {"forward": forward, "graph": graph, "direct": direct},
        catalog=catalog,
        proposals_attempted={"graph": 3, "direct": 4},
    )
    fwd = report.by_method("forward")
    grf = report.by_method("graph")
    dir_ = report.by_method("direct")

    # Headline axis: forward beats both baselines on mean |eq_set|.
    assert fwd.mean_eq_set_size > grf.mean_eq_set_size
    assert fwd.mean_eq_set_size > dir_.mean_eq_set_size
    # Baselines are entirely singleton-equivalence.
    assert grf.fraction_singleton_eq_set == 1.0
    assert dir_.fraction_singleton_eq_set == 1.0
    # Filter pass rate populated only where proposals were supplied.
    assert fwd.filter_pass_rate is None
    assert grf.filter_pass_rate == pytest.approx(1 / 3)
    assert dir_.filter_pass_rate == pytest.approx(1 / 4)
    # Catalog size carries through.
    assert report.catalog_size == 4
    # No marker violations on a clean run.
    assert report.notes == []

    md = render_markdown(report, title="unit-test comparison")
    assert "unit-test comparison" in md
    assert "distinct valid paths" in md
    assert "Deferred axes" in md
    # All three method columns must appear.
    for label in ("forward", "graph", "direct"):
        assert label in md

    j = report_to_json(report)
    assert {m["method"] for m in j["methods"]} == {"forward", "graph", "direct"}
    assert j["catalog_size"] == 4


# ---------------------------------------------------------------------------
# Catalog loader
# ---------------------------------------------------------------------------


def test_load_catalog_round_trip(tmp_path: Path):
    p = tmp_path / "catalog.json"
    p.write_text(json.dumps([["s", "a"], ["t", "b"]]))
    cat = load_catalog(p)
    assert cat == {("s", "a"), ("t", "b")}


def test_load_catalog_rejects_bad_shape(tmp_path: Path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"not": "a list"}))
    with pytest.raises(CompareError):
        load_catalog(p)


def test_baseline_version_prefix_is_orthogonality_marker():
    # Same orthogonality guard as the generators: the prefix is the audit-able
    # signal that report aggregators can use to keep the headline tally clean.
    assert BASELINE_VERSION_PREFIX == "baseline-"
