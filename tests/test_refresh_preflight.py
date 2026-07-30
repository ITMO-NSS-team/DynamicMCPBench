"""E9.11 — refresh preflight: quarantine a broken environment, don't blame anyone.

The failure this guards against is silent and expensive. A fixture file is
deleted, a sandbox relation is never seeded, an API key drops out of `.env` —
and the refresh sweep records every reference call as `broken`, the server looks
decayed, and once the task is readmitted every candidate agent fails it. Two
headline numbers absorb our own missing setup, and neither is recoverable later.

So the assertions here are about *what the numbers must not absorb*:
  - the four requirement kinds are derived from a reference trace, and the
    conservative non-claims (relative paths, unknown servers) stay non-claims
  - an unmet requirement quarantines the task before any live call is made
  - a quarantined report leaves the decay aggregates untouched
  - `unknown` — a relation we could not probe — never quarantines
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path

from dmcp.manifest import Dynamism, Manifest, ServerEntry
from dmcp.preflight import (
    check_requirements,
    derive_requirements,
    discover_tables,
    parse_relation_names,
    run_preflight,
)
from dmcp.refresh import decay_summary, per_server_decay, refresh_one
from dmcp.trace import Step, StepKind, StepStatus, Trace, TransportKind


def _manifest() -> Manifest:
    return Manifest(
        servers=[
            ServerEntry(
                server_id="fs",
                transport=TransportKind.stdio,
                dynamism=Dynamism.live_read,
                command="echo",
            ),
            ServerEntry(
                server_id="db",
                transport=TransportKind.stdio,
                dynamism=Dynamism.stateful_write,
                sandbox=True,
                command="echo",
            ),
            ServerEntry(
                server_id="api",
                transport=TransportKind.stdio,
                dynamism=Dynamism.live_read,
                command="echo",
                requires_env=["DMCP_TEST_TOKEN"],
            ),
        ]
    )


def _trace(calls: list[tuple[str, str, dict]]) -> Trace:
    t = Trace(goal="preflight-test")
    now = datetime.now(UTC)
    for server_id, tool, args in calls:
        t.steps.append(
            Step.build(
                step_id=t.next_step_id(),
                kind=StepKind.call_tool_agent,
                server_id=server_id,
                tool_name=tool,
                arguments=args,
                result={"content": [{"type": "text", "text": "ok"}], "isError": False},
                status=StepStatus.success,
                started_at=now,
                ended_at=now,
            )
        )
    return t


class _Recorder:
    """Records every call so a quarantined run can be shown to have made none."""

    def __init__(self, tools: dict[str, list[str]] | None = None, listing: str = ""):
        self._tools = tools or {}
        self._listing = listing
        self.calls: list[tuple[str, str]] = []

    async def list_tools(self, server_id: str):
        return [type("T", (), {"name": n})() for n in self._tools.get(server_id, [])]

    async def call_tool(self, server_id: str, tool: str, args: dict):
        self.calls.append((server_id, tool))
        if tool in ("list_tables", "show_tables"):
            return {"content": [{"type": "text", "text": self._listing}], "isError": False}
        return {"content": [{"type": "text", "text": "ok"}], "isError": False}


def test_derives_all_four_requirement_kinds(tmp_path: Path):
    ref = _trace(
        [
            ("fs", "read_file", {"path": str(tmp_path / "in.csv")}),
            ("db", "write_report", {"output_path": str(tmp_path / "out/report.md")}),
            ("db", "run_sql", {"query": "SELECT * FROM orders JOIN main.customers ON 1=1"}),
            ("api", "fetch", {"endpoint": "https://example.invalid/v1"}),
        ]
    )
    reqs = derive_requirements(ref, _manifest())
    by_kind = {(r.kind, r.target) for r in reqs}
    assert ("file", str(tmp_path / "in.csv")) in by_kind
    # A path argument on a stateful_write server is a write target, not a read.
    assert ("writable", str(tmp_path / "out/report.md")) in by_kind
    assert ("table", "orders") in by_kind
    assert ("table", "main.customers") in by_kind
    assert ("credential", "DMCP_TEST_TOKEN") in by_kind
    # A URL is not a path, however path-ish the argument name is.
    assert not any(r.target.startswith("https://") for r in reqs)


def test_does_not_claim_what_it_cannot_justify():
    """Relative paths and unknown servers yield no requirement at all.

    A false quarantine removes a task from the benchmark silently, so the
    derivation is biased toward under-claiming; these are the two places that
    bias is load-bearing.
    """
    ref = _trace(
        [
            ("fs", "read_file", {"path": "data/relative.csv"}),
            ("ghost", "read_file", {"path": "/absolutely/gone.csv"}),
        ]
    )
    assert derive_requirements(ref, _manifest()) == []


def test_writable_checks_the_parent_when_the_file_is_absent(tmp_path: Path):
    ref = _trace([("db", "write", {"path": str(tmp_path / "new.txt")})])
    ok = run_preflight(ref, _manifest(), load_env=False)
    assert ok.ok, ok.summary()

    missing_parent = _trace([("db", "write", {"path": str(tmp_path / "nope" / "new.txt")})])
    bad = run_preflight(missing_parent, _manifest(), load_env=False)
    assert not bad.ok
    assert "parent directory" in bad.unmet[0].detail


def test_unknown_relations_never_quarantine():
    """A relation we could not probe is `unknown`, and unknown is not a failure."""
    ref = _trace([("db", "run_sql", {"query": "SELECT * FROM orders"})])
    result = run_preflight(ref, _manifest(), load_env=False)
    assert [f.status for f in result.findings] == ["unknown"]
    assert result.ok
    # With an inventory in hand the same requirement becomes decidable.
    seeded = check_requirements(
        derive_requirements(ref, _manifest()),
        table_inventory={"db": {"orders"}},
        load_env=False,
    )
    assert seeded.ok and seeded.findings[0].status == "satisfied"
    empty = check_requirements(
        derive_requirements(ref, _manifest()),
        table_inventory={"db": {"customers"}},
        load_env=False,
    )
    assert not empty.ok


def test_quarantine_blocks_every_live_call(tmp_path: Path):
    ref = _trace(
        [
            ("fs", "read_file", {"path": str(tmp_path / "deleted.csv")}),
            ("fs", "stat", {"path": str(tmp_path)}),
        ]
    )
    rec = _Recorder()
    report = asyncio.run(refresh_one(reference=ref, task_id=uuid.uuid4(), manifest=_manifest(), recorder=rec))
    # The point of preflight: nothing was executed, so nothing can be blamed.
    assert rec.calls == []
    assert report.quarantined
    assert report.counts["quarantined"] == 2
    assert report.counts["broken"] == 0
    assert not report.spec_likely_stale
    assert report.preflight is not None and "deleted.csv" in report.preflight.summary()


def test_intact_environment_still_refreshes_normally(tmp_path: Path):
    present = tmp_path / "present.csv"
    present.write_text("a,b\n")
    ref = _trace([("fs", "read_file", {"path": str(present)})])
    rec = _Recorder()
    report = asyncio.run(refresh_one(reference=ref, task_id=uuid.uuid4(), manifest=_manifest(), recorder=rec))
    assert rec.calls == [("fs", "read_file")]
    assert not report.quarantined
    assert report.counts["identical"] == 1
    assert report.preflight is not None and report.preflight.ok


def test_preflight_can_be_turned_off(tmp_path: Path):
    ref = _trace([("fs", "read_file", {"path": str(tmp_path / "deleted.csv")})])
    rec = _Recorder()
    report = asyncio.run(
        refresh_one(
            reference=ref,
            task_id=uuid.uuid4(),
            manifest=_manifest(),
            recorder=rec,
            preflight=False,
        )
    )
    assert rec.calls == [("fs", "read_file")]
    assert report.preflight is None and not report.quarantined


def test_quarantined_reports_leave_the_decay_numbers_alone(tmp_path: Path):
    healthy = _trace([("fs", "read_file", {"path": str(tmp_path)})])
    sick = _trace([("fs", "read_file", {"path": str(tmp_path / "gone.csv")})])
    good = asyncio.run(
        refresh_one(reference=healthy, task_id=uuid.uuid4(), manifest=_manifest(), recorder=_Recorder())
    )
    bad = asyncio.run(
        refresh_one(reference=sick, task_id=uuid.uuid4(), manifest=_manifest(), recorder=_Recorder())
    )

    summary = decay_summary([good, bad])
    assert summary["specs_quarantined"] == 1
    # The quarantined spec is not a refreshed spec, not a stale spec, and not a
    # call outcome: a missing fixture must not read as a decaying server.
    assert summary["specs_refreshed"] == 1
    assert summary["specs_stale"] == 0
    assert summary["call_outcomes"]["total"] == 1
    assert per_server_decay([good, bad])["fs"]["live_calls"] == 1


def test_relation_inventory_is_discovered_from_a_read_only_listing_tool():
    rec = _Recorder(tools={"db": ["run_sql", "list_tables"]}, listing='["orders", "customers"]')
    inventory = asyncio.run(discover_tables(rec, ["db", "fs"]))
    assert inventory == {"db": {"orders", "customers"}}
    # A server with no listing tool is absent rather than empty, so its
    # requirements stay `unknown` instead of failing.
    assert "fs" not in inventory


def test_relation_names_parse_from_the_shapes_servers_actually_return():
    assert parse_relation_names('["Orders", "customers"]') == {"orders", "customers"}
    assert parse_relation_names('[{"name": "orders"}, {"table_name": "items"}]') == {"orders", "items"}
    assert parse_relation_names('{"tables": ["orders"]}') == {"orders"}
    assert parse_relation_names("orders\ncustomers\n") == {"orders", "customers"}
    assert parse_relation_names("") == set()
