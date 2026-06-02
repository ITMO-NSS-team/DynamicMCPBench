# Paper scaffold for DynamicMCPBench (EMNLP 2026 Industry Track)

This directory holds the LaTeX source for the DynamicMCPBench paper,
targeted at the **EMNLP 2026 Industry Track**. Empirical numbers flow
in from `docs/experiments/<id>_numbers.json` via the figure/table
regenerator (`paper/regenerate.py`); section prose is hand-edited.

## Layout

| path | role |
|---|---|
| `main.tex` | top-level paper; loads `acl.sty` in `[review]` mode and `\input`s every section |
| `sections/<name>.tex` | one file per paper section (abstract, introduction, related_work, method, substrate, experiments, discussion, conclusion, limitations) |
| `figures/<slug>.tex` | LaTeX `figure` block per `fig:<slug>` row in `figures.md` — regenerated, do not hand-edit |
| `tables/<slug>.tex` | LaTeX `table` block per `tab:<slug>` row in `figures.md` — regenerated, do not hand-edit |
| `figures.md` | the figure/table **index and contract** (status, gating step, data source); the regenerator reads this file |
| `regenerate.py` | parses `figures.md`, dispatches each row to a per-id renderer, writes the `.tex` artifacts; cross-reference validator scans `sections/*.tex` for `\input{figures/...}` / `\input{tables/...}` |
| `custom.bib` | hand-curated bibliography; `anthology.bib.txt` is the ACL Anthology mirror |
| `acl.sty`, `acl_natbib.bst`, `acl_latex.tex`, `acl_lualatex.tex` | the upstream ACL template files (do **not** modify per ACL policy) |
| `formatting.md` | upstream ACL formatting reference |

## Building

```
cd paper
pdflatex main
bibtex   main
pdflatex main
pdflatex main
```

Section files include figures/tables via `\input{figures/<slug>}` /
`\input{tables/<slug>}` (no extension — LaTeX adds `.tex`). The working
directory is `paper/` so the paths resolve.

Regenerate the figure/table artifacts whenever a `docs/experiments/*_numbers.json`
or `manifests/local.json` is updated:

```
uv run dmcp paper-figures
```

The regenerator is idempotent (re-running on unchanged data produces
byte-identical artifacts). Rows whose backing data isn't on disk yet
emit a clearly-marked placeholder so the `\ref{...}` still resolves.

## How the paper assembles

1. **Empirical numbers** live exclusively in `docs/experiments/*.md`
   and `docs/experiments/*_numbers.json`. Section prose cites the
   experiment id (e.g. *"e4.4 measured Kendall's $\tau$ = -0.816"*);
   the actual number is rendered by `regenerate.py` into a figure or
   table that the section `\input`s.
2. **Hard invariants** that the paper claims live in `CLAUDE.md` and
   `memory/feedback_agb_orthogonality.md`. The AGB-contrast paragraph
   in `sections/related_work.tex` is sourced verbatim from the
   four-pillars table there so the orthogonality story stays in sync.
3. **Figure / table identifiers** (`fig:pipeline`, `tab:rq2_comparison`,
   ...) are the join key across `figures.md`, `regenerate.py`'s
   renderer dispatch, the generated `.tex` artifacts, and the `\ref{...}`
   citations in section files. The cross-reference validator
   (`paper/regenerate.py::validate_cross_references`) enforces this on
   every regenerate.

## When this scaffold changes

A step that **adds** a figure or table:

1. Add a row to `figures.md` with a stable `fig:` or `tab:` id, status,
   gating-step pointer, and data-source pointer.
2. Register a renderer in `regenerate.py::RENDERERS` (or rely on the
   placeholder fall-through for `pending` / `manual` rows).
3. `\input{figures/<slug>}` or `\input{tables/<slug>}` in the
   relevant section file and `\ref{fig:slug}` / `\ref{tab:slug}` in the
   prose.

