# DMCP Studio — Build, Evaluate & Publish Plan (for Claude Code)

**Owner:** DynamicMCPBench team
**Target:** EMNLP 2026 System Demonstrations track (Budapest, Oct 24–29, 2026)
**Hard deadline:** **Fri, July 10, 2026, 11:59pm AoE** (no rebuttal stage). Notification Aug 20; camera-ready Aug 30.
**Status doc:** keep a running `PROGRESS.md` (see §10)

> **Three mandatory submission components** (missing any → desk reject): (1) the paper, (2) a ≤2.5-min screencast, (3) a **live demo URL or installable package link, in the PDF**. See §11 for the full CFP compliance checklist — read it before writing a line of code, because several rules shape the build (single-blind, no-anonymization, sandbox/ethics, 2-page appendix cap, "no evaluation = desk reject").

> This file is the execution spec. It assumes the DynamicMCPBench *pipeline* already exists (the submitted industry paper). The job here is to wrap that pipeline in an interactive studio, validate it for live use, and write the demo paper. Work milestone by milestone, smallest shippable slice first.

---

## 0. Context

- **What exists:** a working DMCP pipeline — server collection, goal generation, forward exploration (explorer agent), trace distillation into a `TaskSpec` (effect checkpoints, minefields, partial order), and a two-tier effect scorer (Tier-1 deterministic, Tier-2 effect-equivalence judge), with deterministic replay. Implemented in Python with `pydantic_ai`.
- **What we're building:** **DMCP Studio** — a web app that runs that pipeline interactively across four stages (Collect → Explore → Distill → Score) and dramatizes the paper's thesis: *grade effects, not the answer.* The signature interaction is an **Effect ⇄ Answer toggle** that flips a candidate's verdict.
- **Design target:** the HTML mockup `dmcp_studio.html` (the visual + interaction spec). Match its look, stages, and the verdict-flip behavior. Replace its canned data with real pipeline calls behind a LIVE/REPLAY switch.
- **The three showcase cases** the demo must reproduce on real runs:
  1. clean pass via an *equivalence-set* tool (`get_price_history` instead of `download`);
  2. a confident agent that **passes answer-match but fails effects** (skips a required tool — incomplete aggregation);
  3. a correct agent that **fails answer-match but passes effects** because live data drifted (stale-answer case).

---

## 1. Scope & non-goals

**In scope**
- A backend that wraps the existing pipeline and streams stage progress.
- A frontend upgraded from the mockup, wired to the backend, with LIVE and REPLAY modes.
- A small set of frozen REPLAY fixtures for safe, reproducible demoing.
- Validation experiments sufficient for a *system* paper (not a new model study).
- The 6-page demo paper and an ≤3-minute screencast.

**Non-goals (do not build)**
- New science / new scoring methods — the method is fixed by the submitted paper.
- Re-running the full 24-model × 750-task study (already done; we *display* its results, optionally recompute a small slice).
- Auth, multi-tenant accounts, or any production hardening beyond demo safety.
- Calling real state-changing servers outside a sandbox (hard rule — see §10).

---

## 2. Architecture

```
                 ┌────────────────────────── DMCP Studio ──────────────────────────┐
  Browser  ◄──►  │  Frontend (static SPA, built from dmcp_studio.html)             │
   (SSE)         │     stages: collect · explore · distill · score                 │
                 │                       │ fetch + EventSource                      │
                 │  FastAPI backend  ────┤                                          │
                 │     /servers  /goal  /explore(SSE)  /distill  /score(SSE)  /lb   │
                 │     mode = LIVE | REPLAY                                         │
                 │            │                                                     │
                 │   dmcp_adapter.py  ── thin shim over the EXISTING pipeline ──┐   │
                 └─────────────────────────────────────────────────────────────┼───┘
                                                                                │
                        existing DMCP modules (collect / explore / distill / score / replay)
```

**Key decisions (implement exactly):**
1. **Wrap, don't rewrite.** All real work goes through `dmcp_adapter.py`, which calls the existing pipeline. The backend never reimplements scoring or distillation.
2. **LIVE vs REPLAY is a first-class mode.** REPLAY serves frozen fixtures deterministically — this is both demo-safety *and* on-thesis (the paper scores under deterministic replay). Default the public demo to REPLAY; LIVE is an explicit toggle.
3. **Stream the two slow stages** (explore, score) over **SSE** so the UI fills call-by-call. `/distill` and `/score` also return a final JSON summary.
4. **State-changing servers are sandbox-only**, enforced in the adapter, not the UI (§10).
5. **Frontend stays framework-light.** Keep the mockup's vanilla approach unless a clear need arises; do not introduce a build toolchain that costs days.

