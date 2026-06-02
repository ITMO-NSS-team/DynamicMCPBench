# Figures & tables — index and data contract

This file is the **input contract** for the regenerator
(`paper/regenerate.py`). Every figure / table referenced by a
`\input{figures/<slug>}` / `\input{tables/<slug>}` directive in
`paper/sections/*.tex` has a row here with a stable id, the intended
caption, the regenerable data source, and a status flag.

The regenerator reads this file, finds the data source, and writes a
LaTeX artifact under `paper/figures/<slug>.tex` (for `fig:` ids) or
`paper/tables/<slug>.tex` (for `tab:` ids). Section files `\input`
these artifacts; `\ref{<id>}` resolves to the figure or table label
emitted by the renderer.

## Status values

- **ready** — backing data and decision-rule call already committed; the
  figure can be auto-built today.
- **partial** — backing data committed but a follow-up step adds more
  rows / models / strata (so the artifact will be rebuilt then).
- **pending** — backing data not yet committed; the step that produces
  it is the gating step in the third column.
- **manual** — qualitative / illustration figure, no JSON backing —
  authored by hand from the spec described here.

## Figures

| id | caption | status | gating step | data source / notes |
|---|---|---|---|---|
| `fig:pipeline` | DynamicMCPBench pipeline: server manifest → goal-gen → explorer → distiller → evaluator (Tier-1 / Tier-2) → report; the parallel `refresh` arrow for the living-bench loop. | manual | — | Block diagram authored from `paper/sections/method.tex`. Source-of-truth: `docs/CONCEPT.md`. |
| `fig:trace_distill_example` | One worked example: a recorded trace (left) compiled into a `TaskSpec` (right) — checkpoints, equivalence sets, minefields, partial order. | manual | — | Pick one v3 trace (preferably a cross-server one). Source-of-truth: a row from `traces/v3.jsonl` + the matching `specs/v3.jsonl` row. |
| `fig:rq1_kendall` | Per-model trace-align vs answer-match accuracy on the v3 substrate; Kendall's τ between the two rankings. | ready | — | `docs/experiments/e4.4_numbers.json` (kendall_tau_rankings, models[*].trace_accuracy / answer_accuracy). Decision rule in `e4.4-rq1-comparison.md`. |
| `fig:perf_by_dynamism_depth` | Pass rate by (dynamism × complexity_bin), per candidate model + pooled. The visual companion to RQ3's pooled coefficients. | partial | E4.7 (≥ 5-model leaderboard) for the model dimension | Per-model: aggregate `evals/v3_{model}.jsonl::passed` joined with `specs/v3.jsonl::dynamism + complexity.trace_depth → complexity_bin`. The numbers backing the RQ3 coefficients live in `docs/experiments/e4.5_numbers.json`. |
| `fig:p_alt_degradation` | P_alt degradation curves (accuracy vs P_alt and SAE rate vs P_alt) per strategy × level, with Wilson CIs and complexity-bin facets. | pending | E2.7 (P_alt driver, already merged) + an experiment-doc run | `dmcp curve` output: `reports/curve.md` / its JSON form. Wire under `docs/experiments/<id>_numbers.json` when the experiment doc lands. |
| `fig:decay_curve` | Per-server decay over time: drift, broken, identical rates as the substrate ages. | pending | E1.5 (decay metrics + backoff, already merged) + an experiment-doc run on multi-window refresh data | `dmcp refresh` outputs over multiple time windows. Wire via a `docs/experiments/e1.5_numbers.json` once we run it on the v3 substrate. |

## Tables

| id | caption | status | gating step | data source / notes |
|---|---|---|---|---|
| `tab:rq2_comparison` | Forward distillation vs graph-sampling vs direct generate-then-verify, on the offline-derivable axes (mean / max &#124;eq_set&#124;, singleton rate, missing-arg-predicate rate, coverage, filter pass rate, executable-by-construction, ordering density). | ready | — | `docs/experiments/e4.3_numbers.json`. Decision rule in `e4.3-rq2-comparison.md`. |
| `tab:capability_profile` | Per-model accuracy stratified by (dynamism × complexity bin × recovery_required × runtime_branching); ≥ 5 models. | pending | E4.7 (leaderboard) — itself gated on E3.1 | Built from per-model `evals/*.jsonl` once E4.7 produces them. Same input as `fig:perf_by_dynamism_depth`. |
| `tab:rq4_agreement` | Per-tier (Tier-1 / Tier-2) Cohen's κ vs human consensus; Krippendorff's α over the full grid; per-tier false-pass / false-fail rates; replay flip rate. | pending | E4.6 annotation pass | `docs/experiments/e4.6_numbers.json` once the human annotation pass completes. Pre-registered protocol in `e4.6-rq4-scorer-vs-human.md`. |
| `tab:substrate` | Substrate breakdown: server count, by dynamism, by domain (tags), tool counts, mining funnel (registry size → installable → vetted). | partial | E3.5 (substrate coverage report) — itself gated on E3.1 | Built from `manifests/local.json` + future `manifests/crawled.json`. Funnel data lives in `crawled/discovered.jsonl` + `crawled/vetted.jsonl`. |
| `tab:rq3_failure_drivers` | Pooled coefficients + odds ratios + drop-loglik importance for the RQ3 failure model. | ready | — | `docs/experiments/e4.5_numbers.json` (pooled fit). Decision rule in `e4.5-rq3-failure-model.md`. |
| `tab:ablation` | RQ2 / §5 sampling-strategy ablation (random / hard_neg / cross_domain / same_name / sibling / stratified) — accuracy + SAE rate per cell with paired tests. | pending | an experiment doc that exercises `dmcp/ablation.py` (E2.8) on the full substrate | Built from a future `docs/experiments/e2.8_numbers.json` once an ablation report lands. |

## Cross-reference contract

Every `\input{figures/<slug>}` and `\input{tables/<slug>}` directive in
`paper/sections/*.tex` MUST resolve to a `fig:<slug>` / `tab:<slug>`
row in this file. `paper/regenerate.py::validate_cross_references`
enforces this on every run and `dmcp paper-figures --fail-on-pending`
exits non-zero when violations exist.

## When this index changes

A step that adds a figure / table:

1. Adds a row here with a stable `fig:` or `tab:` id (kebab-case after
   the colon).
2. Adds `\input{figures/<slug>}` / `\input{tables/<slug>}` and a
   `\ref{<id>}` citation in the relevant `paper/sections/<name>.tex`.
3. Cites the data source in column 5 — never with a number, only with
   a pointer (e.g. `docs/experiments/<id>_numbers.json`).
4. Registers a renderer in `paper/regenerate.py::RENDERERS` if the
   default placeholder isn't enough.

A step that **updates** an existing figure's data only touches the
backing `docs/experiments/<id>_numbers.json` and re-runs
`dmcp paper-figures`. Section prose never copies numbers from the JSON;
the section text says `\ref{<id>}` and lets the regenerator do the
rest.
