#!/usr/bin/env python3
"""E8.0a: cost-calibration runner — picks the leaderboard pool by measured $/spec.

Per-model: shells `dmcp eval --replay` over N specs from a fixed corpus, captures
EvaluationResult.summary.cost (E8.1), then extrapolates to {leaderboard, corpus}
× pass^k ∈ {1, 3, 5} using the *live* OpenRouter price table (with the static
PRICES table as a pinned fallback). Output is a markdown ranking + numbers JSON
+ a Pareto-frontier "recommended subset" the user can plug straight back into
build_corpus / run_leaderboard.

Calibration vs. headline runs: the calibration spend is deliberate and small
(N=10 × 10 models ≈ $2-8 at the user's redacted-pool prices). The script is
also `--skip-eval` aware so the aggregator can be re-run over an existing
calibration directory without spending again.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dmcp.openrouter_prices import (  # noqa: E402
    DEFAULT_CACHE_PATH,
    LivePrice,
    fetch_live,
    get_effective_price,
    load_cache,
)

DMCP = str(ROOT / ".venv" / "bin" / "dmcp")
if not Path(DMCP).exists():
    DMCP = "dmcp"

# The user-redacted pool (2026-06-04): mid-frontier anchor + cheap-skewed
# value tiers; tested per pool member, recommendation emerges from the Pareto.
DEFAULT_POOL: tuple[str, ...] = (
    "anthropic/claude-sonnet-4.6",  # A. Mid frontier anchor
    "minimax/minimax-m3",  # B. Large cheap
    "qwen/qwen3.7-max",  # B. Large cheap (qwen3.6 if/when live)
    "z-ai/glm-5.1",  # B. Large cheap (BFCL-v3 tool-use leader)
    "moonshotai/kimi-k2.6",  # C. Tool specialist
    "qwen/qwen3-coder-plus",  # C. Tool specialist
    "anthropic/claude-haiku-4.5",  # D. Small fast
    "google/gemini-3.1-flash",  # D. Small fast
    "deepseek/deepseek-v3.1",  # E. Open value
    "meta-llama/llama-3.3-70b-instruct",  # E. Open value
)

# E8.0b free-endpoint pool (user 2026-06-04). Run these first; layer paid
# OpenRouter models on top only for capabilities the free pool can't cover.
FREE_POOL: tuple[str, ...] = (
    "deepseek-v4-pro",
    "kimi-k2p6",
    "kimi-k2p5",
    "glm-5p1",
    "gpt-oss-120b",
    "minimax-m2p7",
)

DEFAULT_CORPUS_SIZES: tuple[int, ...] = (600, 1100)  # E8.8 leaderboard / E8.7 full
DEFAULT_PASS_K: tuple[int, ...] = (1, 3, 5)


def _slug(s: str) -> str:
    return s.replace("/", "_").replace(":", "_").replace(".", "-")


def _run(cmd: list[str], *, env_override: dict[str, str] | None = None) -> int:
    print("+ " + " ".join(cmd), flush=True)
    env = None
    if env_override:
        import os as _os

        env = _os.environ.copy()
        env.update(env_override)
    return subprocess.run(cmd, check=False, env=env).returncode


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * (pct / 100.0)
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return float(s[int(k)])
    return float(s[lo] + (s[hi] - s[lo]) * (k - lo))


def _per_model_metrics(rows: list[dict], live: dict[str, LivePrice]) -> dict[str, Any]:
    """Per-spec mean cost / tokens / latency; per-run accuracy.

    Cost is taken from `summary.cost.cost_usd` when the row has it; otherwise
    recomputed against the live price table from `prompt_tokens + completion_tokens`
    (which is how a `--skip-eval` re-aggregate over a stale fixture stays honest
    when prices have changed since the run).
    """
    if not rows:
        return {
            "runs": 0,
            "passed": 0,
            "accuracy": 0.0,
            "mean_cost_usd": 0.0,
            "mean_prompt_tokens": 0,
            "mean_completion_tokens": 0,
            "latency_p50_ms": 0.0,
            "latency_p95_ms": 0.0,
            "unknown_price": False,
        }
    n = len(rows)
    passed = sum(1 for r in rows if r.get("passed"))
    total_cost = 0.0
    total_in = total_out = 0
    latencies: list[float] = []
    unknown = False
    for r in rows:
        model = r.get("candidate_model") or ""
        cost_block = (r.get("summary") or {}).get("cost") or {}
        pin = int(cost_block.get("prompt_tokens") or 0)
        pout = int(cost_block.get("completion_tokens") or 0)
        total_in += pin
        total_out += pout
        latencies.extend(float(x) for x in (cost_block.get("latencies_ms") or []))
        # Recompute against live to stay honest under price rotation.
        if get_effective_price(model, live) is None and (pin or pout):
            unknown = True
        from dmcp.openrouter_prices import compute_cost_usd

        total_cost += compute_cost_usd(model, pin, pout, live)
    return {
        "runs": n,
        "passed": passed,
        "accuracy": passed / n,
        "mean_cost_usd": total_cost / n,
        "mean_prompt_tokens": total_in // n,
        "mean_completion_tokens": total_out // n,
        "latency_p50_ms": round(_percentile(latencies, 50), 1),
        "latency_p95_ms": round(_percentile(latencies, 95), 1),
        "unknown_price": unknown,
    }


def extrapolate(
    metrics: dict[str, Any],
    *,
    corpus_sizes: tuple[int, ...] = DEFAULT_CORPUS_SIZES,
    pass_k: tuple[int, ...] = DEFAULT_PASS_K,
) -> list[dict[str, Any]]:
    """Projected $ + $/correct per (corpus_size, pass_k) cell.

    Naive multiplier: total_$ = mean_cost_usd × corpus_size × pass_k. accuracy
    is held constant across the corpus (the calibration sample is from the
    same distribution as the full corpus); $/correct = total_$ / (corpus_size
    × accuracy) when accuracy > 0 else None.
    """
    out: list[dict[str, Any]] = []
    mc = float(metrics["mean_cost_usd"])
    acc = float(metrics["accuracy"])
    for size in corpus_sizes:
        for k in pass_k:
            total = mc * size * k
            correct = size * acc
            out.append(
                {
                    "corpus_size": size,
                    "pass_k": k,
                    "projected_usd": round(total, 4),
                    "projected_correct": round(correct, 2),
                    "projected_usd_per_correct": round(total / correct, 4) if correct > 0 else None,
                }
            )
    return out


def _pareto_frontier(per_model: list[dict[str, Any]]) -> list[str]:
    """Models on the accuracy-vs-$/spec Pareto frontier — the recommended subset.

    Sort by $/spec ascending; keep a model only when its accuracy beats every
    cheaper model. Includes the cheapest model unconditionally so the floor
    is always represented.
    """
    rows = sorted(per_model, key=lambda r: r["mean_cost_usd"])
    frontier: list[str] = []
    best_acc = -1.0
    for r in rows:
        if r["accuracy"] > best_acc:
            frontier.append(r["model"])
            best_acc = r["accuracy"]
    return frontier


def render_markdown(payload: dict[str, Any]) -> str:
    rows = payload["models"]
    if not rows:
        return "# Cost calibration\n\n_No per-model rows yet._\n"
    frontier = set(payload.get("recommended_subset") or [])
    lines = [
        "# Cost calibration",
        "",
        f"N = {payload['sample_size']} spec(s) per model · pool = {payload['n_models']} models",
        f"live prices fetched: {payload.get('live_price_count', 0)} models",
        "",
        "## Per-model measured cost",
        "",
        "| model | runs | acc | $/spec | p_in | p_out | p50 ms | p95 ms | on frontier |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(rows, key=lambda r: r["mean_cost_usd"]):
        warn = " ⚠ price unknown" if r.get("unknown_price") else ""
        on = "★" if r["model"] in frontier else ""
        lines.append(
            f"| `{r['model']}`{warn} | {r['runs']} | {r['accuracy'] * 100:.1f}% | "
            f"${r['mean_cost_usd']:.5f} | {r['mean_prompt_tokens']} | "
            f"{r['mean_completion_tokens']} | {r['latency_p50_ms']:.0f} | "
            f"{r['latency_p95_ms']:.0f} | {on} |"
        )
    if payload.get("extrapolation"):
        lines += ["", "## Extrapolated total $ per (corpus × pass^k)", ""]
        sizes = sorted({c["corpus_size"] for r in rows for c in r["extrapolation"]})
        ks = sorted({c["pass_k"] for r in rows for c in r["extrapolation"]})
        header_cells = [f"{s}×k{k}" for s in sizes for k in ks]
        lines.append("| model | " + " | ".join(header_cells) + " |")
        lines.append("|---|" + "|".join(["---"] * len(header_cells)) + "|")
        for r in sorted(rows, key=lambda r: r["mean_cost_usd"]):
            by_cell = {(c["corpus_size"], c["pass_k"]): c["projected_usd"] for c in r["extrapolation"]}
            row_cells = [f"${by_cell.get((s, k), 0):.2f}" for s in sizes for k in ks]
            lines.append(f"| `{r['model']}` | " + " | ".join(row_cells) + " |")
        # Pool total per cell — what we'd actually spend running the WHOLE pool.
        lines.append("")
        lines.append("### Pool total $ (sum across all models)")
        lines.append("")
        lines.append("| corpus × pass^k | pool total $ |")
        lines.append("|---|---|")
        for s in sizes:
            for k in ks:
                tot = sum(
                    next(
                        (
                            c["projected_usd"]
                            for c in r["extrapolation"]
                            if c["corpus_size"] == s and c["pass_k"] == k
                        ),
                        0,
                    )
                    for r in rows
                )
                lines.append(f"| {s} × k{k} | ${tot:.2f} |")
    if frontier:
        lines += ["", "## Recommended subset (Pareto frontier)", ""]
        for m in sorted(frontier):
            lines.append(f"- `{m}`")
    return "\n".join(lines) + "\n"


def aggregate(
    cells: dict[str, list[dict]],
    live: dict[str, LivePrice],
    *,
    corpus_sizes: tuple[int, ...] = DEFAULT_CORPUS_SIZES,
    pass_k: tuple[int, ...] = DEFAULT_PASS_K,
) -> dict[str, Any]:
    """Compose per-model metrics + extrapolation + frontier into the payload."""
    per_model: list[dict[str, Any]] = []
    for model, rows in cells.items():
        m = _per_model_metrics(rows, live)
        m["model"] = model
        m["extrapolation"] = extrapolate(m, corpus_sizes=corpus_sizes, pass_k=pass_k)
        per_model.append(m)
    frontier = _pareto_frontier(per_model) if per_model else []
    sample_size = max((m["runs"] for m in per_model), default=0)
    return {
        "models": per_model,
        "n_models": len(per_model),
        "sample_size": sample_size,
        "live_price_count": len(live),
        "extrapolation": True,
        "recommended_subset": frontier,
    }


def _eval_cmd(
    *,
    specs: Path,
    manifest: Path,
    model: str,
    reference_traces: Path,
    pool: str,
    p_alt: float,
    pool_size: int,
    budget: int,
    out_path: Path,
) -> list[str]:
    """Single-model `dmcp eval --replay` invocation for one calibration cell."""
    return [
        DMCP,
        "eval",
        str(specs),
        "-m",
        str(manifest),
        "--model",
        model,
        "--replay",
        "--reference-traces",
        str(reference_traces),
        "--pool",
        pool,
        "--p-alt",
        str(p_alt),
        "--pool-size",
        str(pool_size),
        "--budget",
        str(budget),
        "-o",
        str(out_path),
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--models",
        default=",".join(DEFAULT_POOL),
        help="Comma-separated model ids (default: the user-redacted 10-model pool).",
    )
    ap.add_argument(
        "--free-pool",
        action="store_true",
        help=("Shortcut: use the FREE_POOL (E8.0b) instead of --models; ignored if --models is set."),
    )
    ap.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help=(
            "Run up to N model cells in parallel, each pinned to a different "
            "provider API key (auto-discovered from FREE_MODELS_API_KEY[_2,_3,...] / "
            "OPENROUTER_API_KEY[_2,_3,...]). Default 1 = sequential."
        ),
    )
    ap.add_argument("--n", type=int, default=10, help="Specs per model.")
    ap.add_argument("--specs", default="specs/v3.jsonl", help="Source TaskSpec JSONL.")
    ap.add_argument(
        "--reference-traces",
        default="traces/v3.jsonl",
        help="Reference traces JSONL for replay.",
    )
    ap.add_argument("--manifest", default="manifests/servers.json")
    ap.add_argument("--pool", default="target", help="Pool mode for eval.")
    ap.add_argument("--p-alt", type=float, default=0.5)
    ap.add_argument("--pool-size", type=int, default=8)
    ap.add_argument("--budget", type=int, default=12)
    ap.add_argument(
        "--corpus-sizes",
        default=",".join(str(s) for s in DEFAULT_CORPUS_SIZES),
        help="Comma-separated corpus sizes to extrapolate to.",
    )
    ap.add_argument(
        "--pass-k",
        default=",".join(str(k) for k in DEFAULT_PASS_K),
        help="Comma-separated pass^k values.",
    )
    ap.add_argument("--out", default="reports/cost_calibration", help="Per-cell eval directory.")
    ap.add_argument("--report", default=None, help="Markdown path (default: <out>/cost_calibration.md).")
    ap.add_argument("--json", default=None, help="Numbers JSON path.")
    ap.add_argument(
        "--prices-cache",
        default=str(DEFAULT_CACHE_PATH),
        help="Path for the live-price cache (read+write).",
    )
    ap.add_argument(
        "--no-live-prices",
        action="store_true",
        help=("Skip the OpenRouter fetch; use whatever's already in the cache (or fall back to static)."),
    )
    ap.add_argument(
        "--skip-eval",
        action="store_true",
        help="Skip the dmcp eval dispatch; aggregate over existing eval_<model>.jsonl files only.",
    )
    a = ap.parse_args()

    cache_path = Path(a.prices_cache)
    if a.no_live_prices:
        live = load_cache(cache_path)
        print(f"[prices] using cache: {len(live)} live prices from {cache_path}")
    else:
        try:
            live = fetch_live(cache_path=cache_path)
            print(f"[prices] fetched {len(live)} live prices → {cache_path}")
        except Exception as e:
            print(f"[prices] live fetch failed ({e}); falling back to cache + static")
            live = load_cache(cache_path)

    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    # `--free-pool` is a convenience for the E8.0b run; respects an explicit
    # `--models` so a user mixing the two can still override.
    if a.free_pool and a.models == ",".join(DEFAULT_POOL):
        models = list(FREE_POOL)
    else:
        models = [m for m in a.models.split(",") if m]
    corpus_sizes = tuple(int(s) for s in a.corpus_sizes.split(",") if s)
    pass_k = tuple(int(k) for k in a.pass_k.split(",") if k)

    # Pre-stage the spec subset once before any parallel cell needs it
    # (avoids racing N processes writing the same file).
    specs_subset = out_dir / f"specs_subset_n{a.n}.jsonl"
    if not a.skip_eval and not specs_subset.exists():
        src = Path(a.specs).read_text(encoding="utf-8").splitlines()
        head = [line for line in src if line.strip()][: a.n]
        specs_subset.write_text("\n".join(head) + "\n", encoding="utf-8")

    # Discover concurrency lanes — one key per parallel cell. We pin a single
    # provider per calibration call (homogeneous pool: free or paid), so we
    # ask the registry for the first model's provider and reuse its key pool.
    # Parent process must load .env explicitly — dmcp.llm only does so inside
    # the subprocess, which is too late for us to read here.
    keys: list[str] = []
    key_env_var = ""
    if not a.skip_eval and models:
        sys.path.insert(0, str(ROOT))
        from dotenv import load_dotenv

        from dmcp.providers import pool_keys, resolve

        load_dotenv(override=False)
        provider = resolve(models[0])
        key_env_var = provider.api_key_env
        keys = pool_keys(provider)
        if not keys:
            raise SystemExit(f"no API keys found for provider {provider.name!r} (env {key_env_var})")
    requested = max(1, int(a.concurrency))
    lanes = max(1, min(requested, len(keys) or requested))
    if requested > lanes and keys:
        print(f"[warn] requested --concurrency {requested} but only {lanes} key(s) configured; capping")

    def _cell(model: str, key: str) -> tuple[str, int]:
        eval_path = out_dir / f"eval_{_slug(model)}.jsonl"
        cmd = _eval_cmd(
            specs=specs_subset,
            manifest=Path(a.manifest),
            model=model,
            reference_traces=Path(a.reference_traces),
            pool=a.pool,
            p_alt=a.p_alt,
            pool_size=a.pool_size,
            budget=a.budget,
            out_path=eval_path,
        )
        # Pin THIS subprocess to one specific key — overrides the .env value
        # so parallel cells don't share an account-level rate limit.
        env_override = {key_env_var: key} if key_env_var else None
        return model, _run(cmd, env_override=env_override)

    cells: dict[str, list[dict]] = {}
    if a.skip_eval:
        for model in models:
            cells[model] = _read_jsonl(out_dir / f"eval_{_slug(model)}.jsonl")
    elif lanes <= 1:
        for model in models:
            _, rc = _cell(model, keys[0])
            if rc != 0:
                print(f"[warn] model {model} exited {rc}; continuing")
            cells[model] = _read_jsonl(out_dir / f"eval_{_slug(model)}.jsonl")
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        print(f"[dispatch] running {len(models)} model(s) over {lanes} concurrent lane(s)")
        # Round-robin keys across model cells so each lane stays bound to one
        # key even if N_models > N_keys (each key sees N_models / N_keys cells
        # sequentially, but the lanes themselves run in parallel).
        with ThreadPoolExecutor(max_workers=lanes) as ex:
            futs = {ex.submit(_cell, model, keys[i % len(keys)]): model for i, model in enumerate(models)}
            for fut in as_completed(futs):
                model = futs[fut]
                _, rc = fut.result()
                if rc != 0:
                    print(f"[warn] model {model} exited {rc}; continuing")
        for model in models:
            cells[model] = _read_jsonl(out_dir / f"eval_{_slug(model)}.jsonl")

    payload = aggregate(cells, live, corpus_sizes=corpus_sizes, pass_k=pass_k)
    md = render_markdown(payload)
    report_path = Path(a.report) if a.report else (out_dir / "cost_calibration.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(md, encoding="utf-8")
    print(f"wrote {report_path}")
    if a.json:
        jp = Path(a.json)
        jp.parent.mkdir(parents=True, exist_ok=True)
        jp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {jp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
