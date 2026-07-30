"""E1.5 — refresh classification, retry-with-backoff, and per-server decay aggregation.

Drives `refresh_one` against an injected fake recorder so live MCP servers
aren't needed. Asserts:
  - identical / drifted / failure / skipped classification
  - retries-with-backoff (transient exception then success → identical/drifted)
  - exhausted retries → unresolved, deferred to the next window
  - per-server drift rate aggregation across multiple refresh reports
  - decay markdown table renders the per-server breakdown

E9.12 split the old single `broken` label into schema_drift / state_decay /
unresolved; the finer attribution itself is covered in
`test_refresh_attribution.py`, and the aggregates here still speak the legacy
`broken` label so older windows stay comparable.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dmcp.manifest import Dynamism, Manifest, ServerEntry
from dmcp.refresh import (
    CallRefreshOutcome,
    RefreshReport,
    decay_summary,
    per_server_decay,
    refresh_one,
)
from dmcp.report import decay_markdown, load_refresh_reports
from dmcp.trace import Step, StepKind, StepStatus, Trace, TransportKind


def _build_manifest(*, with_stateful: bool = False) -> Manifest:
    entries = [
        ServerEntry(
            server_id="time",
            transport=TransportKind.stdio,
            dynamism=Dynamism.static,
            command="echo",
        ),
        ServerEntry(
            server_id="weather",
            transport=TransportKind.stdio,
            dynamism=Dynamism.live_read,
            command="echo",
        ),
    ]
    if with_stateful:
        entries.append(
            ServerEntry(
                server_id="db",
                transport=TransportKind.stdio,
                dynamism=Dynamism.stateful_write,
                sandbox=True,
                command="echo",
            )
        )
    return Manifest(servers=entries)


def _text_result(s: str, *, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": s}], "isError": is_error}


def _ref_trace(calls: list[tuple[str, str, dict, str]]) -> Trace:
    """Build a reference trace from (server, tool, args, result_text) tuples."""
    t = Trace(goal="refresh-test")
    now = datetime.now(UTC)
    for server_id, tool, args, text in calls:
        sid = t.next_step_id()
        t.steps.append(
            Step.build(
                step_id=sid,
                kind=StepKind.call_tool_agent,
                server_id=server_id,
                tool_name=tool,
                arguments=args,
                result=_text_result(text),
                status=StepStatus.success,
                started_at=now,
                ended_at=now,
            )
        )
    return t


class _FakeTool:
    def __init__(self, name: str):
        self.name = name
        self.input_schema: dict = {}


class _FakeRecorder:
    """Drop-in for TraceRecorder: deterministically scripts call_tool outcomes."""

    def __init__(self, plan: dict[tuple[str, str], list]):
        # plan[(server, tool)] = list of responses to pop in order;
        # each response is either a result dict or an Exception instance to raise.
        self._plan = {k: list(v) for k, v in plan.items()}
        self.calls: list[tuple[str, str]] = []

    async def list_tools(self, server_id: str):
        """Discovery for failure attribution (E9.12): every planned tool is live."""
        return [_FakeTool(tool) for (sid, tool) in self._plan if sid == server_id]

    async def call_tool(self, server_id: str, tool: str, args: dict):
        self.calls.append((server_id, tool))
        responses = self._plan.get((server_id, tool))
        if not responses:
            raise AssertionError(f"unexpected call to {server_id}/{tool}")
        resp = responses.pop(0)
        if isinstance(resp, BaseException):
            raise resp
        return resp


def _no_sleep(_: float) -> asyncio.Future:
    fut: asyncio.Future = asyncio.get_event_loop().create_future()
    fut.set_result(None)
    return fut


def _run(coro):
    return asyncio.run(coro)


def test_classifies_identical_drifted_failed_skipped():
    manifest = _build_manifest(with_stateful=True)
    ref = _ref_trace(
        [
            ("time", "get_time", {"tz": "UTC"}, "2024-01-01T00:00:00"),
            ("weather", "current", {"city": "Paris"}, "sunny 20C"),
            ("weather", "current", {"city": "Tokyo"}, "rain 18C"),
            ("db", "insert", {"row": 1}, "ok"),
        ]
    )
    rec = _FakeRecorder(
        {
            ("time", "get_time"): [_text_result("2024-01-01T00:00:00")],  # identical
            ("weather", "current"): [
                _text_result("cloudy 19C"),  # drifted
                # isError with the tool still live and an intact schema: the
                # server itself says the record is gone → state_decay (E9.12).
                _text_result("no such city: Tokyo", is_error=True),
            ],
        }
    )
    report = _run(
        refresh_one(
            reference=ref,
            task_id=uuid.uuid4(),
            manifest=manifest,
            recorder=rec,
            sleep=_no_sleep,
            transient_retries=0,
        )
    )
    classes = [o.classification for o in report.call_outcomes]
    assert sorted(classes) == ["drifted", "identical", "skipped", "state_decay"]
    skipped = next(o for o in report.call_outcomes if o.classification == "skipped")
    assert skipped.server_id == "db"
    assert report.counts == {
        "identical": 1,
        "drifted": 1,
        "broken": 0,
        "schema_drift": 0,
        "state_decay": 1,
        "unresolved": 0,
        "skipped": 1,
        "quarantined": 0,
        "total": 4,
    }
    assert report.spec_likely_stale is True
    # These arguments name no file, relation or credential, so preflight has
    # nothing to check and the sweep proceeds (E9.11).
    assert report.quarantined is False


def test_retry_with_backoff_recovers_transient_flake():
    manifest = _build_manifest()
    ref = _ref_trace([("weather", "current", {"city": "Paris"}, "sunny")])
    rec = _FakeRecorder(
        {
            ("weather", "current"): [
                ConnectionResetError("connection reset by peer"),
                TimeoutError("read timed out"),
                _text_result("sunny"),  # eventual success → identical
            ]
        }
    )
    report = _run(
        refresh_one(
            reference=ref,
            task_id=uuid.uuid4(),
            manifest=manifest,
            recorder=rec,
            sleep=_no_sleep,
            transient_retries=2,
            initial_backoff_s=0.01,
        )
    )
    assert report.counts["identical"] == 1
    assert report.counts["broken"] == 0
    outcome = report.call_outcomes[0]
    assert outcome.classification == "identical"
    assert outcome.retry_count == 2
    assert len(rec.calls) == 3  # the two failures + the recovering call


def test_exhausted_retries_becomes_unresolved():
    manifest = _build_manifest()
    ref = _ref_trace([("weather", "current", {"city": "Paris"}, "sunny")])
    rec = _FakeRecorder(
        {
            ("weather", "current"): [
                TimeoutError("flake"),
                TimeoutError("flake"),
                TimeoutError("flake"),
            ]
        }
    )
    report = _run(
        refresh_one(
            reference=ref,
            task_id=uuid.uuid4(),
            manifest=manifest,
            recorder=rec,
            sleep=_no_sleep,
            transient_retries=2,
            initial_backoff_s=0.01,
        )
    )
    # A server that stayed unreachable is not evidence that the spec decayed:
    # it is deferred to the next window, and the decay tally never sees it.
    assert report.counts["unresolved"] == 1
    assert report.counts["broken"] == 0
    assert report.spec_likely_stale is False
    o = report.call_outcomes[0]
    assert o.classification == "unresolved"
    assert o.retry_count == 2
    assert "TimeoutError" in o.reason
    assert "2 retries" in o.reason


def _make_outcome(server: str, classification: str, retries: int = 0) -> CallRefreshOutcome:
    return CallRefreshOutcome(
        reference_step_id=0,
        server_id=server,
        tool_name="t",
        arguments_canonical="{}",
        classification=classification,
        reason="",
        retry_count=retries,
    )


def _make_report(
    server_outcomes: list[tuple[str, str, int]],
    refreshed_at: datetime,
) -> RefreshReport:
    outcomes = [_make_outcome(s, c, r) for s, c, r in server_outcomes]
    counts = {
        "identical": sum(1 for o in outcomes if o.classification == "identical"),
        "drifted": sum(1 for o in outcomes if o.classification == "drifted"),
        "broken": sum(1 for o in outcomes if o.classification == "broken"),
        "skipped": sum(1 for o in outcomes if o.classification == "skipped"),
        "total": len(outcomes),
    }
    return RefreshReport(
        task_id=uuid.uuid4(),
        source_trace_id=uuid.uuid4(),
        refreshed_at=refreshed_at,
        call_outcomes=outcomes,
        counts=counts,
        spec_likely_stale=counts["broken"] > 0,
    )


def test_per_server_decay_aggregates_drift_rate_across_runs():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = t0 + timedelta(days=7)
    r1 = _make_report(
        [
            ("weather", "drifted", 1),
            ("weather", "drifted", 0),
            ("weather", "identical", 0),
            ("time", "identical", 0),
        ],
        refreshed_at=t0,
    )
    r2 = _make_report(
        [
            ("weather", "drifted", 0),
            ("weather", "broken", 2),
            ("time", "identical", 0),
        ],
        refreshed_at=t1,
    )

    per = per_server_decay([r1, r2])

    assert set(per) == {"weather", "time"}
    w = per["weather"]
    # 3 drifted + 1 identical + 1 broken = 5 live calls across two refreshes
    assert w["refreshes"] == 2
    assert w["live_calls"] == 5
    assert w["drifted"] == 3
    assert w["identical"] == 1
    assert w["broken"] == 1
    assert abs(w["drift_rate"] - 3 / 5) < 1e-9
    assert abs(w["broken_rate"] - 1 / 5) < 1e-9
    assert w["retries"] == 3
    assert w["first_seen"] == t0
    assert w["last_seen"] == t1

    t = per["time"]
    assert t["refreshes"] == 2
    assert t["live_calls"] == 2
    assert t["drift_rate"] == 0.0


def test_decay_markdown_renders_table(tmp_path: Path):
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    r1 = _make_report([("weather", "drifted", 0), ("time", "identical", 0)], refreshed_at=t0)
    r2 = _make_report(
        [("weather", "broken", 1), ("weather", "drifted", 0)],
        refreshed_at=t0 + timedelta(days=3),
    )
    refresh_file = tmp_path / "refresh.jsonl"
    refresh_file.write_text("\n".join(r.to_jsonl() for r in (r1, r2)) + "\n", encoding="utf-8")

    md = decay_markdown([refresh_file])
    assert "## Decay" in md
    assert "| Server | Refreshes |" in md
    assert "`weather`" in md
    assert "`time`" in md
    # weather: 2 drifted + 1 broken = 3 live → drift 67%, broken 33%
    assert "67%" in md
    assert "33%" in md


def test_load_refresh_reports_roundtrip(tmp_path: Path):
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    r = _make_report([("weather", "identical", 0)], refreshed_at=t0)
    path = tmp_path / "refresh.jsonl"
    path.write_text(r.to_jsonl() + "\n", encoding="utf-8")
    loaded = load_refresh_reports([path])
    assert len(loaded) == 1
    assert loaded[0].task_id == r.task_id


def test_decay_summary_includes_per_server():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    r = _make_report([("weather", "drifted", 0)], refreshed_at=t0)
    s = decay_summary([r])
    assert s["specs_refreshed"] == 1
    assert "per_server" in s
    assert "weather" in s["per_server"]
