#!/usr/bin/env python3
"""Opt-in LIVE smoke for DMCP Studio — runs the real pipeline end to end.

This makes REAL network + paid LLM calls (goal-gen, an explorer agent over a
live MCP server, and a distiller). It is deliberately NOT part of the test gate.
It requires OPENROUTER_API_KEY in .env and the read-only server installed
(e.g. `uv pip install -e ".[servers]"`).

Run (from the repo root):
    uv run python dmcp-studio/scripts/live_smoke.py --yes-spend [server_id ...]

Default server: yfinance. Prints the generated goal, each streamed live tool
call, and the distilled checkpoint count.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# make `backend` importable (dmcp-studio/ is hyphenated, not a package)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import live  # noqa: E402


async def main(server_ids: list[str]) -> int:
    print(f"LIVE smoke over {server_ids} (this spends OpenRouter budget)…\n")
    goal = await live.live_goal(server_ids)
    print(f"GOAL: {goal.goal}\nPERSONA: {goal.persona}\n")

    trace_id = None
    async for ev in live.stream_explore(server_ids, goal.goal, goal.persona):
        if ev["event"] == "call":
            d = ev["data"]
            print(f"  call #{d['idx']}: {d['server_id']}.{d['tool_name']}({d['arguments']}) ok={d['ok']}")
        elif ev["event"] == "done":
            trace_id = ev["data"]["trace_id"]
            print(f"\nDONE: {ev['data']}")

    spec = await live.live_distill(trace_id)
    print(f"\nDISTILLED TaskSpec: {len(spec.checkpoints)} checkpoints, prompt: {spec.prompt[:80]}…")
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--yes-spend"]
    if "--yes-spend" not in sys.argv:
        print("Refusing to run: this spends paid LLM budget. Re-run with --yes-spend.", file=sys.stderr)
        raise SystemExit(2)
    try:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    except Exception:
        pass
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("OPENROUTER_API_KEY missing (.env). Aborting.", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(asyncio.run(main(args or ["yfinance"])))
