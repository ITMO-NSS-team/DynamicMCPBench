"""Render the data figures for Section 4 from the released HuggingFace dataset.

Inputs (the TokenWasteGroup/DynamicMCPBench dataset, also cached locally):
  <data>/leaderboard_e8.10d/matrix.json      8 API models  x 15 categories (pass^3)
  <data>/leaderboard_local_50x15/matrix.json 16 local models x 15 categories (pass^3)
  <data>/leaderboard_*/verdicts/*.jsonl      per-run EvaluationResult rows
  <data>/specs.jsonl                          task specs (complexity.trace_depth)

Outputs (committed PNGs, \\includegraphics'd by sections/results.tex):
  fig_heatmap.png     pass^3 by model x task category (flagship)
  fig_difficulty.png  accuracy vs task length | accuracy by task category
  fig_compute.png     accuracy vs prompt tokens per task
  fig_size.png        accuracy vs model size (local; appendix)

Every number is read straight from the dataset; nothing is hard-coded.
Run:  DMCP_DATA=/path/to/dataset uv run --with matplotlib python paper/figures/make_figures.py
"""

from __future__ import annotations

import collections
import glob
import json
import os
import re
import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

DATA = os.environ.get("DMCP_DATA", "/tmp/hf2")
OUT = os.path.dirname(os.path.abspath(__file__))
plt.rcParams.update({"font.size": 11, "axes.titlesize": 15, "axes.titleweight": "bold"})


# ---- load the two leaderboards (pass^3 per model x category cell) ----
def _load_json(p):
    with open(p) as f:
        return json.load(f)


boards = {b: _load_json(f"{DATA}/{b}/matrix.json") for b in ("leaderboard_e8.10d", "leaderboard_local_50x15")}
STRATS = boards["leaderboard_e8.10d"]["strategies"]
cells = {}
overall = {}  # model -> overall pass^3
group = {}  # model -> "API"/"local"
for b, tag in (("leaderboard_e8.10d", "API"), ("leaderboard_local_50x15", "local")):
    m = boards[b]
    for k, (p, n) in m["cells"].items():
        cells[k] = p / n
    for r in m["leaderboard"]:
        overall[r["model"]] = r["acc"]
        group[r["model"]] = tag

api = sorted([m for m in overall if group[m] == "API"], key=lambda m: -overall[m])
loc = sorted([m for m in overall if group[m] == "local"], key=lambda m: -overall[m])
models = api + loc  # API group then local group, each best->worst
# categories sorted hardest -> easiest (mean pass^3 over all 24 models)
cat_mean = {s: statistics.mean(cells[f"{m}|{s}"] for m in models) for s in STRATS}
cats = sorted(STRATS, key=lambda s: cat_mean[s])
catlabel = {s: s.replace("_", "-") for s in STRATS}

# ---- pass^3 per (model, task) from verdicts; depth from specs ----
depth = {}
with open(f"{DATA}/specs.jsonl", encoding="utf-8") as f:
    for ln in f:
        if ln.strip():
            d = json.loads(ln)
            depth[d["task_id"]] = d["complexity"]["trace_depth"]


def dbin(t):
    x = depth[t]
    return 0 if x <= 2 else 1 if x <= 4 else 2


passk = collections.defaultdict(dict)  # model -> task -> bool
ptok = {}  # model -> mean prompt tokens / run
for vf in glob.glob(f"{DATA}/leaderboard_*/verdicts/*.jsonl"):
    mdl = os.path.basename(vf)[:-6].replace("evals_", "")
    runs = collections.defaultdict(list)
    toks = []
    with open(vf, encoding="utf-8") as f:
        for ln in f:
            if not ln.strip():
                continue
            r = json.loads(ln)
            runs[r["task_id"]].append(bool(r["passed"]))
            c = (r.get("summary") or {}).get("cost") or {}
            if c.get("prompt_tokens"):
                toks.append(c["prompt_tokens"])
    for t, res in runs.items():
        passk[mdl][t] = bool(res) and all(res)
    if toks:
        ptok[mdl] = statistics.mean(toks)

# length: pooled across all models, by depth bin
binagg = [[0, 0], [0, 0], [0, 0]]
for mdl in passk:
    for t, ok in passk[mdl].items():
        b = dbin(t)
        binagg[b][0] += ok
        binagg[b][1] += 1
length_pct = [100 * a / n for a, n in binagg]

