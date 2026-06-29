// Pure verdict logic (no React) — the heart of the "effect vs answer" story.
// Returns structured rich text so the rendering stays in the component and the
// decision logic is unit-testable.
import type { DResponse, DStatus, ScoreDone, ScoreMode } from "../types";

export interface Span {
  text: string;
  bold?: boolean;
}
export type RichText = Span[];

const t = (text: string): Span => ({ text });
const b = (text: string): Span => ({ text, bold: true });

export interface ScoreVerdict {
  pass: boolean;
  label: string;
  why: RichText;
}

export function scoreVerdict(done: ScoreDone, mode: ScoreMode): ScoreVerdict {
  if (mode === "effect") {
    if (done.effect_pass) {
      return {
        pass: true,
        label: "Effect scoring · grades the trajectory",
        why: [
          t("All "),
          b(`${done.required} effects`),
          t(
            " reproduced under deterministic replay — including any equivalence-set tool. The final answer is never read.",
          ),
        ],
      };
    }
    const missing = done.checkpoints
      .filter((c) => !c.met)
      .map((c) => "#" + c.n)
      .join(", ");
    const tail = t(
      " never fired. The trajectory stopped short of the required evidence, so the run fails — no matter how complete the prose looks.",
    );
    return {
      pass: false,
      label: "Effect scoring · grades the trajectory",
      why: missing ? [t("Checkpoint "), b(missing), tail] : [t("A required effect"), tail],
    };
  }

  if (!done.answer_pass && done.effect_pass) {
    return {
      pass: false,
      label: "Answer matching · grades the final string",
      why: [
        t(
          "The prose is correct work, but its live numbers no longer match the stored reference, so string-matching ",
        ),
        b("fails a genuinely correct run"),
        t(". This is the false penalty effect-scoring avoids."),
      ],
    };
  }
  if (done.answer_pass) {
    return {
      pass: true,
      label: "Answer matching · grades the final string",
      why: [
        t("The summary mentions the companies and the right terms, so a string-matcher "),
        b("accepts it"),
        t(" — even when a required tool was never called."),
      ],
    };
  }
  return {
    pass: false,
    label: "Answer matching · grades the final string",
    why: [t("The final answer doesn't match the reference string.")],
  };
}

export function contrastNote(done: ScoreDone, live: boolean): RichText {
  let note: RichText;
  if (done.effect_pass !== done.answer_pass) {
    note =
      done.answer_pass && !done.effect_pass
        ? [
            b("The disagreement: "),
            t(
              "answer-matching would pass this run on its confident summary, but a required effect never fired. Effect-scoring catches the missing work — incomplete aggregation, the dominant failure mode in the paper.",
            ),
          ]
        : [
            b("The disagreement: "),
            t(
              "this agent did everything right, but answer-matching fails it because the live data moved since the reference was recorded. Effect-scoring passes it.",
            ),
          ];
  } else {
    note = done.effect_pass
      ? [
          t(
            "Both modes agree here. The interesting cases are confident-but-incomplete and stale-but-correct.",
          ),
        ]
      : [t("Both modes fail this run.")];
  }
  if (live) {
    return [
      b("Live mode: "),
      t(
        "scoring runs on deterministic replay (the graded path); live drives collect/explore/distill. ",
      ),
      ...note,
    ];
  }
  return note;
}

// ---- Advisor (Stage 0) verdict mapping ----
export interface AdvisorVerdict {
  chip: string;
  tone: "pass" | "fail" | "";
  mode: string;
}

const ADVISOR_VERDICT: Record<DStatus, AdvisorVerdict> = {
  approved: { chip: "APPROVED", tone: "pass", mode: "design is statistically defensible" },
  warning: { chip: "WARNING", tone: "", mode: "usable design, with caveats" },
  refused: { chip: "REFUSED", tone: "fail", mode: "this design would fool you" },
  needs_clarification: { chip: "CLARIFY", tone: "", mode: "needs more to plan" },
};

export function advisorVerdict(status: DStatus): AdvisorVerdict {
  return ADVISOR_VERDICT[status];
}

export function advisorWhy(r: DResponse): string {
  if (r.status === "refused" && r.refusal)
    return `${r.refusal.reason} ${r.refusal.statistical_reason}`;
  if (r.status === "needs_clarification" && r.clarification) return r.clarification.why_needed;
  if (r.status === "warning")
    return `${r.warnings.length} warning${r.warnings.length === 1 ? "" : "s"} — usable, but the claim is bounded.`;
  return "The planned design supports the claim within its stated boundary; every parameter cites a guide rule.";
}
