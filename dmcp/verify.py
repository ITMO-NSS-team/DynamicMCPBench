"""Deep server verification (E3 Phase B + dependency-aware 100% gate).

Boots a server, lists its tools, and EXERCISES each tool with arguments
synthesized from its input schema (LLM-realistic when a client is given),
recording per-tool ok / error / timeout / skipped.

Two passes make the gate HONEST rather than lenient:
  * Pass 1 exercises every non-destructive tool and HARVESTS id-like scalar
    values (ids, handles, keys, names, paths…) out of successful results.
  * Pass 2 RETRIES each still-failing tool once, feeding back the prior error
    AND the harvested values — so a tool that needs an existing id/handle
    produced by another tool (a PREREQUISITE) can reuse a real one. A retry that
    succeeds using a value harvested from tool X records an X -> tool dependency
    edge (the trace-native "complementary edge"); these edges feed the graph
    baseline and tool-pool sampling downstream.

Gate: with `require_all=True` a server is kept iff it initializes, exercises
>=1 tool, and EVERY exercised tool returns ok (pass_rate == 1.0). Otherwise the
legacy `min_tool_pass_rate` threshold applies. `strict=True` additionally treats
auth/credential/not-found messages returned as *successful content* as failures.

Safety: destructive-looking tools (delete / drop / ...) are skipped unless the
server is declared sandboxed. Per-tool and per-server timeouts bound the work.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from dmcp.llm import OpenRouterClient
from dmcp.recorder import ServerConfig, TraceRecorder

_DESTRUCTIVE_WORDS = {
    "delete",
    "remove",
    "drop",
    "destroy",
    "truncate",
    "purge",
    "wipe",
    "reset",
    "uninstall",
    "revoke",
    "clear",
}


def _name_tokens(name: str) -> set[str]:
    """Split a tool name on snake_case and camelCase into lowercased tokens."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name or "")
    return {t.lower() for t in re.split(r"[^A-Za-z0-9]+", spaced) if t}


def is_destructive(tool_name: str) -> bool:
    return bool(_name_tokens(tool_name) & _DESTRUCTIVE_WORDS)


def _value_for(spec: Any) -> Any:
    if not isinstance(spec, dict):
        return "test"
    if "default" in spec:
        return spec["default"]
    ex = spec.get("examples")
    if isinstance(ex, list) and ex:
        return ex[0]
    en = spec.get("enum")
    if isinstance(en, list) and en:
        return en[0]
    t = spec.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), "string")
    if t in ("integer", "number"):
        return 1
    if t == "boolean":
        return True
    if t == "array":
        return []
    if t == "object":
        return {}
    return "test"


def synthesize_args(input_schema: dict | None) -> dict[str, Any]:
    """Minimal valid args for a tool: fill only the REQUIRED properties, taking
    default / examples / enum / type-based placeholders."""
    schema = input_schema or {}
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    return {name: _value_for(props.get(name, {})) for name in props if name in required}


_LLM_ARGS_SYSTEM = (
    "You produce a realistic JSON arguments object to successfully CALL an MCP "
    "tool for a simple read/query. Use plausible REAL values (a real city or IANA "
    "timezone like 'Europe/London', a real URL such as https://example.com, a "
    "common query like 'Alan Turing'). When the field needs an existing id / "
    "handle / name and real values are offered below, REUSE one of them. Respect "
    "the schema's required fields and types. Prefer small/cheap requests. Return "
    "via the emit_args tool."
)


def _emit_args_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "emit_args",
            "description": "Emit the JSON arguments object to call the tool.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["arguments"],
                "properties": {"arguments": {"type": "object", "additionalProperties": True}},
            },
        },
    }


async def llm_synthesize_args(
    tool_name: str,
    description: str,
    input_schema: dict | None,
    llm: OpenRouterClient,
    *,
    prior_error: str | None = None,
    available: list[dict] | None = None,
) -> dict[str, Any]:
    """Ask an LLM for realistic call arguments; fall back to schema-based synthesis.

    `available` is a list of {"key","value"} scalars harvested from other tools'
    outputs (prerequisite resolution); `prior_error` is the previous failure to fix.
    """
    user = (
        f"Tool: {tool_name}\nDescription: {description or '(none)'}\n"
        f"Input JSON schema:\n{json.dumps(input_schema or {})[:1500]}\n\n"
    )
    if available:
        user += (
            "Real values harvested from OTHER tools' outputs on this same server. "
            "REUSE one when a field needs an existing id/handle/name:\n"
            f"{json.dumps(available)[:800]}\n\n"
        )
    if prior_error:
        user += (
            f"A previous call FAILED with: {prior_error[:200]}\nFix the arguments so the call succeeds.\n\n"
        )
    user += "Produce realistic arguments to call this tool once."
    try:
        resp = await llm.chat(
            messages=[
                {"role": "system", "content": _LLM_ARGS_SYSTEM},
                {"role": "user", "content": user},
            ],
            tools=[_emit_args_schema()],
            tool_choice={"type": "function", "function": {"name": "emit_args"}},
            temperature=0.0,
        )
        if resp.tool_calls:
            a = resp.tool_calls[0].arguments.get("arguments")
            if isinstance(a, dict):
                return a
    except Exception:
        pass
    return synthesize_args(input_schema)


