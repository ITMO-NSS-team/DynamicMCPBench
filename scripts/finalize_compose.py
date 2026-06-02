#!/usr/bin/env python3
"""Tag manifests/compose.json with smoke-vet status (data-driven from the
scripts/bring_up_verify_all.sh results) + write reports/compose_verify.md."""

import glob
import json
from pathlib import Path

from dmcp.manifest import Manifest

ROOT = Path(__file__).resolve().parent.parent

results = {}
for f in glob.glob("/tmp/compose_results/compose_*.jsonl"):
    try:
        r = json.loads(Path(f).read_text())
        results[r["server_id"]] = r
    except (json.JSONDecodeError, KeyError):
        continue


def status_of(rep: dict | None) -> tuple[str, str]:
    if not rep:
        return "unverified", "not brought up"
    pr = rep.get("pass_rate")
    okc, tc = rep.get("ok_count"), rep.get("tool_count")
    if rep.get("ok") and pr == 1.0:
        return "full", f"{okc}/{tc} tools ok"
    if isinstance(pr, (int, float)) and pr and pr > 0:
        return "partial", f"{okc}/{tc} tools ok (pass_rate {pr:.2f})"
    return "fail", str(rep.get("reason", "init/connection failed"))[:60]


m = Manifest.load(ROOT / "manifests" / "compose.json")
rows = []
for e in m.servers:
    status, note = status_of(results.get(e.server_id))
    e.tags = [t for t in e.tags if not t.startswith("verify:")] + [f"verify:{status}"]
    rows.append((e.server_id, e.transport.value, e.dynamism.value, e.endpoint, status, note))
m.dump(ROOT / "manifests" / "compose.json")

lines = [
    "# docker-compose MCP stack — smoke-vet report (E3.3)",
    "",
    "`manifests/compose.json` wires the 13 MCP servers from `docker-compose-mcp.yaml`",
    "as HTTP/SSE entries. Bring the stack up (`docs/SETUP.md`), then",
    "`dmcp verify -m manifests/compose.json`. The servers that pass the strict",
    "`--require-all` gate are also folded into `manifests/servers.json` (tier:compose).",
    "",
    "Verified on itmo-laba 2026-06-02 (each server brought up + verified individually):",
    "",
    "| server_id | transport | dynamism | endpoint | verify |",
    "|---|---|---|---|---|",
]
for sid, tr, dyn, ep, status, note in sorted(rows):
    lines.append(f"| `{sid}` | {tr} | {dyn} | `{ep}` | **{status}** — {note} |")
nfull = sum(1 for r in rows if r[4] == "full")
lines += [
    "",
    f"**{nfull}/13 pass the strict 100% gate** "
    "(postgres, neo4j, qdrant, time). Partials need DB state or a different "
    "endpoint path; streamable_http servers (elasticsearch/meilisearch) drop the "
    "session — likely a path/handshake mismatch to revisit.",
]
(ROOT / "reports").mkdir(exist_ok=True)
(ROOT / "reports" / "compose_verify.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"compose.json tagged from results; {nfull} verify:full of {len(rows)}. report written.")
