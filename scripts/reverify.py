#!/usr/bin/env python3
"""Re-verify an existing manifest under the strict content-aware gate, each server
in its own killable subprocess (reuses scripts/collect_servers.py primitives, which
already pass `dmcp verify --strict`). Writes the survivors to --out. No re-install:
pypi venvs from the original crawl are reused; npm runs via cached npx.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import collect_servers as C  # noqa: E402


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--min-pass-rate", type=float, default=0.5)
    ap.add_argument("--verify-timeout", type=float, default=150.0)
    ap.add_argument("--log", default="reverify.log")
    a = ap.parse_args()

    src = json.loads((ROOT / a.inp).read_text(encoding="utf-8"))["servers"]
    out = ROOT / a.out
    fh = open(ROOT / a.log, "a", encoding="utf-8")  # noqa: SIM115 (lives for the whole run)
    kept: list[dict] = []
    lock = asyncio.Lock()
    sem = asyncio.Semaphore(a.concurrency)

    def wm() -> None:
        out.write_text(json.dumps({"manifest_version": "0.1.0", "servers": kept}, indent=2), encoding="utf-8")

    C.log(fh, f"strict re-verify of {len(src)} servers from {a.inp}")

    async def rv(e: dict) -> None:
        async with sem:
            sid = e["server_id"]
            rep = await C._verify(sid, e["command"], e["args"], a.min_pass_rate, a.verify_timeout)
            ok = bool(rep and rep.get("ok"))
            async with lock:
                if ok:
                    kept.append(e)
                    wm()
                r = rep or {}
                C.log(
                    fh,
                    f"  {'KEEP' if ok else 'drop'} [{len(kept):>3}] {sid} "
                    f"({r.get('ok_count')}/{r.get('tool_count')}) {str(r.get('reason', ''))[:55]}",
                )

    await asyncio.gather(*[rv(e) for e in src], return_exceptions=True)
    wm()
    C.log(fh, f"DONE: {len(kept)}/{len(src)} survived strict gate -> {out}")
    fh.close()


if __name__ == "__main__":
    asyncio.run(main())
