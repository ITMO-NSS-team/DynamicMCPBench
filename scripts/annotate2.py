"""DynamicMCPBench human validation v2 — quality of GENERATED QUESTIONS + scorer audit.

Two-phase, blind: Phase A judges the question from spec+gold ONLY (no model shown) ->
unbiased question-quality. Phase B reveals the top model's (Qwen3.6) run + the auto
verdict -> scorer FP/FN. Anonymous raters (alpha..zeta). HF fetch -> annotate -> submit.

Annotator workflow (each colleague):
  huggingface-cli login                      # your own token, once
  python annotate2.py fetch  --rater gamma   # download your assignment from HF
  python annotate2.py run    --rater gamma   # annotate (keyboard, resume-safe)
  python annotate2.py submit --rater gamma   # push your file back to HF

Lead workflow:
  python annotate2.py build  --evals E --cand C --specs S --traces T \
        --raters alpha,beta,gamma,delta,epsilon,zeta --kappa 50 --push
  python annotate2.py report --out reports/human_validation.md --json ... --pull
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

# Phase A (blind)
Q1 = {"v": "valid", "a": "valid-but-ambiguous", "u": "unsolvable", "b": "broken"}
Q1_HELP = {
    "v": "valid — a capable agent could solve it with these tools; prompt is clear",
    "a": "valid-but-ambiguous — solvable, but the prompt is loose / has >1 reading",
    "u": "unsolvable — the given tools genuinely cannot accomplish it",
    "b": "broken — nonsensical, self-contradictory, or malformed task",
}
Q1_REASON = {
    "c": "contradictory",
    "t": "required-tool-missing",
    "p": "prompt-unclear",
    "d": "needs-external-data",
    "o": "other (type a reason)",
}
Q2 = {"y": "yes", "b": "borderline", "n": "no"}
Q2_HELP = {
    "y": "yes — the claimed category fits",
    "b": "borderline — sort of, but weak",
    "n": "no — wrong; you'll pick the real category",
}
Q3 = {"y": "yes", "p": "partial", "n": "no"}
Q3_HELP = {
    "y": "yes — the gold trace fully solves the task",
    "p": "partial — gold does most of it but misses something",
    "n": "no — the gold trace does NOT solve the task",
}
# Phase B (reveal)
Q5 = {"s": "success", "p": "partial", "f": "fail"}
Q5_HELP = {
    "s": "success — did everything asked, correct result",
    "p": "partial — right approach / some correct results, but incomplete or partly wrong",
    "f": "fail — did nothing useful: wrong tools, errored, empty, or only restated the task",
}
Q6 = {"y": "fair", "l": "too-loose", "t": "too-strict", "w": "wrong-checkpoints"}
Q6_HELP = {
    "y": "fair — the verdict matches reality",
    "l": "too-loose — it PASSED something that wasn't really done (FP risk)",
    "t": "too-strict — it FAILED something that was actually done (FN risk)",
    "w": "wrong-checkpoints — the rubric checks the wrong thing entirely",
}


def _jsonl(path):
    """Read a jsonl file, returning the non-empty raw lines (context-managed)."""
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


def _req(cp):
    k = cp.get("kind")
    if k == "tool_effect":
        eq = ", ".join(
            f"{r['server_id'].split('__')[-1]}.{r['tool_name']}" for r in cp.get("equivalence_set", [])
        )
        ap = cp.get("arg_predicate")
        suffix = f"  args~{json.dumps(ap, ensure_ascii=False)[:80]}" if ap else ""
        return f"call one of [{eq}]" + suffix
    if k == "value_produced":
        return f"value~{json.dumps(cp.get('predicate'), ensure_ascii=False)[:80]} in {cp.get('scope')}"
    return json.dumps(cp, ensure_ascii=False)[:90]


def _calls(tr, step_kind):
    return [
        f"{s.server_id.split('__')[-1]}.{s.tool_name}({json.dumps(s.arguments, ensure_ascii=False)[:90]})"
        for s in tr.steps
        if s.kind is step_kind.call_tool_agent and s.tool_name
    ]


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
            tags = release_hf._goal_tags(golds[str(s.source_trace_id)].model_dump())
            cat[tid] = release_hf._strategy(tags)
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
        auto_pass = bool(ev["passed"]) and calls_n > 0  # FP-guarded shown verdict
        passk = all(x["passed"] and x["summary"]["agent_call_count"] > 0 for x in rs)
        final = ((ct.seed_metadata.get("exploration", {}).get("final_message") if ct else "") or "")[:600]
        items.append(
            {
                "item_id": tid,
                "task_id": tid,
                "category_claimed": cat.get(tid, "?"),
                "prompt": s.prompt,
                "gold_calls": _calls(gt, StepKind) if gt else [],
                "model_calls": _calls(ct, StepKind) if ct else [],
                "model_final": final,
                "model_calls_n": calls_n,
                "checkpoints": [
                    {"id": c.get("checkpoint_id"), "kind": c.get("kind"), "req": _req(c)}
                    for c in json.loads(s.model_dump_json())["checkpoints"]
                ],
                "_auto_pass": auto_pass,
                "_measured_passk": passk,
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
    uniq = {r: [] for r in raters}
    for i, it in enumerate(rest):  # round-robin -> category-balanced unique slices
        uniq[raters[i % len(raters)]].append(it)

    os.makedirs(a.out, exist_ok=True)
    kshuf = list(kappa)
    rng.shuffle(kshuf)
    for r in raters:
        assigned = [dict(it) for it in kshuf] + [dict(it) for it in uniq[r]]  # kappa FIRST
        rng2 = random.Random(hash(r) & 0xFFFF)
        tail = assigned[len(kshuf) :]
        rng2.shuffle(tail)
        assigned = assigned[: len(kshuf)] + tail
        rows = [{**{k: v for k, v in it.items() if k != "_measured_passk"}, "rater": r} for it in assigned]
        _write_jsonl(os.path.join(a.out, f"annotate_{r}.jsonl"), rows)
    _write_json(
        os.path.join(a.out, "_passk_key.json"),
        {it["item_id"]: it["_measured_passk"] for it in items},
    )
    man = {
        "raters": raters,
        "tasks": len(items),
        "kappa_per_cat": per_cat,
        "kappa_n": len(kappa),
        "unique_n": len(rest),
        "per_rater": {r: len(kshuf) + len(uniq[r]) for r in raters},
    }
    _write_json(os.path.join(a.out, "manifest.json"), man, indent=1)
    print(json.dumps(man, indent=1))
    if a.push:
        _hf_upload_dir(a.out, ASSIGN_DIR, exclude=("_passk_key.json",))
        print(f"pushed assignments -> hf://{REPO}/{ASSIGN_DIR}/")


# --------------------------------------------------------------------------- run (TUI)


def _ask(prompt, mapping, allow_nav=True, help=None):
    d = help or mapping
    lines = "\n".join(f"     [{k}] {d.get(k, mapping[k])}" for k in mapping)
    nav = "     (Enter=back, x=skip, q=save&quit)\n" if allow_nav else ""
    while True:
        x = input(f"  {prompt}\n{lines}\n{nav}   > ").strip().lower()
        if allow_nav and x in ("", "x", "q"):
            return {"": "back", "x": "skip", "q": "quit"}[x]
        if x in mapping:
            return mapping[x]
        print("   ? not a valid key")


def _ask_int(prompt, lo, hi):
    while True:
        x = input(f"  {prompt} [{lo}-{hi}]  (x=skip): ").strip().lower()
        if x == "x":
            return None
        if x.isdigit() and lo <= int(x) <= hi:
            return int(x)
        print("   ?")


def cmd_run(a):
    path = a.file or f"annotate_{a.rater}.jsonl"
    items = [json.loads(ln) for ln in _jsonl(path)]
    todo = [i for i, it in enumerate(items) if not it.get("ann")]
    print(f"\n{path}: {len(items)} items, {len(items) - len(todo)} done, {len(todo)} left.")
    print("Phase A = judge the QUESTION (model hidden). Phase B = judge the model run + scorer.\n")
    pos = 0
    while pos < len(todo):
        idx = todo[pos]
        it = items[idx]
        kp = " [KAPPA]" if it.get("is_kappa") else ""
        print("=" * 80)
        print(f"[{pos + 1}/{len(todo)}]{kp}  claimed category: {it['category_claimed']}")
        print(f"\nUSER PROMPT:\n  {it['prompt'][:500]}")
        print("\nGOLD solution (reference):")
        for c in it["gold_calls"][:10]:
            print(f"   {c}")
        print("\nSUCCESS RUBRIC (checkpoints):")
        for cp in it["checkpoints"]:
            print(f"   [{cp['kind']}] {cp['req']}")
        print("-" * 80 + "\n  --- PHASE A: judge the QUESTION (the model is hidden) ---")
        ann = {}
        q1 = _ask("Q1. Is the task valid & solvable with the tools?", Q1, help=Q1_HELP)
        if q1 in ("back", "skip", "quit"):
            pos = _nav(q1, pos, path, items)
            if q1 == "quit":
                return
            continue
        ann["valid"] = q1
        if q1 in ("unsolvable", "broken"):
            rsn = _ask("   why?", Q1_REASON, allow_nav=False)
            ann["valid_reason"] = rsn
            if rsn == "other (type a reason)":
                ann["valid_reason_text"] = input("   describe in your own words: ").strip()
        q2 = _ask("Q2. Is the claimed category correct?", Q2, help=Q2_HELP)
        if q2 in ("back", "skip", "quit"):
            pos = _nav(q2, pos, path, items)
            if q2 == "quit":
                return
            continue
        if q2 == "no":
            print("   real category:")
            for n, c in enumerate(CATS):
                print(f"     {n:2d} {c}")
            while True:
                v = input("   number: ").strip()
                if v.isdigit() and 0 <= int(v) < len(CATS):
                    q2 = "no:" + CATS[int(v)]
                    break
                print("   ?")
        ann["category"] = q2
        q3 = _ask("Q3. Does the GOLD trace actually solve the task?", Q3, help=Q3_HELP)
        if q3 in ("back", "skip", "quit"):
            pos = _nav(q3, pos, path, items)
            if q3 == "quit":
                return
            continue
        ann["gold_ok"] = q3
        ann["difficulty"] = _ask_int("Q4. Difficulty for a capable agent?", 1, 5)
        # ---- PHASE B reveal ----
        print("\n  --- PHASE B: the model's attempt is revealed ---")
        print(f"  MODEL made {it['model_calls_n']} calls:")
        for c in it["model_calls"][:12]:
            print(f"     {c}")
        if len(it["model_calls"]) > 12:
            print(f"     ... (+{len(it['model_calls']) - 12} more)")
        print(f"  MODEL FINAL: {it['model_final'][:300]!r}")
        print(f"  >>> AUTO-SCORER VERDICT: {'PASS' if it['_auto_pass'] else 'FAIL'}")
        q5 = _ask("Q5. Did the model actually do what the user asked?", Q5, help=Q5_HELP)
        if q5 in ("back", "skip", "quit"):
            pos = _nav(q5, pos, path, items)
            if q5 == "quit":
                return
            continue
        ann["model_success"] = q5
        ann["fp"] = bool(it["_auto_pass"] and q5 == "fail")  # scored PASS but did nothing useful
        ann["lenient"] = bool(it["_auto_pass"] and q5 == "partial")  # scored PASS but only partial
        ann["fn"] = bool((not it["_auto_pass"]) and q5 == "success")
        if ann["fp"]:
            print("   *** scorer FALSE POSITIVE (auto=PASS, you=fail) ***")
        if ann["fn"]:
            print("   *** scorer FALSE NEGATIVE (auto=FAIL, you=success) ***")
        q6 = _ask("Q6. Is the auto-scorer's verdict fair for this run?", Q6, help=Q6_HELP)
        if q6 in ("back", "skip", "quit"):
            pos = _nav(q6, pos, path, items)
            if q6 == "quit":
                return
            continue
        ann["scorer_fair"] = q6
        note = input("  optional note (Enter=skip): ").strip()
        if note:
            ann["note"] = note
        items[idx]["ann"] = ann
        _write_jsonl(path, items)
        pos += 1
    _write_jsonl(path, items)
    print("\nALL DONE — thank you! now run:  python annotate2.py submit --rater " + (a.rater or "<you>"))


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


def _hf_upload_dir(local_dir, path_in_repo, exclude=()):
    api = _hf_api()
    for fn in os.listdir(local_dir):
        if fn in exclude:
            continue
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
    n = len(_jsonl(fn))
    print(f"fetched {fn} ({n} items). now: python annotate2.py run --rater {a.rater}")


def cmd_submit(a):
    fn = f"annotate_{a.rater}.jsonl"
    if not os.path.exists(fn):
        sys.exit(f"{fn} not found — run `fetch` then `run` first")
    lines = _jsonl(fn)
    done = sum(1 for ln in lines if json.loads(ln).get("ann"))
    _hf_api().upload_file(
        path_or_fileobj=fn, path_in_repo=f"{SUBMIT_DIR}/{fn}", repo_id=REPO, repo_type="dataset"
    )
    print(f"submitted {fn} ({done}/{len(lines)} annotated) -> hf://{REPO}/{SUBMIT_DIR}/")


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
    pbar = sum(pi) / n
    pe = sum(p * p for p in pj)
    return (pbar - pe) / (1 - pe) if (1 - pe) else float("nan")


def cmd_report(a):
    if a.pull:
        from huggingface_hub import HfApi, hf_hub_download

        api = HfApi()
        files = [f for f in api.list_repo_files(REPO, repo_type="dataset") if f.startswith(SUBMIT_DIR + "/")]
        os.makedirs("human_eval/submissions", exist_ok=True)
        for f in files:
            hf_hub_download(REPO, f, repo_type="dataset", local_dir=".")
        print(f"pulled {len(files)} submissions")
    rows = []
    for f in glob.glob("human_eval/submissions/annotate_*.jsonl") + glob.glob("annotate_*.jsonl"):
        for ln in _jsonl(f):
            d = json.loads(ln)
            if d.get("ann"):
                rows.append(d)
    passk_key = {}
    if os.path.exists(a.passk_key):
        with open(a.passk_key, encoding="utf-8") as f:
            passk_key = json.load(f)
    print(f"{len(rows)} annotated items, {len({r['task_id'] for r in rows})} distinct tasks")

    cstat = collections.defaultdict(collections.Counter)
    conf = collections.Counter()
    fp = fn = ap = af = lenient = 0
    diff_pairs = []
    for r in rows:
        an = r["ann"]
        c = r["category_claimed"]
        cstat[c]["n"] += 1
        cstat[c]["valid"] += an["valid"] in ("valid", "valid-but-ambiguous")
        cstat[c]["catok"] += an["category"] == "yes"
        cstat[c]["goldok"] += an["gold_ok"] == "yes"
        if an["category"].startswith("no:"):
            conf[(c, an["category"][3:])] += 1
        if r["_auto_pass"]:
            ap += 1
            fp += an.get("fp", False)
            lenient += an.get("lenient", False)
        else:
            af += 1
            fn += an.get("fn", False)
        if an.get("difficulty") and r["task_id"] in passk_key:
            diff_pairs.append((an["difficulty"], 1 if passk_key[r["task_id"]] else 0))

    fn_line = f" | false-negative: {fn}/{af} ({100 * fn / af:.1f}%)" if af else ""
    len_line = f"\n- scorer lenient (auto-PASS but human-partial): {lenient}/{ap}" if ap else ""
    out = [
        "# Human validation — generated-question quality + scorer audit\n",
        "Pre-registered: per-category validity & category-correctness; gate Fleiss kappa >= 0.7.\n",
        f"- annotated items: **{len(rows)}** | distinct tasks: **{len({r['task_id'] for r in rows})}**",
        f"- scorer **false-positive rate (auto-PASS but human-fail): {fp}/{ap} ({100 * fp / ap:.1f}%)**"
        + fn_line
        + len_line,
        "\n## Per-category quality\n",
        "| category | n | %valid | %category-correct | %gold-correct |",
        "|---|---|---|---|---|",
    ]
    tot = collections.Counter()
    for c in CATS:
        s = cstat.get(c)
        if not s or not s["n"]:
            continue
        n = s["n"]
        for k in ("n", "valid", "catok", "goldok"):
            tot[k] += s[k]
        pv, pc, pg = 100 * s["valid"] / n, 100 * s["catok"] / n, 100 * s["goldok"] / n
        out.append(f"| {c} | {n} | {pv:.0f} | {pc:.0f} | {pg:.0f} |")
    if tot["n"]:
        out.append(
            f"| **ALL** | {tot['n']} | **{100 * tot['valid'] / tot['n']:.0f}** | "
            f"**{100 * tot['catok'] / tot['n']:.0f}** | **{100 * tot['goldok'] / tot['n']:.0f}** |"
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
        fields = [
            ("valid", ["valid", "valid-but-ambiguous", "unsolvable", "broken"], lambda an: an["valid"]),
            ("category", ["yes", "no"], lambda an: "yes" if an["category"] == "yes" else "no"),
            ("gold_ok", ["yes", "partial", "no"], lambda an: an["gold_ok"]),
            ("model_success", ["success", "partial", "fail"], lambda an: an["model_success"]),
        ]
        for field, dom, key in fields:
            tab = []
            for anns in full.values():
                cnt = [0] * len(dom)
                for an in anns:
                    val = key(an)
                    if val in dom:
                        cnt[dom.index(val)] += 1
                tab.append(cnt)
            out.append(f"- kappa[{field}] = **{_fleiss(tab):.3f}**")
    else:
        out.append("- (no kappa-set items yet)")

    if conf:
        out.append("\n## Category confusion (claimed -> human-corrected)\n")
        for (cl, real), k in conf.most_common(25):
            out.append(f"- {cl} -> {real}: {k}")
    if diff_pairs:
        byd = collections.defaultdict(list)
        for d, p in diff_pairs:
            byd[d].append(p)
        out.append("\n## Difficulty calibration (human difficulty vs measured pass^3)\n")
        for d in sorted(byd):
            v = byd[d]
            out.append(f"- difficulty {d}: pass^3 = {100 * sum(v) / len(v):.0f}% (n={len(v)})")

    flagged = [
        r
        for r in rows
        if r["ann"]["valid"] in ("unsolvable", "broken")
        or r["ann"]["category"].startswith("no:")
        or r["ann"]["gold_ok"] == "no"
        or r["ann"].get("fp")
    ]
    out.append(f"\n## Flagged for corpus cleaning: {len(flagged)}")
    for r in flagged[:80]:
        an = r["ann"]
        why = []
        if an["valid"] in ("unsolvable", "broken"):
            why.append(an["valid"] + "/" + an.get("valid_reason", ""))
        if an["category"].startswith("no:"):
            why.append("mislabel->" + an["category"][3:])
        if an["gold_ok"] == "no":
            why.append("bad-gold")
        if an.get("fp"):
            why.append("scorer-FP")
        out.append(f"- {r['task_id'][:8]} [{r['category_claimed']}]: {', '.join(why)}")

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
                "confusion": {f"{k[0]}->{k[1]}": v for k, v in conf.items()},
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
    b.add_argument("--kappa", type=int, default=50)
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
    rp.add_argument("--passk-key", dest="passk_key", default="annotation_set/_passk_key.json")
    rp.set_defaults(fn=cmd_report)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