def _result_text(result: dict[str, Any]) -> str:
    parts = [
        c.get("text", "")
        for c in (result.get("content") or [])
        if isinstance(c, dict) and c.get("type") == "text"
    ]
    return ("\n".join(parts) if parts else str(result))[:160]


_CONTENT_ERROR_RE = re.compile(
    r"(?i)("
    r"unauthorized|forbidden|access denied|permission denied|"
    r"not authenticated|unauthenticated|authentication (?:required|failed)|"
    r"requires? (?:authentication|authorization|an? (?:api[ _-]?key|account|login|token))|"
    r"(?:missing|invalid|expired|provide|need(?:s|ed)?|requires?|must set|please set) "
    r"[^\n]{0,24}(?:api[ _-]?key|access token|auth token|bearer token|credentials?)|"
    r"invalid (?:api[ _-]?key|token|credentials?)|"
    r"please (?:log ?in|sign ?in|authenticate)|"
    r"command not found|cli not found|not installed|\bENOENT\b|no such file or directory|"
    r"not configured|environment variable[^\n]{0,30}(?:not set|required|missing)|"
    r"\b(?:401|403)\b"
    r")"
)


def _content_error_signal(result: dict[str, Any]) -> str | None:
    """Detect a failure message returned as *successful* content. Servers needing
    creds / local deps often answer 200 with an error string; in strict mode we
    treat that as a tool failure so the gate measures real capability."""
    parts = [
        c.get("text", "")
        for c in (result.get("content") or [])
        if isinstance(c, dict) and c.get("type") == "text"
    ]
    text = "\n".join(parts) if parts else str(result)
    m = _CONTENT_ERROR_RE.search(text[:4000])
    return m.group(0)[:80] if m else None


_ID_KEY_RE = re.compile(
    r"(?i)(^|_)(id|ids|key|keys|token|handle|uuid|guid|slug|ref|cursor|sha|hash|"
    r"name|title|path|url|uri|number|num|code|owner|repo|repository|file|filename|"
    r"database|table|collection|channel|user|username|email|symbol|ticker)s?$"
)


def _result_json(result: dict[str, Any]) -> Any:
    """Best-effort parse of a tool result's text content into JSON."""
    parts = [
        c.get("text", "")
        for c in (result.get("content") or [])
        if isinstance(c, dict) and c.get("type") == "text"
    ]
    text = ("\n".join(parts)).strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _harvest_values(result: dict[str, Any], source_tool: str, cap: int = 12) -> list[dict]:
    """Pull id-like scalar values out of a successful result so a later tool that
    needs an existing id/handle (a prerequisite) can reuse a REAL one."""
    out: list[dict] = []
    data = _result_json(result)
    if data is None:
        return out

    def walk(obj: Any, keyhint: str | None, depth: int) -> None:
        if len(out) >= cap or depth > 4:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, k, depth + 1)
        elif isinstance(obj, list):
            for v in obj[:3]:
                walk(v, keyhint, depth + 1)
        elif isinstance(obj, str | int) and not isinstance(obj, bool):
            s = str(obj)
            if keyhint and _ID_KEY_RE.search(keyhint) and 0 < len(s) <= 80:
                out.append({"source": source_tool, "key": keyhint, "value": obj})

    walk(data, None, 0)
    return out


async def _call_and_classify(
    recorder: TraceRecorder,
    server_id: str,
    tool_name: str,
    args: dict[str, Any],
    timeout: float,
    strict: bool,
) -> tuple[dict[str, Any], dict | None]:
    """Call one tool; return (per-tool entry, result-if-cleanly-ok-else-None)."""
    try:
        res = await asyncio.wait_for(recorder.call_tool(server_id, tool_name, args), timeout=timeout)
    except TimeoutError:
        return {"tool": tool_name, "status": "timeout"}, None
    except Exception as e:
        return {"tool": tool_name, "status": "error", "reason": f"{type(e).__name__}: {e}"[:160]}, None
    if res.get("isError"):
        return {"tool": tool_name, "status": "error", "reason": _result_text(res)}, None
    sig = _content_error_signal(res) if strict else None
    if sig:
        return {"tool": tool_name, "status": "error", "reason": f"content-signal: {sig}"}, None
    return {"tool": tool_name, "status": "ok"}, res


