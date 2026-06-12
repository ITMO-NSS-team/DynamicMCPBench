#!/usr/bin/env python3
"""E5.3: build (and optionally push) the HuggingFace dataset release.

Bundles the released artifacts into ``<out>/``:
  - ``specs.jsonl``        the TaskSpecs (the benchmark)
  - ``traces.jsonl``       the reference traces (deterministic replay world)
  - ``direct_alt.json``    OPT-IN cross-server equivalence groups (reviewed only)
  - ``labels.json``        strategy / difficulty / dynamism / scope distribution
  - ``README.md``          the dataset card / datasheet (provenance, schema, stats)

The build path is dependency-free and runs in CI / a fresh clone with no network
or token (``--dry-run``, the default). ``--push`` lazily imports ``huggingface_hub``
and uploads the folder. No credentials or env values are ever shipped: the manifest
is read only for aggregate counts, DirectAlt ships tool-name groupings only and is
opt-in, and a secret scan refuses to publish if anything key-shaped slips in.

Usage:
  uv run python scripts/release_hf.py --specs data/corpus/specs.jsonl \\
      --traces data/corpus/traces.jsonl --manifest manifests/servers.json \\
      --out dist/hf                         # dry-run: build + validate locally
  uv run python scripts/release_hf.py ... --repo-id ORG/DynamicMCPBench --push
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Strings that must never appear in a shipped artifact (defensive secret scan).
# The lookbehind keeps `sk-`/`AKIA`/`ghp_` from matching inside longer tokens —
# e.g. `govuk-icon-mask-cdf42...` (an asset filename in a fetched page) is not
# an OpenAI key; a real key is always preceded by a quote, space, or separator.
_SECRET_RE = re.compile(
    r"(?<![A-Za-z0-9-])"
    r"(sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{12,}|ghp_[A-Za-z0-9]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _goal_tags(trace: dict) -> list[str]:
    found: list[str] = []

    def walk(o):
        if found:
            return
        if isinstance(o, dict):
            gt = o.get("goal_tags")
            if isinstance(gt, list):
                found.extend(str(x) for x in gt)
                return
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(trace)
    return found


def _strategy(tags: list[str]) -> str:
    return next((t.split(":", 1)[1] for t in tags if t.startswith("strategy:")), "unknown")


def _depth_bin(d: int) -> str:
    return "1-2 (simple)" if d <= 2 else ("3-4 (medium)" if d <= 4 else "5+ (hard)")


def _scan_secrets(path: Path) -> list[str]:
    hits = _SECRET_RE.findall(path.read_text(encoding="utf-8", errors="ignore"))
    return [path.name for _ in hits]


def build(args: argparse.Namespace) -> dict:
    specs_p = ROOT / args.specs
    traces_p = ROOT / args.traces
    specs = _read(specs_p)
    traces = _read(traces_p)
    if not specs:
        raise SystemExit(f"no specs at {specs_p}")
    tags_for_trace = {t.get("trace_id"): _goal_tags(t) for t in traces}

    # Referential integrity: every spec's source trace is present.
    trace_ids = {t.get("trace_id") for t in traces}
    orphans = [s["task_id"] for s in specs if s.get("source_trace_id") not in trace_ids]

    by_strategy: dict[str, int] = collections.Counter()
    by_depth: dict[str, int] = collections.Counter()
    by_dyn: dict[str, int] = collections.Counter()
    by_scope: dict[str, int] = collections.Counter()
    for s in specs:
        st = _strategy(tags_for_trace.get(s.get("source_trace_id"), []))
        depth = int((s.get("complexity") or {}).get("trace_depth", len(s.get("servers_used", []))))
        by_strategy[st] += 1
        by_depth[_depth_bin(depth)] += 1
        by_dyn[s.get("dynamism", "unknown")] += 1
        by_scope["inter-server" if len(set(s.get("servers_used", []))) >= 2 else "intra-server"] += 1

    labels = {
        "n_specs": len(specs),
        "n_traces": len(traces),
        "orphan_specs": orphans,
        "by_strategy": dict(sorted(by_strategy.items())),
        "by_depth_bin": dict(sorted(by_depth.items())),
        "by_dynamism": dict(sorted(by_dyn.items())),
        "by_scope": dict(sorted(by_scope.items())),
    }

    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(specs_p, out / "specs.jsonl")
    shutil.copyfile(traces_p, out / "traces.jsonl")
    (out / "labels.json").write_text(json.dumps(labels, indent=2) + "\n", encoding="utf-8")

    shipped_direct_alt = 0
    if args.direct_alt:
        da = json.loads((ROOT / args.direct_alt).read_text(encoding="utf-8"))
        groups = da.get("groups", da) if isinstance(da, dict) else da
        reviewed = [g for g in groups if g.get("reviewed") is True]
        (out / "direct_alt.json").write_text(
            json.dumps({"groups": reviewed}, indent=2) + "\n", encoding="utf-8"
        )
        shipped_direct_alt = len(reviewed)

    n_servers = 0
    if args.manifest and (ROOT / args.manifest).exists():
        man = json.loads((ROOT / args.manifest).read_text(encoding="utf-8"))
        n_servers = len(man.get("servers", man) if isinstance(man, dict) else man)

    (out / "README.md").write_text(
        _dataset_card(args, labels, shipped_direct_alt, n_servers), encoding="utf-8"
    )

    # Defensive secret scan over everything we are about to publish.
    leaked = [name for f in sorted(out.glob("*")) if f.is_file() for name in _scan_secrets(f)]
    if leaked:
        raise SystemExit(f"REFUSING to release: secret-shaped content in {sorted(set(leaked))}")

    return {"out": out, "labels": labels, "direct_alt": shipped_direct_alt, "orphans": orphans}


def _dataset_card(args: argparse.Namespace, labels: dict, n_direct_alt: int, n_servers: int) -> str:
    def tbl(d: dict) -> str:
        return "\n".join(f"| `{k}` | {v} |" for k, v in d.items())

    repo = args.repo_id or "ORG/DynamicMCPBench"
    return f"""---
