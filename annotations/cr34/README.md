# CR 3.4 — cross-model scorer-strictness annotation

Camera-ready item 3.4, promised to reviewer 1npx: *"this covers one model, so we
cannot yet show the strictness is model-independent … we will validate that for
the camera-ready."*

## What this measures

One quantity: **P(human passes | the deterministic scorer failed)**, per model.

The pass side is not re-annotated. The first pass already established it at 95%
precision, and the disagreement does not live there. Every card in this package
is a run the scorer failed, so the annotation goes straight at the conservatism
the paper discloses as a lower bound.

## Design

| | |
|---|---|
| models | `gemma4-31b` (42.5), `qwen3-8b` (22.1), `smollm3-3b` (7.2) |
| baseline for comparison | `qwen3.6-35b` (48.5), already annotated in the first pass |
| unique cards | 180 — 60 per model, 4 per task category |
| shared reliability set | 20 cards, 3 votes each |
| total judgments | **210** |
| per rater | **33 to 37 cards** |

Three new models plus the baseline give four points spanning 7 to 49 pass^3,
which is what the claim needs: the strictness moves the level, not the ordering.

All three have complete released candidate traces (750 tasks x 3 repeats), so
the sample is drawn from the whole slice rather than from whatever was available.

Every category is covered equally for every model, with the same allocation, so a
difference between models is a difference in strictness and not in which tasks
each model happened to fail. First attempt only, one card per task, seed 0.

## Load, against the first pass

The first pass was 975 cards over 6 raters, about 162 each, with three questions
per card. This is about 35 each with **one** question, since task validity and
reference correctness are already measured on the same 750 tasks.

## Running it

Same instrument as before:

```bash
uv run python scripts/annotate2.py run --rater <name>     # annotate
uv run python scripts/annotate2.py submit --rater <name>  # push when done
```

Assignments are the `annotate_<rater>.jsonl` files here; copy the one with your
name to the repo root (or pass `--file`). The single question that matters is Q3,
*do you agree with the auto-grader* — every card here is shown as a FAIL, so a
`no` means you would have passed the run.

Judge by reading, not by the checkpoint rules. That asymmetry is the measurement.

## Rebuilding

```bash
uv run python scripts/cr34_annotation_package.py --out annotations/cr34
```

Deterministic given the seed. Regenerates from the released corpus, so nothing
here needs to be trusted on faith.

## Reading the result

Compare each model's false-negative rate against the baseline's 49.9% (230 of
461). At 60 cards per model the interval is roughly ±13 points, which is enough
to rule out a large swing between models and not enough to resolve a small one.
Say so in the write-up rather than implying more precision than the sample has.