---

## 3. Repo layout

```
dmcp-studio/
├── PROGRESS.md                 # running log (see §10)
├── README.md                   # quickstart: how to run LIVE and REPLAY
├── backend/
│   ├── app.py                  # FastAPI app + routes
│   ├── dmcp_adapter.py         # shim over existing pipeline (the only integration point)
│   ├── replay_store.py         # load/serve frozen fixtures
│   ├── models.py               # pydantic response models (ServerCard, TaskSpec, Verdict…)
│   └── fixtures/               # frozen REPLAY runs (json) — produced in Workstream B
├── frontend/
│   ├── index.html              # built from dmcp_studio.html
│   ├── app.js                  # state machine + SSE wiring
│   └── styles.css              # extracted from the mockup
├── experiments/
│   ├── e1_agreement.py         # studio-vs-batch verdict agreement
│   ├── e2_latency.py           # per-stage latency budget
│   ├── e3_curate.py            # pick + freeze showcase fixtures
│   └── results/                # csv/json + plots
├── paper/
│   ├── main.tex                # ACL demo template (6pp)
│   ├── figures/
│   └── screencast_script.md
└── scripts/
    └── run_demo.sh             # one command to launch the studio
```

---

## 4. API contract (build the backend to this)

All responses are JSON unless noted. `mode` query param ∈ {`live`,`replay`}, default `replay`.

| Method | Route | Purpose | Returns |
|---|---|---|---|
| GET | `/api/servers?mode=` | list collected servers + dynamism tags | `ServerCard[]` |
| POST | `/api/goal` `{server_ids[]}` | generate a goal from the tool surface | `{goal, persona}` |
| GET | `/api/explore?mode=&goal_id=` | **SSE** stream of explorer tool calls | events: `call` (one per tool call), `done` (`{trace_id, n_calls, success}`) |
| POST | `/api/distill` `{trace_id}` | compile trace → TaskSpec | `TaskSpec` (checkpoints, equivalence sets, minefields, partial order, complexity profile) |
| GET | `/api/score?mode=&task_id=&candidate=&equiv_overrides=` | **SSE** stream candidate calls + per-checkpoint verdicts | events: `call`, `checkpoint` (`{n, met}`), `done` (`{effect_pass, answer_pass, final_answer, met_count, required}`) |
| GET | `/api/leaderboard` | static study results for the peek panel | `Row[]` |

**Important:** `/api/score` returns *both* `effect_pass` and `answer_pass` every time. The Effect/Answer toggle is a pure frontend re-render over the same payload — never a second backend call. The `equiv_overrides` param lets the UI enable/disable members of an equivalence set and re-score (Tier-1 only).

`models.py` should mirror the existing `TaskSpec` exactly — reuse the pipeline's own pydantic models if importable; only add view-only fields the UI needs.

---

## 5. Workstream A — Build the Studio

### A0 · Map the existing pipeline *(do this first, ~0.5 day)*
- Read the existing repo. Produce `backend/INTEGRATION_NOTES.md` listing: the entry points for collect / generate-goal / explore / distill / score / replay; their input and output types; whether `TaskSpec` and checkpoint models are importable; and where deterministic replay reads/writes its recorded world.
- **Do not guess function signatures.** If an entry point is unclear, list the candidates in `INTEGRATION_NOTES.md` and pick the most likely, noting the assumption.
- **Acceptance:** a one-page map that the remaining milestones can be implemented against without re-opening the question.

### A1 · Adapter + minimal backend *(skeleton end-to-end)*
- Implement `dmcp_adapter.py` with one function per pipeline stage, returning the `models.py` types. Start REPLAY-only (read fixtures or hand-stubbed JSON so the API shape is real before LIVE works).
- Stand up `app.py` with all six routes returning REPLAY data. SSE endpoints stream from a fixture with realistic inter-event delays (300–600 ms).
- **Acceptance:** `curl` each route; SSE routes stream events; payloads validate against `models.py`.

### A2 · Port the frontend to the backend
- Extract the mockup into `index.html` / `app.js` / `styles.css`. Keep the design, the four-stage stepper, the checkpoint ledger, and the verdict bar.
- Replace the canned JS data with `fetch` + `EventSource` against the API. The explore and score streams drive the existing call-by-call animations.
- Preserve the **editable equivalence set** → it sends `equiv_overrides` to `/api/score` and re-renders.
- **Acceptance:** full click-through in REPLAY mode reproduces all three showcase verdict outcomes, including the live re-score when toggling an equivalence-set member.