license: {args.license}
task_categories:
- other
tags:
- mcp
- agents
- tool-use
- benchmark
pretty_name: DynamicMCPBench
---

# DynamicMCPBench

Trace-native benchmark for evaluating tool-using agents on **dynamic** MCP servers.
Tasks are generated *forward*: an explorer agent drives live MCP tools into a recorded
trace, which a distiller compiles into a `TaskSpec` scored on **effects** (checkpoints,
equivalence sets, minefields, partial order) — not answer-matching. The headline error
class is the **Server Attribution Error** (right tool type, wrong server).

## Contents

| file | description |
|---|---|
| `specs.jsonl` | {labels["n_specs"]} TaskSpecs — the benchmark. |
| `traces.jsonl` | {labels["n_traces"]} reference traces — replay world for fair model comparison. |
| `labels.json` | strategy / difficulty / dynamism / scope distribution. |
| `direct_alt.json` | {n_direct_alt} reviewed cross-server equivalence groups (tool-name groupings only). |

Generated from a substrate of {n_servers} vetted MCP servers.

## Label distribution

**By generation strategy**

| strategy | n |
|---|---|
{tbl(labels["by_strategy"])}

**By difficulty (measured trace depth)**

| bin | n |
|---|---|
{tbl(labels["by_depth_bin"])}

**By dynamism**

| class | n |
|---|---|
{tbl(labels["by_dynamism"])}

**By scope**

| scope | n |
|---|---|
{tbl(labels["by_scope"])}

## Spec schema

Each row of `specs.jsonl`: `task_id`, `source_trace_id`, `prompt`, `dynamism`,
`servers_used`, `complexity` (`trace_depth`, ...), `checkpoints` (effect predicates +
`equivalence_set`), `minefields` (forbidden effects), `ordering` (partial order),
`notes`, `created_at`. Score with the `dmcp` evaluator in replay mode against
`traces.jsonl`.

## Provenance & licence

Produced by the DynamicMCPBench pipeline (`{repo}`). Released under `{args.license}`.
No credentials or environment values are included; the substrate manifest is summarised
only as aggregate counts.
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--specs", required=True)
    ap.add_argument("--traces", required=True)
    ap.add_argument("--manifest", default="manifests/servers.json")
    ap.add_argument(
        "--direct-alt", default=None, help="opt-in: ship reviewed cross-server equivalence groups"
    )
    ap.add_argument("--out", default="dist/hf")
    ap.add_argument("--repo-id", default=None, help="HF dataset repo id, e.g. ORG/DynamicMCPBench")
    ap.add_argument("--license", default="cc-by-4.0")
    ap.add_argument("--push", action="store_true", help="actually upload (needs huggingface_hub + HF_TOKEN)")
    args = ap.parse_args()

    info = build(args)
    out = info["out"]
    print(f"[release] bundle -> {out}")
    print(
        f"  specs={info['labels']['n_specs']} traces={info['labels']['n_traces']} "
        f"direct_alt={info['direct_alt']} orphans={len(info['orphans'])}"
    )
    print(f"  strategies={info['labels']['by_strategy']}")
    if info["orphans"]:
        print(f"  WARNING: {len(info['orphans'])} specs reference a missing trace")

    if not args.push:
        print("[release] dry-run (no push). Re-run with --push --repo-id ORG/NAME to publish.")
        return
    if not args.repo_id:
        raise SystemExit("--push requires --repo-id")
    from huggingface_hub import HfApi  # lazy: only needed to publish

    api = HfApi()
    api.create_repo(args.repo_id, repo_type="dataset", exist_ok=True)
    api.upload_folder(folder_path=str(out), repo_id=args.repo_id, repo_type="dataset")
    print(f"[release] pushed -> https://huggingface.co/datasets/{args.repo_id}")


if __name__ == "__main__":
    main()