# ============================ FIG: heatmap ============================
M = [[cells[f"{m}|{s}"] for s in cats] for m in models]
fig, ax = plt.subplots(figsize=(11, 9))
im = ax.imshow(M, aspect="auto", cmap="RdYlGn", vmin=0, vmax=max(max(r) for r in M))
ax.set_xticks(range(len(cats)))
ax.set_xticklabels([catlabel[s] for s in cats], rotation=45, ha="right", fontsize=9)
ax.set_yticks(range(len(models)))
ax.set_yticklabels(models, fontsize=9)
ax.axhline(len(api) - 0.5, color="black", lw=2)  # API | local separator
ax.set_xlabel("task category")
ax.set_ylabel("model")
ax.set_title(r"pass$^3$ accuracy by model and task category")
cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02)
cb.set_label(r"pass$^3$")
fig.tight_layout()
fig.savefig(f"{OUT}/fig_heatmap.png", dpi=150, bbox_inches="tight")
plt.close(fig)

# ====================== FIG: difficulty (2 panels) ======================
fig, (axL, axR) = plt.subplots(1, 2, figsize=(11, 4.2))
axL.plot(["short\n(1-2)", "medium\n(3-4)", "long\n(5+)"], length_pct, "o-", lw=2.5, ms=9, color="#1f77b4")
axL.set_ylim(0, max(length_pct) * 1.25)
axL.set_xlabel("task length (tool-chain depth)")
axL.set_ylabel(r"pass$^3$ (%)")
axL.set_title("accuracy vs task length")
for x, y in enumerate(length_pct):
    axL.annotate(f"{y:.0f}%", (x, y), textcoords="offset points", xytext=(0, 8), ha="center")
order = sorted(cats, key=lambda s: cat_mean[s])
vals = [100 * cat_mean[s] for s in order]
axR.barh([catlabel[s] for s in order], vals, color="#4c78a8")
axR.set_xlabel(r"mean pass$^3$ (%)")
axR.set_title("accuracy by task category")
axR.tick_params(axis="y", labelsize=9)
fig.tight_layout()
fig.savefig(f"{OUT}/fig_difficulty.png", dpi=150, bbox_inches="tight")
plt.close(fig)

# ============================ FIG: compute ============================
fig, ax = plt.subplots(figsize=(6.4, 4.6))
for tag, color in (("API", "#d62728"), ("local", "#1f77b4")):
    xs = [ptok[m] / 1000 for m in models if group[m] == tag and m in ptok]
    ys = [100 * overall[m] for m in models if group[m] == tag and m in ptok]
    ax.scatter(xs, ys, s=60, color=color, label=tag, alpha=0.85, edgecolor="white")
ax.set_xlabel("prompt tokens per task (thousands)")
ax.set_ylabel(r"pass$^3$ (%)")
ax.set_title("accuracy vs compute per task")
ax.legend(frameon=False)
fig.tight_layout()
fig.savefig(f"{OUT}/fig_compute.png", dpi=150, bbox_inches="tight")
plt.close(fig)

# ====================== FIG: size (local; appendix) ======================
fig, ax = plt.subplots(figsize=(6.4, 4.6))
sx, sy = [], []
for m in loc:
    mm = re.search(r"(\d+)b", m)
    if mm:
        sx.append(int(mm.group(1)))
        sy.append(100 * overall[m])
ax.scatter(sx, sy, s=60, color="#1f77b4", alpha=0.85, edgecolor="white")
ax.set_xlabel("model size (billion parameters)")
ax.set_ylabel(r"pass$^3$ (%)")
ax.set_title("accuracy vs model size")
fig.tight_layout()
fig.savefig(f"{OUT}/fig_size.png", dpi=150, bbox_inches="tight")
plt.close(fig)

# ---- echo the numbers rendered, for verification ----
print("models:", len(models), "| API:", len(api), "| local:", len(loc))
print("length pooled pass^3 (short/med/long):", [round(x) for x in length_pct])
print("category mean pass^3 hardest->easiest:", [(catlabel[s], round(100 * cat_mean[s], 1)) for s in cats])
print(
    "top overall:",
    models[0],
    round(100 * overall[models[0]], 1),
    "| min:",
    round(100 * min(overall.values()), 1),
)
print(
    "prompt tok/task range (k):",
    round(min(ptok.values()) / 1000, 1),
    "-",
    round(max(ptok.values()) / 1000, 1),
)
print("wrote: fig_heatmap.png fig_difficulty.png fig_compute.png fig_size.png")
