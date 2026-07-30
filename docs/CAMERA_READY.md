# Camera-ready commitments (EMNLP 2026 Industry Track)

Everything we promised the four reviewers in the rebuttal, in one place. Each
item names the reviewer it was promised to and the exact wording it answers, so
nothing is quietly dropped between rebuttal and camera-ready.

Status legend: `[ ]` not started · `[~]` in progress · `[x]` done.

---

## 1. Paper text — corrections we owe (no compute)

**1.1 Narrow Principle 1.** `[x]` — promised to RJAT, sJ7917 (and reflected to
1npx). Done: the guarantee is gone from §1, §3.1 (Principle 1), §3.3 and the
Conclusion, replaced by the enforced-and-audited grounding invariant, with
necessity and equivalence-set recall named as open. "Provably achievable" in
§3.3 was softened in the same pass (same claim, stronger wording). Exact
before/after is quoted to RJAT and sJ7917 in `paper/rebuttals/Followup to
Reviewer *.txt`.
Remove "so a spurious 'unnecessary tool' cannot arise" / "cannot arise by
construction" wherever it appears: abstract-adjacent claim in §1, Principle 1 in
§3.1, and the Conclusion. Replace with the measured invariant: *every required
`tool_effect` checkpoint is grounded in a successful call in its reference
trace*, presented as an empirically evaluated property, not a guarantee. Also
soften §3.3 "the distiller never introduces a checkpoint the trace does not
justify."

**1.2 Fix the Tier-2 naming collision.** `[x]` — promised to RJAT.
Done: §3.4 now says the judge is optional, off by default, enabled for no
reported number, and scopes the claim ("no reported score depends on a model's
judgment *at scoring time*") explicitly against construction, which is
LLM-driven. Appendix D gains a "Scoring, and the two 'Tier-2's" block that
detaches 0.75 from the judge and names it the *replay argument-match threshold*
(field-level comparison, `difflib` fallback, no model); the Appendix E prompt
heading now reads "Effect-equivalence judge (the optional Tier-2 component;
disabled for every reported result)".
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

**1.3 State the replay path-freedom trade-off.** `[x]` — promised to 1npx.
Done: new §3.4 paragraph "What path-agnosticism means under replay" — the
trade-off is resolved in favour of comparability; inside replay path freedom
means order freedom, tolerated extra calls, argument-representation tolerance
and equivalence-set members the reference exercised; a route the reference
never took misses the cache and errors; unrestricted path freedom exists only
in live mode, which the leaderboard deliberately does not use.
Say explicitly that under deterministic replay a candidate cannot execute a route
the reference never took (cache miss → error), so path-agnosticism inside replay
means order freedom, tolerated extra calls, argument-representation tolerance and
equivalence-set members the reference exercised. Unrestricted path freedom exists
only in live mode, which the leaderboard deliberately does not use.

