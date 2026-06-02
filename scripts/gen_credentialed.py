#!/usr/bin/env python3
"""Generate manifests/credentialed.json — the Bucket A key-requiring MCP servers
(docs/credentials_bucket_a.md), env-plumbed from .env (never committed) and gated on
present keys. Run via npx (portable). dynamism is capped at live_read: SaaS servers
can't be sandboxed, so we only attest read behavior (write tools are destructive and
skipped by verify), consistent with the crawled tier."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (server_id, npm_pkg, [env vars], domain, description)
SERVERS = [
    (
        "github",
        "@modelcontextprotocol/server-github",
        ["GITHUB_PERSONAL_ACCESS_TOKEN"],
        "dev",
        "GitHub — real repo state: issues, PRs, commits, file contents.",
    ),
    (
        "brave_search",
        "@modelcontextprotocol/server-brave-search",
        ["BRAVE_API_KEY"],
        "search",
        "Brave Search — real web search results.",
    ),
    (
        "tavily",
        "tavily-mcp",
        ["TAVILY_API_KEY"],
        "search",
        "Tavily — research-flavored web search/answer API.",
    ),
    (
        "exa",
        "exa-mcp-server",
        ["EXA_API_KEY"],
        "search",
        "Exa — semantic web search (find pages by meaning).",
    ),
    (
        "firecrawl",
        "firecrawl-mcp-server",
        ["FIRECRAWL_API_KEY"],
        "web-scraping",
        "Firecrawl — scrape/crawl JS-rendered sites.",
    ),
    (
        "linear",
        "linear-mcp",
        ["LINEAR_API_KEY"],
        "productivity",
        "Linear — real issue tracker: issues, status, comments.",
    ),
    (
        "notion",
        "@notionhq/notion-mcp-server",
        ["NOTION_API_KEY"],
        "productivity",
        "Notion — real workspace pages: read/write/search.",
    ),
    (
        "slack",
        "slack-workspace-mcp-server",
        ["SLACK_BOT_TOKEN"],
        "communication",
        "Slack — real messaging: post, list channels, history.",
    ),
    (
        "supabase",
        "@supabase/mcp-server-supabase",
        ["SUPABASE_ACCESS_TOKEN", "SUPABASE_PROJECT_REF"],
        "data",
        "Supabase — real Postgres + auth + storage.",
    ),
]

servers = []
for sid, pkg, env_vars, domain, desc in SERVERS:
    servers.append(
        {
            "server_id": sid,
            "transport": "stdio",
            "dynamism": "live_read",
            "sandbox": False,
            "description": desc,
            "tags": ["credentialed", "tier:credentialed", "pkg:npm", f"domain:{domain}"],
            "command": "npx",
            "args": ["-y", pkg],
            "requires_env": env_vars,
        }
    )

out = ROOT / "manifests" / "credentialed.json"
out.write_text(json.dumps({"manifest_version": "0.1.0", "servers": servers}, indent=2), encoding="utf-8")
print(f"wrote {out} with {len(servers)} credentialed servers")
print("env vars referenced:", sorted({v for _, _, evs, _, _ in SERVERS for v in evs}))