async def verify_server(
    config: ServerConfig,
    *,
    sandbox: bool = False,
    per_tool_timeout: float = 20.0,
    min_tool_pass_rate: float = 0.5,
    llm: OpenRouterClient | None = None,
    strict: bool = False,
    require_all: bool = False,
) -> dict[str, Any]:
    """Boot one server and exercise every tool (two passes). Returns a report."""
    report: dict[str, Any] = {
        "server_id": config.server_id,
        "initialized": False,
        "ok": False,
        "tools": [],
        "dependencies": [],
        "reason": "",
    }
    pool: list[dict] = []  # id-like values harvested across this server's tools
    try:
        recorder = TraceRecorder(servers=[config], goal=f"verify:{config.server_id}")
        async with recorder:
            report["initialized"] = True
            specs = recorder.trace.tool_specs.get(config.server_id, [])

            # ---- pass 1: exercise every non-destructive tool, harvest outputs ----
            pending: list[tuple[dict, Any]] = []  # (entry, tool_spec) for retry
            for ts in specs:
                if is_destructive(ts.name) and not sandbox:
                    report["tools"].append(
                        {"tool": ts.name, "status": "skipped", "reason": "destructive, not sandboxed"}
                    )
                    continue
                args = (
                    await llm_synthesize_args(ts.name, ts.description or "", ts.input_schema, llm)
                    if llm is not None
                    else synthesize_args(ts.input_schema)
                )
                entry, res = await _call_and_classify(
                    recorder, config.server_id, ts.name, args, per_tool_timeout, strict
                )
                report["tools"].append(entry)
                if entry["status"] == "ok" and res is not None:
                    pool.extend(_harvest_values(res, ts.name))
                elif entry["status"] != "skipped":
                    pending.append((entry, ts))

            # ---- pass 2: retry failures with harvested ids + error feedback ----
            if llm is not None:
                available = [{"key": h["key"], "value": h["value"]} for h in pool]
                for entry, ts in pending:
                    if entry["status"] == "timeout":
                        continue  # don't re-run hangs
                    args2 = await llm_synthesize_args(
                        ts.name,
                        ts.description or "",
                        ts.input_schema,
                        llm,
                        prior_error=entry.get("reason"),
                        available=available or None,
                    )
                    new_entry, res2 = await _call_and_classify(
                        recorder, config.server_id, ts.name, args2, per_tool_timeout, strict
                    )
                    if new_entry["status"] == "ok":
                        entry["status"] = "ok"
                        entry["reason"] = "recovered on retry"
                        for field, val in args2.items():
                            for h in pool:
                                if h["value"] == val and h["source"] != ts.name:
                                    report["dependencies"].append(
                                        {
                                            "producer": h["source"],
                                            "consumer": ts.name,
                                            "field": field,
                                            "via_key": h["key"],
                                        }
                                    )
                                    entry["recovered_via"] = h["source"]
                                    break
                        if res2 is not None:
                            pool.extend(_harvest_values(res2, ts.name))
    except Exception as e:
        report["reason"] = f"init failed: {type(e).__name__}: {str(e)[:160]}"
        return report

    exercised = [t for t in report["tools"] if t["status"] != "skipped"]
    ok_count = sum(1 for t in exercised if t["status"] == "ok")
    report["tool_count"] = len(report["tools"])
    report["ok_count"] = ok_count
    report["pass_rate"] = (ok_count / len(exercised)) if exercised else 0.0
    if require_all:
        report["ok"] = bool(report["initialized"] and exercised and ok_count == len(exercised))
    else:
        report["ok"] = bool(
            report["initialized"]
            and report["tools"]
            and (not exercised or report["pass_rate"] >= min_tool_pass_rate)
        )
    if not report["reason"]:
        skipped = len(report["tools"]) - len(exercised)
        deps = f", {len(report['dependencies'])} deps" if report["dependencies"] else ""
        report["reason"] = (
            f"{ok_count}/{len(exercised)} tools ok" + (f" ({skipped} skipped)" if skipped else "") + deps
        )
    return report
