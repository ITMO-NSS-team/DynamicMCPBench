#!/usr/bin/env python3
"""Robustly capture each MCP server's tool surface in a KILLABLE subprocess.

goal-gen's inline live capture crashes the whole run on a single hanging server
(anyio cancel-scope bug when an MCP stdio task group is cancelled by a timeout).
This captures each server in its OWN process group with a hard timeout + SIGKILL
(the scripts/collect_servers.py pattern), so a hang dies with the child and can't
poison the parent loop. Output: surfaces.json = {server_id: [ToolSpec-dict, ...]}
for `dmcp goal-gen --surfaces` / `build_corpus --surfaces` (no live capture).

Worker mode (internal): --one <server_id> boots that one server and prints its
tool surface as JSON on stdout. The orchestrator spawns one worker per server.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


async def _capture_one(server_id: str, manifest_path: str) -> list[dict]:
    from dmcp.manifest import Manifest
    from dmcp.recorder import TraceRecorder

    m = Manifest.load(Path(manifest_path))
    entry = m.by_id(server_id)
    rec = TraceRecorder(servers=[entry.to_config()], goal=f"capture:{server_id}")
    async with rec:
        specs = list(rec.trace.tool_specs.get(server_id, []))
    return [t.model_dump(mode="json") for t in specs]


def _worker(server_id: str, manifest_path: str) -> None:
    try:
        specs = asyncio.run(_capture_one(server_id, manifest_path))
        sys.stdout.write(json.dumps(specs))
    except Exception:
        sys.stdout.write("[]")


async def _orchestrate(manifest_path: str, out_path: str, sids: list[str], timeout: float, conc: int) -> None:
    import collect_servers  # SIGKILL-isolated subprocess helpers (scripts/ on sys.path)

    sem = asyncio.Semaphore(conc)
    surfaces: dict[str, list] = {}
    me = str(Path(__file__).resolve())

    async def go(sid: str) -> None:
        async with sem:
            cmd = [sys.executable, me, "--one", sid, "--manifest", manifest_path]
            rc, out, killed = await collect_servers.run_capture(cmd, timeout)
            try:
                specs = json.loads(out) if out.strip() else []
            except Exception:
                specs = []
            surfaces[sid] = specs
            print(f"  {sid}: {'KILLED(timeout)' if killed else f'{len(specs)} tools'}", flush=True)

    await asyncio.gather(*[go(s) for s in sids])
    working = {k: v for k, v in surfaces.items() if v}
    Path(ROOT / out_path).write_text(json.dumps(working, indent=2), encoding="utf-8")
    print(f"\ncaptured {len(working)}/{len(sids)} servers with tools -> {out_path}")
    print(f"total tools: {sum(len(v) for v in working.values())}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--one", default=None, help="worker mode: capture one server_id")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", default="manifests/surfaces.json")
    ap.add_argument("--server", action="append", dest="servers", default=None)
    ap.add_argument("--timeout", type=float, default=45.0)
    ap.add_argument("--concurrency", type=int, default=8)
    a = ap.parse_args()

    if a.one:
        _worker(a.one, a.manifest)
        return

    from dmcp.manifest import Manifest

    m = Manifest.load(Path(a.manifest) if Path(a.manifest).is_absolute() else ROOT / a.manifest)
    sids = a.servers or [s.server_id for s in m.servers]
    print(f"capturing {len(sids)} servers (timeout={a.timeout}s, concurrency={a.concurrency})...")
    asyncio.run(_orchestrate(a.manifest, a.out, sids, a.timeout, a.concurrency))


if __name__ == "__main__":
    main()
