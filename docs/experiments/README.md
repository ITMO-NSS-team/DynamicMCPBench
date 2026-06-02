# Experiment & validation reports

Every experiment, RQ, or empirical validation in DynamicMCPBench produces a
committed report here — **including negative or failed results**. A "fail" is a
finding, not something to bury: silently dropping a negative result is forbidden
(see the Results rule in `CLAUDE.md` / `docs/AUTONOMY.md`).

## Rules

- One report per experiment: `docs/experiments/<step-id>-<slug>.md` (e.g.
  `e1.4a-persona-diversity.md`).
- A step that makes an empirical claim is **not `done` until its report is
  committed** with a result.
- The report must contain:
  1. **Question / hypothesis** — what is being tested.
  2. **Method** — conditions, sample size, seeds, models, and the **exact
     reproduce command(s)**.
  3. **Decision rule** — pre-registered *before* running (what counts as
     positive / neutral / negative), to avoid p-hacking.
  4. **Data** — the numbers / table.
  5. **Result** — classified **positive | neutral | negative**.
  6. **Conclusion & implication** — what we now believe; what changes.
- **Raw artifacts stay out of git** (`traces/ specs/ evals/ reports/ crawled/`
  are git-ignored and regenerable). Commit only the report + distilled numbers
  (and, if small and useful, a snapshot under this folder).
- Pre-register before you run: write the report with method + decision rule and
  `status: planned`, then fill `status: done` + data + result after running.

## Template

```markdown
# <Title> (<step-id>)
- status: planned | done
- result: — | positive | neutral | negative

## Question / hypothesis
## Method (+ reproduce command)
## Decision rule (pre-registered)
## Data
## Result
## Conclusion & implication
```

## Index

- `e1.4a-persona-diversity.md` — does persona seeding raise goal diversity?
- `e4.3-rq2-comparison.md` — RQ2 forward vs graph vs direct generation-quality.
- `e4.4-rq1-comparison.md` — RQ1 answer-match vs trace-align (Kendall's τ, false-pass / false-fail).
- `e4.5-rq3-failure-model.md` — RQ3 trace-property failure model (coefficients + permutation importance).
