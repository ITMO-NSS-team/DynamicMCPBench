#!/usr/bin/env python3
"""Measure what the retriever actually surfaces, to explain the e9.1 matrix.

The matrix says success rises with `rag-k` and that `flat` (whole catalog) is no
better than `rag:32`. Two mechanisms predict that shape and the matrix alone
cannot separate them:

  (a) retrieval-bound — small k hides the tools the task needs, and success
      tracks how often the needed tool is on screen at all;
  (b) selection-bound — the tools are on screen and the agent still fails to
      pick and drive them.

Under `--pool full` the required tools are *guaranteed* to be in the pool
(`build_eval_pool` returns `required + catalog.excluding(required)`), so `flat`
has recall 1.0 by construction. Measuring recall at each k separates the two: if
recall@32 is already high while success is not, (a) is exhausted and the residual
gap belongs to (b).

Recall is counted per checkpoint, not per tool: a `tool_effect` checkpoint is
*reachable* iff at least one member of its `equivalence_set` is exposed, since any
member satisfies it. A task is reachable iff all of its tool_effect checkpoints
are. Counting "all required tools present" would understate recall badly on specs
with large equivalence sets.

The ranking replicates `dmcp.architecture.rag_surface` exactly — same
`"name: description"` text, same cosine, same index tie-break — so these numbers
describe the surfaces the graded runs actually saw. Texts are built per task
(a required tool carries its reference trace's ToolSpec, a distractor a catalog
stub, and the two can differ) and deduplicated globally before embedding.

Scope of v0: measurement of the exposure surface. It grades nothing and runs no
agent; the only model call is the embedding of the tool texts and the prompts.

Reproduce:
    uv run python scripts/cr_recall.py --corpus hfdl --k 4,8,16,32
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
from pathlib import Path

from dmcp.architecture import cosine
from dmcp.llm import OpenRouterClient
from dmcp.manifest import Manifest
from dmcp.pools import build_eval_pool, pool_to_tool_surface
from dmcp.sampling import ToolCatalog
from dmcp.spec import TaskSpec, ToolEffectCheckpoint
from dmcp.trace import Trace

BUCKETS = ("short (1-2)", "medium (3-4)", "long (5+)")


def load_jsonl(path: str | Path) -> list[dict]:
    return [json.loads(ln) for ln in Path(path).read_text().splitlines() if ln.strip()]


async def embed_all(llm: OpenRouterClient, texts: list[str], *, batch: int = 256) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), batch):
        out.extend(await llm.embed(texts[i : i + batch]))
    return out


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="hfdl")
    ap.add_argument("--subset", default="manifests/subsets/cr150.jsonl")
    ap.add_argument("--manifest", default="manifests/servers.json")
    ap.add_argument("--k", default="4,8,16,32")
    ap.add_argument("--json-out", default="docs/experiments/data/e9.1_recall.json")
    ap.add_argument("--cache", default="evals/cr/recall_embeddings.json")
    ap.add_argument("--per-task-out", default="evals/cr/recall_per_task.json")
    args = ap.parse_args()

    ks = sorted(int(x) for x in args.k.split(","))
    corpus = Path(args.corpus)
    manifest = Manifest.load(Path(args.manifest))
    traces = [Trace.model_validate(t) for t in load_jsonl(corpus / "traces.jsonl")]
    by_trace = {t.trace_id: t for t in traces}
    catalog = ToolCatalog.from_traces(traces, manifest=manifest)

    want = {json.loads(ln)["task_id"] for ln in Path(args.subset).read_text().splitlines() if ln.strip()}
    specs = [TaskSpec.model_validate(s) for s in load_jsonl(corpus / "specs.jsonl") if s["task_id"] in want]
    depth = {tid: sum(1 for s in t.steps if s.kind == "call_tool_agent") for tid, t in by_trace.items()}

    def bucket(spec: TaskSpec) -> str:
        n = depth.get(spec.source_trace_id, 0)
        return BUCKETS[0] if n <= 2 else (BUCKETS[1] if n <= 4 else BUCKETS[2])

    print(f"{len(specs)} specs, catalog {len(catalog)} tools")

    # Build each task's surface, then embed the union of distinct texts once.
    flats: dict[str, list[tuple[str, str, str]]] = {}  # task -> [(server, tool, text)]
    for s in specs:
        ref = by_trace.get(s.source_trace_id)
        surface = pool_to_tool_surface(
            build_eval_pool(s, catalog, mode="full"), ref.tool_specs if ref else {}
        )
        flats[s.task_id] = [
            (sid, t.name, f"{t.name}: {(t.description or '').strip()}".strip())
            for sid, ts in surface.items()
            for t in ts
        ]

    texts = sorted({txt for f in flats.values() for _, _, txt in f})
    prompts = [s.prompt for s in specs]

    # Embeddings are deterministic for a fixed model, so cache them: re-running the
    # analysis then costs nothing and cannot silently drift onto a different model.
    cache_path = Path(args.cache)
    cache: dict[str, list[float]] = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    missing = [t for t in {*texts, *prompts} if t not in cache]
    if missing:
        llm = OpenRouterClient()
        print(f"embedding {len(missing)} new texts ({len(cache)} cached)…")
        cache.update(zip(missing, await embed_all(llm, missing), strict=True))
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache))
    else:
        print(f"all {len(cache)} embeddings cached")
    vec_of = cache
    prompt_vecs = [cache[p] for p in prompts]

    # k -> task_id -> (reachable_checkpoints, total, fully_reachable)
    per_k: dict[int, dict[str, tuple[int, int, bool]]] = {k: {} for k in ks}
    for spec, pv in zip(specs, prompt_vecs, strict=True):
        flat = flats[spec.task_id]
        ranked = sorted(range(len(flat)), key=lambda i: (-cosine(pv, vec_of[flat[i][2]]), i))
        cps = [cp for cp in spec.checkpoints if isinstance(cp, ToolEffectCheckpoint)]
        for k in ks:
            shown = {(flat[i][0], flat[i][1]) for i in ranked[:k]}
            hit = sum(1 for cp in cps if any((r.server_id, r.tool_name) in shown for r in cp.equivalence_set))
            # A spec with no tool_effect checkpoints demands no particular tool, so
            # retrieval cannot gate it. Vacuously reachable, not unreachable.
            per_k[k][spec.task_id] = (hit, len(cps), hit == len(cps))

    out: dict[str, dict] = {}
    print(f"\n{'k':>5} {'checkpoint recall':>18} {'tasks fully reachable':>23}")
    print("-" * 49)
    for k in ks:
        rows = list(per_k[k].values())
        hit, tot = sum(h for h, _, _ in rows), sum(t for _, t, _ in rows)
        full = sum(1 for _, _, f in rows if f)
        by_bucket = {}
        for b in BUCKETS:
            sel = [per_k[k][s.task_id] for s in specs if bucket(s) == b]
            if sel:
                by_bucket[b] = round(100 * sum(h for h, _, _ in sel) / sum(t for _, t, _ in sel), 1)
        out[str(k)] = {
            "checkpoint_recall": round(100 * hit / tot, 1),
            "tasks_fully_reachable": round(100 * full / len(rows), 1),
            "checkpoint_recall_by_bucket": by_bucket,
            "checkpoints": tot,
            "tasks": len(rows),
        }
        print(f"{k:>5} {100 * hit / tot:17.1f}% {100 * full / len(rows):22.1f}%   {by_bucket}")
    print(f"{'flat':>5} {100.0:17.1f}% {100.0:22.1f}%   (guaranteed by --pool full)")

    # `hier` exposes exactly one server's tools, so a task whose checkpoints cannot
    # all be satisfied from a single server is unreachable under it no matter how
    # good the router is. That ceiling is a property of the tasks alone: compute it
    # with an oracle router that always picks the best possible server.
    oracle: dict[str, bool] = {}
    servers_needed: list[int] = []
    for s in specs:
        cps = [cp for cp in s.checkpoints if isinstance(cp, ToolEffectCheckpoint)]
        per_cp = [{r.server_id for r in cp.equivalence_set} for cp in cps]
        oracle[str(s.task_id)] = bool(per_cp) and bool(set.intersection(*per_cp))
        servers_needed.append(len({sid for opts in per_cp for sid in opts}))
    ceiling = 100 * sum(oracle.values()) / len(oracle)
    print(f"\nhier ceiling with an oracle router (single server suffices): {ceiling:.1f}% of tasks")
    for b in BUCKETS:
        sel = [oracle[str(s.task_id)] for s in specs if bucket(s) == b]
        if sel:
            print(f"    {b:14} {100 * sum(sel) / len(sel):5.1f}%")
    spread = collections.Counter(servers_needed)
    print(f"    distinct servers a task can draw on: {dict(sorted(spread.items()))}")
    out["hier_oracle_ceiling"] = {
        "tasks_single_server_sufficient_pct": round(ceiling, 1),
        "by_bucket": {
            b: round(
                100
                * sum(oracle[str(s.task_id)] for s in specs if bucket(s) == b)
                / max(1, sum(1 for s in specs if bucket(s) == b)),
                1,
            )
            for b in BUCKETS
        },
    }

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(out, indent=2))
        print(f"\nwrote {args.json_out}")
    if args.per_task_out:
        Path(args.per_task_out).write_text(
            json.dumps({str(k): {str(t): v[2] for t, v in per_k[k].items()} for k in ks}, indent=2)
        )
        print(f"wrote {args.per_task_out}")


if __name__ == "__main__":
    asyncio.run(main())
