"""Attribute a failed refresh call: schema drift, state decay, or nothing (Phase 4B).

`dmcp.refresh` used to label every failed reference call `broken`. That single
label covered three very different worlds — a tool that changed shape, a record
that was deleted, and a socket that hiccupped — and the decay number the paper
reports was their sum. A flaky network therefore read as substrate decay, which
is the one claim the refresh protocol exists to make honestly.

This module is the pure, deterministic half of the finer classifier:

  transient    — the call failed in a way that says "try again", not "this is
                 gone": a timeout, a dropped connection, HTTP 429, a recoverable
                 5xx. `dmcp.refresh` retries these with backoff and, if they
                 outlive the retries, carries them to the next refresh window
                 instead of deciding decay now.
  schema_drift — the server answered discovery and the tool is gone, or its
                 input schema no longer admits the reference call (a new
                 required parameter, a removed one, a changed type).
  state_decay  — discovery is intact and the schema still admits the call, but
                 the server says the thing the call needs is not there.
  unresolved   — everything else, including "we could not even reach discovery".
                 Refresh quarantines these: they are excluded from the decay
                 rates rather than counted against the server.

Scope of v0: text- and schema-level heuristics over what the server already
told us; no extra probing beyond the one `list_tools` call refresh makes on a
server that failed. Every heuristic is biased the same way — toward `transient`
and `unresolved` and away from `schema_drift` / `state_decay` — because those
two are the numbers we publish, and a benchmark that over-reports its own
headline is worse than one that under-reports it. Out of scope: parsing
server-specific error envelopes, and any judgement about *why* a record is gone.
"""

from __future__ import annotations

import re
from typing import Any, Literal

ATTRIBUTION_VERSION = "0.1.0"

FailureClass = Literal["schema_drift", "state_decay", "unresolved"]

# Exception types that are transient by construction, matched by class name so
# that library-specific subclasses (httpx, anyio, mcp) are covered without
# importing them.
TRANSIENT_EXC_NAMES = frozenset(
    {
        "TimeoutError",
        "ConnectTimeout",
        "ReadTimeout",
        "WriteTimeout",
        "PoolTimeout",
        "ConnectionError",
        "ConnectionResetError",
        "ConnectionAbortedError",
        "ConnectionRefusedError",
        "BrokenPipeError",
        "IncompleteRead",
        "RemoteProtocolError",
        "ConnectError",
        "ReadError",
        "WriteError",
        "ClosedResourceError",
        "BrokenResourceError",
        "EndOfStream",
    }
)

# Phrases that mark a failure as retryable wherever it surfaced — raised as an
# exception or returned as an `isError` body.
TRANSIENT_PHRASES = (
    "timed out",
    "timeout",
    "connection reset",
    "connection refused",
    "connection aborted",
    "connection closed",
    "broken pipe",
    "temporarily unavailable",
    "service unavailable",
    "too many requests",
    "rate limit",
    "ratelimit",
    "bad gateway",
    "gateway timeout",
    "server disconnected",
    "remote end closed",
    "try again",
    "overloaded",
)

# HTTP statuses we treat as recoverable. Bare numbers are ambiguous in prose
# ("500 rows"), so a match only counts alongside a word that makes it a status.
RECOVERABLE_STATUS = (429, 500, 502, 503, 504)
_STATUS_RE = re.compile(r"\b(?:429|500|502|503|504)\b")
_STATUS_CONTEXT = ("http", "status", "code", "gateway", "unavailable", "request", "error")

# Phrases that say the thing the call needed is not there any more. Narrow on
# purpose: a generic server error must not be promoted to state decay.
MISSING_RECORD_PHRASES = (
    "not found",
    "no such",
    "does not exist",
    "doesn't exist",
    "no longer exists",
    "no longer available",
    "has been deleted",
    "was deleted",
    "has been removed",
    "no matching",
    "no results",
    "no rows",
    "empty result",
    "unknown id",
    "invalid id",
    "missing record",
    "404",
)
_NOT_FOUND_STATUS_RE = re.compile(r"\b404\b")


def _low(text: str | None) -> str:
    return (text or "").lower()


def _has_recoverable_status(low: str) -> bool:
    return bool(_STATUS_RE.search(low)) and any(w in low for w in _STATUS_CONTEXT)


def is_transient_text(text: str | None) -> bool:
    """True when an error message asks to be retried rather than believed."""
    low = _low(text)
    if not low:
        return False
    return any(p in low for p in TRANSIENT_PHRASES) or _has_recoverable_status(low)


