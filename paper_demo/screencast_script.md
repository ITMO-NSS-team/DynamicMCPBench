# DMCP Studio - short screencast script (<= 2.5 min)

Record in **Replay** at `http://127.0.0.1:8000`. Start on **Stage 0 -
Design** after the default Advisor plan has loaded and shows **APPROVED**.

## Beats

**0:00-0:20 - Problem.**
> "Agent builders increasingly rely on MCP servers: finance tools, databases,
> file stores, and private APIs. The practical question is which agent-server
> setup is worth trusting on *your* live tools."
>
> "String-matching final answers is brittle on live data, and fixed tool lists
> punish valid alternative paths. DMCP Studio instead designs the benchmark
> first, then grades effects."

Screen: Stage 0 header and the Design -> Collect -> Explore -> Distill -> Score
stepper.

**0:20-0:50 - Benchmark Advisor.**
> "Studio starts with Benchmark Advisor. The user gives an evaluation question,
> candidate models, server scope, budget, attempts, and safety constraints. The
> Advisor turns that into a statistical plan before any corpus is generated."
>
> "The important fields are the verdict, task budget, attempts, planned MDE, and
> claim boundary. Attempts help reliability analysis, but unique tasks are the
> planning unit. If the MDE is too large for the claim, the Advisor asks for more
> tasks or a narrower claim."

Action: point at **Advisor verdict**, **tasks**, **attempts**, **planned MDE**,
**Power curve**, and **Claim card**. Do not explain every panel.

**0:50-1:15 - Demo result.**
> "Now we carry the approved design into Collect. In Replay, the guarded launch
> loads a frozen report instead of spending on a new run."
>
> "The result is intentionally modest: on a 100-task finance corpus, DeepSeek is
> observed two points above MiniMax, but the confidence interval crosses zero.
> So Studio allows a scoped, inconclusive comparison and forbids a best-model
> claim."

Action: click **Carry this design into Collect**, confirm replay report load,
start replay demo, and point at the report headline, delta, CI, and report
boundaries.

**1:15-1:40 - Collect and explore.**
> "Below that is the benchmark substrate: open-source MCP servers, here a
> finance-tool server. Studio reads each tool surface and tags it by dynamism:
> static, live-read, or stateful-write. From this substrate, DMCP generates a
> realistic goal and records a successful reference trace."

Action: show the finance server card, click **Generate a goal and explore ->**,
and let the replayed tool calls appear.

**1:40-2:05 - Distill.**
> "The trace is distilled into path-agnostic effect checkpoints. A checkpoint
> can require a value, a tool effect, or any tool from an equivalence set. That
> means the benchmark checks what happened, not the exact route."

Action: move to **Distill** and point at the checkpoint ledger plus one
equivalence chip, for example `download` / `get_price_history`.

**2:05-2:25 - Score and close.**
> "Finally, we replay a candidate against those checkpoints. Flip Effect to
> Answer and the verdict can change on the same run: fluent prose can hide
> missing work, while correct live effects can disagree with a stale reference
> answer."
>
> "DMCP Studio is a workbench for agent evaluation over MCP servers: choose the
> claim first, generate from an open-source MCP substrate, and grade effects,
> not prose."

Action: go to **Score**, run or reuse a candidate, toggle **Effect -> Answer**,
and end on the verdict bar.

## Shot list

| time | screen | cue |
|---|---|---|
| 0:00 | Stage 0 header | MCP-agent selection problem |
| 0:20 | Advisor metrics | approved plan, MDE, claim boundary |
| 0:50 | Replay statistical report | scoped, inconclusive result |
| 1:15 | server cards -> Explore | open-source MCP substrate becomes goals |
| 1:40 | Distill | trace becomes effect checkpoints |
| 2:05 | Score | Effect/Answer verdict flip |
