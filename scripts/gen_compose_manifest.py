#!/usr/bin/env python3
"""Generate manifests/compose.json — the docker-compose-mcp.yaml stack wired as a
DynamicMCPBench manifest (HTTP/SSE transport). server_ids are prefixed `compose_`
to avoid colliding with the stdio substrate (e.g. the `git` substrate server)."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# service: (host_port, transport, path, dynamism, domain)
# transports/paths reflect each image's MCP endpoint; supergateway wrappers expose SSE at /sse.
SERVICES = [
    ("postgres", 8001, "sse", "/sse", "stateful_write", "data"),
    ("mongo", 8002, "streamable_http", "/mcp", "stateful_write", "data"),
    ("neo4j", 8003, "sse", "/sse", "stateful_write", "data"),
    ("qdrant", 8005, "sse", "/sse", "stateful_write", "data"),
    ("redis", 8006, "sse", "/sse", "stateful_write", "data"),
    ("duckdb", 8008, "sse", "/sse", "stateful_write", "data"),
    ("elasticsearch", 8010, "sse", "/sse", "stateful_write", "search"),
    ("meilisearch", 8011, "sse", "/sse", "stateful_write", "search"),
    ("grafana", 8012, "sse", "/sse", "live_read", "cloud-infra"),
    ("prometheus", 8013, "sse", "/sse", "live_read", "cloud-infra"),
    ("kafka", 8018, "streamable_http", "/mcp", "stateful_write", "cloud-infra"),
    ("git", 8019, "sse", "/sse", "stateful_write", "dev"),
    ("time", 8020, "sse", "/sse", "static", "productivity"),
]

servers = []
for svc, port, transport, path, dyn, domain in SERVICES:
    servers.append(
        {
            "server_id": f"compose_{svc}",
            "transport": transport,
            "dynamism": dyn,
            # the ephemeral compose container IS the sandbox for stateful_write servers
            "sandbox": dyn == "stateful_write",
            "description": f"{svc} MCP server from docker-compose-mcp.yaml (container-sandboxed).",
            "tags": ["compose", "docker", "pkg:docker", f"dyn:{dyn}", f"domain:{domain}"],
            "endpoint": f"http://localhost:{port}{path}",
        }
    )

out = ROOT / "manifests" / "compose.json"
out.write_text(json.dumps({"manifest_version": "0.1.0", "servers": servers}, indent=2), encoding="utf-8")
print(f"wrote {out} with {len(servers)} compose MCP servers")
print("up-now (minimal):", [s for s in ("postgres", "mongo", "qdrant", "git", "time")])
