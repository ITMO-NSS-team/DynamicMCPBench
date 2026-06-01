"""Comparison-only baselines for DynamicMCPBench (RQ2).

These modules implement alternative TaskSpec generators (graph-sampling /
back-instruction, direct generation, ...) so the forward-exploration headline
can be quantitatively compared against the closest prior-art shapes. They are
**not** the project's headline path — see
`memory/feedback_agb_orthogonality.md`. Every spec produced here is labeled
with `distiller_version` starting with `baseline-` so reports cannot confuse
forward-distilled and baseline-back-instructed specs.
"""

from __future__ import annotations
