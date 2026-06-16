"""DynamicMCPBench human validation — lean, ~2h for 6 anonymous raters (alpha..zeta).

Goal: confirm the auto-generated tasks are GOOD. Three one-tap questions per card:
  Phase A (model hidden):  Q1 valid task?         Q2 reference answer correct?
  Phase B (model shown):   Q3 agree with the auto-grader?  (-> scorer false pos/neg)
No tool-pool dump, no checkpoint rubric, no category quiz — just read the prompt and the
answer. Category is recorded from generation, so validity is reported per category for free.

Annotator:  huggingface-cli login
            python3 scripts/annotate2.py fetch  --rater gamma
            python3 scripts/annotate2.py run    --rater gamma
            python3 scripts/annotate2.py submit --rater gamma
Lead:       python3 scripts/annotate2.py build  --evals E --cand C --specs S --traces T \
                   --raters alpha,beta,gamma,delta,epsilon,zeta --kappa 60 --push
            python3 scripts/annotate2.py report --pull --out reports/human_validation.md
"""

import argparse
import collections
import glob
import json
import os
import random
import shutil
import sys

REPO = "TokenWasteGroup/DynamicMCPBench"
ASSIGN_DIR = "human_eval/assignments"
SUBMIT_DIR = "human_eval/submissions"

CATS = [
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

Q1 = {"y": "yes", "n": "no"}
Q1_HELP = {
    "y": "yes — a real person could plausibly ask this and it's answerable",
    "n": "no — nonsensical, self-contradictory, or impossible with these tools",
}
Q2 = {"y": "yes", "p": "partial", "n": "no"}
Q2_HELP = {
    "y": "yes — the reference answer correctly & fully solves the task",
    "p": "partial — it solves most of it but misses/garbles something",
    "n": "no — the reference answer is wrong or didn't actually solve it",
}
Q3 = {"y": "yes", "n": "no"}
Q3_HELP = {
    "y": "yes — the auto-grader's PASS/FAIL is right",
    "n": "no — the auto-grader is wrong (you'd flip its verdict)",
}


def _jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [ln for ln in f if ln.strip()]


def _write_jsonl(path, objs):
    with open(path, "w", encoding="utf-8") as f:
        for o in objs:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")


def _write_json(path, obj, indent=None):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=indent)


# --------------------------------------------------------------------------- build


def _desc_map(*traces):
    """tool 'server.name' -> description, unioned across the given traces' tool_specs."""
    m = {}
    for tr in traces:
        if tr is None:
            continue
        for server_id, specs in (tr.tool_specs or {}).items():
            for sp in specs or []:
                nm = getattr(sp, "name", None) or (sp.get("name") if isinstance(sp, dict) else None)
                if not nm:
                    continue
                desc = (
                    getattr(sp, "description", "")
                    or (sp.get("description") if isinstance(sp, dict) else "")
                    or ""
                )
                m[f"{server_id.split('__')[-1]}.{nm}"] = desc
    return m


def _tools_used(tr, step_kind, desc_map):
    """Tools actually CALLED in this trace (deduped), each with its description."""
    seen, out = set(), []
    for s in tr.steps:
        if s.kind is step_kind.call_tool_agent and s.tool_name:
            short = f"{s.server_id.split('__')[-1]}.{s.tool_name}"
            if short in seen:
                continue
            seen.add(short)
            raw = " ".join((desc_map.get(short, "") or "").split())  # collapse whitespace
            cut = raw.find(". ")
            d = raw[: cut + 1] if cut != -1 else raw  # first sentence only
            if len(d) > 200:
                d = d[:200].rsplit(" ", 1)[0] + "…"
            out.append(f"{short} — {d}" if d else short)
    return out


def _final(tr):
    return ((tr.seed_metadata or {}).get("exploration", {}).get("final_message") or "") if tr else ""


