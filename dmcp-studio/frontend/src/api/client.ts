// Typed API client for the DMCP Studio backend. Sync routes are fetched and
// validated against the zod schemas; the two streaming stages use EventSource.
import type { z } from "zod";
import {
  CandidateListSchema,
  DistillOutSchema,
  DResponseSchema,
  GoalOutSchema,
  LeaderboardSchema,
  ServerListSchema,
} from "./schemas";
import type { Mode } from "./schemas";

async function getValidated<T>(url: string, schema: z.ZodType<T>): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} → ${r.status}`);
  return schema.parse(await r.json());
}

async function postValidated<T>(url: string, body: unknown, schema: z.ZodType<T>): Promise<T> {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${url} → ${r.status}`);
  return schema.parse(await r.json());
}

export const api = {
  servers: (mode: Mode) => getValidated(`/api/servers?mode=${mode}`, ServerListSchema),
  goal: (mode: Mode, serverIds: string[]) =>
    postValidated(`/api/goal?mode=${mode}`, { server_ids: serverIds }, GoalOutSchema),
  distill: (mode: Mode) =>
    postValidated(`/api/distill?mode=${mode}`, { trace_id: null }, DistillOutSchema),
  candidates: (mode: Mode) => getValidated(`/api/candidates?mode=${mode}`, CandidateListSchema),
  leaderboard: (mode: Mode) => getValidated(`/api/leaderboard?mode=${mode}`, LeaderboardSchema),
  advisorDesign: (req: Record<string, unknown>) =>
    postValidated("/api/advisor/design", req, DResponseSchema),
};

// Minimal typed wrapper over EventSource: dispatches parsed frames by event
// name and returns a cleanup function that closes the stream.
export type SSEHandlers = Record<string, (data: unknown) => void>;

export function openSSE(url: string, handlers: SSEHandlers, onError?: () => void): () => void {
  const es = new EventSource(url);
  for (const [event, fn] of Object.entries(handlers)) {
    es.addEventListener(event, (e) => {
      try {
        fn(JSON.parse((e as MessageEvent).data));
      } catch {
        /* ignore a malformed frame */
      }
    });
  }
  es.onerror = () => {
    es.close();
    onError?.();
  };
  return () => es.close();
}
