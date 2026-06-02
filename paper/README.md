# Paper scaffold for DynamicMCPBench

This directory holds the **paper skeleton** that the rest of the project
writes into. It is intentionally markdown (not LaTeX) at this stage so
that:

- it round-trips cleanly with `docs/CONCEPT.md` and the experiment reports
  in `docs/experiments/`;
- E5.2 (`auto-generated figures & tables`) can edit it without parsing
  LaTeX;
- a final LaTeX conversion (NeurIPS or EMNLP style file) is a single
  pandoc-like pass at the end, against a frozen content snapshot.

## Files

| file | role |
|---|---|
| `README.md` (this) | scaffold meta, how the paper is assembled |
| `draft.md` | the §1–§7 skeleton — section abstracts, claims, AGB contrast, figure / table placeholders inlined where they belong |
| `figures.md` | explicit index of every figure / table — id, caption, status, data source. The input contract for E5.2. |

## How the paper assembles

1. **Empirical numbers** live exclusively in `docs/experiments/*.md` and
   `docs/experiments/*_numbers.json`. The paper never re-derives them; it
   cites the experiment id (e.g. *"e4.4 measured Kendall's τ = −0.816"*).
   When E5.2 lands it will read the JSONs to regenerate the figure
   payloads deterministically.
2. **Hard invariants** that the paper claims live in
   `CLAUDE.md` and `memory/feedback_agb_orthogonality.md`. The AGB-contrast
   paragraph in `draft.md §2` is sourced verbatim from the four pillars
   table there so the orthogonality story stays in sync.
3. **Figure / table identifiers** are stable across this scaffold and the
   future LaTeX render (`fig:pipeline`, `tab:rq2`, …). E5.2 binds them
   to actual rendered artifacts.

## Status of each section

| section | status | gated by |
|---|---|---|
| §1 Introduction | drafted skeleton | finalized once §5 lands |
| §2 Related work + AGB contrast | drafted skeleton | none — AGB contrast is the headline differentiator |
| §3 Method | drafted skeleton | E0 / E1 / E2 — pipeline is built |
| §4 Substrate | drafted skeleton | E3 (≥ 100 servers) — currently 16 |
| §5 Experiments (RQ1–RQ4) | partial — RQ1/RQ2/RQ3 have data, RQ4 awaits annotators | E4.6 (annotation pass), E4.7 (leaderboard), E1.5 (decay) |
| §6 Discussion | drafted skeleton | follows §5 |
| §7 Limitations + Conclusion | drafted skeleton | follows §6 |

A step that needs to add to the paper writes into `draft.md` directly,
cites the experiment id in `docs/experiments/`, and updates the
corresponding row in `figures.md`. A step that produces a new figure or
table from data adds a row to `figures.md` and references it in
`draft.md`. Empirical claims **never** appear in `draft.md` without a
backing experiment row.

## Future LaTeX conversion

Out of scope for E5.1 — the scaffold is markdown. When the paper is ready
to render, the conversion will be:

```
pandoc --standalone --filter pandoc-crossref \
       paper/draft.md -o paper/draft.tex --template neurips_2026
```

(NeurIPS / EMNLP template choice is deferred to whichever venue we
target; that decision blocks on §5 being complete.)
