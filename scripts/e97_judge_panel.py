"""E9.7 — Tier-2 override rates per category, across judge families.

Camera-ready item 3.2, promised to reviewers 1npx and RJAT: "we will replay them
through several judge families and report per-category rates".

Replays every Tier-1 `tool_effect` failure in the released leaderboards through a
panel of judge models, holding the prompt and the schema fixed so the only thing
that varies is the judge family. The prompt below is copied verbatim from
`dmcp/judge.py` so the panel is comparable to the paper's own configuration.

Panel design. Three of the four families authored no part of the corpus (its
goals, explorations, distillations and validations came from openai, qwen,
anthropic, deepseek, z-ai, moonshotai and minimax) and all three have open
weights, so the panel is reproducible without a paid key. The paper's default
judge is included as the reference point.

Task category is recovered from `provenance.goal_id` in the released specs, which
resolves 750/750 on the evaluation slice at exactly 50 per category.

Output is one JSONL row per (judge, model, task, repeat, checkpoint), written
incrementally; re-running skips work already present, so the run is resumable.

    python e97_judge_panel.py --out /workspace/e97 --concurrency 24
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
import time
from pathlib import Path

CATEGORIES = [
    "ambiguous_intent",
    "complementary",
    "cross_domain",
    "cross_server_alt",
    "decoy",
    "destructive_adjacent",
    "hard_neg",
    "homonym_trap",
    "long_similar_chain",
    "prerequisite_strict",
    "random",
    "recovery_required",
    "same_name",
    "sibling",
    "stratified",
]

# Verbatim from dmcp/judge.py — the panel must vary only the family.
JUDGE_SYSTEM = """
You are an effect-equivalence judge for an agent benchmark.

You will be shown:
  - one *failed* tool_effect checkpoint that the candidate did not satisfy
    by the deterministic rule
  - the candidate's full list of successful tool calls (server, tool, args,
    short result preview)

Your job is to decide ONE binary question:

  Did the candidate achieve the same *effect* the checkpoint requires,
  via any path (different tool, different arguments, different sequence)?

Decision rules:
  - The default answer is NO. Only say YES when the candidate trace clearly
    contains evidence that the required effect was produced.
  - "Equivalent effect" means: an external observer of the world would not
    be able to tell whether the candidate took the reference path or an
    alternative path — the same fact was retrieved, the same record was
    created, the same state was mutated.
  - The candidate's final natural-language summary is NOT evidence on its
    own. You need to see a corresponding tool call.
  - For checkpoints whose arg_predicate names a specific value (e.g. a
    repo_path, a timezone), be strict: a different value usually means a
    different effect.

