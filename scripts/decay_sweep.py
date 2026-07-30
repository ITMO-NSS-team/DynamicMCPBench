#!/usr/bin/env python3
"""Wide refresh/decay sweep: re-execute reference traces across the whole server catalogue.

The first decay snapshot (`docs/experiments/decay-living-benchmark.md`) covered
22 traces on 3 server families, which is enough to show that decay exists but
not to say anything per-domain. This driver widens it: it takes a deterministic
stratified sample of at most K specs per primary server, runs each one through
`dmcp refresh` in an isolated subprocess with a wall-clock timeout, and
aggregates the per-call outcomes by server and by domain.

Two design points matter for the validity of the numbers:

* **Never two specs of the same server in flight.** Workers pull whole servers,
  not individual specs, so concurrency spreads *across* servers. The earlier
  run lost 9 of 10 wikipedia traces to self-inflicted rate limiting; sharding by
  server keeps parallelism from manufacturing that artifact.
* **Aggregate from the structured report, not from stdout.** Each
  `CallRefreshOutcome` carries its own `server_id` and `classification`, so a
  trace that touches several servers is attributed per call rather than being
  charged wholesale to one "primary" server.

`stateful_write` servers are never sampled (invariant 4): exploration and
refresh must not cause real side effects, and `dmcp refresh` skips them anyway.

Scope of v0: sampling, execution, and aggregation of already-defined refresh
classifications. Out of scope: deciding *why* a call drifted (that is the E9.12
attribution classifier, which this script consumes rather than reimplements),
any LLM call, and any mutation of the corpus.

Run:
    uv run python scripts/decay_sweep.py --specs specs.jsonl --traces traces.jsonl \
        --manifest manifests/servers.json --per-server 2 --workers 6 --out-dir reports/decay_sweep
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DMCP = ROOT / ".venv" / "bin" / "dmcp"

SWEEP_VERSION = "0.1.0"

# Classifications emitted by dmcp.refresh (mirrors refresh.ALL_CLASSIFICATIONS).
ATTRIBUTABLE = ("schema_drift", "state_decay")
LIVE = ("identical", "drifted", *ATTRIBUTABLE)
ALL = (*LIVE, "unresolved", "skipped", "quarantined")

# Deterministic keyword -> domain map over `server_id + description`. First rule
# that matches wins, so the order below is part of the definition. This is a
# coarse topical grouping for reporting only; it never feeds scoring.
DOMAIN_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "law_compliance",
        (
            "law",
            "legal",
            "statute",
            "regulation",
            "regulatory",
            "compliance",
            "gdpr",
            "dpia",
            "iso 42001",
            "42001",
            "19650",
            "dora",
            "nis2",
            "csrd",
            "federal register",
            "edpb",
            "ai bill",
            "ai act",
        ),
    ),
    (
        "security",
        (
            "security",
            "threat",
            "cve",
            "vulnerab",
            "injection",
            "firewall",
            "malware",
            "incident",
            "rate limiter",
            "audit log",
            "watermark",
            "bias detection",
            "scan",
        ),
    ),
    (
        "finance_markets",
        (
            "financ",
            "market",
            "trading",
            "trade",
            "stock",
            "ticker",
            "invest",
            "bank",
            "payment",
            "crypto",
            "bitcoin",
            "valuation",
            "insurance",
            "claims",
            "retirement",
            "annuit",
            "apra",
            "asic",
            "x402",
            "tax",
        ),
    ),
    (
        "science_health",
        (
            "arxiv",
            "pubmed",
            "paper",
            "scholar",
            "research",
            "biomed",
            "medical",
            "health",
            "clinical",
            "healthcare",
            "disease",
            "aihw",
        ),
    ),
    (
        "gov_statistics",
        (
            "worldbank",
            "eurostat",
            "statistic",
            "census",
            "bureau",
            "government",
            "australian bureau",
            "wgea",
            "aemo",
            "nace",
        ),
    ),
    (
        "geo_weather",
        (
            "weather",
            "climate",
            "air quality",
            "geoloc",
            "geograph",
            "openstreetmap",
            "osm",
            "map",
            "location",
            "timezone",
            "flight",
        ),
    ),
    (
        "reference_knowledge",
        (
            "wikipedia",
            "wikidata",
            "encyclopedi",
            "openlibrary",
            "library",
            "book",
            "quran",
            "qur",
            "dictionary",
            "knowledge base",
            "hermetic",
        ),
    ),
    (
        "dev_tools",
        (
            "code",
            "developer",
            "unreal",
            "unity",
            "pyspark",
            "dependenc",
            "package",
            "repositor",
            "api reference",
            "sdk",
            "tech stack",
            "technolog",
            "e18e",
        ),
    ),
    (
        "ai_agents",
        ("prompt", "llm", "agent", "persona", "thinking", "handoff", "design token", "advisor"),
    ),
    ("web_scraping", ("scrape", "scraping", "fetch", "crawl", "webpage", "http")),
    (
        "industry_business",
        (
            "construction",
            "procurement",
            "subcontractor",
            "travel",
            "hotel",
            "sport",
            "retail",
            "product",
            "logistic",
            "haulage",
            "skip hire",
            "brand",
            "marketing",
            "seo",
            "semrush",
            "vendor",
            "session",
        ),
    ),
    (
        "infrastructure",
        (
            "grafana",
            "mongo",
            "postgres",
            "meilisearch",
            "sqlite",
            "filesystem",
            "memory graph",
            "version control",
            "current time",
        ),
    ),
)


def domain_for(server_id: str, description: str = "") -> str:
    """Assign a coarse topical domain to a server. Unmatched servers land in `other`."""
    hay = f"{server_id} {description}".lower().replace("_", " ")
    for name, keywords in DOMAIN_RULES:
        if any(k in hay for k in keywords):
            return name
    return "other"


def primary_server(trace: dict[str, Any]) -> str:
    """The server a trace is mostly about, used only to stratify the sample.

    Local scaffolding servers (git/sqlite) are skipped when labelling because a
    trace that merely records its work there is really about the live server it
    queried.
    """
    counts = collections.Counter(
        step.get("server_id")
        for step in (trace.get("steps") or [])
        if step.get("kind") == "call_tool_agent" and step.get("server_id")
    )
    for server_id, _ in counts.most_common():
        if server_id not in ("git", "sqlite"):
            return server_id
    return counts.most_common(1)[0][0] if counts else "?"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load_manifest(path: Path) -> dict[str, dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    servers = raw["servers"] if isinstance(raw, dict) else raw
    return {s["server_id"]: s for s in servers}


def stratified_sample(
    specs: list[dict[str, Any]],
    traces: dict[str, dict[str, Any]],
    manifest: dict[str, dict[str, Any]],
    per_server: int,
) -> dict[str, list[dict[str, Any]]]:
    """Group specs by primary server and keep at most `per_server` of each.

    Deterministic: specs are ordered by `task_id` within a server and servers by
    id. `stateful_write` servers and servers absent from the manifest are
    dropped — the former by invariant, the latter because they cannot be run.
    """
    by_server: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for spec in specs:
        trace = traces.get(str(spec.get("source_trace_id")))
        if trace is None:
            continue
        server_id = primary_server(trace)
        entry = manifest.get(server_id)
        if entry is None or entry.get("dynamism") == "stateful_write":
            continue
        by_server[server_id].append(spec)
    return {
        server_id: sorted(items, key=lambda s: str(s["task_id"]))[:per_server]
        for server_id, items in sorted(by_server.items())
    }


def outcomes_from_report(report_path: Path) -> list[dict[str, Any]] | None:
    """Read the per-call outcomes out of a `dmcp refresh` report, if it exists."""
    if not report_path.exists():
        return None
    rows = load_jsonl(report_path)
    if not rows:
        return None
    calls: list[dict[str, Any]] = []
    for row in rows:
        for outcome in row.get("call_outcomes") or []:
            calls.append(
                {
                    "server_id": outcome.get("server_id", "?"),
                    "classification": outcome.get("classification", "?"),
                    "retry_count": outcome.get("retry_count", 0),
                }
            )
        if row.get("quarantined") and not (row.get("call_outcomes") or []):
            calls.append({"server_id": "?", "classification": "quarantined", "retry_count": 0})
    return calls


def run_spec(
    spec: dict[str, Any],
    trace: dict[str, Any],
    manifest_path: Path,
    *,
    timeout: int,
    retries: int,
) -> dict[str, Any]:
    """Run one spec through `dmcp refresh` in its own subprocess."""
    tmpdir = Path(tempfile.mkdtemp(prefix="decay_sweep_"))
    spec_path, trace_path = tmpdir / "spec.jsonl", tmpdir / "trace.jsonl"
    report_path = tmpdir / "report.jsonl"
    spec_path.write_text(json.dumps(spec) + "\n", encoding="utf-8")
    trace_path.write_text(json.dumps(trace) + "\n", encoding="utf-8")
    cmd = [
        str(DMCP), "refresh", str(spec_path),
        "--reference-traces", str(trace_path),
        "--manifest", str(manifest_path),
        "--retries", str(retries),
        "--output", str(report_path),
    ]  # fmt: skip
    status = "ok"
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        calls = outcomes_from_report(report_path)
        if calls is None:
            status, calls = "crashed", []
    except subprocess.TimeoutExpired:
        status, calls = "timeout", outcomes_from_report(report_path) or []
    finally:
        for path in (spec_path, trace_path, report_path):
            path.unlink(missing_ok=True)
        os.rmdir(tmpdir)
    return {"task_id": str(spec["task_id"]), "status": status, "calls": calls}


def run_sweep(
    sample: dict[str, list[dict[str, Any]]],
    traces: dict[str, dict[str, Any]],
    manifest_path: Path,
    *,
    workers: int,
    timeout: int,
    retries: int,
) -> list[dict[str, Any]]:
    """Execute the sample, one worker per server so no server is hit concurrently."""
    queue = collections.deque(sorted(sample.items()))
    lock, results = threading.Lock(), []
    total = sum(len(v) for v in sample.values())
    done = 0

    def worker() -> None:
        nonlocal done
        while True:
            with lock:
                if not queue:
                    return
                server_id, specs = queue.popleft()
            for spec in specs:
                trace = traces[str(spec["source_trace_id"])]
                record = run_spec(spec, trace, manifest_path, timeout=timeout, retries=retries)
                record["server_id"] = server_id
                with lock:
                    results.append(record)
                    done += 1
                    counts = collections.Counter(c["classification"] for c in record["calls"])
                    print(
                        f"[{done}/{total}] {server_id[:38]:38} {record['status']:8} {dict(counts) or '{}'}",
                        flush=True,
                    )

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(max(1, workers))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return sorted(results, key=lambda r: (r["server_id"], r["task_id"]))


def _rates(counts: collections.Counter[str]) -> dict[str, Any]:
    """Percentages over *live* calls only; unresolved/skipped/quarantined are excluded."""
    live = sum(counts[c] for c in LIVE)
    attributable = sum(counts[c] for c in ATTRIBUTABLE)
    out: dict[str, Any] = {c: counts[c] for c in ALL}
    out["live_calls"] = live
    out["attributable"] = attributable
    if live:
        out["identical_pct"] = round(100 * counts["identical"] / live, 1)
        out["drifted_pct"] = round(100 * counts["drifted"] / live, 1)
        out["broken_pct"] = round(100 * attributable / live, 1)
    return out


def aggregate(records: list[dict[str, Any]], manifest: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Fold per-call outcomes into overall / per-server / per-domain views."""
    overall: collections.Counter[str] = collections.Counter()
    per_server: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    per_domain: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    statuses: collections.Counter[str] = collections.Counter()
    servers_seen: dict[str, set[str]] = collections.defaultdict(set)

    for record in records:
        statuses[record["status"]] += 1
        for call in record["calls"]:
            server_id = call["server_id"]
            entry = manifest.get(server_id, {})
            domain = domain_for(server_id, entry.get("description") or "")
            classification = call["classification"]
            overall[classification] += 1
            per_server[server_id][classification] += 1
            per_domain[domain][classification] += 1
            servers_seen[domain].add(server_id)

    return {
        "sweep_version": SWEEP_VERSION,
        "specs_attempted": len(records),
        "spec_status": dict(sorted(statuses.items())),
        "servers_sampled": len({r["server_id"] for r in records}),
        "servers_with_calls": len(per_server),
        "overall": _rates(overall),
        "per_server": {k: _rates(v) for k, v in sorted(per_server.items())},
        "per_domain": {
            k: {**_rates(v), "servers": len(servers_seen[k])} for k, v in sorted(per_domain.items())
        },
    }


