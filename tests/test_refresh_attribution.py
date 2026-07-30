"""E9.12 — the finer refresh classifier: only attributable failures count as decay.

Before this, every failed reference call was `broken`, so a dropped connection
and a deleted tool produced the same number — the number the paper publishes as
substrate decay. The split asserted here is what makes that number mean
something:

  transient    retried with backoff, and if it outlives the retries it is
               deferred to the next window, not counted
  schema_drift discovery says the tool is gone or reshaped
  state_decay  discovery is intact and the server says the record is gone
  unresolved   anything we cannot pin on the server — excluded from the rates

The tests are written from the direction of the bias: it is a bug for a network
flake to become decay, and a bug for `unresolved` to enter a rate.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest

from dmcp.attribution import (
    attribute_failure,
    is_transient_error,
    is_transient_text,
    looks_like_missing_record,
    schema_incompatibility,
    tool_input_schema,
)
from dmcp.manifest import Dynamism, Manifest, ServerEntry
from dmcp.refresh import per_server_decay, refresh_one
from dmcp.trace import Step, StepKind, StepStatus, Trace, TransportKind


def _manifest() -> Manifest:
    return Manifest(
        servers=[
            ServerEntry(
                server_id="api",
                transport=TransportKind.stdio,
                dynamism=Dynamism.live_read,
                command="echo",
            )
        ]
    )


def _trace(calls: list[tuple[str, dict, str]]) -> Trace:
    t = Trace(goal="attribution-test")
    now = datetime.now(UTC)
    for tool, args, text in calls:
        t.steps.append(
            Step.build(
                step_id=t.next_step_id(),
                kind=StepKind.call_tool_agent,
                server_id="api",
                tool_name=tool,
                arguments=args,
                result={"content": [{"type": "text", "text": text}], "isError": False},
                status=StepStatus.success,
                started_at=now,
                ended_at=now,
            )
        )
    return t


class _Tool:
    def __init__(self, name: str, schema: dict | None = None):
        self.name = name
        self.input_schema = schema if schema is not None else {}


class _Recorder:
    """Scripts call_tool responses and serves a discovery listing for attribution."""

    def __init__(self, responses: list, tools: list[_Tool] | None = None, discovery_error: bool = False):
        self._responses = list(responses)
        self._tools = tools if tools is not None else [_Tool("fetch")]
        self._discovery_error = discovery_error
        self.calls = 0
        self.list_tools_calls = 0

    async def call_tool(self, server_id: str, tool: str, args: dict):
        self.calls += 1
        resp = self._responses.pop(0) if self._responses else self._responses
        if isinstance(resp, BaseException):
            raise resp
        return resp

    async def list_tools(self, server_id: str):
        self.list_tools_calls += 1
        if self._discovery_error:
            raise ConnectionError("server gone")
        return self._tools


def _err(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": True}


def _ok(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": False}


def _refresh(responses, tools=None, discovery_error=False, retries=2, args=None):
    rec = _Recorder(responses, tools=tools, discovery_error=discovery_error)
    ref = _trace([("fetch", args if args is not None else {"id": "42"}, "hello")])
    report = asyncio.run(
        refresh_one(
            reference=ref,
            task_id=uuid.uuid4(),
            manifest=_manifest(),
            recorder=rec,
            transient_retries=retries,
            initial_backoff_s=0.0,
            sleep=_instant,
        )
    )
    return report, rec


async def _instant(_: float) -> None:
    return None


# --- the transient predicate ------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        TimeoutError("timed out"),
        ConnectionResetError("connection reset by peer"),
        RuntimeError("HTTP 429 Too Many Requests"),
        RuntimeError("upstream returned status 503"),
        OSError("socket hangup"),
    ],
)
def test_transient_errors_are_recognised(exc):
    assert is_transient_error(exc)


@pytest.mark.parametrize(
    "exc",
    [
        ValueError("unknown tool 'fetch'"),
        RuntimeError("invalid arguments: 'id' must be an integer"),
        FileNotFoundError("/tmp/gone.csv"),
    ],
)
def test_non_transient_errors_are_not_retried_away(exc):
    assert not is_transient_error(exc)


def test_a_bare_number_is_not_a_status_code():
    """`500 rows` must not read as HTTP 500 — that would defer real failures."""
    assert not is_transient_text("returned 500 rows")
    assert is_transient_text("upstream error, http 500")


def test_a_wrapped_transient_cause_still_counts():
    try:
        try:
            raise ConnectionResetError("reset")
        except ConnectionResetError as inner:
            raise RuntimeError("call failed") from inner
    except RuntimeError as e:
        assert is_transient_error(e)


def test_missing_record_phrases_are_narrow():
    assert looks_like_missing_record("Error: record not found")
    assert looks_like_missing_record("no such table: orders")
    assert not looks_like_missing_record("internal error while planning the query")


# --- schema comparison ------------------------------------------------------


def test_schema_incompatibility_flags_the_three_breaking_changes():
    args = {"id": "42"}
    assert schema_incompatibility({"properties": {"id": {"type": "string"}}}, args) is None

    added = schema_incompatibility({"properties": {"id": {}, "region": {}}, "required": ["region"]}, args)
    assert added is not None and "region" in added

    removed = schema_incompatibility({"properties": {"identifier": {}}}, args)
    assert removed is not None and "'id'" in removed

    retyped = schema_incompatibility({"properties": {"id": {"type": "integer"}}}, args)
    assert retyped is not None and "integer" in retyped


def test_an_unparsed_schema_is_not_evidence_of_change():
    """No properties, or a composite type we don't model, must not read as drift."""
    assert schema_incompatibility({}, {"id": "42"}) is None
    composite = {"properties": {"id": {"anyOf": [{"type": "string"}]}}}
    assert schema_incompatibility(composite, {"id": "42"}) is None


