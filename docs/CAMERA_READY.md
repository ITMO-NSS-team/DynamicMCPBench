# Camera-ready commitments (EMNLP 2026 Industry Track)

Everything we promised the four reviewers in the rebuttal, in one place. Each
item names the reviewer it was promised to and the exact wording it answers, so
nothing is quietly dropped between rebuttal and camera-ready.

Status legend: `[ ]` not started · `[~]` in progress · `[x]` done.

---

## 1. Paper text — corrections we owe (no compute)

**1.1 Narrow Principle 1.** `[ ]` — promised to RJAT, sJ7917 (and reflected to
1npx).
Remove "so a spurious 'unnecessary tool' cannot arise" / "cannot arise by
construction" wherever it appears: abstract-adjacent claim in §1, Principle 1 in
§3.1, and the Conclusion. Replace with the measured invariant: *every required
`tool_effect` checkpoint is grounded in a successful call in its reference
trace*, presented as an empirically evaluated property, not a guarantee. Also
soften §3.3 "the distiller never introduces a checkpoint the trace does not
justify."

**1.2 Fix the Tier-2 naming collision.** `[ ]` — promised to RJAT.
The paper attaches the 0.75 threshold to the LLM judge (§3.4 and Appendix D).
Two unrelated mechanisms share the name "Tier-2":
- `replay.py` `tier2_threshold` (default 0.75) — a **deterministic** argument
  matcher (field-level match, `difflib` fallback) that decides when a cached
  result is served. No model.
- `judge.py` — the **optional LLM** effect-equivalence judge. Binary,
  upgrade-only, `--judge` defaults to off, never enabled for any reported number.
Rename one of them and state plainly that no reported result involves an LLM
judgment, while noting the scope: that covers *scoring*, not *construction* (the
distiller and validator are LLMs).

**1.3 State the replay path-freedom trade-off.** `[ ]` — promised to 1npx.
Say explicitly that under deterministic replay a candidate cannot execute a route
the reference never took (cache miss → error), so path-agnosticism inside replay
means order freedom, tolerated extra calls, argument-representation tolerance and
equivalence-set members the reference exercised. Unrestricted path freedom exists
only in live mode, which the leaderboard deliberately does not use.

**1.4 State the tool-exposure scope boundary.** `[ ]` — promised to RJAT, sJ7917.
Say that the headline condition is a controlled pool and does not measure
open-universe retrieval, and do not let the distractor analysis (Appendix L)
stand in for retrieval.

**1.5 Report GLM-5.1 with the same-family caveat.** `[ ]` — promised to 4Rex.

**1.6 Reframe benchmark decay.** `[ ]` — promised to 4Rex.
Present 36% as a materiality demonstration, not a universal reproduction rate.
Keep both caveats visible: `broken` is an upper bound (single retry), and nine of
ten Wikipedia traces were excluded for rate limiting, so the Wikipedia row rests
on three calls.

**1.7 Add missing limitations.** `[ ]`
- No controlled cross-distiller study (same traces distilled independently by
  every family in the pool) — promised to sJ7917.
- Equivalence-set **recall** is unmeasured; the audit reports precision.
- Scorer strictness is validated on one model only.

---

## 2. Appendix — new content from data we already have (no compute)

