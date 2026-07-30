"""Tests for the wide refresh/decay sweep driver (`scripts/decay_sweep.py`).

Covers the pure parts: domain assignment, sample stratification, per-call
aggregation and rate arithmetic. The subprocess runner itself is not exercised
here — it shells out to live MCP servers, which has no place in the test suite.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import decay_sweep  # noqa: E402


def _trace(trace_id: str, *servers: str, internal: tuple[str, ...] = ()) -> dict:
    steps = [{"kind": "call_tool_agent", "server_id": s} for s in servers]
    steps += [{"kind": "call_tool_server_internal", "server_id": s} for s in internal]
    return {"trace_id": trace_id, "steps": steps}


def _spec(task_id: str, trace_id: str) -> dict:
    return {"task_id": task_id, "source_trace_id": trace_id}


def _manifest(**servers: str) -> dict:
    return {sid: {"server_id": sid, "dynamism": dyn, "description": ""} for sid, dyn in servers.items()}


# --- domain assignment -------------------------------------------------------


def test_domain_for_matches_known_families():
    assert decay_sweep.domain_for("yfinance", "Stock market data") == "finance_markets"
    assert decay_sweep.domain_for("arxiv", "Search scholarly papers") == "science_health"
    assert decay_sweep.domain_for("wikipedia", "Encyclopedia search") == "reference_knowledge"
    assert decay_sweep.domain_for("eu_ansvar__italian_law_mcp", "") == "law_compliance"


def test_domain_for_falls_back_to_other():
    assert decay_sweep.domain_for("zzz_unmatched", "a widget of no known kind") == "other"


def test_domain_for_normalises_underscores():
    # "federal_register" must match the "federal register" keyword.
    assert decay_sweep.domain_for("io_github__federal_register_mcp", "") == "law_compliance"


def test_domain_for_is_first_rule_wins():
    # Matches both law_compliance ("compliance") and finance_markets ("bank");
    # rule order makes the result deterministic rather than dict-order dependent.
    assert decay_sweep.domain_for("x", "bank compliance reporting") == "law_compliance"


# --- primary server ----------------------------------------------------------


def test_primary_server_picks_the_most_called():
    trace = _trace("t", "alpha", "beta", "beta")
    assert decay_sweep.primary_server(trace) == "beta"


def test_primary_server_ignores_local_scaffolding():
    trace = _trace("t", "git", "git", "git", "arxiv")
    assert decay_sweep.primary_server(trace) == "arxiv"


def test_primary_server_ignores_server_internal_steps():
    trace = _trace("t", "alpha", internal=("beta", "beta", "beta"))
    assert decay_sweep.primary_server(trace) == "alpha"


def test_primary_server_handles_empty_trace():
    assert decay_sweep.primary_server({"steps": []}) == "?"


# --- stratification ----------------------------------------------------------


def test_stratified_sample_caps_per_server():
    traces = {f"t{i}": _trace(f"t{i}", "alpha") for i in range(5)}
    specs = [_spec(f"task-{i}", f"t{i}") for i in range(5)]
    sample = decay_sweep.stratified_sample(specs, traces, _manifest(alpha="live_read"), 2)
    assert list(sample) == ["alpha"]
    assert [s["task_id"] for s in sample["alpha"]] == ["task-0", "task-1"]


def test_stratified_sample_is_deterministic_by_task_id():
    traces = {f"t{i}": _trace(f"t{i}", "alpha") for i in range(3)}
    specs = [_spec("task-c", "t0"), _spec("task-a", "t1"), _spec("task-b", "t2")]
    sample = decay_sweep.stratified_sample(specs, traces, _manifest(alpha="live_read"), 2)
    assert [s["task_id"] for s in sample["alpha"]] == ["task-a", "task-b"]


def test_stratified_sample_skips_stateful_write():
    """Invariant 4: refresh must never cause real side effects."""
    traces = {"t0": _trace("t0", "git"), "t1": _trace("t1", "alpha")}
    specs = [_spec("task-0", "t0"), _spec("task-1", "t1")]
    manifest = _manifest(git="stateful_write", alpha="live_read")
    sample = decay_sweep.stratified_sample(specs, traces, manifest, 3)
    assert list(sample) == ["alpha"]


def test_stratified_sample_skips_servers_absent_from_manifest():
    traces = {"t0": _trace("t0", "ghost"), "t1": _trace("t1", "alpha")}
    specs = [_spec("task-0", "t0"), _spec("task-1", "t1")]
    sample = decay_sweep.stratified_sample(specs, traces, _manifest(alpha="live_read"), 3)
    assert list(sample) == ["alpha"]


def test_stratified_sample_skips_orphan_specs():
    specs = [_spec("task-0", "missing-trace")]
    assert decay_sweep.stratified_sample(specs, {}, _manifest(alpha="live_read"), 3) == {}


# --- rates -------------------------------------------------------------------


def test_rates_exclude_non_live_calls_from_the_denominator():
    import collections

    counts = collections.Counter(
        identical=5, drifted=3, schema_drift=1, state_decay=1, unresolved=40, skipped=7, quarantined=3
    )
    rates = decay_sweep._rates(counts)
    assert rates["live_calls"] == 10  # 5 + 3 + 1 + 1; the other 50 are excluded
    assert rates["attributable"] == 2
    assert rates["identical_pct"] == 50.0
    assert rates["drifted_pct"] == 30.0
    assert rates["broken_pct"] == 20.0


def test_rates_omit_percentages_when_nothing_ran_live():
    import collections

    rates = decay_sweep._rates(collections.Counter(unresolved=4, skipped=2))
    assert rates["live_calls"] == 0
    assert "identical_pct" not in rates


# --- aggregation -------------------------------------------------------------


def _record(server: str, status: str, *calls: tuple[str, str]) -> dict:
    return {
        "task_id": f"task-{server}",
        "server_id": server,
        "status": status,
        "calls": [{"server_id": s, "classification": c, "retry_count": 0} for s, c in calls],
    }


def test_aggregate_attributes_calls_to_their_own_server():
    """A trace sampled under `alpha` may call `beta`; the call belongs to beta."""
    records = [_record("alpha", "ok", ("alpha", "identical"), ("beta", "drifted"))]
    manifest = _manifest(alpha="live_read", beta="live_read")
    agg = decay_sweep.aggregate(records, manifest)
    assert agg["per_server"]["alpha"]["identical"] == 1
    assert agg["per_server"]["alpha"]["drifted"] == 0
    assert agg["per_server"]["beta"]["drifted"] == 1
    assert agg["servers_sampled"] == 1
    assert agg["servers_with_calls"] == 2


def test_aggregate_rolls_up_by_domain_and_counts_distinct_servers():
    records = [
        _record("yfinance", "ok", ("yfinance", "identical"), ("yfinance", "drifted")),
        _record("apra", "ok", ("apra", "drifted")),
        _record("arxiv", "ok", ("arxiv", "state_decay")),
    ]
    manifest = {
        "yfinance": {"dynamism": "live_read", "description": "stock market"},
        "apra": {"dynamism": "live_read", "description": "bank regulator data"},
        "arxiv": {"dynamism": "live_read", "description": "scholarly papers"},
    }
    agg = decay_sweep.aggregate(records, manifest)
    finance = agg["per_domain"]["finance_markets"]
    assert finance["live_calls"] == 3
    assert finance["servers"] == 2
    assert agg["per_domain"]["science_health"]["broken_pct"] == 100.0


def test_aggregate_records_spec_status():
    records = [_record("a", "ok", ("a", "identical")), _record("b", "timeout")]
    agg = decay_sweep.aggregate(records, _manifest(a="live_read", b="live_read"))
    assert agg["spec_status"] == {"ok": 1, "timeout": 1}
    assert agg["specs_attempted"] == 2


# --- report reading ----------------------------------------------------------


def test_outcomes_from_report_returns_none_when_absent(tmp_path: Path):
    assert decay_sweep.outcomes_from_report(tmp_path / "nope.jsonl") is None


def test_outcomes_from_report_returns_none_when_empty(tmp_path: Path):
    path = tmp_path / "r.jsonl"
    path.write_text("", encoding="utf-8")
    assert decay_sweep.outcomes_from_report(path) is None


def test_outcomes_from_report_synthesises_a_quarantine_row(tmp_path: Path):
    """A preflight quarantine has no calls but must not be silently dropped."""
    path = tmp_path / "r.jsonl"
    path.write_text(json.dumps({"quarantined": True, "call_outcomes": []}) + "\n", encoding="utf-8")
    calls = decay_sweep.outcomes_from_report(path)
    assert calls == [{"server_id": "?", "classification": "quarantined", "retry_count": 0}]


def test_outcomes_from_report_reads_call_level_fields(tmp_path: Path):
    path = tmp_path / "r.jsonl"
    row = {
        "quarantined": False,
        "call_outcomes": [
            {"server_id": "alpha", "classification": "drifted", "retry_count": 1},
            {"server_id": "beta", "classification": "identical", "retry_count": 0},
        ],
    }
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    calls = decay_sweep.outcomes_from_report(path)
    assert [c["server_id"] for c in calls] == ["alpha", "beta"]
    assert calls[0]["retry_count"] == 1


# --- rendering ---------------------------------------------------------------


def test_render_markdown_reports_the_totals_and_the_exclusions():
    records = [
        _record("yfinance", "ok", ("yfinance", "identical"), ("yfinance", "drifted")),
        _record("arxiv", "ok", ("arxiv", "unresolved"), ("arxiv", "skipped")),
    ]
    manifest = {
        "yfinance": {"dynamism": "live_read", "description": "stock market"},
        "arxiv": {"dynamism": "live_read", "description": "scholarly papers"},
    }
    markdown = decay_sweep.render_markdown(decay_sweep.aggregate(records, manifest), min_calls=1)
    assert "| **all** |" in markdown
    assert "1 unresolved, 1 skipped" in markdown
    assert "broken (upper bound)" in markdown


def test_render_markdown_hides_thin_per_server_rows():
    records = [_record("alpha", "ok", ("alpha", "identical"))]
    markdown = decay_sweep.render_markdown(
        decay_sweep.aggregate(records, _manifest(alpha="live_read")), min_calls=5
    )
    assert "| alpha |" not in markdown  # 1 live call is below the threshold


# --- committed constants -----------------------------------------------------


def test_live_classifications_exclude_unresolved():
    """`unresolved` is by definition unattributable and must never count as decay."""
    assert "unresolved" not in decay_sweep.LIVE
    assert set(decay_sweep.ATTRIBUTABLE) == {"schema_drift", "state_decay"}


def test_domain_rules_have_no_duplicate_names():
    names = [name for name, _ in decay_sweep.DOMAIN_RULES]
    assert len(names) == len(set(names))
    assert "other" not in names  # `other` is the fallback, not a rule


@pytest.mark.parametrize("server_id", ["yfinance", "arxiv", "wikipedia"])
def test_prior_snapshot_servers_are_all_classified(server_id: str):
    """The three families of the first decay snapshot must land in real domains."""
    assert decay_sweep.domain_for(server_id, "") != "other"