### A3 · Wire LIVE mode to the real pipeline
- Implement the LIVE branch of each adapter function calling the real pipeline. Add a `mode` toggle in the UI header (default REPLAY).
- Stream real explorer/candidate calls as they happen. Add per-stage timeouts and a graceful "server unreachable → fall back to REPLAY fixture" path so a flaky server never bricks the demo.
- **Acceptance:** with at least one live read-only server (e.g. `yfinance` or `arxiv`), a goal can be generated, explored, distilled, and a candidate scored end-to-end, live.

### A4 · "Bring your own server" entry *(stretch, high demo value)*
- Add an input on Stage 1 to register an MCP server by URL/command; the adapter collects its tool surface and tags dynamism. Reuse the existing collector.
- **Acceptance:** a reviewer can paste a read-only MCP server not in the corpus and reach a distilled TaskSpec.

### A5 · Polish & demo-safety pass
- Loading/empty/error states in the interface's own voice (no stack traces to the user). Keyboard focus visible; `prefers-reduced-motion` respected (already in the mockup CSS — keep it).
- Pre-warm REPLAY fixtures on startup. `scripts/run_demo.sh` launches backend + serves frontend with one command.
- **Acceptance:** cold-start to first verdict in REPLAY < 30 s; no console errors; works on a projector-resolution window.

### A6 · Package for submission
- `README.md` quickstart; a hosted URL or a single-command Docker run; ensure the demo link required by the CFP resolves.
- **Acceptance:** a fresh machine can run the studio from the README in < 10 min.

---

## 6. Workstream B — Experiments / validation (what the *demo paper* needs)

The science is done; these validate the *system* and produce the figures + the frozen fixtures. Run them on the existing corpus.

### E1 · Studio-vs-batch agreement *(credibility — the key one)*
- For ~100 (task, candidate) pairs, score via the studio backend and via the original batch pipeline. Confirm identical Tier-1 verdicts.
- **Output:** agreement rate (target 100% on Tier-1; explain any Tier-2 differences), table for the paper. `experiments/e1_agreement.py`.

### E2 · Latency budget *(decides what to pre-cache)*
- Measure per-stage wall-clock in LIVE mode (goal, explore, distill, score) across server families; record token/tool-call counts.
- **Output:** latency table + the decision rule for which stages run live vs replay in the booth. `experiments/e2_latency.py`.

### E3 · Showcase curation → frozen fixtures *(the demo's spine)*
- From real runs, find and freeze fixtures that vividly show the three showcase cases (clean-equivalence pass; answer-pass/effect-fail; answer-fail/effect-pass). Save under `backend/fixtures/`.
- Reuse the paper's worked example (AAPL/MSFT/GOOGL) as the default fixture so the demo matches Figure/Table 1.
- **Output:** 3–5 curated fixtures + a one-line rationale each. `experiments/e3_curate.py`.

### E4 · Decay / refresh sanity *(ties to the paper's refresh protocol)*
- Re-run the refresh protocol on a few frozen reference traces; confirm the studio's "this fixture still reproduces / has drifted" indicator matches. Lightweight — reuse existing refresh code.
- **Output:** a small decay readout the studio can display as a badge.

### E5 · Informal usability *(optional, nice for the paper)*
- 3–5 people unfamiliar with the system; measure time-to-first-verdict-flip and note confusions. No formal study.
- **Output:** a sentence or two + fixes folded back into A5.

---

## 7. Workstream C — Paper & screencast

**Paper (`paper/main.tex`, EMNLP 2026 official style, ≤6 pages + unlimited refs + optional unlimited ethics/broader-impact + appendix capped at 2 pages). Single-blind: include author names and affiliations; self-references allowed. Accepted papers get +1 content page.**

