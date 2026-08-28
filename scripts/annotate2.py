"""DynamicMCPBench human validation — lean, ~2h for 6 anonymous raters (alpha..zeta).

Goal: confirm the auto-generated tasks are GOOD. Three one-tap questions per card:
  Phase A (model hidden):  Q1 valid task?         Q2 reference answer correct?
  Phase B (model shown):   Q3 agree with the auto-grader?  (-> scorer false pos/neg)
No tool-pool dump, no checkpoint rubric, no category quiz — just read the prompt and the
answer. Category is recorded from generation, so validity is reported per category for free.

Annotator:  pip install rich huggingface_hub   # rich = the colour/arrow TUI (optional)
            huggingface-cli login
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
import re
import shutil
import sys

try:  # rich is optional — visuals degrade to plain text if it's not installed
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text

    _console: Console | None = Console()
except Exception:  # pragma: no cover - cosmetic fallback
    _console = None

REPO = "TokenWasteGroup/DynamicMCPBench"
# Working prefixes for a NEW annotation campaign. The completed campaigns are
# released as human_eval/round1 (the pass reported in the paper) and
# human_eval/round2 (a later re-annotation of a 192-task subset); a new pass
# should claim its own round prefix rather than reuse these.
ASSIGN_DIR = "human_eval/assignments"
SUBMIT_DIR = "human_eval/submissions"
# Released, read-only. `report` reads these; --suffix _v2 selects round 2.
ROUND_DIRS = {"": "human_eval/round1", "_v2": "human_eval/round2"}

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


def _calls(tr, step_kind):
    """The actual tool calls made in this trace: 'server.tool({args})' (full args)."""
    out = []
    for s in tr.steps:
        if s.kind is step_kind.call_tool_agent and s.tool_name:
            args = json.dumps(s.arguments, ensure_ascii=False)
            out.append(f"{s.server_id.split('__')[-1]}.{s.tool_name}({args})")
    return out


def _first_sentence(raw):
    raw = " ".join((raw or "").split())
    cut = raw.find(". ")
    d = raw[: cut + 1] if cut != -1 else raw
    return (d[:200].rsplit(" ", 1)[0] + "…") if len(d) > 200 else d


def _tool_desc_list(call_lists, desc_map):
    """Unique tools across the call lists, each with a one-line (first-sentence) description."""
    names, seen = [], set()
    for calls in call_lists:
        for c in calls:
            nm = c.split("(", 1)[0]
            if nm not in seen:
                seen.add(nm)
                names.append(nm)
    out = []
    for nm in names:
        d = _first_sentence(desc_map.get(nm, ""))
        out.append(f"{nm} — {d}" if d else nm)
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
        gc = _calls(gt, StepKind) if gt else []
        mc = _calls(ct, StepKind) if ct else []
        items.append(
            {
                "task_id": tid,
                "category_claimed": cat.get(tid, "?"),
                "prompt": s.prompt,  # full
                "tools_desc": _tool_desc_list([gc, mc], dm),
                "gold_calls": gc,
                "gold_answer": _final(gt),
                "model_calls": mc,
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


_ESC = "\x1b"


def _supports_arrows():
    """Arrow UI only when rich is present and we own a real terminal both ways."""
    if _console is None or not sys.stdin.isatty() or not sys.stdout.isatty():
        return False
    try:
        import termios  # noqa: F401
        import tty  # noqa: F401

        return True
    except Exception:
        return False


def _getch():
    """One keypress -> 'up' / 'down' / 'enter' / lowercased char (raw mode)."""
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == _ESC:
            seq = sys.stdin.read(2)
            return {"[A": "up", "[B": "down", "[C": "right", "[D": "left"}.get(seq, "esc")
        if ch in ("\r", "\n"):
            return "enter"
        if ch == "\x03":
            raise KeyboardInterrupt
        return ch.lower()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _menu_typed(prompt, rows, hotkeys):
    """Fallback identical to the original typed flow (Enter=back, x=skip, q=quit)."""
    lines = "\n".join(f"     [{hk}] {label}" for (_v, hk, label) in rows if hk)
    while True:
        x = input(f"  {prompt}\n{lines}\n     (Enter=back, x=skip, q=save&quit)\n   > ").strip().lower()
        if x == "":
            return "back"
        if x in hotkeys:
            return hotkeys[x]
        print("   ? not a valid key")


def _menu(prompt, rows, hotkeys):
    """Arrow-key single-select. rows: list of (value, hotkey|None, label).

    Returns the chosen value. ↑/↓ (or j/k) move, Enter confirms; the original
    letter keys still work as instant accelerators. Falls back to the typed
    prompt when arrows aren't available — same return values either way.
    """
    if not _supports_arrows():
        return _menu_typed(prompt, rows, hotkeys)
    _console.print(f"  [bold]{prompt}[/]")
    n = len(rows)
    sel = 0

    def draw(first):
        out = []
        if not first:
            out.append(f"{_ESC}[{n}A")  # cursor up to repaint in place
        for i, (_v, hk, label) in enumerate(rows):
            out.append(f"\r{_ESC}[2K")  # carriage return + clear line
            tag = f"[{hk}] " if hk else ""
            if i == sel:
                out.append(f"  {_ESC}[1;30;46m ❯ {tag}{label} {_ESC}[0m")
            else:
                out.append(f"  {_ESC}[2m   {tag}{label}{_ESC}[0m")
            out.append("\n")
        sys.stdout.write("".join(out))
        sys.stdout.flush()

    draw(True)
    while True:
        k = _getch()
        if k in ("up", "k"):
            sel = (sel - 1) % n
        elif k in ("down", "j"):
            sel = (sel + 1) % n
        elif k == "enter":
            return rows[sel][0]
        elif k in hotkeys:
            return hotkeys[k]
        else:
            continue
        draw(False)


def _ask(prompt, mapping, help=None):
    """Same contract as before: returns a mapping value, or 'back'/'skip'/'quit'."""
    d = help or mapping
    rows = [(mapping[k], k, d.get(k, mapping[k])) for k in mapping]
    rows += [
        ("back", None, "← back to previous card"),
        ("skip", "x", "skip this card"),
        ("quit", "q", "save & quit"),
    ]
    hotkeys = {k: mapping[k] for k in mapping}
    hotkeys["x"] = "skip"
    hotkeys["q"] = "quit"
    return _menu(prompt, rows, hotkeys)


def _card_header(pos, total, left):
    if _console:
        _console.print()
        _console.rule(f"[bold]CARD [cyan]{pos}[/]/[cyan]{total}[/]  [dim]({left} left)[/]")
    else:
        print("=" * 78)
        print(f"CARD {pos}/{total}")


def _panel(body, title, border):
    """rich Panel from a literal Text body (no markup parsing -> injection-safe)."""
    _console.print(Panel(body, title=title, border_style=border, padding=(0, 1)))


def _section_prompt(prompt):
    if _console:
        _panel(Text(prompt, style="bold white"), "[bold yellow]USER ASKS[/]", "yellow")
    else:
        print(f"\nUSER ASKS:\n  {prompt}")


def _section_tools(tools):
    if _console:
        t = Text()
        for x in tools or ["(none recorded)"]:
            t.append(f"• {x}\n", style="cyan")
        _panel(t, "[bold]TOOLS[/] [dim](first sentence of each description)[/]", "bright_black")
    else:
        print("\nTOOLS (first sentence of each tool's description):")
        for t in tools or ["  (none recorded)"]:
            print(f"   {t}")
        print("-" * 78)


def _section_reference(calls, answer):
    if _console:
        t = Text()
        t.append("the explorer called:\n", style="dim")
        for c in calls or ["(no tool calls)"]:
            t.append(f"   {c}\n", style="green")
        t.append("\nit answered:\n", style="dim")
        t.append(f"  {answer or '(no answer recorded)'}", style="white")
        _panel(t, "[bold green]REFERENCE ANSWER[/] [dim](explorer's solution)[/]", "green")
    else:
        print("\nREFERENCE ANSWER (the explorer agent's solution).")
        print("  the explorer called:")
        for c in calls or ["   (no tool calls)"]:
            print(f"     {c}")
        print(f"  it answered:\n  {answer or '(no answer recorded)'}")


def _section_model(n, calls, answer, is_pass):
    verdict = "PASS" if is_pass else "FAIL"
    if _console:
        t = Text()
        t.append("the model called:\n", style="dim")
        for c in calls or ["(none — made no tool calls)"]:
            t.append(f"   {c}\n", style="magenta")
        t.append("\nMODEL ANSWER:\n", style="dim")
        t.append(f"  {answer or '(empty)'}\n", style="white")
        t.append("\nAUTO-GRADER said: ", style="dim")
        t.append(verdict, style="bold green" if is_pass else "bold red")
        _panel(t, f"[bold]A MODEL ATTEMPTED IT[/] [dim]({n} tool calls)[/]", "blue")
    else:
        print(f"\n  --- a model then attempted it ({n} tool calls) ---")
        print("  the model called:")
        for c in calls or ["   (none — made no tool calls)"]:
            print(f"     {c}")
        print(f"  MODEL ANSWER:\n  {answer or '(empty)'}")
        print(f"  AUTO-GRADER said: {verdict}")


def cmd_run(a):
    path = a.file or f"annotate_{a.rater}.jsonl"
    items = [json.loads(ln) for ln in _jsonl(path)]
    todo = [i for i, it in enumerate(items) if not it.get("ann")]
    summary = f"{path}: {len(items)} cards, {len(items) - len(todo)} done, {len(todo)} left."
    if _console:
        _console.print()
        _console.print(f"[bold]{summary}[/]  [dim]↑/↓ move · Enter select · letters jump[/]")
        _console.print()
    else:
        print(f"\n{summary}\n")
    pos = 0
    while pos < len(todo):
        idx = todo[pos]
        it = items[idx]
        _card_header(pos + 1, len(todo), len(todo) - pos - 1)
        _section_prompt(it["prompt"])
        _section_tools(it.get("tools_desc", []))
        ann = {}
        q1 = _ask("Q1. Is this a valid, realistic task?", Q1, help=Q1_HELP)
        if q1 in ("back", "skip", "quit"):
            pos = _nav(q1, pos, path, items)
            if q1 == "quit":
                return
            continue
        ann["valid"] = q1
        _section_reference(it.get("gold_calls", []), it.get("gold_answer", ""))
        q2 = _ask("Q2. Does this REFERENCE answer correctly solve the task?", Q2, help=Q2_HELP)
        if q2 in ("back", "skip", "quit"):
            pos = _nav(q2, pos, path, items)
            if q2 == "quit":
                return
            continue
        ann["ref_ok"] = q2
        # Phase B: reveal the model attempt + the auto-grader verdict
        _section_model(
            it["model_calls_n"],
            it.get("model_calls", []),
            it.get("model_answer", ""),
            bool(it["_auto_pass"]),
        )
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


def _fname(rater: str, suffix: str = "") -> str:
    """Assignment/submission filename. A suffix keeps a new pass from colliding
    with an earlier one: raters reuse their names, so `annotate_delta.jsonl` from
    a second study would otherwise overwrite the first study's raw data on HF."""
    return f"annotate_{rater}{suffix}.jsonl"