def cmd_build(a):
    sys.path.insert(0, "scripts")
    import release_hf

    from dmcp.spec import TaskSpec
    from dmcp.trace import StepKind, Trace

    specs, golds, cat = {}, {}, {}
    for ln in _jsonl(a.specs):
        s = TaskSpec.model_validate_json(ln)
        specs[str(s.task_id)] = s
    for ln in _jsonl(a.traces):
        try:
            t = Trace.model_validate_json(ln)
            golds[str(t.trace_id)] = t
        except Exception:
            pass
    for tid, s in specs.items():
        if str(s.source_trace_id) in golds:
            cat[tid] = release_hf._strategy(release_hf._goal_tags(golds[str(s.source_trace_id)].model_dump()))
        else:
            cat[tid] = "?"

    runs = collections.defaultdict(list)
    for ln in _jsonl(a.evals):
        d = json.loads(ln)
        runs[d["task_id"]].append(d)
    cand = {}
    for ln in _jsonl(a.cand):
        try:
            t = Trace.model_validate_json(ln)
            cand[str(t.trace_id)] = t
        except Exception:
            pass

    items = []
    for tid, s in specs.items():
        rs = runs.get(tid)
        if not rs:
            continue
        ev = rs[0]
        ct = cand.get(ev.get("candidate_trace_id", ""))
        gt = golds.get(str(s.source_trace_id))
        calls_n = ev["summary"]["agent_call_count"]
        dm = _desc_map(gt, ct)
        items.append(
            {
                "task_id": tid,
                "category_claimed": cat.get(tid, "?"),
                "prompt": s.prompt,  # full
                "gold_tools": _tools_used(gt, StepKind, dm) if gt else [],
                "gold_answer": _final(gt),
                "model_tools": _tools_used(ct, StepKind, dm) if ct else [],
                "model_answer": _final(ct),
                "model_calls_n": calls_n,
                "_auto_pass": bool(ev["passed"]) and calls_n > 0,  # FP-guarded shown verdict
                "ann": None,
            }
        )

    by = collections.defaultdict(list)
    for it in items:
        by[it["category_claimed"]].append(it)
    rng = random.Random(a.seed)
    for lst in by.values():
        rng.shuffle(lst)
    raters = [r.strip() for r in a.raters.split(",") if r.strip()]
    per_cat = max(1, a.kappa // len(CATS))
    kappa, rest = [], []
    for lst in by.values():
        for it in lst[:per_cat]:
            it["is_kappa"] = True
        kappa += lst[:per_cat]
        rest += lst[per_cat:]
    for it in rest:
        it["is_kappa"] = False
    rng.shuffle(rest)
    if a.per_rater:  # cap unique cards per rater to fit a time budget (kappa added on top)
        rest = rest[: a.per_rater * len(raters)]
    uniq = {r: [] for r in raters}
    for i, it in enumerate(rest):
        uniq[raters[i % len(raters)]].append(it)

    os.makedirs(a.out, exist_ok=True)
    kshuf = list(kappa)
    rng.shuffle(kshuf)
    for r in raters:
        assigned = [dict(it) for it in kshuf] + [dict(it) for it in uniq[r]]
        rng2 = random.Random(hash(r) & 0xFFFF)
        tail = assigned[len(kshuf) :]
        rng2.shuffle(tail)
        assigned = assigned[: len(kshuf)] + tail
        _write_jsonl(os.path.join(a.out, f"annotate_{r}.jsonl"), [{**it, "rater": r} for it in assigned])
    man = {
        "raters": raters,
        "tasks": len(items),
        "kappa_per_cat": per_cat,
        "kappa_n": len(kappa),
        "per_rater": {r: len(kshuf) + len(uniq[r]) for r in raters},
    }
    _write_json(os.path.join(a.out, "manifest.json"), man, indent=1)
    print(json.dumps(man, indent=1))
    if a.push:
        _hf_upload_dir(a.out, ASSIGN_DIR)
        print(f"pushed assignments -> hf://{REPO}/{ASSIGN_DIR}/")


# --------------------------------------------------------------------------- run (TUI)


def _ask(prompt, mapping, help=None):
    d = help or mapping
    lines = "\n".join(f"     [{k}] {d.get(k, mapping[k])}" for k in mapping)
    while True:
        x = input(f"  {prompt}\n{lines}\n     (Enter=back, x=skip, q=save&quit)\n   > ").strip().lower()
        if x in ("", "x", "q"):
            return {"": "back", "x": "skip", "q": "quit"}[x]
        if x in mapping:
            return mapping[x]
        print("   ? not a valid key")


def cmd_run(a):
    path = a.file or f"annotate_{a.rater}.jsonl"
    items = [json.loads(ln) for ln in _jsonl(path)]
    todo = [i for i, it in enumerate(items) if not it.get("ann")]
    print(f"\n{path}: {len(items)} cards, {len(items) - len(todo)} done, {len(todo)} left.\n")
    pos = 0
    while pos < len(todo):
        idx = todo[pos]
        it = items[idx]
        print("=" * 78)
        print(f"CARD {pos + 1}/{len(todo)}")
        print(f"\nUSER ASKS:\n  {it['prompt']}")
        print("\nTOOLS AVAILABLE (what the task is built on):")
        for t in it.get("gold_tools", []) or ["  (none recorded)"]:
            print(f"   {t}")
        print("-" * 78)
        ann = {}
        q1 = _ask("Q1. Is this a valid, realistic task?", Q1, help=Q1_HELP)
        if q1 in ("back", "skip", "quit"):
            pos = _nav(q1, pos, path, items)
            if q1 == "quit":
                return
            continue
        ann["valid"] = q1
        print("\nREFERENCE ANSWER (how it was solved):")
        print(f"  {it.get('gold_answer', '') or '(no answer recorded)'}")
        q2 = _ask("Q2. Does this REFERENCE answer correctly solve the task?", Q2, help=Q2_HELP)
        if q2 in ("back", "skip", "quit"):
            pos = _nav(q2, pos, path, items)
            if q2 == "quit":
                return
            continue
        ann["ref_ok"] = q2
        # Phase B: reveal the model attempt + the auto-grader verdict
        verdict = "PASS" if it["_auto_pass"] else "FAIL"
        print(f"\n  --- a model then attempted it ({it['model_calls_n']} tool calls) ---")
        print("  TOOLS THE MODEL USED:")
        for t in it.get("model_tools", []) or ["   (none — made no tool calls)"]:
            print(f"   {t}")
        print(f"  MODEL ANSWER:\n  {it.get('model_answer', '') or '(empty)'}")
        print(f"  AUTO-GRADER said: {verdict}")
        q3 = _ask("Q3. Do you agree with the auto-grader?", Q3, help=Q3_HELP)
        if q3 in ("back", "skip", "quit"):
            pos = _nav(q3, pos, path, items)
            if q3 == "quit":
                return
            continue
        ann["grader_ok"] = q3
        ann["fp"] = bool(it["_auto_pass"] and q3 == "no")  # graded PASS, human disagrees -> false positive
        ann["fn"] = bool((not it["_auto_pass"]) and q3 == "no")
        note = input("  optional note (Enter=skip): ").strip()
        if note:
            ann["note"] = note
        items[idx]["ann"] = ann
        _write_jsonl(path, items)
        pos += 1
    _write_jsonl(path, items)
    print(
        "\nALL DONE — thank you! now run:  python3 scripts/annotate2.py submit --rater "
        + (a.rater or "<you>")
    )


def _nav(cmd, pos, path, items):
    if cmd == "back":
        return max(0, pos - 1)
    if cmd == "skip":
        return pos + 1
    _write_jsonl(path, items)
    print("saved — resume anytime with the same `run` command.")
    return pos


# --------------------------------------------------------------------------- HF io


def _hf_api():
    from huggingface_hub import HfApi

    return HfApi()


def _hf_upload_dir(local_dir, path_in_repo):
    api = _hf_api()
    for fn in os.listdir(local_dir):
        api.upload_file(
            path_or_fileobj=os.path.join(local_dir, fn),
            path_in_repo=f"{path_in_repo}/{fn}",
            repo_id=REPO,
            repo_type="dataset",
        )


def cmd_fetch(a):
    from huggingface_hub import hf_hub_download

    fn = f"annotate_{a.rater}.jsonl"
    p = hf_hub_download(REPO, f"{ASSIGN_DIR}/{fn}", repo_type="dataset", local_dir=".")
    shutil.copy(p, fn)
    print(f"fetched {fn} ({len(_jsonl(fn))} cards). now: python3 scripts/annotate2.py run --rater {a.rater}")


def cmd_submit(a):
    fn = f"annotate_{a.rater}.jsonl"
    if not os.path.exists(fn):
        sys.exit(f"{fn} not found — run `fetch` then `run` first")
    lines = _jsonl(fn)
    done = sum(1 for ln in lines if json.loads(ln).get("ann"))
    _hf_api().upload_file(
        path_or_fileobj=fn, path_in_repo=f"{SUBMIT_DIR}/{fn}", repo_id=REPO, repo_type="dataset"
    )
    print(f"submitted {fn} ({done}/{len(lines)} done) -> hf://{REPO}/{SUBMIT_DIR}/")


# --------------------------------------------------------------------------- report


def _fleiss(table):
    n = len(table)
    if not n:
        return float("nan")
    big_n = sum(table[0])
    if big_n < 2:
        return float("nan")
    cols = len(table[0])
    pj = [sum(table[i][j] for i in range(n)) / (n * big_n) for j in range(cols)]
    pi = [(sum(c * c for c in table[i]) - big_n) / (big_n * (big_n - 1)) for i in range(n)]
    return (
        (sum(pi) / n - sum(p * p for p in pj)) / (1 - sum(p * p for p in pj))
        if sum(p * p for p in pj) < 1
        else float("nan")
    )


def cmd_report(a):
    if a.pull:
        from huggingface_hub import HfApi, hf_hub_download

        api = HfApi()
        files = [f for f in api.list_repo_files(REPO, repo_type="dataset") if f.startswith(SUBMIT_DIR + "/")]
        for f in files:
            hf_hub_download(REPO, f, repo_type="dataset", local_dir=".")
        print(f"pulled {len(files)} submissions")
    rows = []
    for f in glob.glob("human_eval/submissions/annotate_*.jsonl") + glob.glob("annotate_*.jsonl"):
        for ln in _jsonl(f):
            d = json.loads(ln)
            if d.get("ann"):
                rows.append(d)
    print(f"{len(rows)} cards annotated, {len({r['task_id'] for r in rows})} distinct tasks")

    cstat = collections.defaultdict(collections.Counter)
    fp = fn = ap = af = 0
    for r in rows:
        an = r["ann"]
        c = r["category_claimed"]
        cstat[c]["n"] += 1
        cstat[c]["valid"] += an["valid"] == "yes"
        cstat[c]["refok"] += an["ref_ok"] == "yes"
        if r["_auto_pass"]:
            ap += 1
            fp += an.get("fp", False)
        else:
            af += 1
            fn += an.get("fn", False)

    fn_line = f" | false-neg {fn}/{af} ({100 * fn / af:.1f}%)" if af else ""
    out = [
        "# Human validation — generated-task quality (lean, 3 one-tap questions)\n",
        "Pre-registered: per-category % valid & % reference-correct; reliability Fleiss kappa >= 0.7.\n",
        f"- cards: **{len(rows)}** | distinct tasks: **{len({r['task_id'] for r in rows})}**",
        f"- scorer **false-positive {fp}/{ap} ({100 * fp / ap:.1f}%)**"
        + fn_line
        + " (human disagrees with auto-grader)",
        "\n## Per-category quality\n",
        "| category | n | % valid | % reference-correct |",
        "|---|---|---|---|",
    ]
    tot = collections.Counter()
    for c in CATS:
        s = cstat.get(c)
        if not s or not s["n"]:
            continue
        for k in ("n", "valid", "refok"):
            tot[k] += s[k]
        out.append(f"| {c} | {s['n']} | {100 * s['valid'] / s['n']:.0f} | {100 * s['refok'] / s['n']:.0f} |")
    if tot["n"]:
        out.append(
            f"| **ALL** | {tot['n']} | **{100 * tot['valid'] / tot['n']:.0f}** | "
            f"**{100 * tot['refok'] / tot['n']:.0f}** |"
        )

    ks = collections.defaultdict(list)
    for r in rows:
        if r.get("is_kappa"):
            ks[r["task_id"]].append(r["ann"])
    out.append("\n## Reliability — Fleiss kappa (shared kappa-set)\n")
    if ks:
        nr = max(len(v) for v in ks.values())
        full = {k: v for k, v in ks.items() if len(v) == nr}
        out.append(f"- kappa-set tasks with all {nr} raters: {len(full)}")
        for field, dom in [
            ("valid", ["yes", "no"]),
            ("ref_ok", ["yes", "partial", "no"]),
            ("grader_ok", ["yes", "no"]),
        ]:
            tab = []
            for anns in full.values():
                cnt = [0] * len(dom)
                for an in anns:
                    if an[field] in dom:
                        cnt[dom.index(an[field])] += 1
                tab.append(cnt)
            out.append(f"- kappa[{field}] = **{_fleiss(tab):.3f}**")
    else:
        out.append("- (no kappa-set items yet)")

    flagged = [
        r for r in rows if r["ann"]["valid"] == "no" or r["ann"]["ref_ok"] == "no" or r["ann"].get("fp")
    ]
    out.append(f"\n## Flagged for cleaning: {len(flagged)}")
    for r in flagged[:80]:
        an = r["ann"]
        why = []
        if an["valid"] == "no":
            why.append("invalid")
        if an["ref_ok"] == "no":
            why.append("bad-reference")
        if an.get("fp"):
            why.append("scorer-FP")
        out.append(
            f"- {r['task_id'][:8]} [{r['category_claimed']}]: {', '.join(why)} {an.get('note', '')[:50]}"
        )

    md = "\n".join(out)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(md)
    print(md)
    if a.json:
        _write_json(
            a.json,
            {
                "n": len(rows),
                "fp": fp,
                "ap": ap,
                "fn": fn,
                "af": af,
                "per_cat": {c: dict(s) for c, s in cstat.items()},
                "flagged": [r["task_id"] for r in flagged],
            },
            indent=1,
        )
    print(f"\nwrote {a.out}")


# --------------------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    for o in ("evals", "cand", "specs", "traces"):
        b.add_argument("--" + o, required=True)
    b.add_argument("--raters", required=True)
    b.add_argument("--kappa", type=int, default=60)
    b.add_argument(
        "--per-rater",
        dest="per_rater",
        type=int,
        default=0,
        help="cap unique cards per rater (0 = cover all tasks); kappa set is added on top",
    )
    b.add_argument("--seed", type=int, default=7)
    b.add_argument("--out", default="annotation_set")
    b.add_argument("--push", action="store_true")
    b.set_defaults(fn=cmd_build)
    f = sub.add_parser("fetch")
    f.add_argument("--rater", required=True)
    f.set_defaults(fn=cmd_fetch)
    r = sub.add_parser("run")
    r.add_argument("--rater", default="")
    r.add_argument("--file", default="")
    r.set_defaults(fn=cmd_run)
    s = sub.add_parser("submit")
    s.add_argument("--rater", required=True)
    s.set_defaults(fn=cmd_submit)
    rp = sub.add_parser("report")
    rp.add_argument("--out", default="reports/human_validation.md")
    rp.add_argument("--json", default="")
    rp.add_argument("--pull", action="store_true")
    rp.set_defaults(fn=cmd_report)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
