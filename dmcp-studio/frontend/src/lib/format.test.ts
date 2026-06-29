import { describe, expect, it } from "vitest";
import { fmtArgs } from "./format";

describe("fmtArgs", () => {
  it("renders arrays as bracketed lists", () => {
    expect(fmtArgs({ symbols: ["AAPL", "MSFT"] })).toBe("symbols=[AAPL,MSFT]");
  });

  it("renders nested objects as JSON, not [object Object]", () => {
    expect(fmtArgs({ filter: { from: "2020" } })).toBe('filter={"from":"2020"}');
  });

  it("joins multiple args", () => {
    expect(fmtArgs({ a: 1, b: "x" })).toBe("a=1, b=x");
  });
});
