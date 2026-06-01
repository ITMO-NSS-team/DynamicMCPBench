"""Reproducer for e1.4a — does persona seeding raise goal diversity?

Runs goal generation in both conditions (persona-seeded vs free-form) over
several seeds on a set of read-only servers, then scores each goal set on:

  - PRIMARY  : semantic intent diversity = (# distinct user intents) / (# goals),
               judged by an LLM (OpenRouter, temperature 0). Directly tests
               whether personas diversify *intent* — the signal the lexical
               metric missed in the E1.4 null result.
  - SECONDARY: lexical diversity (dmcp.personas.diversity_score).

Decision rule (pre-registered): on the PRIMARY metric, persona-seeding is
positive iff its seed-mean exceeds free-form with non-overlapping ±stdev bands;
otherwise neutral (or negative if free-form is higher beyond the bands). With
only 3 seeds the ±stdev band is a rough CI proxy — reported as such.

Run: uv run python docs/experiments/e1.4a_run.py   (needs OPENROUTER_API_KEY)
"""

from __future__ import annotations

import asyncio
import re
import statistics
from pathlib import Path

from dmcp.goal_gen import generate_goals
from dmcp.llm import OpenRouterClient
from dmcp.manifest import Manifest
from dmcp.personas import diversity_score

CANDIDATE_SERVERS = ["time", "fetch", "wikipedia", "arxiv"]
SEEDS = [0, 1, 2]
PER_SERVER = 4

INTENT_SYS = (
    "You assess intent diversity for a set of user goals. Two goals share an "
    "intent if they ask for essentially the same kind of task/result, even when "
    "worded differently. Count how many DISTINCT intents the set contains."
)


async def intent_ratio(goals: list[str], llm: OpenRouterClient) -> float:
    """Distinct-intent ratio in (0, 1]: distinct intents / number of goals."""
    if len(goals) < 2:
        return 0.0
    listed = "\n".join(f"{i + 1}. {g}" for i, g in enumerate(goals))
    resp = await llm.chat(
        messages=[
            {"role": "system", "content": INTENT_SYS},
            {
                "role": "user",
                "content": (
                    f"Reply with ONLY an integer — the number of distinct intents "
                    f"among these {len(goals)} goals:\n{listed}"
                ),
            },
        ],
        temperature=0.0,
        max_tokens=8,
    )
    m = re.search(r"\d+", resp.content or "")
    k = int(m.group()) if m else len(goals)
    return min(max(k, 1), len(goals)) / len(goals)


async def main() -> None:
    manifest = Manifest.load(Path("manifests/local.json"))
    have = {e.server_id for e in manifest.servers}
    servers = [s for s in CANDIDATE_SERVERS if s in have]
    llm = OpenRouterClient()
    results: dict[bool, list[tuple[int, float, float]]] = {True: [], False: []}

    for seed in SEEDS:
        for use_p in (True, False):
            try:
                g = await generate_goals(
                    manifest=manifest,
                    server_ids=servers,
                    llm=llm,
                    single_per_server=PER_SERVER,
                    cross_pairs=0,
                    seed=seed,
                    use_personas=use_p,
                )
            except Exception as exc:
                print(f"seed={seed} personas={use_p} ERROR {type(exc).__name__}: {exc}")
                continue
            texts = [entry.goal for entry in g.entries if entry.goal]
            lex = diversity_score(texts)
            intent = await intent_ratio(texts, llm)
            results[use_p].append((len(texts), lex, intent))
            print(f"seed={seed} personas={use_p} n={len(texts)} lexical={lex:.4f} intent={intent:.4f}")

    def summarize(idx: int, use_p: bool) -> tuple[float, float]:
        vals = [r[idx] for r in results[use_p]]
        if not vals:
            return 0.0, 0.0
        return statistics.mean(vals), (statistics.pstdev(vals) if len(vals) > 1 else 0.0)

    print("\n=== summary (mean ± stdev over seeds) ===")
    print(f"servers used: {servers}  seeds: {SEEDS}  per_server: {PER_SERVER}")
    for label, idx in (("intent (PRIMARY)", 2), ("lexical (secondary)", 1)):
        pm, ps = summarize(idx, True)
        fm, fs = summarize(idx, False)
        if pm - ps > fm + fs:
            verdict = "POSITIVE (persona > free)"
        elif fm - fs > pm + ps:
            verdict = "NEGATIVE (free > persona)"
        else:
            verdict = "NEUTRAL (bands overlap)"
        print(f"{label:22s} persona={pm:.4f}±{ps:.4f}  free={fm:.4f}±{fs:.4f}  -> {verdict}")


if __name__ == "__main__":
    asyncio.run(main())
