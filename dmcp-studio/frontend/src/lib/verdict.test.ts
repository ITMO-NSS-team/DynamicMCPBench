import { describe, expect, it } from "vitest";
import { advisorVerdict, contrastNote, scoreVerdict } from "./verdict";
import type { ScoreDone } from "../types";

// hermes3-8b: trajectory misses checkpoint #5, but the prose reads convincingly.
const confidentButIncomplete: ScoreDone = {
  effect_pass: false,
  answer_pass: true,
  final_answer: "AAPL, MSFT and GOOGL look healthy.",
  met_count: 5,
  required: 6,
  checkpoints: [
    { n: 1, checkpoint_id: "cp1", kind: "tool_effect", met: true, reason: "" },
    { n: 5, checkpoint_id: "cp5", kind: "tool_effect", met: false, reason: "" },
  ],
};

describe("scoreVerdict", () => {
  it("fails under effect scoring and names the missing checkpoint", () => {
    const v = scoreVerdict(confidentButIncomplete, "effect");
    expect(v.pass).toBe(false);
    expect(v.why.map((s) => s.text).join("")).toContain("#5");
  });

  it("passes under answer matching for the same run (the flip)", () => {
    const v = scoreVerdict(confidentButIncomplete, "answer");
    expect(v.pass).toBe(true);
  });

  it("never renders an empty checkpoint reference when nothing is individually unmet", () => {
    const noUnmetRows: ScoreDone = { ...confidentButIncomplete, checkpoints: [] };
    const v = scoreVerdict(noUnmetRows, "effect");
    expect(v.pass).toBe(false);
    expect(v.why.every((s) => s.text.trim().length > 0)).toBe(true);
  });

  it("flags the false penalty when answer fails a genuinely correct run", () => {
    const staleButCorrect: ScoreDone = {
      ...confidentButIncomplete,
      effect_pass: true,
      answer_pass: false,
    };
    const v = scoreVerdict(staleButCorrect, "answer");
    expect(v.pass).toBe(false);
    expect(v.why.some((s) => s.bold && /genuinely correct run/.test(s.text))).toBe(true);
  });
});

describe("contrastNote", () => {
  it("describes the disagreement when modes diverge", () => {
    const note = contrastNote(confidentButIncomplete, false);
    expect(note[0].bold).toBe(true);
    expect(note.map((s) => s.text).join("")).toContain("disagreement");
  });

  it("prefixes a live-mode caveat", () => {
    const note = contrastNote(confidentButIncomplete, true);
    expect(note.map((s) => s.text).join("")).toContain("Live mode");
  });
});

describe("advisorVerdict", () => {
  it("maps statuses to tone and chip", () => {
    expect(advisorVerdict("approved")).toMatchObject({ tone: "pass", chip: "APPROVED" });
    expect(advisorVerdict("refused")).toMatchObject({ tone: "fail", chip: "REFUSED" });
    expect(advisorVerdict("warning").tone).toBe("");
  });
});
