"""CR 3.4 — build the cross-model annotation package (scorer strictness).

Promised to reviewer 1npx: the human study covers one model, so we cannot yet
show the scorer's conservatism is model-independent. This builds the smallest
package that can.

What is measured. Only the conditional false-negative rate, P(human passes |
scorer failed). The pass side is already established at 95% precision on the
first pass and is not re-annotated, so every card here is a run the deterministic
scorer failed. That is where the disagreement lives and it is the only quantity
the promise needs.

Design. Three models spanning the capability range, all with complete released
candidate traces, compared against the already-annotated baseline. 90 cards per
model, six per task category so every category is covered equally, drawn with a
fixed seed. A shared reliability set goes to every rater for agreement.

Load. 270 unique cards over six raters is 45 each, plus the shared set. Against
the first pass (975 cards, about 162 per rater) that is roughly half the work,
and it asks one question per card instead of three.

    uv run python scripts/cr34_annotation_package.py --out human_eval/cr34
"""

from __future__ import annotations

import argparse
import collections
import json
import random
from pathlib import Path

REPO = "TokenWasteGroup/DynamicMCPBench"
BASELINE = "qwen3.6-35b"
# span the leaderboard: 42.5 / 22.1 / 7.2 pass^3, all with full released traces
MODELS = ["gemma4-31b", "qwen3-8b", "smollm3-3b"]
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
RATERS = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta"]


def jsonl(p: Path):
    with p.open() as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def category_of(spec: dict) -> str | None:
    goal = (spec.get("provenance") or {}).get("goal_id") or ""
    goal = goal[5:] if goal.startswith("auto-") else goal
    for c in sorted(CATEGORIES, key=len, reverse=True):
        if goal.startswith(c) or goal.startswith(c.replace("_", "-")):
            return c
    return None


def final_message(trace: dict) -> str:
    exp = (trace.get("seed_metadata") or {}).get("exploration") or {}
    return exp.get("final_message") or ""


def calls_of(trace: dict) -> list[dict]:
    return [
        {"server_id": s.get("server_id"), "tool_name": s.get("tool_name"), "arguments": s.get("arguments")}
        for s in trace.get("steps", [])
        if s.get("tool_name") and s.get("kind") == "call_tool_agent"
    ]


def pull(root: Path) -> tuple[dict, dict, dict]:
    from huggingface_hub import hf_hub_download

    def get(rel: str) -> Path:
        return Path(hf_hub_download(REPO, rel, repo_type="dataset", local_dir=str(root)))

    specs = {s["task_id"]: s for s in jsonl(get("specs.jsonl"))}
    golds = {t["trace_id"]: t for t in jsonl(get("traces.jsonl"))}
    per_model = {}
    for m in MODELS:
        v = list(jsonl(get(f"leaderboard_local_50x15/verdicts/{m}.jsonl")))
        c = {t["trace_id"]: t for t in jsonl(get(f"leaderboard_local_50x15/candidate_traces/{m}.jsonl"))}
        per_model[m] = (v, c)
    return specs, golds, per_model


def build_cards(specs, golds, per_model, per_category: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    cards: list[dict] = []
    for model, (verdicts, traces) in per_model.items():
        by_cat: dict[str, list[dict]] = collections.defaultdict(list)
        seen: set[str] = set()
        for row in verdicts:
            if row.get("passed") or row.get("repeat_index") != 0:
                continue  # scorer-FAIL runs only, first attempt, one card per task
            tid = row["task_id"]
            if tid in seen:
                continue
            spec, trace = specs.get(tid), traces.get(row.get("candidate_trace_id"))
            if spec is None or trace is None:
                continue
            seen.add(tid)
            gold = golds.get(spec.get("source_trace_id"))
            by_cat[category_of(spec)].append(
                {
                    "task_id": tid,
                    "model": model,
                    "category_claimed": category_of(spec),
                    "prompt": spec.get("prompt"),
                    "gold_calls": calls_of(gold) if gold else [],
                    "gold_answer": final_message(gold) if gold else "",
                    "model_calls": calls_of(trace),
                    "model_answer": final_message(trace),
                    "model_calls_n": len(calls_of(trace)),
                    "_auto_pass": False,
                    "ann": None,
                }
            )
        for cat in CATEGORIES:
            pool = by_cat.get(cat, [])
            rng.shuffle(pool)
            cards.extend(pool[:per_category])
    return cards


def assign(cards: list[dict], kappa_n: int, seed: int, shared_raters: int) -> dict[str, list[dict]]:
    rng = random.Random(seed)
    pool = list(cards)
    rng.shuffle(pool)
    # reliability set: spread across categories, judged by every rater
    kappa: list[dict] = []
    per_cat = max(1, kappa_n // len(CATEGORIES))
    taken: collections.Counter = collections.Counter()
    rest: list[dict] = []
    for c in pool:
        if taken[c["category_claimed"]] < per_cat and len(kappa) < kappa_n:
            kappa.append(c)
            taken[c["category_claimed"]] += 1
        else:
            rest.append(c)
    out: dict[str, list[dict]] = {r: [] for r in RATERS}
    for i, c in enumerate(rest):
        out[RATERS[i % len(RATERS)]].append({**c, "is_kappa": False})
    # the shared set goes to `shared_raters` people, not all of them: three votes
    # is enough for agreement and costs half as much as six.
    for j, c in enumerate(kappa):
        for k in range(shared_raters):
            out[RATERS[(j + k) % len(RATERS)]].append({**c, "is_kappa": True})
    for r in RATERS:
        rng.shuffle(out[r])
        for c in out[r]:
            c["rater"] = r
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="human_eval/cr34")
    ap.add_argument("--per-category", type=int, default=4)
    ap.add_argument("--kappa", type=int, default=20)
    ap.add_argument("--shared-raters", type=int, default=3)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    specs, golds, per_model = pull(out / "hf")
    cards = build_cards(specs, golds, per_model, args.per_category, args.seed)
    packs = assign(cards, args.kappa, args.seed, args.shared_raters)

    per_model_n = collections.Counter(c["model"] for c in cards)
    print(f"unique cards: {len(cards)}  {dict(per_model_n)}")
    for r, pack in packs.items():
        path = out / f"annotate_{r}.jsonl"
        with path.open("w") as fh:
            for c in pack:
                fh.write(json.dumps(c) + "\n")
        shared = sum(1 for c in pack if c["is_kappa"])
        print(f"  {r:<8} {len(pack):3d} cards ({shared} shared)")
    total = sum(len(p) for p in packs.values())
    print(f"total judgments: {total}  (unique {len(cards)} + shared {args.kappa} x {args.shared_raters})")


if __name__ == "__main__":
    main()
