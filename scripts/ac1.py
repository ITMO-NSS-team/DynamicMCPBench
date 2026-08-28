#!/usr/bin/env python3
"""CR 5.2 / E9.13 — regenerate the inter-annotator agreement figures.

The paper reports three Gwet AC1 coefficients (task validity, reference
correctness, grader agreement) but the repo only implemented Fleiss kappa
(`scripts/annotate2.py::_fleiss`), so a reader could not reproduce a published
number. This script computes **both** coefficients from the same shared
kappa-set that `annotate2.py report` uses, and can check them against the
committed `docs/experiments/e4.6_numbers.json`.

Why two coefficients at all: the validity axis is near-unanimous (~99% "yes"),
and there kappa suffers the prevalence paradox — chance agreement is estimated
so high that kappa collapses toward 0 despite ~99% raw agreement. Gwet's AC1
estimates chance agreement from the *categories*, not the marginals, and stays
interpretable. Both are printed side by side so the degeneracy is visible
rather than hidden behind whichever number is more flattering.

Scope of v0: the three annotation fields of the human-validation study
(`valid`, `ref_ok`, `grader_ok`), unweighted, over items rated by every rater
in the kappa-set. Out of scope: weighted/ordinal variants (AC2), bootstrap
confidence intervals, and per-category breakdowns.

    uv run python scripts/ac1.py                        # from local submissions
    uv run python scripts/ac1.py --pull                 # fetch submissions from HF first
    uv run python scripts/ac1.py --check                # verify e4.6_numbers.json
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
NUMBERS = ROOT / "docs" / "experiments" / "e4.6_numbers.json"

# Same repo/dir constants as scripts/annotate2.py — the annotations are the
# study's raw data and live in the (private) HF dataset, not in git.
REPO = "TokenWasteGroup/DynamicMCPBench"
SUBMIT_DIR = "human_eval/round1"  # the pass reported in the paper

# (annotation field, category domain, name used in the paper / numbers JSON)
FIELDS: list[tuple[str, list[str], str]] = [
    ("valid", ["yes", "no"], "validity"),
    ("ref_ok", ["yes", "partial", "no"], "reference_correctness"),
    ("grader_ok", ["yes", "no"], "grader_agreement"),
]


# --------------------------------------------------------------------------- math


def percent_agreement(table: list[list[int]]) -> float:
    """Mean over items of the proportion of rater *pairs* that agree."""
    if not table:
        return float("nan")
    total = 0.0
    n_items = 0
    for counts in table:
        n = sum(counts)
        if n < 2:
            continue
        total += (sum(c * c for c in counts) - n) / (n * (n - 1))
        n_items += 1
    return total / n_items if n_items else float("nan")


def _category_means(table: list[list[int]]) -> list[float]:
    """Mean proportion of ratings falling in each category, per item then averaged."""
    n_items = len(table)
    cols = len(table[0])
    means = [0.0] * cols
    for counts in table:
        n = sum(counts)
        if n == 0:
            continue
        for j in range(cols):
            means[j] += counts[j] / n
    return [m / n_items for m in means]


def fleiss_kappa(table: list[list[int]]) -> float:
    """Fleiss' kappa: chance agreement from the observed category marginals.

    Mirrors `scripts/annotate2.py::_fleiss` (which assumes an equal number of
    ratings per item) but tolerates a ragged table, so both coefficients can be
    computed over exactly the same items.
    """
    if not table:
        return float("nan")
    p_a = percent_agreement(table)
    pj = _category_means(table)
    p_e = sum(p * p for p in pj)
    if p_e >= 1.0:
        return float("nan")
    return (p_a - p_e) / (1 - p_e)


def gwet_ac1(table: list[list[int]]) -> float:
    """Gwet's first-order agreement coefficient (Gwet 2008), multi-rater form.

    Chance agreement is `(1/(K-1)) * sum_k pi_k (1 - pi_k)` — it peaks when the
    categories are used evenly and vanishes when one category dominates, which
    is precisely the case where kappa degenerates.
    """
    if not table:
        return float("nan")
    k = len(table[0])
    if k < 2:
        return float("nan")
    p_a = percent_agreement(table)
    pj = _category_means(table)
    p_e = sum(p * (1 - p) for p in pj) / (k - 1)
    if p_e >= 1.0:
        return float("nan")
    return (p_a - p_e) / (1 - p_e)


def rating_table(items: list[list[str]], domain: list[str]) -> list[list[int]]:
    """One row per item: how many raters chose each category. Off-domain dropped."""
    table = []
    for labels in items:
        counts = [0] * len(domain)
        for label in labels:
            if label in domain:
                counts[domain.index(label)] += 1
        table.append(counts)
    return table


# --------------------------------------------------------------------------- data


def load_rows(paths: list[str]) -> list[dict[str, Any]]:
    """Annotated cards from the submission JSONLs (same shape as annotate2)."""
    rows: list[dict[str, Any]] = []
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                if d.get("ann"):
                    rows.append(d)
    return rows


def default_paths() -> list[str]:
    return sorted(glob.glob("human_eval/round1/annotate_*.jsonl")) or sorted(glob.glob("annotate_*.jsonl"))


def kappa_set(rows: list[dict[str, Any]]) -> tuple[dict[str, list[dict]], int]:
    """The shared kappa-set: tasks carrying a rating from every rater.

    Identical selection to `annotate2.py report` — `nr` is the maximum number of
    raters seen on any kappa item, and only items with all `nr` ratings count.
    """
    by_task: dict[str, list[dict]] = collections.defaultdict(list)
    for r in rows:
        if r.get("is_kappa"):
            by_task[r["task_id"]].append(r["ann"])
    if not by_task:
        return {}, 0
    nr = max(len(v) for v in by_task.values())
    return {k: v for k, v in by_task.items() if len(v) == nr}, nr


def agreement_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Both coefficients per field over the shared kappa-set."""
    full, nr = kappa_set(rows)
    per_field: dict[str, Any] = {}
    for field, domain, name in FIELDS:
        table = rating_table([[an.get(field) for an in anns] for anns in full.values()], domain)
        per_field[name] = {
            "field": field,
            "domain": domain,
            "items": len(table),
            "percent_agreement": percent_agreement(table),
            "fleiss_kappa": fleiss_kappa(table),
            "ac1": gwet_ac1(table),
        }
    return {"raters": nr, "kappa_set_tasks": len(full), "fields": per_field}