def test_tool_input_schema_reads_both_naming_conventions():
    assert tool_input_schema([_Tool("fetch", {"properties": {}})], "fetch") == {"properties": {}}
    assert tool_input_schema([{"name": "fetch", "inputSchema": {"x": 1}}], "fetch") == {"x": 1}
    assert tool_input_schema([_Tool("fetch")], "other") is None


def test_attribute_failure_needs_discovery_to_blame_anyone():
    cls, reason = attribute_failure(
        tool_name="fetch",
        arguments={},
        error_text="boom",
        live_tools=None,
        discovery_error="ConnectionError: gone",
    )
    assert cls == "unresolved" and "discovery" in reason


# --- end to end through refresh_one ----------------------------------------


def test_a_transient_flake_that_recovers_is_just_a_retry():
    report, rec = _refresh([ConnectionResetError("reset"), _ok("hello")])
    assert report.counts["identical"] == 1
    assert report.call_outcomes[0].retry_count == 1
    assert rec.calls == 2
    # Nothing failed in the end, so discovery was never needed.
    assert rec.list_tools_calls == 0


def test_a_transient_flake_that_outlives_its_retries_is_deferred_not_decay():
    report, rec = _refresh([TimeoutError("timed out")] * 3)
    o = report.call_outcomes[0]
    assert o.classification == "unresolved"
    assert "deferred" in o.reason and "2 retries" in o.reason
    assert rec.calls == 3
    # The whole point: an unreachable-for-a-while server is not a stale spec.
    assert report.spec_likely_stale is False
    assert report.counts["schema_drift"] == 0 and report.counts["state_decay"] == 0


def test_a_non_transient_error_is_not_retried():
    report, rec = _refresh([ValueError("bad arguments")] * 3)
    assert rec.calls == 1  # no point burning backoff on a verdict that won't change
    assert report.call_outcomes[0].classification == "unresolved"


def test_a_rate_limited_isError_body_is_retried_like_an_exception():
    """Servers that wrap HTTP report 429 in the body, not by raising."""
    report, rec = _refresh([_err("HTTP 429: rate limit exceeded"), _ok("hello")])
    assert rec.calls == 2
    assert report.counts["identical"] == 1


def test_a_removed_tool_is_schema_drift():
    report, rec = _refresh([_err("unknown tool")], tools=[_Tool("fetch_v2")])
    o = report.call_outcomes[0]
    assert o.classification == "schema_drift"
    assert "no longer exposed" in o.reason
    assert report.spec_likely_stale is True
    assert rec.list_tools_calls == 1


def test_a_reshaped_tool_is_schema_drift():
    tools = [_Tool("fetch", {"properties": {"id": {}, "region": {}}, "required": ["region"]})]
    report, _ = _refresh([_err("missing required parameter: region")], tools=tools)
    o = report.call_outcomes[0]
    assert o.classification == "schema_drift"
    assert "region" in o.reason


def test_an_intact_schema_over_a_missing_record_is_state_decay():
    tools = [_Tool("fetch", {"properties": {"id": {"type": "string"}}})]
    report, _ = _refresh([_err("record 42 not found")], tools=tools)
    o = report.call_outcomes[0]
    assert o.classification == "state_decay"
    assert report.spec_likely_stale is True


def test_an_unattributable_server_error_stays_unresolved():
    tools = [_Tool("fetch", {"properties": {"id": {"type": "string"}}})]
    report, _ = _refresh([_err("internal error 1e7f while planning")], tools=tools)
    assert report.call_outcomes[0].classification == "unresolved"
    assert report.spec_likely_stale is False


def test_discovery_that_cannot_be_reached_never_blames_the_tool():
    report, rec = _refresh([ValueError("boom")], discovery_error=True)
    assert report.call_outcomes[0].classification == "unresolved"
    assert rec.list_tools_calls == 1


def test_discovery_is_probed_once_per_failing_server():
    rec = _Recorder([_err("record not found")] * 2, tools=[_Tool("fetch", {})])
    ref = _trace([("fetch", {"id": "1"}, "a"), ("fetch", {"id": "2"}, "b")])
    report = asyncio.run(
        refresh_one(
            reference=ref,
            task_id=uuid.uuid4(),
            manifest=_manifest(),
            recorder=rec,
            transient_retries=0,
            sleep=_instant,
        )
    )
    assert report.counts["state_decay"] == 2
    assert rec.list_tools_calls == 1


# --- aggregation ------------------------------------------------------------


def test_unresolved_calls_stay_out_of_every_decay_rate():
    decayed, _ = _refresh(
        [_err("record 42 not found")],
        tools=[_Tool("fetch", {"properties": {"id": {"type": "string"}}})],
    )
    deferred, _ = _refresh([TimeoutError("timed out")] * 3)

    per = per_server_decay([decayed, deferred])["api"]
    assert per["unresolved"] == 1
    assert per["live_calls"] == 1  # the deferred call is not a live observation
    assert per["state_decay"] == 1
    assert per["broken_rate"] == 1.0
    assert per["state_decay_rate"] == 1.0
    assert per["schema_drift_rate"] == 0.0
    assert per["unresolved_rate"] == 0.5