Call the `emit_equivalence_judgment` tool exactly once with your decision.
""".strip()

JUDGE_TOOL = {
    "type": "function",
    "function": {
        "name": "emit_equivalence_judgment",
        "description": "Emit the binary equivalence decision for one failed checkpoint.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["equivalent", "reason"],
            "properties": {
                "equivalent": {"type": "boolean"},
                "reason": {"type": "string"},
                "candidate_step_id": {"type": ["integer", "null"]},
            },
        },
    },
}

PANEL = [
    ("anthropic/claude-haiku-4.5", "reference: the paper's default judge"),
    ("google/gemma-4-26b-a4b-it", "open weights, authored no part of the corpus"),
    ("mistralai/mistral-small-3.2-24b-instruct", "open weights, authored no part of the corpus"),
    ("meta-llama/llama-3.3-70b-instruct", "open weights, authored no part of the corpus"),
]

REPO = "TokenWasteGroup/DynamicMCPBench"
API = "https://openrouter.ai/api/v1/chat/completions"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def category_of(spec: dict) -> str | None:
    goal = (spec.get("provenance") or {}).get("goal_id") or ""
    goal = goal[5:] if goal.startswith("auto-") else goal
    for c in sorted(CATEGORIES, key=len, reverse=True):
        if goal.startswith(c) or goal.startswith(c.replace("_", "-")):
            return c
    return None


def jsonl(path: Path):
    with path.open() as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def fetch_corpus(root: Path) -> tuple[dict, list[tuple[str, Path, Path]]]:
    """Pull specs, verdicts and candidate traces; return specs and per-model file pairs."""
    from huggingface_hub import HfApi, hf_hub_download

    files = HfApi().list_repo_files(REPO, repo_type="dataset")
    want = [f for f in files if f == "specs.jsonl" or "/verdicts/" in f or "candidate_traces" in f]
    log(f"pulling {len(want)} files from the release")
    local: dict[str, Path] = {}
    for f in want:
        local[f] = Path(hf_hub_download(REPO, f, repo_type="dataset", local_dir=str(root)))

    specs = {s["task_id"]: s for s in jsonl(local["specs.jsonl"])}
    pairs: list[tuple[str, Path, Path]] = []
    for f, p in local.items():
        if "/verdicts/" not in f:
            continue
        board = f.split("/")[0]
        model = Path(f).stem.replace("evals_", "")
        for cand, cp in local.items():
            same = Path(cand).stem.replace("ctraces_", "") == model
            if board in cand and "candidate_traces" in cand and same:
                pairs.append((model, p, cp))
                break
    log(f"{len(specs)} specs, {len(pairs)} models with both verdicts and traces")
    return specs, pairs


def build_worklist(specs: dict, pairs) -> list[dict]:
    """Every Tier-1 tool_effect failure whose candidate trace was released."""
    work: list[dict] = []
    for model, vpath, cpath in pairs:
        traces = {t["trace_id"]: t for t in jsonl(cpath)}
        for row in jsonl(vpath):
            trace = traces.get(row.get("candidate_trace_id"))
            spec = specs.get(row["task_id"])
            if trace is None or spec is None:
                continue
            calls = [
                {
                    "step_id": s.get("step_id"),
                    "server_id": s.get("server_id"),
                    "tool_name": s.get("tool_name"),
                    "arguments": s.get("arguments"),
                    "result_preview": _preview(s),
                }
                for s in trace.get("steps", [])
                if s.get("tool_name") and s.get("status") == "success"
            ]
            by_id = {c.get("checkpoint_id"): c for c in spec.get("checkpoints", [])}
            for cp in row.get("checkpoint_results", []):
                if cp.get("kind") != "tool_effect" or cp.get("passed"):
                    continue
                work.append(
                    {
                        "model": model,
                        "task_id": row["task_id"],
                        "repeat": row.get("repeat_index"),
                        "checkpoint_id": cp.get("checkpoint_id"),
                        "category": category_of(spec),
                        "checkpoint": by_id.get(cp.get("checkpoint_id")),
                        "tier1_reason": cp.get("reason"),
                        "calls": calls,
                    }
                )
    return work


def _preview(step: dict, limit: int = 600) -> str:
    res = step.get("result") or {}
    content = res.get("content") or []
    parts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
    return ("\n".join(parts) if parts else json.dumps(res, default=str))[:limit]


def user_prompt(item: dict) -> str:
    return json.dumps(
        {
            "failed_checkpoint": item["checkpoint"],
            "tier1_reason": item["tier1_reason"],
            "candidate_successful_calls": item["calls"],
        },
        default=str,
    )[:60000]


async def judge_one(client, judge: str, item: dict, key: str, sem) -> dict | None:
    body = {
        "model": judge,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": user_prompt(item)},
        ],
        "tools": [JUDGE_TOOL],
        "tool_choice": {"type": "function", "function": {"name": "emit_equivalence_judgment"}},
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    async with sem:
        for attempt in range(6):
            try:
                r = await client.post(API, json=body, headers=headers, timeout=120)
                if r.status_code in (429, 500, 502, 503, 504):
                    await asyncio.sleep(min(60, 2**attempt) + random.random())
                    continue
                data = r.json()
                if "error" in data:
                    await asyncio.sleep(min(60, 2**attempt) + random.random())
                    continue
                tc = (data["choices"][0]["message"] or {}).get("tool_calls")
                if not tc:
                    return {**_key(item), "judge": judge, "ok": False, "why": "no_tool_call"}
                args = json.loads(tc[0]["function"]["arguments"])
                return {
                    **_key(item),
                    "judge": judge,
                    "ok": True,
                    "equivalent": bool(args.get("equivalent")),
                    "reason": (args.get("reason") or "")[:300],
                    "tokens": (data.get("usage") or {}).get("total_tokens"),
                }
            except Exception as exc:  # noqa: BLE001 - retried, then recorded
                if attempt == 5:
                    return {**_key(item), "judge": judge, "ok": False, "why": type(exc).__name__}
                await asyncio.sleep(min(60, 2**attempt) + random.random())
    return None


def stratify(work: list[dict], per_category: int, seed: int = 0) -> list[dict]:
    """Cap each category at `per_category` items, spread evenly across models.

    The same sample goes to every judge, so the cross-family comparison is paired.
    Deterministic given the seed, so the run is reproducible and resumable.
    """
    if not per_category:
        return work
    rng = random.Random(seed)
    by_cat: dict[str, dict[str, list[dict]]] = {}
    for w in work:
        by_cat.setdefault(w["category"], {}).setdefault(w["model"], []).append(w)
    out: list[dict] = []
    for cat in sorted(by_cat):
        buckets = by_cat[cat]
        for items in buckets.values():
            rng.shuffle(items)
        picked: list[dict] = []
        i = 0
        while len(picked) < per_category:
            drained = True
            for model in sorted(buckets):
                items = buckets[model]
                if i < len(items):
                    picked.append(items[i])
                    drained = False
                    if len(picked) >= per_category:
                        break
            if drained:
                break
            i += 1
        out.extend(picked)
    return out


def _key(item: dict) -> dict:
    return {
        "model": item["model"],
        "task_id": item["task_id"],
        "repeat": item["repeat"],
        "checkpoint_id": item["checkpoint_id"],
        "category": item["category"],
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/workspace/e97")
    ap.add_argument("--concurrency", type=int, default=24)
    ap.add_argument("--per-category", type=int, default=300, help="cap per category; 0 = full census")
    ap.add_argument("--limit", type=int, default=0, help="hard cap per judge, for smoke tests")
    args = ap.parse_args()

    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        sys.exit("OPENROUTER_API_KEY is not set")

    import httpx

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    specs, pairs = fetch_corpus(out / "hf")
    work = build_worklist(specs, pairs)
    n_models = len({w["model"] for w in work})
    log(f"population: {len(work)} failed tool_effect checkpoints across {n_models} models")
    work = stratify(work, args.per_category)
    n_cat = len({w["category"] for w in work})
    log(f"work list after stratification: {len(work)} items over {n_cat} categories")

    results = out / "judgments.jsonl"
    done = set()
    if results.exists():
        for r in jsonl(results):
            done.add((r["judge"], r["model"], r["task_id"], r["repeat"], r["checkpoint_id"]))
        log(f"resuming: {len(done)} judgments already on disk")

    sem = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient() as client:
        for judge, why in PANEL:

            def pending(w, j=judge):
                return (j, w["model"], w["task_id"], w["repeat"], w["checkpoint_id"]) not in done

            todo = [w for w in work if pending(w)]
            if args.limit:
                todo = todo[: args.limit]
            log(f"judge {judge} ({why}): {len(todo)} calls")
            written = 0
            with results.open("a") as fh:
                for i in range(0, len(todo), 500):
                    chunk = todo[i : i + 500]
                    for res in await asyncio.gather(*(judge_one(client, judge, w, key, sem) for w in chunk)):
                        if res:
                            fh.write(json.dumps(res) + "\n")
                            written += 1
                    fh.flush()
                    log(f"  {judge}: {written}/{len(todo)}")
            log(f"judge {judge} done: {written} judgments")
    log("ALL DONE")


if __name__ == "__main__":
    asyncio.run(main())
