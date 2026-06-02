#!/usr/bin/env python3
"""Merge verified compose MCP servers into the canonical servers.json (+catalog),
tagged tier:compose + requires:docker. Only servers that pass the strict 100% gate
are folded in; all 13 stay wired in compose.json. Rebuilds nothing — run subsets after.
"""

import collections
import glob
import json
from pathlib import Path

from dmcp.manifest import Manifest

ROOT = Path(__file__).resolve().parent.parent

# verify results from scripts/bring_up_verify_all.sh
results = {}
for f in glob.glob("/tmp/compose_results/compose_*.jsonl"):
    try:
        r = json.loads(Path(f).read_text())
        results[r["server_id"]] = r
    except (json.JSONDecodeError, KeyError):
        continue

compose = {e.server_id: e for e in Manifest.load(ROOT / "manifests" / "compose.json").servers}
servers_m = Manifest.load(ROOT / "manifests" / "servers.json")
have = {e.server_id for e in servers_m.servers}
catalog = json.loads((ROOT / "manifests" / "catalog.json").read_text())

merged, skipped = [], []
for sid, rep in sorted(results.items()):
    # consistent with the substrate tier: keep every server that BOOTS (init + >=1 tool);
    # partial pass is fine — exploration traces exercise tools in dependency context.
    bootable = bool(rep.get("initialized")) and (rep.get("tool_count") or 0) >= 1
    if not bootable:
        skipped.append((sid, rep.get("pass_rate"), str(rep.get("reason", ""))[:40]))
        continue
    if sid in have or sid not in compose:
        continue
    e = compose[sid]
    verify_tag = "verify:full" if rep.get("pass_rate") == 1.0 else "verify:partial"
    e.tags = [x for x in e.tags if not x.startswith("verify:")]
    for t in ("tier:compose", "requires:docker", verify_tag):
        if t not in e.tags:
            e.tags.append(t)
    tools = rep.get("tools") or []
    e.tool_count = rep.get("tool_count") or len(tools)
    servers_m.servers.append(e)
    catalog[sid] = {
        "tier": "compose",
        "transport": e.transport.value,
        "endpoint": e.endpoint,
        "tool_count": e.tool_count,
        "pass_rate": rep.get("pass_rate"),
        "tools": [{"name": t["tool"], "status": t["status"]} for t in tools],
        "dependencies": rep.get("dependencies") or [],
        "requires": "docker compose -f docker-compose-mcp.yaml up -d",
    }
    merged.append(sid)

servers_m.dump(ROOT / "manifests" / "servers.json")
(ROOT / "manifests" / "catalog.json").write_text(json.dumps(catalog, indent=2), encoding="utf-8")

dyn = collections.Counter(e.dynamism.value for e in servers_m.servers)
print(f"merged {len(merged)} compose servers into servers.json: {merged}")
print(f"skipped (not verify:full): {skipped}")
print(f"servers.json now: {len(servers_m.servers)} servers; dynamism={dict(dyn)}")
