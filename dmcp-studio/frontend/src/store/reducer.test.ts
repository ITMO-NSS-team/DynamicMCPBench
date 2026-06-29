import { describe, expect, it } from "vitest";
import { equivOverrides, initialState, reducer, type StudioState } from "./reducer";
import type { ServerCard } from "../types";

const servers: ServerCard[] = [
  { server_id: "yfinance", dynamism: "live_read", sandbox: false, description: "", tools: [] },
  { server_id: "arxiv", dynamism: "live_read", sandbox: false, description: "", tools: [] },
];

describe("reducer", () => {
  it("auto-selects the first server only when nothing is selected", () => {
    const s = reducer(initialState(), { type: "servers_loaded", servers });
    expect(s.selected).toEqual(["yfinance"]);
    const s2 = reducer({ ...s, selected: ["arxiv"] }, { type: "servers_loaded", servers });
    expect(s2.selected).toEqual(["arxiv"]);
  });

  it("toggles server selection", () => {
    let s = reducer(initialState(), { type: "toggle_server", id: "arxiv" });
    expect(s.selected).toContain("arxiv");
    s = reducer(s, { type: "toggle_server", id: "arxiv" });
    expect(s.selected).not.toContain("arxiv");
  });

  it("enables every equivalence-set tool on distill", () => {
    const s = reducer(initialState(), {
      type: "distilled",
      spec: { checkpoints: [], minefields: [] },
      equivSets: { cp3: ["download", "get_price_history"] },
    });
    expect(s.equivOn).toEqual({ download: true, get_price_history: true });
    expect(s.distilled).toBe(true);
  });

  it("keeps at least one equivalence member enabled", () => {
    const base = reducer(initialState(), {
      type: "distilled",
      spec: { checkpoints: [], minefields: [] },
      equivSets: { cp3: ["download", "get_price_history"] },
    });
    const off = reducer(base, { type: "toggle_equiv", tool: "download" });
    expect(off.equivOn.download).toBe(false);
    // turning off the last remaining member is a no-op
    const stillOn = reducer(off, { type: "toggle_equiv", tool: "get_price_history" });
    expect(stillOn.equivOn.get_price_history).toBe(true);
  });

  it("computes equiv overrides only for a strict enabled subset", () => {
    const full: StudioState = {
      ...initialState(),
      equivSets: { cp3: ["download", "get_price_history"] },
      equivOn: { download: true, get_price_history: true },
    };
    expect(equivOverrides(full.equivOn, full.equivSets)).toBe("");
    expect(equivOverrides({ download: true, get_price_history: false }, full.equivSets)).toBe(
      "download",
    );
  });

  it("resets the walkthrough on mode change", () => {
    const dirty: StudioState = { ...initialState(), explored: true, distilled: true, ran: true };
    const s = reducer(dirty, { type: "reset_for_mode", mode: "live" });
    expect(s).toMatchObject({
      mode: "live",
      view: "collect",
      explored: false,
      distilled: false,
      ran: false,
    });
  });
});