The CFP says a demo paper should answer eight specific questions — structure the paper so each is unmistakably covered (reviewers map to them):
1. *What problem does it address?* → Intro: answer-matching and fixed tool lists are fragile on live, stateful MCP servers.
2. *Why important / what impact?* → agents are deployed over MCP now; practitioners need a re-runnable, deployment-specific diagnostic.
3. *What's novel in the approach/tech?* → forward trace-grounded generation + answer-agnostic effect scoring, exposed as a live, inspectable studio.
4. *Who is the target audience?* → agent builders, eval researchers, teams running private MCP fleets.
5. *How does it work?* → the four stages + LIVE/REPLAY design; annotated studio screenshot as the main figure.
6. *How does it compare to existing systems?* → one paragraph vs other agent-eval tools (reuse the parent paper's related-work spine; keep <25% overlap with the submitted industry paper).
7. *How is it licensed?* → state it (e.g., Apache-2.0/MIT) — the CFP asks explicitly.
8. *How was it evaluated? Any user study?* → **mandatory**: E1 agreement + E2 latency, and the E5 informal usability note. **This year, papers reporting no evaluation may be desk-rejected — the evaluation section is not optional.**

Plus a **Limitations** section (after conclusion; doesn't count toward the limit; absence = desk reject) covering live-server flakiness, scorer conservatism, single-task default showcase.

- Required visual aids: include screenshots/diagrams (the CFP requires visual aids for the system).
- **Acceptance:** compiles in the official EMNLP 2026 template; ≤6 pages of content; appendix ≤2 pages; author names present (single-blind); demo link present in the PDF; Limitations + a real evaluation section both present; ethics conforms to the ACM Code of Ethics.

**Screencast (`paper/screencast_script.md`, ≤2.5 min — hard cap, desk-reject if over).**
- 0:00 problem in one line → 0:15 pick servers, generate goal → 0:30 explore streams live → 0:50 distill to TaskSpec, point at the equivalence set → 1:10 run the confident agent, flip Effect→Answer, **show the verdict flip** → 1:45 run the stale agent, flip the other way → 2:05 toggle an equivalence-set tool, re-score live → 2:25 leaderboard peek + "run it on your own servers" close.
- Record against REPLAY for reliability; show one genuinely LIVE explore as proof. Screencast with audio narration, minimal editing (production quality is explicitly not judged). Upload to YouTube/unlisted and put the link in the paper, or submit as MP4 supplementary.

---

## 8. Schedule (single builder; compress if parallelized)

Anchor everything to the **July 10, 2026 AoE** deadline. The day-numbered plan below is a ~3-week sprint; set Day 21 = July 9 (one buffer day before AoE close).

| Days | Focus | Exit criterion |
|---|---|---|
| 1 | A0 map pipeline | `INTEGRATION_NOTES.md` done |
| 2–4 | A1 + A2 (REPLAY end-to-end) | full click-through in REPLAY, all 3 verdicts |
| 5–7 | A3 LIVE mode + fallback | live read-only run end-to-end |
| 8 | E1 + E2 | agreement + latency tables (the mandatory evaluation) |
| 9–10 | E3 freeze fixtures (+ A4 stretch if time) | showcase fixtures committed |
| 11–12 | A5 polish + safety | cold-start < 30 s, no errors |
| 13–16 | Paper draft (C) — cover all 8 CFP questions + evaluation + limitations | full 6-page draft |
| 17 | E4/E5 + figures (E5 feeds the required user-study line) | figures final |
| 18–19 | Paper revision + screencast (≤2.5 min) | screencast recorded & uploaded |
| 20 | A6 package + **deploy the live demo link** | README run < 10 min; demo URL resolves |
| 21 | Submit (paper + video + demo link, all three) | OpenReview submission complete |

> The single-blind, no-rebuttal format means there's no second chance to fix a desk-reject. Treat the §11 checklist as a launch gate, not a formality.

---

## 9. Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Live MCP server flaky/down mid-demo | High | REPLAY default + automatic fallback (A3); freeze fixtures (E3) |
| Benchmark decay changes a live result | High (paper: only 36% reproduce identically) | Score under deterministic replay; LIVE explore is "proof," not the graded path |
| Adapter mismatch with existing code | Medium | A0 first; wrap don't rewrite; reuse pipeline's pydantic models |
| Tier-2 judge nondeterminism in demo | Medium | Headline uses Tier-1 only (matches paper); Tier-2 shown as optional upgrade |
| Content overlap with submitted paper >25% | Medium | Frame as system/tool; keep method description short, cite parent |
| Scope creep (A4, fancy UI) | Medium | A4 is explicitly stretch; ship REPLAY path first |
| State-changing server side effects | Low but severe | Sandbox-only enforced in adapter (§10); ACM ethics code applies |
| **Demo link doesn't resolve at submission** | Medium | **Strict desk-reject trigger this year.** Deploy by Day 20; have an installable-package fallback link if hosting is flaky |
| **Paper reports no evaluation** | Low | **Desk-reject trigger this year.** E1+E2 are mandatory, not optional; E5 adds the user-study line |
| Screencast over 2.5 min | Low | Hard cap; script to 2:25 with buffer; trim editing |

---

## 10. Claude Code working agreement

**Process**
- Keep `PROGRESS.md` updated every session: what shipped, what's next, open questions, assumptions made. One bullet per change.
- Work the smallest shippable slice first; commit in small, labeled chunks (`A1: …`, `E3: …`). Don't bundle unrelated changes.
- After each milestone, run its **Acceptance** check and record the result in `PROGRESS.md`.

**Decide vs ask**
- *Decide and note the assumption* for: file/module names, response field names, animation timings, CSS, fixture contents, anything reversible.
- *Stop and ask* for: anything that would call a real state-changing MCP server outside a sandbox; anything that would modify the existing pipeline's behavior (the adapter must be additive); spending budget on a hosted deployment; any change that risks >25% overlap with the submitted paper.

**Hard rules**
- **Sandbox safety:** the adapter must refuse to invoke any tool on a `stateful_write` server unless it's flagged sandboxed; default-deny. Add a test for this.
- **Wrap, don't rewrite** the pipeline. If the existing code needs a change to be wrappable, surface it as a question, don't fork logic into the studio.
- **One source of truth for verdicts:** `/api/score` returns both effect and answer verdicts; the UI never recomputes them except the Tier-1 equivalence re-score path.
- **Don't fabricate study numbers.** The leaderboard panel must load real results from the parent study, not invented values.

**Quality floor**
- Backend: type-checked pydantic models; a test for the agreement check (E1) and for sandbox default-deny.
- Frontend: responsive to a laptop/projector window; visible keyboard focus; reduced-motion respected.
- `README.md` stays runnable from clean checkout at all times.

**Definition of done (whole project):** a fresh machine runs `scripts/run_demo.sh`, reaches a verdict flip in REPLAY within 30 s, can do one live read-only exploration; the paper compiles in the EMNLP 2026 template to ≤6 pages (appendix ≤2 pages) with author names (single-blind), a resolving demo link in the PDF, a real evaluation section, and a Limitations section; the ≤2.5-min screencast is recorded and linked; and all three submission components are uploaded to OpenReview. Run the §11 checklist as the final gate.

---

### First three actions for Claude Code
1. Create the repo skeleton (§3) and an empty `PROGRESS.md`.
2. Do **A0**: read the existing pipeline and write `backend/INTEGRATION_NOTES.md`.
3. Implement **A1** (REPLAY-only backend) so the API shape is real, then stop and report before wiring the frontend.

---

## 11. EMNLP 2026 demo-track compliance checklist (launch gate)

Source: the official Call for System Demonstrations. No rebuttal stage, so a desk-reject is final — verify every item before submitting.

**Mandatory submission components (all three, or desk reject)**
- [ ] **Paper** (PDF, EMNLP 2026 official style files — unmodified).
- [ ] **Screencast** ≤ **2.5 min**, audio narration, minimal editing; YouTube/unlisted link in the paper *or* MP4 supplementary.
- [ ] **Live demo URL or installable package link, included in the PDF.** Strictly enforced this year; only waivable if a link is genuinely impossible (e.g., special hardware) with a stated reason — not our case.

**Paper format**
- [ ] ≤ **6 content pages** (longer → desk reject); +1 page granted only after acceptance.
- [ ] **Appendix ≤ 2 pages** (note: stricter than main track's unlimited appendix).
- [ ] References: unlimited. Ethics/broader-impact statement: optional, unlimited.
- [ ] **Limitations** section present (absence → desk reject).
- [ ] **Single-blind**: author names + affiliations included; self-references allowed. Do **not** anonymize.
- [ ] Visual aids included (screenshots/diagrams of the system).

**Content the reviewers expect**
- [ ] All eight CFP questions answered (problem, importance/impact, novelty, audience, how it works, comparison, **license**, **evaluation**).
- [ ] **An evaluation is reported** (E1/E2 + E5). Papers with no evaluation may be desk-rejected this year.
- [ ] No commercial sales/marketing framing (that belongs to the Exhibit Program).

**Policies**
- [ ] Original, unpublished, not under review elsewhere; < 25% overlap with the submitted industry paper or any concurrent demo submission.
- [ ] ACM Code of Ethics honored; data use and the live-tool-execution/sandbox safety addressed (ties to §10 sandbox rule).
- [ ] Submitted via OpenReview (link posted ≥ 2 weeks before the deadline — watch for it).

**Dates**
- [ ] Submit by **Fri, July 10, 2026, 11:59pm AoE**. Notification **Aug 20**; camera-ready **Aug 30**. At least one author registers and presents the live demo + poster in Budapest.