def is_transient_error(exc: BaseException | None) -> bool:
    """True for exceptions worth a backoff: by type, by cause, or by message."""
    if exc is None:
        return False
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if type(cur).__name__ in TRANSIENT_EXC_NAMES:
            return True
        if isinstance(cur, OSError) and not isinstance(cur, FileNotFoundError | PermissionError):
            return True
        if is_transient_text(str(cur)):
            return True
        cur = cur.__cause__ or cur.__context__
    return False


def looks_like_missing_record(text: str | None) -> bool:
    """True when the server says the record/resource the call needs is gone."""
    low = _low(text)
    if not low:
        return False
    if _NOT_FOUND_STATUS_RE.search(low) and any(w in low for w in _STATUS_CONTEXT):
        return True
    return any(p in low for p in MISSING_RECORD_PHRASES if p != "404")


def tool_input_schema(tools: list[Any], tool_name: str) -> dict[str, Any] | None:
    """Input schema of `tool_name` in a discovery listing, or None if absent.

    Accepts `ToolSpec`, the raw MCP `Tool`, or a plain dict, so the same helper
    works against a live recorder and a test double.
    """
    for t in tools:
        name = t.get("name") if isinstance(t, dict) else getattr(t, "name", None)
        if name != tool_name:
            continue
        for attr in ("input_schema", "inputSchema", "schema"):
            raw = t.get(attr) if isinstance(t, dict) else getattr(t, attr, None)
            if isinstance(raw, dict):
                return raw
        return {}
    return None


_JSON_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list, tuple),
    "object": (dict,),
}


def _type_matches(value: Any, declared: Any) -> bool:
    """Whether a reference argument still satisfies the declared JSON type.

    Unknown or composite declarations (`anyOf`, a list of types, a `$ref`) are
    treated as matching: an unparsed schema is not evidence of a change.
    """
    if not isinstance(declared, str):
        return True
    expected = _JSON_TYPES.get(declared)
    if expected is None:
        return True
    if declared in ("integer", "number") and isinstance(value, bool):
        return False  # bool is an int in Python, not in JSON Schema
    return isinstance(value, expected)


def schema_incompatibility(schema: dict[str, Any], arguments: dict[str, Any]) -> str | None:
    """Why the live schema no longer admits the reference call, or None.

    Three changes are recognised, all of which would make the reference call
    invalid today: a required parameter the reference never passed, a passed
    parameter the schema no longer declares, and a parameter whose declared type
    the reference value no longer satisfies.
    """
    props = schema.get("properties")
    props = props if isinstance(props, dict) else {}
    required = schema.get("required")
    required = [r for r in required if isinstance(r, str)] if isinstance(required, list) else []

    missing = sorted(r for r in required if r not in arguments)
    if missing:
        return f"schema now requires {', '.join(repr(m) for m in missing)}, absent from the reference call"

    if props:
        unknown = sorted(k for k in arguments if k not in props)
        if unknown:
            return f"schema no longer declares {', '.join(repr(u) for u in unknown)}"
        for key in sorted(arguments):
            spec = props.get(key)
            if isinstance(spec, dict) and not _type_matches(arguments[key], spec.get("type")):
                return f"parameter {key!r} is now typed {spec.get('type')!r}"
    return None


def attribute_failure(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    error_text: str,
    live_tools: list[Any] | None,
    discovery_error: str = "",
) -> tuple[FailureClass, str]:
    """Classify one failed reference call. `live_tools=None` means discovery failed.

    Returns (class, human-readable reason). The reason is written to be read in
    a decay report by someone deciding whether to retire a spec, so it always
    names the evidence the verdict rests on.
    """
    if live_tools is None:
        detail = f" ({discovery_error})" if discovery_error else ""
        return "unresolved", f"could not reach discovery to attribute the failure{detail}: {error_text}"

    schema = tool_input_schema(live_tools, tool_name)
    if schema is None:
        return "schema_drift", f"tool {tool_name!r} is no longer exposed by the server"

    incompatible = schema_incompatibility(schema, arguments)
    if incompatible is not None:
        return "schema_drift", f"tool {tool_name!r} changed shape: {incompatible}"

    if looks_like_missing_record(error_text):
        return "state_decay", f"schema intact, but the server reports the record is gone: {error_text}"

    return (
        "unresolved",
        f"server reachable and {tool_name!r} unchanged, but the failure is not attributable: {error_text}",
    )
