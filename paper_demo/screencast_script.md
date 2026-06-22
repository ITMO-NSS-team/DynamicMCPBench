# DMCP Studio — screencast script (≤ 2.5 min)

**Hard cap: 2:30 (desk-reject if over).** This script is timed to **~2:20**, a
10 s buffer. Audio narration over a screen recording; minimal editing
(production quality is explicitly not judged). Record against **REPLAY** (the
deterministic default) for reliability — every beat below is reproducible from
the committed fixture.

**Before recording**
- Launch: `dmcp-studio/scripts/run_demo.sh` → open `http://127.0.0.1:8000`.
- Window at projector resolution (~1440×900); browser zoom so the four-stage
  stepper and the verdict bar are both legible.
- Start on **Stage 1** (Collect), mode toggle on **REPLAY**.
- Optional: upload to an unlisted YouTube link and put it in the paper, or
  attach the MP4 as supplementary.

> **Live note.** Record the main flow against **REPLAY** for booth reliability
> (deterministic, instant). LIVE mode now works end to end (collect → explore →
> distill over real servers), so you *may* add one brief genuine LIVE explore as
> proof — flip the toggle, pick a server, run one exploration — then return to
> REPLAY for the verdict beats. Keep any live segment short (it spends a few
> seconds and a few cents of LLM budget) and only show it if the network is
> reliable on the day; the verdict flip itself is always REPLAY.

---

## Beats (cumulative time)

**0:00–0:15 · The problem.**
> "Benchmarks for LLM agents over MCP servers grade the final answer, or a fixed
> list of tools. Both break the moment the servers are live and stateful. DMCP
> Studio makes a better idea tangible: grade *effects*, not the answer."

Screen: the title/Stage 1 header.

**0:15–0:35 · Collect → goal.**
> "We point the studio at live MCP servers — here, a finance server. It collects
> each server's tool surface and tags it by dynamism."

Action: show the server cards; click **"Generate a goal & explore →"**. Land on
Stage 2; read the generated goal aloud (one line).

**0:35–0:55 · Explore (forward generation).**
> "A goal generator writes a realistic request; an explorer agent pursues it and
> records every successful tool call into a reference trace. We generate
> *forward*, then distill — no tool graph is imposed."

Action: click **"Run exploration"**; the calls stream in. Let ~4–5 land.

**0:55–1:15 · Distill to a path-agnostic TaskSpec.**
> "The trace is distilled into effect checkpoints. Each demands an effect — that
> some tool from an *equivalence set* ran, or that a value appeared — never one
> specific path."

Action: click **"Distill this trace →"**. Point the cursor at checkpoint #3's
**amber equivalence chips** (`download` / `get_price_history`).

**1:15–1:45 · The verdict flip (the core).**
> "Now score a candidate. This agent wrote a confident summary — but it skipped
> the income-statement step."

Action: Stage 4; select **`hermes3-8b`**; click **"Run candidate"**. The verdict
shows **FAILED**; point at the red, unmet checkpoint #5.
> "Effect-scoring fails it: a required effect never fired. Watch what
> answer-matching does with the same run."

Action: toggle **Effect → Answer**. Verdict flips to **SOLVED**.
> "The prose looks complete, so a string-matcher accepts it. That disagreement —
> incomplete aggregation — is the dominant failure mode in our study."

**1:45–2:05 · The other direction + live re-score.**
> "It cuts both ways."

Action: select **`grok-4.3 (stale)`**, run it; in Effect mode it **passes**,
in Answer mode it **fails**.
> "A correct run, failed by answer-matching only because the live price moved.
> Effect-scoring passes it."

Action (if time): on the clean candidate, click an **equivalence chip** off and
watch the verdict re-score live.

**2:05–2:20 · Close.**
> "Everything you saw scores under deterministic replay, so it's reproducible —
> and you can run the whole pipeline on your *own* MCP servers. DMCP Studio:
> grade effects, not the answer."

Action: brief glance at the leaderboard peek; end on the verdict bar.

---

## Shot list (for editing)

| time | screen | narration cue |
|---|---|---|
| 0:00 | Stage 1 header | problem statement |
| 0:15 | server cards → goal | collect + goal |
| 0:35 | explore stream | forward generation |
| 0:55 | checkpoint ledger + equiv chips | distillation |
| 1:15 | hermes3-8b → FAILED | effect-fail |
| 1:30 | Effect→Answer toggle → SOLVED | the flip |
| 1:45 | grok stale → pass/fail | stale-answer case |
| 2:05 | equivalence re-score / leaderboard | reproducibility + close |
