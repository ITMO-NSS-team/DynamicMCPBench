# RQ4 annotator guide — scorer-vs-human validation

Thank you for annotating! This pass checks whether DynamicMCPBench's
automatic scorer agrees with human judgement about which agent runs
**passed** and which **failed**. Your verdicts are the ground truth the
whole benchmark is measured against, so accuracy matters more than speed.

## What you're judging

Each **cell** is one agent's attempt at one task. You decide: **did the
agent actually accomplish what the prompt asked?**

**Mark `pass` only if the agent did the work, as evidenced by its actual
tool calls and their results** — not because the final answer *sounds*
right. A plausible-sounding final message with no real work behind it is
a **`fail`**. (We've already shown that judging on the final text alone
is misleading — that's the whole point of this benchmark.)

- Did the work but worded the answer awkwardly → **pass** (note the wording).
- Produced a confident answer but the tool calls don't support it → **fail**.
- Called the wrong tools / never got the needed result → **fail**.
- No tool calls at all on a task that required them → **fail**.

## Your materials

You'll receive two files named with your rater id (e.g. `alice`):

| file | use |
|---|---|
| `rq4_worksheet_<you>.md` | **Read this.** One section per cell: the prompt, the agent's tool calls + results, and its final answer. |
| `rq4_annotations_<you>.csv` | **Fill this.** One row per cell; put `pass` or `fail` in the `verdict` column. |

For each cell in the worksheet, find the matching `cell_id` row in your
CSV and fill three columns:

- **`verdict`** — `pass` or `fail` (lowercase, required).
- **`justification`** — 1–3 sentences on *why* (required; it keeps everyone honest).
- **`minutes_spent`** — rough number, for budgeting (optional).

Leave a row blank if you genuinely can't decide — blanks are skipped, not
counted as fail. Don't guess.

## Workload & independence

- Each cell is judged by **3 raters**; the 6 of you are split into two
  triples, each covering ~100 cells. You only annotate your own
  worksheet/CSV.
- **Calibrate first, then go independent.** As a triple, sit down
  together on the **first 10 cells** of your block: each marks them, then
  compare and discuss any disagreements until you share an understanding
  of the pass/fail bar. **Then annotate the remaining cells
  independently** — no discussion, no peeking at each other's CSVs. The
  independence is what makes the agreement statistic meaningful.

## When you're done

Send your filled `rq4_annotations_<you>.csv` back. We ingest all six with:

```bash
python scripts/rq4_annotate.py ingest evals/rq4_annotation/rq4_annotations_*.csv \
  --out evals/rq4_annotations.filled.jsonl
```

…then compute agreement (Cohen's κ, Krippendorff's α, false-pass/fail)
with `dmcp rq4-agreement`. The pre-registered target is **κ ≥ 0.70** for
both scorer tiers; see `docs/experiments/e4.6-rq4-scorer-vs-human.md`.

## For the coordinator — regenerating the packets

```bash
# after candidate traces exist under evals/rq4_gen/ctraces_*.jsonl
python scripts/rq4_annotate.py build \
  --subset evals/rq4_subset.jsonl \
  --assignment evals/rq4_gen/assignment.json \
  --candidate-traces evals/rq4_gen/ctraces_*.jsonl \
  --raters alice bob carol dave erin frank \
  --out evals/rq4_annotation
```

Pass real rater ids to `--raters` (count divisible by 3). Worksheets,
CSVs, the canonical template, and `cells.json` land in `--out`.