# --------------------------------------------------------------------------- output


def _fmt(x: float) -> str:
    return "-" if x != x else f"{x:.3f}"  # NaN-safe


def render_markdown(rep: dict[str, Any]) -> str:
    lines = [
        "# Inter-annotator agreement (CR 5.2)",
        "",
        f"Shared kappa-set: **{rep['kappa_set_tasks']} tasks** rated by all **{rep['raters']}** raters.",
        "",
        "| axis | items | % pairwise agreement | Fleiss kappa | Gwet AC1 |",
        "|---|---|---|---|---|",
    ]
    for name, f in rep["fields"].items():
        lines.append(
            f"| {name} (`{f['field']}`) | {f['items']} | {100 * f['percent_agreement']:.1f}% | "
            f"{_fmt(f['fleiss_kappa'])} | **{_fmt(f['ac1'])}** |"
        )
    lines += [
        "",
        "Where the two coefficients disagree sharply the axis is near-unanimous and",
        "kappa is showing the prevalence paradox, not a reliability problem; the paper",
        "reports AC1 for that reason and this table makes the gap auditable.",
        "",
    ]
    return "\n".join(lines)


def check_against_numbers(rep: dict[str, Any], numbers_path: Path, tol: float = 0.005) -> list[str]:
    """Compare the recomputed AC1 figures with the committed paper numbers."""
    data = json.loads(numbers_path.read_text(encoding="utf-8"))
    published = data.get("ac1") or {}
    problems = []
    for name, f in rep["fields"].items():
        if name not in published:
            problems.append(f"{name}: absent from {numbers_path.name}")
            continue
        got, want = f["ac1"], float(published[name])
        if got != got or abs(got - want) > tol:
            problems.append(f"{name}: recomputed {_fmt(got)} != published {want:.3f}")
    return problems


def pull_submissions() -> int:
    """Download the raw annotations from the HF dataset (network, no LLM)."""
    from huggingface_hub import HfApi, hf_hub_download

    api = HfApi()
    files = [f for f in api.list_repo_files(REPO, repo_type="dataset") if f.startswith(SUBMIT_DIR + "/")]
    for f in files:
        hf_hub_download(REPO, f, repo_type="dataset", local_dir=".")
    print(f"pulled {len(files)} submissions from hf://{REPO}/{SUBMIT_DIR}/")
    return len(files)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", help="Annotation JSONLs (default: the usual submission globs).")
    ap.add_argument("--pull", action="store_true", help="Fetch submissions from the HF dataset first.")
    ap.add_argument("--check", action="store_true", help=f"Verify the AC1 block of {NUMBERS.name}.")
    ap.add_argument("--json", default=None, help="Write the full report to this path.")
    ap.add_argument("--markdown", default=None, help="Write the markdown table to this path.")
    a = ap.parse_args(argv)

    if a.pull:
        pull_submissions()

    paths = a.paths or default_paths()
    if not paths:
        print(
            "no annotation files found — the raw annotations are git-ignored study data;\n"
            "run with --pull to fetch them from the HF dataset.",
            file=sys.stderr,
        )
        return 2

    rows = load_rows(paths)
    rep = agreement_report(rows)
    if not rep["kappa_set_tasks"]:
        print(f"no shared kappa-set items in {len(rows)} annotated cards", file=sys.stderr)
        return 2

    md = render_markdown(rep)
    print(md)

    if a.json:
        Path(a.json).write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {a.json}")
    if a.markdown:
        Path(a.markdown).write_text(md, encoding="utf-8")
        print(f"wrote {a.markdown}")

    if a.check:
        problems = check_against_numbers(rep, NUMBERS)
        if problems:
            print("\nMISMATCH against " + str(NUMBERS) + ":", file=sys.stderr)
            for p in problems:
                print("  - " + p, file=sys.stderr)
            return 1
        print(f"\nOK — AC1 figures match {NUMBERS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
