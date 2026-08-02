# CR 3.4 — cross-model scorer-strictness annotation

Camera-ready item 3.4, promised to reviewer 1npx: *"this covers one model, so we
cannot yet show the strictness is model-independent … we will validate that for
the camera-ready."*

## What this measures

Both strata of the scorer's disagreement with humans, per model:

- **P(human passes | scorer failed)** — the conservatism the paper discloses as a
  lower bound. This is where the disagreement lives, so it carries most of the
  sample: 60 cards per model.
- **P(human passes | scorer passed)** — 10 cards per model. Small, because the
  first pass already put it at 95% precision, but not zero: without it the human
  pass rate cannot be reconstructed, and the claim we made to the reviewer was
  that the strictness moves *the level, not the ordering*. Measuring only the
  fail side would leave the ordering half assumed.

## Design

| | |
|---|---|
| models | `gemma4-31b` (42.5), `qwen3-8b` (22.1), `smollm3-3b` (7.2) |
| baseline for comparison | `qwen3.6-35b` (48.5), already annotated in the first pass |
| unique cards | 210 — per model: 60 scorer-FAIL (4 per category) + 10 scorer-PASS |
| shared reliability set | 20 cards, 3 votes each |
| total judgments | **240** |
| per rater | **38 to 42 cards** |

Three new models plus the baseline give four points spanning 7 to 49 pass^3,
which is what the claim needs: the strictness moves the level, not the ordering.

All three have complete released candidate traces (750 tasks x 3 repeats), so
the sample is drawn from the whole slice rather than from whatever was available.

Every category is covered equally for every model, with the same allocation, so a
difference between models is a difference in strictness and not in which tasks
each model happened to fail. The pass stratum is spread round-robin over
categories so no single category carries it. First attempt only, one card per
task, seed 0.

## Load, against the first pass

The first pass was 975 cards over 6 raters, about 162 each, with three questions
per card. This is about 40 each with **one** question, since task validity and
reference correctness are already measured on the same 750 tasks.

## Running it

Same instrument as before:

```bash
uv run python scripts/annotate2.py run --file annotate_<name>_v2.jsonl
uv run python scripts/annotate2.py submit --file annotate_<name>_v2.jsonl
uv run python scripts/annotate2.py report --suffix _v2 --pull
```

Assignments are the `annotate_<rater>_v2.jsonl` files here; copy the one with
your name to the repo root (or pass `--file`).

**The `_v2` is load-bearing.** Raters reuse their names across studies, so a
submission named `annotate_delta.jsonl` would overwrite the first pass's raw
data on the hub. `submit` now refuses to replace an existing submission unless
you pass `--force`, and `report --suffix _v2` keeps the two passes apart. The single question that matters is Q3,
*do you agree with the auto-grader*. Most cards are shown as FAIL, where `no`
means you would have passed the run; a minority are shown as PASS, where `no`
means you would have failed it. Read the shown verdict before answering.

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

The human pass rate per model is then
`P(auto-pass) x P(human pass | auto-pass) + P(auto-fail) x P(human pass | auto-fail)`,
with the first factor taken exactly from the leaderboard and the other two from
this package. Rank the models by that and compare with the published ordering:
that, and not the fail-side rate alone, is what the promise to the reviewer said.
The pass stratum is 10 cards per model, so it bounds a large deviation from 95%
and nothing finer.
