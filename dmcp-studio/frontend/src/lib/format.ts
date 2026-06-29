// Pure formatting helpers (no React, no DOM) — unit-testable.

function fmtValue(v: unknown): string {
  if (Array.isArray(v)) return "[" + v.join(",") + "]";
  if (v !== null && typeof v === "object") return JSON.stringify(v);
  return String(v);
}

export function fmtArgs(args: Record<string, unknown>): string {
  return Object.entries(args || {})
    .map(([k, v]) => `${k}=${fmtValue(v)}`)
    .join(", ");
}