**2.1 Distiller-fidelity audit.** `[ ]` — promised to 1npx, RJAT, sJ7917.
Protocol, raw counts, Wilson intervals, the length stratification, and the one
identified failure case. Numbers as sent: 261/264 grounded (98.9%, CI 96.7-99.6),
261/261 necessary, 188/188 resolved removals redundant (12 unresolved → 94% on
the conservative reading), 1/100 missing a required effect, 67/67 listed
alternatives equivalent, 95/100 valid as written.
**Open item:** the audit protocol (independent annotators? blinding to the
distiller's retain/drop decision? adjudication of disagreements? written rubric?)
is not documented on our side. Get it from the collaborator who ran it — without
it, an unblinded self-audit reporting three 100% rows is the weakest link in the
whole package.

**2.2 Generation funnel.** `[ ]` — promised to 1npx, sJ7917.
980 goals → 1,014 recorded traces (incl. retries) → 959 parseable (94.6%) → 710
validator-valid (74.0% of parsed, 70.0% of traces). Plus the corpus-level
1,845/2,051, **with** the caveat that the two denominators are not comparable.

**2.3 Human confusion matrix.** `[ ]` — promised to 1npx.
The 2×2 over 975 annotated cards covering all 750 results: 488 / 26 / 230 / 231;
agreement 73.7%; 94.9% of automatic passes confirmed. Frame as the lower-bound
property already stated in Limitations.

**2.4 Leave-own-family-out leaderboard.** `[ ]` — promised to 4Rex; **into the
main body**, not the appendix.
Spearman 0.997 vs the headline, three adjacent swaps with overlapping CIs, GLM-5.1
50.3% → 46.4%, rank 2 → 3.

**2.5 Decay per domain in its own table.** `[ ]` — promised to 4Rex; **into the
main body**.
Include the per-row call counts (yfinance 18, arXiv 105, Wikipedia 3, pooled 126)
so the pooled rate is checkable against the rows.

**2.6 Open-universe retrieval condition.** `[ ]` — promised to RJAT, sJ7917.
Already run: see `docs/experiments/e8.11-retrieval-full-catalog.md`. Promote the
table into the paper: 150 tasks balanced across chain depth, retrieval over the
full 1,168-tool catalog at top-8, 36.7% vs 57.3% curated overall; short 64.0 vs
62.0, medium 30.0 vs 74.0, long 16.0 vs 36.0; 64% of the 274 unmet checkpoints
are tools the agent never called. State that the curated column is one model at
one attempt on 50 tasks per bucket.

**2.7 Restore the six-strategy distractor ablation.** `[ ]`
`paper/` in this repo was reset to the exact submitted sources, which drops an
improvement made after submission (PR #143): the strategy-ablation table in the
appendix gained `sibling` (0.3% / 60% / 0.3% / 59%) and `stratified`
(0.3% / 57% / 0.3% / 57%) rows, a `\tabcolsep` tweak, and a caption saying the
result holds "across all six strategies". Re-apply it for the camera-ready; the
text is recoverable from git history.

---

## 3. Experiments still to run

**3.1 Extend the open-universe condition.** `[x]` — promised to RJAT, sJ7917.
`e8.11` covered one model, one retriever (embedding top-8), one slice, single
attempt. Still owed: the flat full-catalog condition (`--architecture flat`), the
hierarchical router (`hier`), other `rag-k`, more models, and pass^3.

Delivered by `docs/experiments/e9.1-tool-exposure-matrix.md` (report + the
`scripts/cr_*.py` drivers): `rag-k` ∈ {4, 8, 16, 32} and `hier` across four
pre-registered models, every cell 150/150; an exploratory seven-model panel that
widens the curated span from 16.7 to 25.3 points; and a reconciliation showing
`e8.11`'s table and this one are different draws from the same slice (0.94 sd
apart) whose paired deficits agree to 2.7 points. Adjudication: H1/H2/H3 neutral,
H4 positive — the registration defects are written up, not worked around.
pass^3 at `rag:8` is now complete for all four registered models at 150/150.
**Residual, deliberately left open:** `flat` ran on `minimax-m3` only (36.0) — the
condition needs a 1M-token context, so the row is partial by design (H5) and
closing it means the `qwen3.7-max` cell. `gpt-5.4-mini` is excluded on technical
grounds (`require_parameters` + `temperature` → 404), artifacts quarantined under
`evals/cr/quarantine/`. Neither gap blocks the promise to RJAT and sJ7917: the
condition was to be extended beyond one model, one retriever and one attempt, and
it is — seven models, four retrieval depths, a router, and three attempts.

**3.2 Tier-2 override rates per category.** `[ ]` — promised to 1npx, RJAT.
Replay the saved leaderboard Tier-1 failures through the judge, across **several
judge families** at temperature 0, and report override rates overall and for each
of the 15 categories. Blocker: the existing judge-enabled records
(`annotations/rq4/scorer/evals_*.jsonl`) carry no category field, so this needs a
re-run joined against the specs.
Known so far, on the 200-cell subset at one attempt: 120 invocations, 7 checkpoint
upgrades, 3 cell flips, 96/200 → 99/200 (+1.5 points).
Note: `dmcp/baselines/rq4_agreement.py::_tier1_verdict` drops `tier==2` rows and
therefore mis-derives Tier-1 — fix or bypass it before reusing.

**3.3 Widen the refresh.** `[ ]` — promised to 4Rex.
Re-execute reference traces across more of the 121 servers, not 22 traces over
three families.

**3.4 Model-independence of scorer strictness.** `[ ]` — promised to 1npx.
The human study covers one model. Annotate at least one more model to show the
conservatism shifts the level rather than the ordering. This is annotation work,
not compute, and is the most expensive item on the list.

---

## 4. Code and data

**4.1 Fix the one broken task and tighten the reference validator.** `[ ]` —
promised to 1npx, RJAT, sJ7917.
Reject a claimed-successful exploration that does not produce every required
external effect.

**4.2 Release the audit's item-level labels and rubric.** `[ ]` — promised to
sJ7917. Depends on 2.1.

**4.3 Refresh preflight.** `[ ]` — promised to RJAT.
Confirm required files, tables, credentials and writable resources before a
refreshed task is readmitted; quarantine rather than count as agent failure.

**4.4 Finer refresh classifier.** `[ ]` — promised to RJAT.
Retry transient errors (timeouts, connection errors, 429, recoverable 5xx) with
backoff across windows; classify schema drift only when discovery shows a changed
or removed tool on a reachable server; state decay when the schema is intact but
a required record is gone; quarantine whatever remains unresolved.

---

## 5. Verify before submitting the camera-ready

**5.1 Reproducibility Statement.** `[ ]`
It claims all reported numbers are regenerated from the released evaluation
records. Confirm the evaluation records really are in the HF release, or soften
the sentence. `scripts/release_hf.py` uploads specs, traces and the manifest.

**5.2 Gwet's AC1.** `[ ]`
Three AC1 figures are reported; the repo implements only Fleiss kappa
(`scripts/annotate2.py::_fleiss`). Add a script that regenerates the AC1 numbers.

**5.3 Internal consistency.** `[ ]`
§3.4 says 16% of checkpoints admit ≥2 tools; Appendix I says 15.5% over 4,651
checkpoints. 15.5% is the corpus figure and 16% is the 750-slice figure — pick
one framing and label it.

---

## Provenance

Rebuttal texts as sent: `paper/rebuttals/Response to Reviewer {1npx,RJAT,sJ7917,4Rex}.txt`.
New experiment behind 2.6: `docs/experiments/e8.11-retrieval-full-catalog.md`,
numbers in `e8.11_numbers.json`, comparison script `scripts/rag_compare.py`.
