"""Render the data figures for Section 4 from the released HuggingFace dataset.

Inputs (the TokenWasteGroup/DynamicMCPBench dataset, also cached locally):
  <data>/leaderboard_api/matrix.json      8 API models  x 15 categories (pass^3)
  <data>/leaderboard_local/matrix.json 16 local models x 15 categories (pass^3)
  <data>/leaderboard_*/verdicts/*.jsonl      per-run EvaluationResult rows
  <data>/specs.jsonl                          task specs (complexity.trace_depth)

Outputs (committed PNGs, \\includegraphics'd by sections/results.tex):
  fig_heatmap.png     pass^3 by model x task category (flagship)
  fig_difficulty.png  accuracy vs task length | accuracy by task category
  fig_compute.png     accuracy vs prompt tokens per task
  fig_size.png        accuracy vs model size (local; appendix)
  fig_failure.png     failure-mode taxonomy | IAE rate vs accuracy (appendix)

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
import numpy as np  # noqa: E402

DATA = os.environ.get("DMCP_DATA", "/tmp/hf2")
OUT = os.path.dirname(os.path.abspath(__file__))

# ---- house style: clean, cohesive, colour-blind-friendly (Okabe-Ito) ----
INK = "#1a1a1a"
PALETTE = {"blue": "#0072B2", "vermillion": "#D55E00", "green": "#009E73", "orange": "#E69F00"}
HEATMAP_CMAP = "viridis"
plt.rcParams.update(
    {
        "figure.dpi": 150,
        "savefig.dpi": 200,
        "savefig.bbox": "tight",
        "font.size": 11,
        "font.family": "sans-serif",
        "font.sans-serif": ["DejaVu Sans", "Arial", "Helvetica"],
        "axes.titlesize": 14,
        "axes.titleweight": "bold",
        "axes.titlepad": 10,
        "axes.labelsize": 11,
        "axes.labelcolor": INK,
        "axes.edgecolor": "#9aa0a6",
        "axes.linewidth": 0.8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.axisbelow": True,
        "axes.grid": True,
        "axes.grid.axis": "y",
        "grid.color": "#e8e8e8",
        "grid.linewidth": 0.9,
        "xtick.color": INK,
        "ytick.color": INK,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "text.color": INK,
        "legend.frameon": False,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
    }
)


# ---- load the two leaderboards (pass^3 per model x category cell) ----
def _load_json(p):
    with open(p) as f:
        return json.load(f)


boards = {b: _load_json(f"{DATA}/{b}/matrix.json") for b in ("leaderboard_api", "leaderboard_local")}
STRATS = boards["leaderboard_api"]["strategies"]
cells = {}
overall = {}  # model -> overall pass^3
group = {}  # model -> "API"/"local"
for b, tag in (("leaderboard_api", "API"), ("leaderboard_local", "local")):
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
etax = collections.Counter()  # pooled auto-classified failure-mode counts
iae_tot = collections.defaultdict(lambda: [0, 0])  # model -> [iae events, opportunities]
mine_present = mine_hit = 0  # runs with a minefield available / that invoked one
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
            s = r.get("summary") or {}
            c = s.get("cost") or {}
            if c.get("prompt_tokens"):
                toks.append(c["prompt_tokens"])
            for k, v in (s.get("error_taxonomy") or {}).get("counts", {}).items():
                etax[k] += v
            iae = s.get("iae") or {}
            iae_tot[mdl][0] += iae.get("total", 0)
            iae_tot[mdl][1] += iae.get("opportunities", 0)
            if s.get("minefields_total", 0) > 0:
                mine_present += 1
                mine_hit += s.get("minefields_hit", 0) > 0
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
vmax = max(max(r) for r in M)
fig, ax = plt.subplots(figsize=(12, 9))
im = ax.imshow(M, aspect="auto", cmap=HEATMAP_CMAP, vmin=0, vmax=vmax)
ax.set_xticks(range(len(cats)))
ax.set_xticklabels([catlabel[s] for s in cats], rotation=40, ha="right", fontsize=9)
ax.set_yticks(range(len(models)))
ax.set_yticklabels(models, fontsize=9)
# crisp white separators between cells; drop the inherited y-grid and the frame
ax.set_xticks([j - 0.5 for j in range(len(cats) + 1)], minor=True)
ax.set_yticks([i - 0.5 for i in range(len(models) + 1)], minor=True)
ax.grid(which="major", visible=False)
ax.grid(which="minor", color="white", linewidth=0.8)
ax.tick_params(which="minor", length=0)
ax.tick_params(which="major", length=0)
for sp in ax.spines.values():
    sp.set_visible(False)
for i in range(len(models)):
    for j in range(len(cats)):
        v = M[i][j]
        ax.text(
            j,
            i,
            f"{round(100 * v)}",
            ha="center",
            va="center",
            fontsize=6.5,
            color="white" if v < 0.55 * vmax else INK,
        )
# divider between the API and local model groups
ax.axhline(len(api) - 0.5, color=INK, linewidth=1.3)
ax.set_xlabel("task category")
ax.set_ylabel("model")
ax.set_title("pass$^3$ accuracy by model and task category (%)")
cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02)
cb.set_label("pass$^3$")
cb.outline.set_visible(False)
fig.tight_layout()
fig.savefig(f"{OUT}/fig_heatmap.png")
plt.close(fig)

# ====================== FIG: difficulty (2 panels) ======================
fig, (axL, axR) = plt.subplots(1, 2, figsize=(11, 4.2))
xlab = ["short\n(1-2)", "medium\n(3-4)", "long\n(5+)"]
axL.plot(xlab, length_pct, "-", lw=2.6, color=PALETTE["blue"], zorder=3)
axL.plot(xlab, length_pct, "o", ms=11, color=PALETTE["blue"], mec="white", mew=1.6, zorder=4)
axL.set_ylim(0, max(length_pct) * 1.25)
axL.set_xlabel("task length (tool-chain depth)")
axL.set_ylabel("pass$^3$ (%)")
axL.set_title("accuracy vs task length")
axL.grid(axis="y")
for x, y in enumerate(length_pct):
    axL.annotate(
        f"{y:.0f}%",
        (x, y),
        textcoords="offset points",
        xytext=(0, 11),
        ha="center",
        fontweight="bold",
        color=PALETTE["blue"],
    )
order = sorted(cats, key=lambda s: cat_mean[s])
vals = [100 * cat_mean[s] for s in order]
cmap = plt.get_cmap(HEATMAP_CMAP)
norm = plt.Normalize(min(vals) * 0.6, max(vals))
bars = axR.barh(
    [catlabel[s] for s in order],
    vals,
    color=[cmap(norm(v)) for v in vals],
    edgecolor="white",
    linewidth=0.6,
)
axR.set_xlabel("mean pass$^3$ (%)")
axR.set_title("accuracy by task category")
axR.tick_params(axis="y", labelsize=9)
axR.grid(axis="x")
axR.set_xlim(0, max(vals) * 1.12)
for b, v in zip(bars, vals, strict=True):
    axR.text(v + 0.5, b.get_y() + b.get_height() / 2, f"{v:.0f}", va="center", fontsize=8, color="#555")
fig.tight_layout()
fig.savefig(f"{OUT}/fig_difficulty.png")
plt.close(fig)

# ============================ FIG: compute ============================
fig, ax = plt.subplots(figsize=(6.4, 4.6))
for tag, color in (("API", PALETTE["vermillion"]), ("local", PALETTE["blue"])):
    xs = [ptok[m] / 1000 for m in models if group[m] == tag and m in ptok]
    ys = [100 * overall[m] for m in models if group[m] == tag and m in ptok]
    ax.scatter(xs, ys, s=72, color=color, label=tag, alpha=0.9, edgecolor="white", linewidth=1.2, zorder=3)
ax.set_xlabel("prompt tokens per task (thousands)")
ax.set_ylabel("pass$^3$ (%)")
ax.set_title("accuracy vs compute per task")
ax.grid(axis="both")
ax.legend(title="model class")
fig.tight_layout()
fig.savefig(f"{OUT}/fig_compute.png")
plt.close(fig)

# ====================== FIG: size (local; appendix) ======================
fig, ax = plt.subplots(figsize=(6.4, 4.6))
sx, sy = [], []
for m in loc:
    mm = re.search(r"(\d+)b", m)
    if mm:
        sx.append(int(mm.group(1)))
        sy.append(100 * overall[m])
ax.scatter(sx, sy, s=72, color=PALETTE["blue"], alpha=0.9, edgecolor="white", linewidth=1.2, zorder=3)
ax.set_xlabel("model size (billion parameters)")
ax.set_ylabel("pass$^3$ (%)")
ax.set_title("accuracy vs model size")
ax.grid(axis="both")
fig.tight_layout()
fig.savefig(f"{OUT}/fig_size.png")
plt.close(fig)

# ================== FIG: failure analysis (2 panels; appendix) ==================
# Left: pooled auto-classified failure modes. Right: IAE rate vs accuracy.
# Active modes only (E1/E2/E5 are unpopulated: E2 is not auto-classified in v0,
# and prerequisite/ordering checkpoints are rare in this corpus).
FMODE = {
    "E3": ("incomplete\naggregation", PALETTE["vermillion"]),
    "E6": ("tool-blindness", PALETTE["orange"]),
    "E7": ("argument\nhallucination", PALETTE["green"]),
    "E4": ("server confusion\n(SAE)", PALETTE["blue"]),
}
active = sorted(FMODE, key=lambda k: -etax[k])
etot = sum(etax.values()) or 1
shares = [100 * etax[k] / etot for k in active]
fig, (axL, axR) = plt.subplots(1, 2, figsize=(11, 4.4))
axL.barh(range(len(active)), shares, color=[FMODE[k][1] for k in active], edgecolor="white")
axL.set_yticks(range(len(active)))
axL.set_yticklabels([FMODE[k][0] for k in active], fontsize=10)
axL.invert_yaxis()
axL.set_xlabel("share of classified failures (%)")
axL.set_title("how agents fail")
axL.grid(axis="x")
axL.set_xlim(0, max(shares) * 1.15)
for i, v in enumerate(shares):
    axL.text(v + 1, i, f"{v:.0f}%", va="center", fontsize=9, color="#555")
ix = {m: 100 * iae_tot[m][0] / max(iae_tot[m][1], 1) for m in models}
for tag, color in (("API", PALETTE["vermillion"]), ("local", PALETTE["blue"])):
    gx = [ix[m] for m in models if group[m] == tag]
    gy = [100 * overall[m] for m in models if group[m] == tag]
    axR.scatter(gx, gy, s=62, color=color, label=tag, alpha=0.9, edgecolor="white", linewidth=1.0, zorder=3)
xs = np.array([ix[m] for m in models])
ys = np.array([100 * overall[m] for m in models])
rr = float(np.corrcoef(xs, ys)[0, 1])
sl, ic = np.polyfit(xs, ys, 1)
xr = np.array([xs.min(), xs.max()])
axR.plot(xr, sl * xr + ic, color=INK, lw=1.5, ls="--", zorder=2)
axR.text(
    0.96,
    0.95,
    f"r = {rr:.2f}",
    transform=axR.transAxes,
    ha="right",
    va="top",
    fontsize=13,
    fontweight="bold",
)
axR.set_xlabel("incomplete-aggregation rate (%)")
axR.set_ylabel("pass$^3$ (%)")
axR.set_title("aggregation failure predicts accuracy")
axR.grid(axis="both")
axR.legend(title="model class", loc="lower left")
fig.tight_layout()
fig.savefig(f"{OUT}/fig_failure.png")
plt.close(fig)
print("failure modes (% of classified):", [(k, round(100 * etax[k] / etot, 1)) for k in active])
_mr = 100 * mine_hit / mine_present
print(f"IAE-accuracy r = {rr:.3f} | minefield hit {mine_hit}/{mine_present} ({_mr:.2f}%)")

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
