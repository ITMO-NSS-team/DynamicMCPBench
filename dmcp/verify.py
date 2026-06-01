"""Deep server verification (E3 Phase B).

Boots a server, lists its tools, and EXERCISES each tool with arguments
synthesized from its input schema, recording per-tool ok / error / timeout /
skipped. A server PASSES if it initializes, exposes >=1 tool, and at least
`min_tool_pass_rate` of its non-skipped tools return without error.

Safety: destructive-looking tools (delete / drop / ...) are skipped unless the
server is declared sandboxed. Per-tool and per-server timeouts bound the work.
Used to vet crawled servers before they enter the manifest (no-creds focus).
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

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


def _result_text(result: dict[str, Any]) -> str:
    parts = [
        c.get("text", "")
        for c in (result.get("content") or [])
        if isinstance(c, dict) and c.get("type") == "text"
    ]
    return ("\n".join(parts) if parts else str(result))[:160]


async def verify_server(
    config: ServerConfig,
    *,
    sandbox: bool = False,
    per_tool_timeout: float = 20.0,
    min_tool_pass_rate: float = 0.5,
) -> dict[str, Any]:
    """Boot one server and exercise every tool. Returns a structured report."""
    report: dict[str, Any] = {
        "server_id": config.server_id,
        "initialized": False,
        "ok": False,
        "tools": [],
        "reason": "",
    }
    try:
        recorder = TraceRecorder(servers=[config], goal=f"verify:{config.server_id}")
        async with recorder:
            report["initialized"] = True
            specs = recorder.trace.tool_specs.get(config.server_id, [])
            for ts in specs:
                if is_destructive(ts.name) and not sandbox:
                    report["tools"].append(
                        {"tool": ts.name, "status": "skipped", "reason": "destructive, not sandboxed"}
                    )
                    continue
                args = synthesize_args(ts.input_schema)
                try:
                    res = await asyncio.wait_for(
                        recorder.call_tool(config.server_id, ts.name, args),
                        timeout=per_tool_timeout,
                    )
                    if res.get("isError"):
                        report["tools"].append(
                            {"tool": ts.name, "status": "error", "reason": _result_text(res)}
                        )
                    else:
                        report["tools"].append({"tool": ts.name, "status": "ok"})
                except TimeoutError:
                    report["tools"].append({"tool": ts.name, "status": "timeout"})
                except Exception as e:
                    report["tools"].append(
                        {"tool": ts.name, "status": "error", "reason": f"{type(e).__name__}: {e}"[:160]}
                    )
    except Exception as e:
        report["reason"] = f"init failed: {type(e).__name__}: {str(e)[:160]}"
        return report

    exercised = [t for t in report["tools"] if t["status"] != "skipped"]
    ok_count = sum(1 for t in exercised if t["status"] == "ok")
    report["tool_count"] = len(report["tools"])
    report["ok_count"] = ok_count
    report["pass_rate"] = (ok_count / len(exercised)) if exercised else 0.0
    report["ok"] = bool(
        report["initialized"]
        and report["tools"]
        and (not exercised or report["pass_rate"] >= min_tool_pass_rate)
    )
    if not report["reason"]:
        skipped = len(report["tools"]) - len(exercised)
        report["reason"] = f"{ok_count}/{len(exercised)} tools ok" + (
            f" ({skipped} skipped)" if skipped else ""
        )
    return report
