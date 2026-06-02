#!/usr/bin/env python3
"""Merge + enrich verified MCP servers into the canonical experiment manifest.

Reads the crawled all-pass manifest (+catalog) and the hand-curated local.json
substrate (+its require-all verify report), merges and dedups, LLM-classifies
each server's DOMAIN, detects cross-server SAME-NAME tool alternatives (the SAE /
P_alt primitive), and writes:
  * manifests/servers.json    — canonical, portable, tagged (domain/dyn/pkg/size/deps/alt)
  * manifests/catalog.json    — per-server package coords, tools, dependencies, pass_rate
  * manifests/direct_alt.json — same-name cross-server tool pairs (DirectAlt seed)

Domain classification needs OPENROUTER_API_KEY; everything else is offline.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dmcp.llm import DEFAULT_MODEL, OpenRouterClient  # noqa: E402
from dmcp.manifest import Manifest, ServerEntry  # noqa: E402
from dmcp.verify import _name_tokens  # noqa: E402

DOMAINS = [
    "dev",
    "web-scraping",
    "data",
    "science",
    "finance",
    "geo-maps",
    "productivity",
    "communication",
    "media",
    "security",
    "cloud-infra",
    "ai-ml",
    "search",
    "other",
]

_CLASSIFY_SYS = (
    "Classify an MCP server into exactly ONE domain from the allowed list, based on "
    "its description and tool names. Choose the best single fit. Return via emit_domain."
)


def _domain_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "emit_domain",
            "description": "Emit the chosen domain label.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["domain"],
                "properties": {"domain": {"type": "string", "enum": DOMAINS}},
            },
        },
    }


async def classify_domain(llm: OpenRouterClient, sid: str, desc: str, tools: list[str]) -> str:
    user = (
        f"Server id: {sid}\nDescription: {desc or '(none)'}\n"
        f"Tools: {', '.join(tools[:40]) or '(none)'}\nAllowed domains: {DOMAINS}"
    )
    try:
        resp = await llm.chat(
            messages=[
                {"role": "system", "content": _CLASSIFY_SYS},
                {"role": "user", "content": user},
            ],
            tools=[_domain_tool()],
            tool_choice={"type": "function", "function": {"name": "emit_domain"}},
            temperature=0.0,
        )
        if resp.tool_calls:
            d = resp.tool_calls[0].arguments.get("domain")
            if d in DOMAINS:
                return d
    except Exception:
        pass
    return "other"


def _size_bucket(n: int) -> str:
    return "small" if n <= 3 else ("medium" if n <= 10 else "large")


def _set_tag(tags: list[str], prefix: str, value: str) -> None:
    """Replace/insert a single-valued tag of the form prefix:value."""
    keep = [t for t in tags if not t.startswith(prefix + ":")]
    keep.append(f"{prefix}:{value}")
    tags[:] = keep


def _load_catalog(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--crawled", default="manifests/crawled-allpass.json")
    ap.add_argument("--crawled-catalog", default=None)
    ap.add_argument("--local", default="manifests/local.json")
    ap.add_argument(
        "--local-report",
        default="reports/local_verify.jsonl",
        help="JSONL from `dmcp verify -m local.json --require-all --json-out`",
    )
    ap.add_argument(
        "--include-local-below-1",
        action="store_true",
        help="Keep substrate servers even if they did not reach pass_rate==1.0",
    )
    ap.add_argument("--out", default="manifests/servers.json")
    ap.add_argument("--catalog-out", default="manifests/catalog.json")
    ap.add_argument("--direct-alt-out", default="manifests/direct_alt.json")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--domain-concurrency", type=int, default=8)
    a = ap.parse_args()

    crawled = Manifest.load(ROOT / a.crawled)
    crawled_cat = _load_catalog(ROOT / (a.crawled_catalog or a.crawled.replace(".json", ".catalog.json")))

    catalog: dict[str, dict] = {}
    servers: list[ServerEntry] = []
    seen: set[str] = set()

    # ---- crawled all-pass servers (already portable + tagged) ----
    for e in crawled.servers:
        if e.server_id in seen:
            continue
        seen.add(e.server_id)
        servers.append(e)
        catalog[e.server_id] = crawled_cat.get(e.server_id, {})

    # ---- hand-curated substrate (re-verified under require-all) ----
    local = Manifest.load(ROOT / a.local)
    local_reports: dict[str, dict] = {}
    rp = ROOT / a.local_report
    if rp.exists():
        for ln in rp.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(ln)
                local_reports[r["server_id"]] = r
            except (json.JSONDecodeError, KeyError):
                continue
    dropped_local: list[tuple[str, str]] = []
    for e in local.servers:
        if e.server_id in seen:
            continue
        rep = local_reports.get(e.server_id, {})
        pr = rep.get("pass_rate")
        ok_all = bool(rep.get("ok")) and pr == 1.0
        if rep and not ok_all and not a.include_local_below_1:
            dropped_local.append((e.server_id, rep.get("reason", "below 1.0")))
            continue
        seen.add(e.server_id)
        tools = rep.get("tools") or []
        tc = rep.get("tool_count") or len(tools)
        if "substrate" not in e.tags:
            e.tags.append("substrate")
        _set_tag(e.tags, "pkg", "pypi")
        if tc:
            _set_tag(e.tags, "size", _size_bucket(tc))
        _set_tag(e.tags, "deps", "yes" if (rep.get("dependencies")) else "no")
        servers.append(e)
        catalog[e.server_id] = {
            "package": {"kind": "pypi-substrate", "identifier": None, "version": None, "entrypoint": None},
            "tool_count": tc,
            "pass_rate": pr,
            "tools": [{"name": t["tool"], "status": t["status"]} for t in tools],
            "dependencies": rep.get("dependencies") or [],
        }

    # ---- cross-server SAME-NAME alternatives (SAE / P_alt seed) ----
    by_name: dict[str, list[tuple[str, str]]] = {}
    for sid, c in catalog.items():
        for t in c.get("tools") or []:
            nm = "_".join(sorted(_name_tokens(t["name"])))
            if nm:
                by_name.setdefault(nm, []).append((sid, t["name"]))
    direct_alt = []
    alt_servers: set[str] = set()
    for nm, owners in by_name.items():
        servers_for_name = {sid for sid, _ in owners}
        if len(servers_for_name) >= 2:
            direct_alt.append(
                {
                    "normalized_tool": nm,
                    "members": [{"server_id": sid, "tool": tool} for sid, tool in owners],
                    "reviewed": False,
                }
            )
            alt_servers |= servers_for_name
    for e in servers:
        _set_tag(e.tags, "alt", "yes" if e.server_id in alt_servers else "no")

    # ---- LLM domain classification (concurrency-bounded) ----
    llm = OpenRouterClient(model=a.model)
    sem = asyncio.Semaphore(a.domain_concurrency)

    async def _classify(e: ServerEntry) -> tuple[str, str]:
        async with sem:
            tools = [t["name"] for t in (catalog.get(e.server_id, {}).get("tools") or [])]
            d = await classify_domain(llm, e.server_id, e.description or "", tools)
            return e.server_id, d

    async def _run() -> dict[str, str]:
        results = await asyncio.gather(*[_classify(e) for e in servers])
        return dict(results)

    domains = asyncio.run(_run())
    for e in servers:
        _set_tag(e.tags, "domain", domains.get(e.server_id, "other"))
        if e.server_id in catalog:
            catalog[e.server_id]["domain"] = domains.get(e.server_id, "other")

    # ---- tidy entries: inline tool_count, drop null package sub-fields ----
    for e in servers:
        c = catalog.get(e.server_id, {})
        e.tool_count = c.get("tool_count") or None
        if e.package:
            e.package = {k: v for k, v in e.package.items() if v is not None} or None

    # ---- write outputs ----
    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    Manifest(manifest_version=crawled.manifest_version, servers=servers).dump(out)
    (ROOT / a.catalog_out).write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    (ROOT / a.direct_alt_out).write_text(json.dumps(direct_alt, indent=2), encoding="utf-8")

    from collections import Counter

    dom_counts = Counter(domains.values())
    print(
        f"servers.json: {len(servers)} servers "
        f"({sum(1 for e in servers if 'substrate' in e.tags)} substrate, "
        f"{len(servers) - sum(1 for e in servers if 'substrate' in e.tags)} crawled)"
    )
    print(f"domains: {dict(dom_counts)}")
    print(f"direct_alt.json: {len(direct_alt)} same-name groups; alt servers: {len(alt_servers)}")
    if dropped_local:
        print(f"dropped substrate (pass_rate<1.0, use --include-local-below-1 to keep): {dropped_local}")


if __name__ == "__main__":
    main()
