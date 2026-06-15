# RQ4 annotation — quickstart

You're one of 6 raters validating the benchmark's automatic scorer
against human judgement. **~100 cells, ~2–4 hours.** Here's the whole flow.

## 1. Get the files

```bash
git clone https://github.com/ITMO-NSS-team/DynamicMCPBench.git
cd DynamicMCPBench/annotations/rq4
```

Your roster name is one of: **alpha, beta, gamma, delta, epsilon, zeta**
(your coordinator tells you which). Two files are yours:

- `rq4_worksheet_<you>.md` — **read** this (the tasks + what each agent did)
- `rq4_annotations_<you>.csv` — **fill** this (your verdicts)

## 2. Judge each cell

Open your worksheet. Each **cell** shows one agent's attempt at one task:
the **prompt**, the agent's **tool calls + results**, and its **final
answer**. For each, decide:

> **Did the agent actually accomplish the task — as shown by its tool
> calls and their results?**

- **`pass`** — it did the work. (Awkward wording is fine if the work is there.)
- **`fail`** — a confident answer with no/with-wrong tool calls behind it,
  or the results don't support the claim, or it never got the needed data.

⚠️ Judge the **work**, not how convincing the final text sounds. A
polished answer with zero real tool calls is a **fail**.

## 3. Record verdicts

In `rq4_annotations_<you>.csv`, for each `cell_id` fill:

| column | what |
|---|---|
| `verdict` | `pass` or `fail` (required, lowercase) |
| `justification` | 1–3 sentences why (required) |
| `minutes_spent` | rough number (optional) |

Edit it in any spreadsheet app or text editor. Leave a row blank only if
you truly can't decide — don't guess.

**Calibrate first:** with the two others on your worksheet, do the **first
10 cells together**, compare, and align on the bar. Then do the rest
**independently** — no discussion. That independence is what makes the
result meaningful.

## 4. Send it back

Email/share your filled `rq4_annotations_<you>.csv`, or:

```bash
git checkout -b rq4-<you>
git add annotations/rq4/rq4_annotations_<you>.csv
git commit -m "rq4 annotations: <you>"
git push origin rq4-<you>
```

That's it — thank you! Full protocol & agreement targets:
`docs/experiments/RQ4_ANNOTATOR_GUIDE.md`.