def _pct(row: dict[str, Any], key: str) -> str:
    return f"{row[key]}%" if key in row else "—"


def render_markdown(agg: dict[str, Any], *, min_calls: int = 5) -> str:
    """Render the per-domain and per-server tables used in the experiment report."""
    lines = [
        f"Specs attempted: {agg['specs_attempted']} across {agg['servers_sampled']} servers "
        f"({agg['servers_with_calls']} produced live calls). "
        f"Spec status: {agg['spec_status']}.",
        "",
        "| domain | servers | live calls | identical | drifted | broken (upper bound) |",
        "|---|---|---|---|---|---|",
    ]
    for domain, row in sorted(agg["per_domain"].items(), key=lambda kv: -kv[1]["live_calls"]):
        if not row["live_calls"]:
            continue
        lines.append(
            f"| {domain} | {row['servers']} | {row['live_calls']} | "
            f"{_pct(row, 'identical_pct')} | {_pct(row, 'drifted_pct')} | "
            f"{_pct(row, 'broken_pct')} |"
        )
    o = agg["overall"]
    lines.append(
        f"| **all** | **{agg['servers_with_calls']}** | **{o['live_calls']}** | "
        f"**{_pct(o, 'identical_pct')}** | **{_pct(o, 'drifted_pct')}** | "
        f"**{_pct(o, 'broken_pct')}** |"
    )
    lines += [
        "",
        f"Per-server (≥{min_calls} live calls):",
        "",
        "| server | live calls | identical | drifted | broken |",
        "|---|---|---|---|---|",
    ]
    for server_id, row in sorted(agg["per_server"].items(), key=lambda kv: -kv[1]["live_calls"]):
        if row["live_calls"] < min_calls:
            continue
        lines.append(
            f"| {server_id} | {row['live_calls']} | {_pct(row, 'identical_pct')} | "
            f"{_pct(row, 'drifted_pct')} | {_pct(row, 'broken_pct')} |"
        )
    lines += [
        "",
        f"Excluded from every rate above: {o['unresolved']} unresolved, {o['skipped']} skipped "
        f"(stateful_write), {o['quarantined']} quarantined (preflight).",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--specs", type=Path, default=Path("specs.jsonl"))
    parser.add_argument("--traces", type=Path, default=Path("traces.jsonl"))
    parser.add_argument("--manifest", type=Path, default=Path("manifests/servers.json"))
    parser.add_argument("--per-server", type=int, default=2)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--out-dir", type=Path, default=Path("reports/decay_sweep"))
    parser.add_argument("--dry-run", action="store_true", help="print the sample and exit")
    args = parser.parse_args(argv)

    specs = load_jsonl(args.specs)
    traces = {str(t["trace_id"]): t for t in load_jsonl(args.traces)}
    manifest = load_manifest(args.manifest)
    sample = stratified_sample(specs, traces, manifest, args.per_server)
    n_specs = sum(len(v) for v in sample.values())
    print(f"sample: {n_specs} specs across {len(sample)} servers", flush=True)
    if args.dry_run:
        for server_id, items in sample.items():
            print(f"  {server_id:44} {len(items)}")
        return 0

    records = run_sweep(
        sample,
        traces,
        args.manifest,
        workers=args.workers,
        timeout=args.timeout,
        retries=args.retries,
    )
    agg = aggregate(records, manifest)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "sweep.json").write_text(
        json.dumps({"aggregate": agg, "records": records}, indent=2) + "\n", encoding="utf-8"
    )
    markdown = render_markdown(agg)
    (args.out_dir / "sweep.md").write_text(markdown + "\n", encoding="utf-8")
    print("\n" + markdown)
    print(f"\nwrote {args.out_dir}/sweep.json and {args.out_dir}/sweep.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
