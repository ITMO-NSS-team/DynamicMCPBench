# Distiller fidelity: hand audit of 100 TaskSpecs (cr-distiller-fidelity)
- status: done
- result: positive

## Question / hypothesis

The automatic reference-validation gate (`e9.10`, `docs/experiments/e9.10-reference-validation-gate.md`)
checks **provenance**: it discards any distilled task whose own reference trace
does not produce every effect the spec requires. Reviewers RJAT, sJ7917 and 4Rex
all raised the same objection, and it is about **necessity**, which provenance
does not cover: *a tool appearing in a successful trace is not proof that it was
necessary*. A checkpoint can be grounded and still be redundant, and an
equivalence set can list an alternative that is not in fact effect-equivalent.

Hypothesis: the distiller does not manufacture unnecessary requirements, does
not achieve compression by dropping load-bearing calls, and does not list
non-equivalent alternatives.

## Method (+ reproduce command)

100 TaskSpecs drawn from the released corpus, each audited by hand against its
own reference trace. Within those specs the audit covers:

- the **264** retained `tool_effect` checkpoints — each labelled (a) is it
  grounded in a successful call, and (b) would the goal still be reachable if it
  were removed;
- **200** of the calls the distiller did *not* retain — each labelled redundant
  / irrelevant / load-bearing;
- the **67** alternatives listed in the specs' equivalence sets — each labelled
  for whether it produces the same effect as the checkpoint it is attached to.

Intervals are Wilson 95% intervals.

**Reproduce:** not reproducible from this repository as committed. The audit was
performed by hand by the authors; the **item-level labels and the annotation
rubric are held externally** and are not part of the released artifact (see
`docs/experiments/e9.10-reference-validation-gate.md` §7.2 and PLAN CR 4.2,
which record this as blocked). Only the aggregates below are reported — they are
the numbers already published in the author responses
(`paper/rebuttals/Response to Reviewer RJAT.txt`, `... sJ7917.txt`,
`... 4Rex.txt`). The corpus the sample was drawn from *is* released.

## Decision rule (pre-registered)

Recorded here as stated in the rebuttal, **after** the audit was run — this
report documents an audit that had already been performed and published, so the
decision rule is *post hoc* and is labelled as such rather than presented as
pre-registered:

- positive if grounding ≥ 95% and no load-bearing call is found among the
  non-retained calls;
- negative if any retained checkpoint is unnecessary, or any listed alternative
  is not effect-equivalent.

## Data

| audited property | rate | Wilson 95% CI |
|---|---|---|
| grounded in a successful call | 261/264 = 98.9% | 96.7 – 99.6 |
| … of those, necessary to the goal | 261/261 = 100% | 98.5 – 100 |
| non-retained call redundant or irrelevant | 188/188 resolved = 100% | 98.0 – 100 |
| listed alternative effect-equivalent | 67/67 = 100% | 94.6 – 100 |
| spec missing a required effect | 1/100 = 1% | 0.2 – 5.4 |
| spec valid as written | 95/100 | — |

Twelve further non-retained calls were **unresolved** — mostly recovery attempts
after a failed call, where necessity is ambiguous. Counting all twelve as errors
gives a floor of **94%** rather than 100% on the redundancy row.

The one spec missing a required effect is a *reference-validation miss*, not a
distillation error: the effect was never executed in the reference trace at all.

Corpus-scale corroboration (already in the paper, `app:funnel`): 5.63 recorded
calls compress to 2.52 required checkpoints; for chains of five or more, 13.5 to
4.1.

## Result

**positive** on the stated rule. Grounding is 98.9%, every grounded checkpoint
in the sample is also necessary, all 188 resolved non-retained calls are
redundant or irrelevant, and all 67 listed alternatives are effect-equivalent.

## Conclusion & implication

The "by construction" phrasing is too strong and has been removed from the
paper: a successful trace gives provenance and achievability, while necessity,
compression and equivalence quality are properties of the distiller and are
therefore *measured*, not assumed.

Two limits travel with this evidence and are stated in the paper alongside it:

1. **Not blinded, not independent.** The audit was performed by the authors, so
   it establishes internal consistency rather than independent replication.
2. **Precision, not recall.** It asks whether every alternative a checkpoint
   *lists* is equivalent — not whether every equivalent alternative that exists
   is listed. Equivalence-set recall remains unmeasured and is declared in
   Limitations.

**Where this landed in the paper:** `paper/sections/appendix.tex`
§"Distiller Fidelity" (`app:fidelity`), with Table `tab:fidelity`; referenced
from `paper/sections/benchmark.tex` (§3.3) and twice from
`paper/sections/limitations.tex`.

**Open item for the camera-ready:** the item-level labels should be obtained
from the annotator and committed (or the rubric published) so the audit becomes
reproducible; until then the appendix states explicitly that the labels are held
externally.