A step that **updates** an existing figure's data only touches the
backing `docs/experiments/<id>_numbers.json` and re-runs
`dmcp paper-figures`. The section prose never copies numbers from the
JSON.

---

# EMNLP 2026 Industry Track rules

The source for the rules below is the official call for papers:
<https://2026.emnlp.org/calls/industry_track/>. Quoted phrases are
verbatim. These rules **govern this submission** — every PR that
touches `paper/` is bound by them.

## Scope

> "design, development, deployment, or analysis of NLP and speech
> systems in real-world settings"

Papers should address "practical challenges related to the deployment
of language processing and generation systems" in non-laboratory
environments. The track accepts both academic and industry authors and
welcomes **negative results** and **vision papers grounded in deployment
experience**.

## Page limits

- **6 pages maximum** for the main paper.
- The **References** and **Limitations** sections do **not** count
  toward the 6-page limit.
- Optional sections that also do not count: acknowledgements (final
  version only), ethical considerations, appendices.
- Accepted papers receive **one additional page** (up to 7 pages
  total) for revisions.

`main.tex` is structured so the 6-page budget is respected by the
hand-edited section files; `sections/limitations.tex` is the mandatory
non-counted section.

## Format

- Must use the official ACL template files from
  <https://acl-org.github.io/ACLPUB/formatting.html>. These are the
  `acl.sty` / `acl_latex.tex` / `acl_natbib.bst` files in this directory.
- "Submissions violating style requirements will be desk-rejected."
- **Do not modify the ACL style files** (`acl.sty`,
  `acl_natbib.bst`) — vendored as-is per ACL policy.

## Anonymisation (double-blind)

- Submissions "must neither include the authors' names nor their
  affiliations."
- Self-references that would reveal identity are forbidden — use
  "Smith (1991) previously showed" instead of "We previously showed
  (Smith, 1991)."
- Code references must point to **anonymous** repositories (e.g.
  Anonymous GitHub).
- "Papers that do not conform to these requirements will be
  desk-rejected."

The default `\usepackage[review]{acl}` directive in `main.tex` enables
the anonymous review mode; switch to `[final]` (or omit the option)
**only** for the camera-ready version.

## Mandatory Limitations section

- A dedicated **Limitations** section is required, placed **before
  references**.
- "Papers without a limitations section will be desk-rejected."

`sections/limitations.tex` is wired in `main.tex` immediately before
the bibliography. **Do not delete it.**

## Submission

- Submit via OpenReview:
  <https://openreview.net/group?id=EMNLP/2026/Industry_Track>.
- Original, **unpublished** work only.
- Papers under review elsewhere are ineligible.
- Multiple-submission policy: "Submissions of identical or closely
  related work to multiple EMNLP 2026 tracks ... will be treated as
  duplicate submissions" and rejected without review.

## Reproducibility and evaluation

- "For papers that rely heavily on empirical evaluations, the
  experimental methods and results should be clear, well-executed, and
  reproducible (though the data may be proprietary)."
- Pay specific attention to evaluation methodology (human vs.
  automated).

DynamicMCPBench's pre-registered decision rules
(`docs/experiments/<id>-*.md`) plus the regenerator-from-JSON pipeline
satisfy this rule by construction; do not hand-write numbers into
section files.

## Ethics

- Papers must honour the ACL Code of Ethics.
- Sensitive data or tasks require an "explicit discussion of these
  issues."
- An optional ethical-considerations section is permitted **beyond**
  the 6-page limit.

## Deadlines (AoE = UTC-12, i.e. 11:59 PM UTC-12:00)

| event | date |
|---|---|
| submission | **June 16, 2026** |
| review release / rebuttal begins | July 22, 2026 |
| author response deadline | July 29, 2026 |
| acceptance notification | August 20, 2026 |
| camera-ready | September 20, 2026 |
| conference | October 24--29, 2026 (Budapest) |

## Conference presentation

- "All accepted papers must be presented at the conference (either via
  online or in-person presence)."
- At least one author must register by the early registration deadline.
- Oral or poster is determined by the program committee.
