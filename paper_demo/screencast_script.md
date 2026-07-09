# DMCP Studio - screencast script (<= 2.5 min)

**Hard cap: 2:30 (desk-reject if over).** This version is timed to **~2:25**,
with the first half centered on the current Benchmark Advisor / Studio state and
the second half showing how DynamicMCPBench works internally. Record against
**REPLAY** for reliability; the flow is deterministic and backed by committed
fixtures, while LIVE remains available for a short proof segment if the network
is stable.

**Before recording**
- Launch: `dmcp-studio/scripts/run_demo.sh` -> open `http://127.0.0.1:8000`.
- Window at projector resolution (~1440x900); keep browser zoom low enough that
  the top stepper, Advisor verdict, metric strip, and report cards are legible.
- Start on **Stage 0 - Design**, mode toggle on **Replay**.
- Let the default design finish computing before recording, so the Advisor
  verdict already shows **APPROVED** and the metric strip is populated.
- Optional: upload to an unlisted YouTube link and put it in the paper, or
  attach the MP4 as supplementary.

> **Live note.** Keep the main recording in **Replay**. LIVE mode can drive
> collect -> explore -> distill -> score over real servers, but the screencast
> should not depend on network latency, third-party server availability, or paid
> model calls. If you add a live proof, make it a 5-8 second insert only.

---

## Beats (cumulative time)

**0:00-0:18 - The problem.**
> "More agent builders now rely on MCP servers: finance tools, file stores,
> databases, and private company APIs. The hard question is no longer just
> whether an agent can call a tool. It is which agent-server setup is worth
> trusting on *your* live servers."
>
> "Answer matching is brittle on live data, and fixed tool lists punish valid
> alternative paths. DMCP Studio makes the alternative tangible: first design a
> defensible benchmark, then grade effects rather than final prose."

Screen: Stage 0 header and top navigation. Keep the cursor near the five-stage
pipeline: Design -> Collect servers -> Explore live -> Distill -> Score.

**0:18-0:38 - Benchmark Advisor as Stage 0.**
> "That is why Studio now starts with Benchmark Advisor. The user describes the
> comparison, the candidate models, the server scope, the task budget, attempts
> per task, and any safety constraints. The Advisor turns that intent into a
> statistical benchmark design before we generate a single task."
>
> "Here the default question is a pairwise finance comparison. The verdict is
> approved, which means the design is launchable, but only within the claim
> boundary shown on screen."

Action: point at **Planning request**, **advisor mode**, **candidate models**,
**server scope**, then the **Advisor verdict** card.

**0:38-1:03 - Statistical report: what the approval means.**
> "The key numbers are here. Tasks are unique benchmark tasks; attempts are
> repeated runs per task. Attempts can support reliability views, but they do
> not multiply the independent sample size."
>
> "The planned MDE is the minimum effect size this budget can roughly resolve.
> With fewer unique tasks, small model gaps are not defensible; with more tasks,
> the MDE shrinks. The power curve makes that tradeoff visible before spending
> generation or evaluation budget."

Action: point at **tasks**, **attempts**, **planned MDE**, **CI width**, and the
**Power curve**. If time allows, drag the task-budget slider slightly and let
the MDE update.

**1:03-1:25 - Advisor panels, quickly.**
> "The rest of the workbench explains the decision. The claim card says what we
> may and may not claim. The method card records the statistical family. The
> assumptions panel keeps independence, missingness, multiplicity, and repeated
> attempts explicit. Alternatives show cheaper, stronger, or narrowed-claim
> designs; issues and repairs tell the user how to fix an underpowered or unsafe
> plan."
>
> "The post-run report shape is also visible here, so the user sees not just how
> to launch a benchmark, but how completed evidence will be interpreted."

Action: scroll through **Claim card**, **Method card**, **Assumptions**,
**Alternatives**, **Issues and repairs**, **Citations**, and **Post-run report
view** without lingering.

**1:25-1:48 - Demo results page.**
> "Now we carry the approved design into Collect. In Replay, the guarded launch
> does not start a real corpus job; it loads a frozen report from the same kind
> of evidence the live handoff produces."
>
> "This report is intentionally modest: on a generated 100-task finance corpus,
> DeepSeek is observed two percentage points above MiniMax, but the confidence
> interval crosses zero. The report therefore allows a scoped, inconclusive
> comparison and forbids a best-model claim. That is the point of the Advisor:
> it helps users choose and interpret agents without overclaiming."

Action: click **Carry this design into Collect**, check **Confirm replay demo
report load**, click **Start replay demo**, then point at **Replay statistical
report**, sample size, MDE/status, paired delta, supported claims, and report
boundaries.

**1:48-2:04 - Collect -> goal: what DMCP runs on.**
> "Below the Advisor handoff are the actual MCP servers. Studio reads each live
> server's tool surface and tags it by dynamism: static, live-read, or
> stateful-write. This is where the user's own servers enter the benchmark."
>
> "From that substrate we generate a realistic goal and move into the internal
> DynamicMCPBench pipeline."

Action: select the finance server cards if needed; click **Generate a goal and
explore ->**. Land on Explore and let the generated goal appear.

**2:04-2:19 - Explore and distill.**
> "DMCP generates forward. An explorer agent pursues the goal and records a
> successful reference trace. Then the distiller converts that trace into
> path-agnostic effect checkpoints: required effects, equivalence sets, values
> produced, and ordering constraints."

Action: run or show the replayed exploration calls, then advance to **Distill**.
Point at the checkpoint ledger and an equivalence chip such as
`download` / `get_price_history`.

**2:19-2:25 - Score and close.**
> "Finally, we score a candidate by replaying its trajectory against those
> checkpoints. Flip Effect to Answer and the verdict can change on the same
> run: fluent prose may hide missing work, while correct live effects may
> disagree with a stale reference answer."
>
> "DMCP Studio is a benchmark-design and evaluation workbench for agents over
> MCP servers: choose the claim first, generate from your servers, and grade
> effects, not the answer."

Action: go to **Score**, run a candidate if already cached, toggle
**Effect -> Answer**, and end on the verdict bar.

---

## Shot list (for editing)

| time | screen | narration cue |
|---|---|---|
| 0:00 | Stage 0 header + stepper | MCP-agent selection problem |
| 0:18 | Planning request + Advisor verdict | Benchmark Advisor designs before generation |
| 0:38 | metric strip + power curve | MDE, unique tasks, attempts caveat |
| 1:03 | claim/method/assumptions/alternatives/report panels | why the approval is bounded |
| 1:25 | Collect Advisor handoff + replay statistical report | observed result and claim boundary |
| 1:48 | server cards | user's MCP servers enter the benchmark |
| 2:04 | Explore -> Distill | reference trace becomes effect checkpoints |
| 2:19 | Score verdict + Effect/Answer toggle | grade effects, not prose |

---

## Fallback cuts if the recording runs long

- Skip dragging the task-budget slider; just point at planned MDE and power
  curve.
- Do not open the export preview.
- Show only the first two Advisor explanation panels: Claim card and
  Assumptions.
- In the final scoring beat, use an already-run candidate rather than waiting
  for a fresh replay.
