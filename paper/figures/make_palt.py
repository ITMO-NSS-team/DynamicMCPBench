"""Render the P_alt distractor-robustness figure (fig:palt, appendix).

Reads the committed E8.9 numbers (docs/experiments/e8.9_numbers.json): for each
model, accuracy and SAE rate as the fraction of the offered tool pool that is
spurious alternatives (P_alt) sweeps 0 -> 1. Both stay flat -- agents are robust
to distractor density and SAE never leaves the floor.

Run:  uv run --with matplotlib python paper/figures/make_palt.py
Output: fig_palt.png  (\\includegraphics'd by sections/appendix.tex)
"""

from __future__ import annotations

import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
with open(os.path.join(ROOT, "docs", "experiments", "e8.9_numbers.json")) as _f:
    DATA = json.load(_f)

INK = "#1a1a1a"
# Okabe-Ito, 5 distinct colour-blind-safe hues
COLORS = ["#0072B2", "#D55E00", "#009E73", "#E69F00", "#CC79A7"]
plt.rcParams.update(
    {
        "figure.dpi": 150,
        "savefig.dpi": 200,
        "savefig.bbox": "tight",
        "font.size": 11,
        "font.family": "sans-serif",
        "font.sans-serif": ["DejaVu Sans", "Arial"],
        "axes.titlesize": 13,
        "axes.titleweight": "bold",
        "axes.titlepad": 9,
        "axes.labelcolor": INK,
        "axes.edgecolor": "#9aa0a6",
        "axes.linewidth": 0.8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.axisbelow": True,
        "axes.grid": True,
        "grid.color": "#e8e8e8",
        "grid.linewidth": 0.9,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "text.color": INK,
        "legend.frameon": False,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
    }
)

curves = DATA["g3_1_p_alt_curves"]
models = [m for m in curves if not m.startswith("_")]
pa = [0.0, 0.25, 0.5, 0.75, 1.0]
pak = ["0.0", "0.25", "0.5", "0.75", "1.0"]

fig, (axA, axS) = plt.subplots(1, 2, figsize=(11, 4.0))
for m, c in zip(models, COLORS, strict=True):
    acc = [curves[m][k]["acc"] for k in pak]
    sae = [curves[m][k]["sae"] for k in pak]
    axA.plot(pa, acc, "-o", color=c, ms=6, mec="white", mew=1.0, lw=2.0, label=m, zorder=3)
    axS.plot(pa, sae, "-o", color=c, ms=6, mec="white", mew=1.0, lw=2.0, label=m, zorder=3)

axA.set_title("accuracy is flat under distractor pressure")
axA.set_ylabel("pass$^3$ (%)")
axA.set_ylim(40, 66)
axS.set_title("server confusion stays at the floor")
axS.set_ylabel("SAE rate (%)")
axS.set_ylim(-0.3, 5)
for ax in (axA, axS):
    ax.set_xlabel("$P_\\mathrm{alt}$ (fraction of tool pool that is spurious alternatives)")
    ax.set_xticks(pa)
axA.legend(loc="lower left", ncol=2, fontsize=8.5, handlelength=1.4, columnspacing=1.0)
fig.tight_layout()
fig.savefig(os.path.join(HERE, "fig_palt.png"))
plt.close(fig)
print("wrote fig_palt.png |", len(models), "models")