def cmd_fetch(a):
    from huggingface_hub import hf_hub_download

    fn = _fname(a.rater, getattr(a, "suffix", ""))
    p = hf_hub_download(REPO, f"{ASSIGN_DIR}/{fn}", repo_type="dataset", local_dir=".")
    shutil.copy(p, fn)
    print(f"fetched {fn} ({len(_jsonl(fn))} cards). now: python3 scripts/annotate2.py run --file {fn}")


def cmd_submit(a):
    fn = a.file or _fname(a.rater, getattr(a, "suffix", ""))
    if not os.path.exists(fn):
        sys.exit(f"{fn} not found — run `fetch` then `run` first")
    remote = f"{SUBMIT_DIR}/{os.path.basename(fn)}"
    api = _hf_api()
    existing = set(api.list_repo_files(REPO, repo_type="dataset"))
    if remote in existing and not a.force:
        sys.exit(
            f"refusing to overwrite hf://{REPO}/{remote}\n"
            f"  a submission already exists under that name. Raters reuse their names across\n"
            f"  studies, so this is how one pass silently erases another. Use --suffix _v2\n"
            f"  (or rename the local file), or pass --force if you really mean to replace it."
        )
    lines = _jsonl(fn)
    done = sum(1 for ln in lines if json.loads(ln).get("ann"))
    api.upload_file(path_or_fileobj=fn, path_in_repo=remote, repo_id=REPO, repo_type="dataset")
    print(f"submitted {fn} ({done}/{len(lines)} done) -> hf://{REPO}/{remote}")


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
        prefix = ROUND_DIRS.get(a.suffix, SUBMIT_DIR)
        files = [f for f in api.list_repo_files(REPO, repo_type="dataset") if f.startswith(prefix + "/")]
        for f in files:
            hf_hub_download(REPO, f, repo_type="dataset", local_dir=".")
        print(f"pulled {len(files)} cards from {prefix}")
    rows = []
    # Each released round lives in its own directory, so a round can no longer
    # absorb a later one by filename; the local fallback still needs the guard.
    round_dir = ROUND_DIRS.get(a.suffix, SUBMIT_DIR)
    pat = f"annotate_*{a.suffix}.jsonl" if a.suffix else "annotate_*.jsonl"
    found = glob.glob(f"{round_dir}/annotate_*.jsonl") + glob.glob(f"{SUBMIT_DIR}/{pat}") + glob.glob(pat)
    if not a.suffix:
        found = [f for f in found if re.fullmatch(r"annotate_[a-z]+\.jsonl", os.path.basename(f))]
    for f in found:
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
    f.add_argument("--suffix", default="", help="pass tag, e.g. _v2")
    f.set_defaults(fn=cmd_fetch)
    r = sub.add_parser("run")
    r.add_argument("--rater", default="")
    r.add_argument("--file", default="")
    r.set_defaults(fn=cmd_run)
    s = sub.add_parser("submit")
    s.add_argument("--rater", default="")
    s.add_argument("--file", default="")
    s.add_argument("--suffix", default="", help="pass tag, e.g. _v2")
    s.add_argument("--force", action="store_true", help="replace an existing submission")
    s.set_defaults(fn=cmd_submit)
    rp = sub.add_parser("report")
    rp.add_argument("--out", default="reports/human_validation.md")
    rp.add_argument("--json", default="")
    rp.add_argument("--pull", action="store_true")
    rp.add_argument("--suffix", default="", help="report on one pass, e.g. _v2")
    rp.set_defaults(fn=cmd_report)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
