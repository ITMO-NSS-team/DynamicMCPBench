#!/usr/bin/env python3
"""Resilient refresh/decay runner: one spec per subprocess with a hard timeout.

`dmcp refresh` crashes the whole batch if a single live call hangs (the
backoff sleep gets cancelled). This driver isolates each spec in its own
subprocess with a wall-clock timeout, so a hung/broken server marks just that
spec's calls and the run continues. Aggregates identical/drifted/broken/skipped
overall and per primary server.

Run:  uv run python scripts/run_decay.py SPECS TRACES MANIFEST [TIMEOUT_S]
"""

from __future__ import annotations

import collections
import json
import os
import re
import subprocess
import sys
import tempfile

SPECS, TRACES, MAN = sys.argv[1], sys.argv[2], sys.argv[3]
TIMEOUT = int(sys.argv[4]) if len(sys.argv) > 4 else 120
DMCP = os.path.join(os.path.dirname(__file__), "..", ".venv", "bin", "dmcp")

traces = {}
for ln in open(TRACES, encoding="utf-8"):
    if ln.strip():
        t = json.loads(ln)
        traces[str(t["trace_id"])] = t
specs = [json.loads(ln) for ln in open(SPECS, encoding="utf-8") if ln.strip()]


def primary_server(t):
    c = collections.Counter(
        s.get("server_id")
        for s in (t.get("steps") or [])
        if (s.get("step_kind") == "call_tool_agent" or s.get("kind") == "call_tool_agent")
        and s.get("server_id")
    )
    # ignore git/sqlite (skipped on refresh) when labelling the live server
    for sid, _ in c.most_common():
        if sid not in ("git", "sqlite"):
            return sid
    return c.most_common(1)[0][0] if c else "?"


LINE = re.compile(r"identical=(\d+)\s+drifted=(\d+)\s+broken=(\d+)\s+skipped=(\d+)")
per_server = collections.defaultdict(lambda: collections.Counter())
overall = collections.Counter()
done = 0
for sp in specs:
    tid = str(sp["source_trace_id"])
    if tid not in traces:
        continue
    srv = primary_server(traces[tid])
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as sf, \
         tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as tf:  # fmt: skip
        sf.write(json.dumps(sp) + "\n")
        tf.write(json.dumps(traces[tid]) + "\n")
        spath, tpath = sf.name, tf.name
    cmd = [DMCP, "refresh", spath, "--reference-traces", tpath, "--manifest", MAN, "--retries", "1"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
        m = LINE.search(r.stdout)
        if m:
            i, d, b, k = (int(x) for x in m.groups())
            per_server[srv].update(identical=i, drifted=d, broken=b, skipped=k, specs=1)
            overall.update(identical=i, drifted=d, broken=b, skipped=k, specs=1)
            status = f"id={i} dr={d} br={b} sk={k}"
        else:
            per_server[srv].update(crashed=1, specs=1)
            overall.update(crashed=1, specs=1)
            status = "no-result (crash)"
    except subprocess.TimeoutExpired:
        per_server[srv].update(timeout=1, specs=1)
        overall.update(timeout=1, specs=1)
        status = "TIMEOUT"
    finally:
        os.unlink(spath)
        os.unlink(tpath)
    done += 1
    print(f"[{done}/{len(specs)}] {srv:10} {status}", flush=True)

result = {"overall": dict(overall), "per_server": {k: dict(v) for k, v in per_server.items()}}
json.dump(result, open("/tmp/decay_results.json", "w"), indent=2)
print("\n=== DECAY SUMMARY ===")
print(json.dumps(result, indent=2))
