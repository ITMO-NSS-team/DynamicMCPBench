#!/usr/bin/env python3
"""CR 5.3 / E9.13 — regenerate the equivalence-set figures the paper reports.

The paper quoted the share of tool-effect checkpoints admitting more than one
interchangeable tool twice, with two different roundings (16\\% in the main text,
15.5\\% in the appendix) and no committed way to tell which population either
covered. This script recomputes the whole distribution from the released
`specs.jsonl` so the number has exactly one source, and can check it against
the committed `docs/experiments/e9.13_eqset_numbers.json`.

The figure matters because it is the paper's path-agnosticism claim: a
checkpoint with an equivalence set of size >1 is one that several distinct
trajectories satisfy, so the share bounds how much of the corpus is graded on
effects rather than on a single gold path.

Scope of v0: unweighted counts of `tool_effect` checkpoint equivalence-set
sizes over one specs JSONL. Out of scope: per-domain or per-server breakdowns,
value-produced checkpoints (they carry no equivalence set), and any weighting
by how often a checkpoint is actually exercised.

    uv run python scripts/eqset_stats.py --pull --check
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
NUMBERS = ROOT / "docs" / "experiments" / "e9.13_eqset_numbers.json"

# The released corpus; same dataset the human-eval submissions come from.
REPO = "TokenWasteGroup/DynamicMCPBench"
SPECS_FILE = "specs.jsonl"

# Sizes reported individually in the appendix; everything above folds into one bucket.
TAIL_FROM = 5


def eqset_distribution(specs: list[dict[str, Any]]) -> collections.Counter:
    """Equivalence-set size -> number of `tool_effect` checkpoints of that size."""
    dist: collections.Counter = collections.Counter()
    for spec in specs:
        for cp in spec.get("checkpoints", []):
            if cp.get("kind") == "tool_effect":
                dist[len(cp.get("equivalence_set") or [])] += 1
    return dist


def summarize(dist: collections.Counter, n_specs: int) -> dict[str, Any]:
    """The published shape: totals, the multi-tool share, and the reported buckets."""
    total = sum(dist.values())
    if not total:
        raise ValueError("no tool_effect checkpoints found")
    multi = sum(n for size, n in dist.items() if size >= 2)
    weighted = sum(size * n for size, n in dist.items())
    buckets = {str(size): dist.get(size, 0) for size in range(1, TAIL_FROM)}
    buckets[f">={TAIL_FROM}"] = sum(n for size, n in dist.items() if size >= TAIL_FROM)
    return {
        "specs": n_specs,
        "tool_effect_checkpoints": total,
        "multi_tool_checkpoints": multi,
        "multi_tool_pct": round(100 * multi / total, 3),
        "mean_size": round(weighted / total, 3),
        "max_size": max(dist),
        "buckets": buckets,
    }


def load_specs(path: str | Path) -> list[dict[str, Any]]:
    specs = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                specs.append(json.loads(line))
    return specs


def default_path() -> str | None:
    for cand in (Path(SPECS_FILE), ROOT / SPECS_FILE):
        if cand.exists():
            return str(cand)
    return None


def render_markdown(s: dict[str, Any]) -> str:
    rows = "\n".join(f"| {size} | {n} |" for size, n in s["buckets"].items())
    return (
        "# Equivalence-set sizes (CR 5.3)\n\n"
        f"{s['specs']} specifications, {s['tool_effect_checkpoints']} tool-effect checkpoints.\n\n"
        "| equivalence-set size | checkpoints |\n|---|---|\n"
        f"{rows}\n\n"
        f"**{s['multi_tool_pct']:.1f}%** of tool-effect checkpoints "
        f"({s['multi_tool_checkpoints']}/{s['tool_effect_checkpoints']}) admit two or more "
        f"interchangeable tools; mean set size {s['mean_size']:.2f}, maximum {s['max_size']}.\n"
    )


def check_against_numbers(s: dict[str, Any], numbers_path: Path) -> list[str]:
    """Compare the recomputed summary with the committed paper numbers."""
    published = json.loads(numbers_path.read_text(encoding="utf-8"))
    problems = []
    for key in ("specs", "tool_effect_checkpoints", "multi_tool_checkpoints", "max_size"):
        if published.get(key) != s[key]:
            problems.append(f"{key}: recomputed {s[key]} != published {published.get(key)}")
    for key, tol in (("multi_tool_pct", 0.05), ("mean_size", 0.005)):
        want = published.get(key)
        if want is None or abs(float(want) - s[key]) > tol:
            problems.append(f"{key}: recomputed {s[key]} != published {want}")
    if published.get("buckets") != s["buckets"]:
        problems.append(f"buckets: recomputed {s['buckets']} != published {published.get('buckets')}")
    return problems


def pull_specs() -> str:
    """Download the released specs from the HF dataset (network, no LLM)."""
    from huggingface_hub import hf_hub_download

    path = hf_hub_download(REPO, SPECS_FILE, repo_type="dataset", local_dir=".")
    print(f"pulled hf://{REPO}/{SPECS_FILE}")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", nargs="?", help=f"Specs JSONL (default: ./{SPECS_FILE}).")
    ap.add_argument("--pull", action="store_true", help="Fetch the released specs from HF first.")
    ap.add_argument("--check", action="store_true", help=f"Verify {NUMBERS.name}.")
    ap.add_argument("--json", dest="json_out", default=None, help="Write the summary to this path.")
    ap.add_argument("--markdown", default=None, help="Write the markdown table to this path.")
    a = ap.parse_args(argv)

    path = pull_specs() if a.pull else (a.path or default_path())
    if not path:
        print(
            f"no {SPECS_FILE} found — the corpus is git-ignored release data;\n"
            "run with --pull to fetch it from the HF dataset.",
            file=sys.stderr,
        )
        return 2

    specs = load_specs(path)
    summary = summarize(eqset_distribution(specs), len(specs))
    md = render_markdown(summary)
    print(md)

    if a.json_out:
        Path(a.json_out).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {a.json_out}")
    if a.markdown:
        Path(a.markdown).write_text(md, encoding="utf-8")
        print(f"wrote {a.markdown}")

    if a.check:
        problems = check_against_numbers(summary, NUMBERS)
        if problems:
            print(f"\nMISMATCH against {NUMBERS}:", file=sys.stderr)
            for p in problems:
                print("  - " + p, file=sys.stderr)
            return 1
        print(f"OK — equivalence-set figures match {NUMBERS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