**1.4 State the tool-exposure scope boundary.** `[x]` — promised to RJAT, sJ7917.
Done in three places: §3.4 ("that pool is controlled, not open … measures tool
*use* and does not measure retrieval over a large catalog"), Appendix D
(evaluation config), and a `\paragraph{Scope.}` at the end of Appendix L
(server-attribution / distractor robustness) saying the probes vary the
composition of a pool that already contains the needed tools and are not a
stand-in for an open-universe retrieval condition.

**1.5 Report GLM-5.1 with the same-family caveat.** `[x]` — promised to 4Rex.
Done in three places: §4.4 (the self-preference sentence no longer states only
the +0.5 mean — it names glm-5.1 71.9 own-family vs 46.4 on the rest, so the
50.3 second place is lifted by same-family tasks and sits level with third
place without them), Appendix A (leaderboard table intro), and Appendix J
(self-preference), which now says the mean is an aggregate, not a per-model
guarantee. The rank 2 → 3 claim is deliberately *not* stated here: it needs the
leave-own-family-out leaderboard, which is item 2.4.

**1.6 Reframe benchmark decay.** `[x]` — promised to 4Rex.
Done: Appendix M now calls the 36% a *materiality demonstration*, not a
universal reproduction rate — a small deliberately live-read sample over three
families, dominated by which families are in it; it establishes that decay is
large enough to matter, not how fast an arbitrary substrate decays. Both
caveats stay visible in the prose and are now also in the table caption:
`broken` is an upper bound (single retry), and nine of ten Wikipedia traces
were excluded for rate limiting, so the Wikipedia row rests on three calls.

**1.7 Add missing limitations.** `[x]`
- No controlled cross-distiller study (same traces distilled independently by
  every family in the pool) — promised to sJ7917.
- Equivalence-set **recall** is unmeasured; the audit reports precision.
- Scorer strictness is validated on one model only.

Done: the first two go in a new "What our checkpoints do not establish"
paragraph in Limitations; the third extends the existing fourth limitation
(human study on one model) with the consequence — we can show the scorer is
conservative, not that its conservatism shifts level rather than ordering. The
§1 sentence from 1.1 was corrected in the same pass: it said these were
questions "we measure", which is false for recall — it now says we audit and
qualify them in Limitations.

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

**2.2 Generation funnel.** `[x]` — promised to 1npx, sJ7917.
980 goals → 1,014 recorded traces (incl. retries) → 959 parseable (94.6%) → 710
validator-valid (74.0% of parsed, 70.0% of traces). Plus the corpus-level
1,845/2,051, **with** the caveat that the two denominators are not comparable.
Done (E9.2): new Appendix "Generation Funnel" with the four-row table and three
caveats — retries mean the columns are not a partition; the 74% is post
retry-fix (the first sweep stamped 417/915 = 46% because one provider returned
empty HTTP 200 bodies); and the corpus-level 1,845/2,051 has a different
denominator and is explicitly not a replication. Numbers in
`docs/experiments/e9.2_numbers.json`, table regenerated by
`scripts/cr_paper_tables.py`.

**2.3 Human confusion matrix.** `[x]` — promised to 1npx.
The 2×2 over 975 annotated cards covering all 750 results: 488 / 26 / 230 / 231;
agreement 73.7%; 94.9% of automatic passes confirmed. Frame as the lower-bound
property already stated in Limitations.
Done (E9.2): new Appendix "Human Validation: the Full Contingency Table". The
prose names the asymmetry as the claim — the threatening cell (auto-pass /
human-fail) holds 26 of 975, the large off-diagonal (230) is the deliberate
conservatism, and 73.7% raw agreement is explicitly *not* the number to
optimize. Regenerated from `docs/experiments/e4.6_numbers.json`.

**2.4 Leave-own-family-out leaderboard.** `[x]` — promised to 4Rex; **into the
main body**, not the appendix.
Done (E9.3). `tab:lofo` in §4.4 orders all 24 models by their score on tasks their
own family did not author. No new run was needed: the "other" column of
`tab:family` *is* the leave-own-family-out score, and models whose family authored
no task keep their headline score by construction (marked †). Spearman ρ = 0.997
against the headline ordering; the only rank movement is three adjacent swaps
(glm-5.1 ↔ qwen3.6-35b, minimax-m3 ↔ gemma4-31b, nemotron-nano-4b ↔ gemma4-e4b),
each between models whose headline CIs already overlap. GLM-5.1 50.3 → 46.4, rank
2 → 3 — the claim 1.5 deferred to this item. ρ and the swap set are *computed*
from the two columns, not transcribed, and asserted against the claimed values.

**2.5 Decay per domain in its own table.** `[x]` — promised to 4Rex; **into the
main body**.
Done (E9.3). `tab:decay` moved from Appendix~`app:decay` to §4.5 with the per-row
call counts intact (yfinance 18, arXiv 105, Wikipedia 3, pooled 126); the pooled
row is recomputed by call-weighting the three rows rather than transcribed, so
36/33/32 is checkable against them and a row that changes without the pooled rate
following fails the check. `app:decay` keeps the protocol and the two bounding
caveats (Wikipedia rate-limiting, single-retry upper bound on `broken`) and now
points at the main-body table.

**2.6 Open-universe retrieval condition.** `[x]` — promised to RJAT, sJ7917.
Done (E9.2), and superseding what was promised: rather than promoting the
single-model `e8.11` table, the appendix carries the full `e9.1` matrix (4
models × 6 conditions, 150 tasks each), the reachability gate (36.7/48.0/62.7/
75.3% of tasks fully reachable at k=4/8/16/32; 1 pass in 1,905 unreachable
attempts), the retrieval-loss vs distraction decomposition (−20.0 vs −8.0), the
regressive-cost and spread-compression finding (ρ=+1.000 at k≤8; top margin
10.0 → 1.3; retained spread 36%), and pass^3 at `rag:8` (19.3/22.0/20.0/25.3
overall, **0.0% on unreachable tasks for every model**). `e8.11` appears as the
earlier independent draw whose deficit replicates (−20.6 vs −23.3). Caveats
kept: one retriever, one router, `flat` on one model, five of six conditions
single-attempt.
Original promise, for the record:
Already run: see `docs/experiments/e8.11-retrieval-full-catalog.md`. Promote the
table into the paper: 150 tasks balanced across chain depth, retrieval over the
full 1,168-tool catalog at top-8, 36.7% vs 57.3% curated overall; short 64.0 vs
62.0, medium 30.0 vs 74.0, long 16.0 vs 36.0; 64% of the 274 unmet checkpoints
are tools the agent never called. State that the curated column is one model at
one attempt on 50 tasks per bucket.

---

**2.7 Restore the six-strategy distractor ablation.** `[x]`
`paper/` in this repo was reset to the exact submitted sources, which dropped an
improvement made after submission (PR #143): the strategy-ablation table in the
appendix gained `sibling` (0.3% / 60% / 0.3% / 59%) and `stratified`
(0.3% / 57% / 0.3% / 57%) rows, a `\tabcolsep` tweak, and a caption saying the
result holds "across all six strategies".

Done (E9.5). Restored, and re-derived rather than re-pasted: `tab:distractor` is
now generated by `scripts/cr_paper_tables.py` from `docs/experiments/e8.9_numbers.json`,
whose six-strategy cells were never reset (only `paper/` was). Every restored
figure reproduces the PR #143 text exactly. The generator also recomputes the
hard\_neg − random contrast from the cells, cross-checks it against the recorded
`delta_pp`, and asserts it still falls short of the pre-registered 15 pp
threshold — so the paragraph's "rejects it decisively" cannot outlive the data.
Prose now says "a six-strategy ablation … every one of the six".

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
Written into the paper by item 2.6 above.

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

**4.1 Fix the one broken task and tighten the reference validator.** `[x]` —
promised to 1npx, RJAT, sJ7917.
Reject a claimed-successful exploration that does not produce every required
external effect. Done (E9.10): `reference_unsatisfied_checkpoints` requires the
reference to satisfy *every* required checkpoint of its own spec, `value_produced`
included, and `dmcp generate` now rejects on it instead of trusting the explorer's
`successful_tool_calls` self-report. Audit:
`docs/experiments/e9.10-reference-validation-gate.md` — 267/1,845 corpus specs
(14.5%) would have been rejected; on the eval slice they are 13.9% of tasks but
40.7% of the never-solved wall (56.7% never solved vs 13.3%); removing them
preserves every model's rank on pass and pass^3. The *specific* audited item
cannot be named until 4.2 releases the item-level labels.

**4.2 Release the audit's item-level labels and rubric.** `[ ]` — promised to
sJ7917. Depends on 2.1.

**4.3 Refresh preflight.** `[x]` — promised to RJAT. Shipped as `dmcp/preflight.py`
(E9.11). A reference trace is read for the four preconditions it depends on —
`credential` (the server's declared `requires_env`), `file` (an absolute path a
read call consumed), `writable` (an absolute path a `stateful_write` call
targeted; the parent is checked when the file does not exist yet) and `table` (a
relation named by a table-ish argument or by SQL, checked against a read-only
`list_tables`-style probe). A task with an unmet precondition is **quarantined**:
`refresh_one` makes no live call at all, the report carries the finding, and the
quarantined spec is excluded from both `decay_summary` and `per_server_decay`, so
our own missing fixture can be read neither as server decay nor as agent failure.
The derivation is deliberately biased toward under-claiming — relative paths and
unknown servers yield no requirement, and an un-probeable relation is `unknown`,
which never quarantines. `dmcp refresh --no-preflight` restores the old
behaviour.

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
Experiments behind 2.6: `docs/experiments/e9.1-tool-exposure-matrix.md` (the
matrix now in the paper; numbers under `docs/experiments/data/e9.1_*.json`,
drivers `scripts/cr_*.py`) and the earlier `e8.11-retrieval-full-catalog.md`
(numbers in `e8.11_numbers.json`, comparison script `scripts/rag_compare.py`).
Tables for 2.2 / 2.3 / 2.6 are regenerated by `scripts/cr_paper_tables.py` and
checked against the paper by `tests/test_cr_paper_tables.py`.

This file is the single copy. A duplicate at the repository root was removed in
the E9.2 PR after status notes were mistakenly written into it.
