"""Render the DynamicMCPBench pipeline diagram (fig:pipeline, Introduction).

Standalone and data-free (unlike make_figures.py): the forward-generative,
trace-grounded flow from docs/CONCEPT.md section 3 ---
  live MCP servers -> forward exploration (-> execution trace)
  -> distill (-> effect checkpoints) -> replay & evaluate
  -> effect-based score, with a refresh / living-bench loop.

Run:  uv run --with matplotlib python paper/figures/make_pipeline.py
Output: fig_pipeline.png  (\\includegraphics'd by sections/introduction.tex)
"""

from __future__ import annotations

import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

OUT = os.path.dirname(os.path.abspath(__file__))
INK = "#1a1a1a"
GREY = "#5a5f66"
PALETTE = {"blue": "#0072B2", "vermillion": "#D55E00", "green": "#009E73", "orange": "#E69F00"}
plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["DejaVu Sans", "Arial"]})


def _tint(hex_color, a=0.12):
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))
    return (1 - a + a * r, 1 - a + a * g, 1 - a + a * b)


# stage: (title, subtitle, accent colour)
STAGES = [
    ("Live MCP servers", "crawl · install · vet\nstatic · live · stateful", PALETTE["blue"]),
    ("Forward exploration", "goal-seeded agent drives\ntools → execution trace", PALETTE["vermillion"]),
    ("Distill → TaskSpec", "effect checkpoints, minefields,\npartial order", PALETTE["orange"]),
    ("Replay & evaluate", "candidate agent on\ndeterministic replay", PALETTE["green"]),
    ("Effect-based score", "reproduce effects, not the\nanswer → leaderboard", PALETTE["blue"]),
]

W, H, GAP = 2.35, 1.5, 0.55
xs = [0.5 + i * (W + GAP) + W / 2 for i in range(len(STAGES))]
ymid = 1.65
fig, ax = plt.subplots(figsize=(13.0, 3.4))
ax.set_xlim(0, xs[-1] + W / 2 + 0.5)
ax.set_ylim(-0.75, 3.2)
ax.axis("off")

for x, (title, sub, accent) in zip(xs, STAGES, strict=True):
    box = FancyBboxPatch(
        (x - W / 2, ymid - H / 2),
        W,
        H,
        boxstyle="round,pad=0.02,rounding_size=0.14",
        linewidth=1.6,
        edgecolor=accent,
        facecolor=_tint(accent),
        zorder=2,
    )
    ax.add_patch(box)
    ax.text(x, ymid + 0.40, title, ha="center", va="center", fontsize=12.5, fontweight="bold", color=accent)
    ax.text(x, ymid - 0.18, sub, ha="center", va="center", fontsize=9.0, color=INK, linespacing=1.3)

# forward arrows between stages
for xa, xb in zip(xs[:-1], xs[1:], strict=True):
    ax.add_patch(
        FancyArrowPatch(
            (xa + W / 2 + 0.04, ymid),
            (xb - W / 2 - 0.04, ymid),
            arrowstyle="-|>",
            mutation_scale=18,
            linewidth=2.0,
            color=GREY,
            zorder=1,
        )
    )


# phase brackets above
def bracket(x0, x1, label, color):
    y = ymid + H / 2 + 0.30
    ax.plot([x0, x0, x1, x1], [y - 0.08, y, y, y - 0.08], color=color, linewidth=1.3, zorder=1)
    ax.text(
        (x0 + x1) / 2,
        y + 0.12,
        label,
        ha="center",
        va="bottom",
        fontsize=10.5,
        fontweight="bold",
        color=color,
    )


bracket(xs[0] - W / 2, xs[2] + W / 2, "FORWARD GENERATION", PALETTE["vermillion"])
bracket(xs[3] - W / 2, xs[4] + W / 2, "EFFECT-SCORED EVALUATION", PALETTE["green"])

# refresh / living-bench loop underneath
yb = ymid - H / 2
ax.add_patch(
    FancyArrowPatch(
        (xs[4], yb),
        (xs[0], yb),
        connectionstyle="arc3,rad=-0.22",
        arrowstyle="-|>",
        mutation_scale=16,
        linewidth=1.6,
        linestyle=(0, (5, 3)),
        color=PALETTE["blue"],
        zorder=1,
    )
)
ax.text(
    (xs[0] + xs[4]) / 2,
    -0.5,
    "refresh — re-run references, classify drift (living benchmark)",
    ha="center",
    va="center",
    fontsize=9.5,
    style="italic",
    color=PALETTE["blue"],
)

fig.tight_layout(pad=0.4)
fig.savefig(f"{OUT}/fig_pipeline.png", dpi=200, bbox_inches="tight")
plt.close(fig)
print("wrote fig_pipeline.png")
