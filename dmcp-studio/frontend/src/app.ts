/* ============================================================
   DMCP Studio — frontend (TypeScript, bundled with Bun).
   Stages call fetch()/EventSource against /api/*; verdicts come
   from the server (effect = real evaluate(); answer = demo foil).
   Build:  bun run build   (emits ../app.js)
   ============================================================ */

let MODE: "replay" | "live" = "replay"; // toggled in the header
const DELAY = 0.4; // SSE pacing hint (server-side sleep, seconds)

/* ---------------- API types (mirror backend/models.py) ---------------- */
interface ServerCard {
  server_id: string;
  dynamism: string;
  sandbox: boolean;
  description: string;
  tools: string[];
}
interface GoalOut {
  goal: string;
  persona: string | null;
}
interface ExploreCall {
  idx: number;
  server_id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  ok: boolean;
}
interface ExploreDone {
  trace_id: string;
  n_calls: number;
  success: boolean;
}
interface CheckpointVerdict {
  n: number;
  checkpoint_id: string;
  kind: string;
  met: boolean;
  reason: string;
}
interface ScoreDone {
  effect_pass: boolean;
  answer_pass: boolean;
  final_answer: string;
  met_count: number;
  required: number;
  checkpoints: CheckpointVerdict[];
}
interface ToolRef {
  server_id: string;
  tool_name: string;
}
interface Checkpoint {
  kind: string;
  checkpoint_id: string;
  description: string;
  equivalence_set?: ToolRef[];
}
interface TaskSpecView {
  checkpoints: Checkpoint[];
  minefields: unknown[];
}
interface DistillOut {
  task_spec: TaskSpecView;
  equivalence_sets: Record<string, string[]>;
}
interface CandidateCard {
  name: string;
  note: string;
}
interface LeaderboardRow {
  model: string;
  group: string;
  pass3: number;
}
interface Leaderboard {
  placeholder: boolean;
  note: string | null;
  rows: LeaderboardRow[];
}

type Mode = "effect" | "answer";

interface State {
  step: number;
  servers: Set<string>;
  explored: boolean;
  distilled: boolean;
  refCalls: ExploreCall[];
  spec: TaskSpecView | null;
  equivSets: Record<string, string[]>;
  equivOn: Record<string, boolean>;
  candidate: string | null;
  mode: Mode;
  ran: boolean;
  lastDone: ScoreDone | null;
  es: EventSource | null;
  goal: string;
  persona: string | null;
}

const state: State = {
  step: 0,
  servers: new Set<string>(),
  explored: false,
  distilled: false,
  refCalls: [],
  spec: null,
  equivSets: {},
  equivOn: {},
  candidate: null,
  mode: "effect",
  ran: false,
  lastDone: null,
  es: null,
  goal: "",
  persona: null,
};

/* ---------------- DOM helpers ---------------- */
function $(id: string): HTMLElement {
  const e = document.getElementById(id);
  if (!e) throw new Error(`missing #${id}`);
  return e;
}
async function getJSON<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} → ${r.status}`);
  return r.json() as Promise<T>;
}
async function postJSON<T>(url: string, body: unknown): Promise<T> {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${url} → ${r.status}`);
  return r.json() as Promise<T>;
}

/* Friendly, in-voice error banner on the active stage (never a stack trace). */
function showError(message: string): void {
  const stage = stages[state.step];
  if (!stage) return;
  stage.querySelectorAll(".error-banner").forEach((n) => n.remove());
  const head = stage.querySelector(".stage-head");
  const el = document.createElement("div");
  el.className = "error-banner";
  el.setAttribute("role", "alert");
  el.innerHTML = `<b>Something went wrong.</b> ${message} The studio stays on the deterministic replay path — try again, or reload.`;
  if (head && head.parentElement) head.parentElement.insertBefore(el, head.nextSibling);
  else stage.prepend(el);
}
function clearError(): void {
  stages[state.step]?.querySelectorAll(".error-banner").forEach((n) => n.remove());
}

/* ---------------- nav ---------------- */
const stages = [...document.querySelectorAll<HTMLElement>(".stage")];
const steps = [...document.querySelectorAll<HTMLElement>(".step")];
function gotoStep(i: number): void {
  state.step = i;
  // leaving Stage 0 — Design (managed outside the .stage/.step index arrays)
  document.getElementById("stage-design")?.classList.remove("active");
  document.getElementById("stepDesign")?.classList.remove("active");
  stages.forEach((s, k) => s.classList.toggle("active", k === i));
  steps.forEach((s, k) => {
    s.classList.toggle("active", k === i);
    s.classList.toggle("done", k < i || (k === 1 && state.explored) || (k === 2 && state.distilled));
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}
$("stepper").addEventListener("click", (e) => {
  const s = (e.target as HTMLElement).closest<HTMLElement>(".step");
  if (!s) return;
  const i = Number(s.dataset.step);
  if (i === 1 && state.servers.size === 0) return;
  if (i === 2 && !state.explored) return;
  if (i === 3 && !state.distilled) return;
  if (i === 1) void ensureGoal();
  gotoStep(i);
});
document.querySelectorAll<HTMLElement>("[data-goto]").forEach((b) =>
  b.addEventListener("click", () => gotoStep(Number(b.dataset.goto))),
);

/* ---------------- LIVE / REPLAY toggle ---------------- */
function setModeUI(m: "replay" | "live"): void {
  MODE = m;
  $("modeToggle")
    .querySelectorAll<HTMLElement>("button")
    .forEach((x) => x.classList.toggle("on", x.dataset.m === m));
}
$("modeToggle").addEventListener("click", (e) => {
  const b = (e.target as HTMLElement).closest<HTMLButtonElement>("button");
  if (!b) return;
  const m = b.dataset.m as "replay" | "live";
  if (m === MODE) return;
  setModeUI(m);
  resetFlow(); // start the walkthrough over in the new mode
});

function resetFlow(): void {
  if (state.es) state.es.close();
  state.servers = new Set<string>();
  state.explored = false;
  state.distilled = false;
  state.refCalls = [];
  state.spec = null;
  state.equivSets = {};
  state.equivOn = {};
  state.candidate = null;
  state.ran = false;
  state.lastDone = null;
  state.goal = "";
  state.persona = null;
  goalLoaded = false;
  candidatesLoaded = false;
  steps.forEach((s) => s.classList.remove("done"));
  (["toDistill", "toScore"] as const).forEach((id) => {
    ($(id) as HTMLButtonElement).disabled = true;
  });
  $("traceStream").innerHTML =
    '<div class="empty">Run exploration to record a successful trajectory.</div>';
  $("ckptList").innerHTML = "";
  $("candPick").innerHTML = "";
  $("goalText").textContent = "Generating a goal from the tool surface…";
  resetRun();
  gotoStep(0);
  void loadServers();
}

/* ---------------- stage 1: servers ---------------- */
async function loadServers(): Promise<void> {
  const grid = $("serverGrid");
  grid.innerHTML = '<div class="empty">Loading servers…</div>';
  let servers: ServerCard[];
  try {
    servers = await getJSON<ServerCard[]>(`/api/servers?mode=${MODE}`);
  } catch {
    grid.innerHTML = "";
    showError("Couldn't reach the studio backend to list servers.");
    return;
  }
  clearError();
  grid.innerHTML = "";
  servers.forEach((s, idx) =>
    grid.appendChild(makeServerCard(s, preselectId ? s.server_id === preselectId : idx === 0)),
  );
  preselectId = null; // consume one-shot preselect
  ($("toExplore") as HTMLButtonElement).disabled = state.servers.size === 0;
}
let preselectId: string | null = null;

function makeServerCard(s: ServerCard, selected: boolean): HTMLElement {
  const isWrite = s.dynamism === "stateful_write";
  if (selected) state.servers.add(s.server_id);
  const el = document.createElement("div");
  el.className = "server-card" + (selected ? " sel" : "");
  const pill = isWrite
    ? `<span class="pill write">stateful-write · ${s.sandbox ? "sandboxed" : "UNSANDBOXED"}</span>`
    : `<span class="pill live">${s.dynamism === "static" ? "static" : "live-read"}</span>`;
  el.innerHTML = `
      <div class="sc-name">${s.server_id}</div>
      <div class="sc-meta">${pill}</div>
      <div class="sc-desc">${s.description}</div>
      <div class="sc-tools">${(s.tools || []).join(" · ")}</div>`;
  el.addEventListener("click", () => {
    if (state.servers.has(s.server_id)) state.servers.delete(s.server_id);
    else state.servers.add(s.server_id);
    el.classList.toggle("sel");
    ($("toExplore") as HTMLButtonElement).disabled = state.servers.size === 0;
  });
  return el;
}

/* Bring-your-own-server (A4): register a server, then explore it in LIVE mode. */
async function addByoServer(): Promise<void> {
  const id = ($("byoId") as HTMLInputElement).value.trim();
  const raw = ($("byoCmd") as HTMLInputElement).value.trim();
  if (!id || !raw) {
    showError("Enter a server id and a launch command (or URL).");
    return;
  }
  const isUrl = /^https?:\/\//i.test(raw);
  const payload = isUrl
    ? { server_id: id, transport: "streamable_http", endpoint: raw }
    : { server_id: id, transport: "stdio", command: raw.split(/\s+/)[0], args: raw.split(/\s+/).slice(1) };
  const btn = $("byoAdd") as HTMLButtonElement;
  btn.disabled = true;
  try {
    const r = await fetch("/api/register-server", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const card = (await r.json()) as ServerCard & { detail?: string };
    if (!r.ok) {
      showError(`Couldn't register that server: ${card.detail || r.status}`);
      return;
    }
    clearError();
    ($("byoId") as HTMLInputElement).value = "";
    ($("byoCmd") as HTMLInputElement).value = "";
    // BYO servers can only be explored live (no replay fixture). Switch to LIVE
    // and reload the grid — live_servers() now includes the registered server,
    // which we auto-select so the visitor can explore it immediately.
    preselectId = card.server_id;
    setModeUI("live");
    resetFlow();
  } catch {
    showError("Couldn't reach the backend to register the server.");
  } finally {
    btn.disabled = false;
  }
}
$("byoAdd").addEventListener("click", () => void addByoServer());

$("toExplore").addEventListener("click", () => {
  void ensureGoal();
  gotoStep(1);
});

/* ---------------- stage 2: goal + explore ---------------- */
let goalLoaded = false;
async function ensureGoal(): Promise<void> {
  if (goalLoaded) return;
  goalLoaded = true;
  try {
    const g = await postJSON<GoalOut & { fellback?: string }>(`/api/goal?mode=${MODE}`, {
      server_ids: [...state.servers],
    });
    state.goal = g.goal;
    state.persona = g.persona;
    $("goalText").textContent = g.goal;
    $("goalPersona").textContent = g.fellback
      ? "fixture goal (live fell back)"
      : g.persona || "persona-seeded";
  } catch {
    goalLoaded = false; // allow a retry
    $("goalText").textContent = "Couldn't generate a goal — reload to try again.";
    showError("The goal generator didn't respond.");
  }
}

interface LineStatus {
  cls: string;
  txt: string;
}
function fmtArgs(args: Record<string, unknown>): string {
  return Object.entries(args || {})
    .map(([k, v]) => `${k}=${Array.isArray(v) ? "[" + v.join(",") + "]" : String(v)}`)
    .join(", ");
}
function traceLine(idx: number, tool: string, args: Record<string, unknown>, status: LineStatus): HTMLElement {
  const row = document.createElement("div");
  row.className = "trace-line";
  row.innerHTML = `<span class="trace-idx">${idx}</span>
    <span class="trace-call"><span class="tool">${tool}</span>(<span class="args">${fmtArgs(args)}</span>)</span>
    <span class="trace-status ${status.cls}">${status.txt}</span>`;
  return row;
}

$("runExplore").addEventListener("click", () => {
  const btn = $("runExplore") as HTMLButtonElement;
  btn.disabled = true;
  const stream = $("traceStream");
  stream.innerHTML = "";
  state.refCalls = [];
  const dot = $("exploreDot");
  dot.style.background = "var(--signal)";
  dot.style.boxShadow = "0 0 8px var(--signal-glow)";
  dot.classList.add("pulsing");

  let url = `/api/explore?mode=${MODE}&delay=${DELAY}`;
  if (MODE === "live") {
    url +=
      `&server_ids=${encodeURIComponent([...state.servers].join(","))}` +
      `&goal=${encodeURIComponent(state.goal)}` +
      (state.persona ? `&persona=${encodeURIComponent(state.persona)}` : "");
  }
  const es = new EventSource(url);
  state.es = es;
  es.addEventListener("fellback", (e) => {
    const d = JSON.parse((e as MessageEvent).data) as { reason: string };
    const banner = document.createElement("div");
    banner.className = "note";
    banner.style.marginBottom = "10px";
    banner.innerHTML = `<b>Live server unreachable</b> — falling back to the deterministic replay fixture. (${d.reason})`;
    stream.prepend(banner);
  });
  es.addEventListener("call", (e) => {
    const c = JSON.parse((e as MessageEvent).data) as ExploreCall;
    state.refCalls.push(c);
    stream.appendChild(traceLine(c.idx, c.tool_name, c.arguments, { cls: "ok", txt: "200 ok" }));
    $("exploreCount").textContent = `${c.idx} calls`;
  });
  let exploreDone = false;
  es.addEventListener("done", (e) => {
    const d = JSON.parse((e as MessageEvent).data) as ExploreDone;
    exploreDone = true;
    es.close();
    dot.classList.remove("pulsing");
    $("exploreCount").textContent = `${d.n_calls} calls · ${d.success ? "success" : "incomplete"}`;
    state.explored = true;
    ($("toDistill") as HTMLButtonElement).disabled = false;
    steps[1]?.classList.add("done");
    btn.disabled = false;
  });
  es.onerror = () => {
    es.close();
    dot.classList.remove("pulsing");
    btn.disabled = false;
    if (!exploreDone) showError("The exploration stream was interrupted.");
  };
});
$("toDistill").addEventListener("click", () => {
  gotoStep(2);
  void runDistill();
});

/* ---------------- stage 3: distill ---------------- */
function renderTraceMirror(): void {
  const m = $("traceMirror");
  m.innerHTML = "";
  state.refCalls.forEach((c, i) => {
    const row = traceLine(c.idx, c.tool_name, c.arguments, { cls: "ok", txt: "ok" });
    row.style.animationDelay = i * 0.04 + "s";
    m.appendChild(row);
  });
  $("traceMirrorCount").textContent = `${state.refCalls.length} calls`;
}

function ckptKindLabel(kind: string): string {
  return kind === "value_produced" ? "value produced" : "tool effect";
}
function ckptInner(cp: Checkpoint, n: number): string {
  const eq = state.equivSets[cp.checkpoint_id];
  let body = `<span class="t">${cp.checkpoint_id}</span> — ${cp.description}`;
  if (eq && eq.length > 1) {
    const tools = eq
      .map((t) => `<span class="equiv-tool ${state.equivOn[t] ? "" : "off"}" data-tool="${t}">${t}</span>`)
      .join('<span class="equiv-or">or</span>');
    body += `<div class="equiv">${tools}</div>
      <div class="equiv-hint">↑ equivalence set — any enabled tool satisfies this effect. Click to toggle and re-score.</div>`;
  }
  const isValue = cp.kind === "value_produced";
  const pathAgnostic =
    eq && eq.length > 1
      ? '<span class="ckpt-kind" style="color:var(--amber);border-color:var(--amber-dim)">path-agnostic</span>'
      : "";
  return `<div class="ckpt-top">
      <span class="ckpt-num">${n}</span>
      <span class="ckpt-kind ${isValue ? "value" : ""}">${ckptKindLabel(cp.kind)}</span>
      ${pathAgnostic}
    </div>
    <div class="ckpt-body">${body}</div>`;
}

async function runDistill(): Promise<void> {
  renderTraceMirror();
  const list = $("ckptList");
  list.innerHTML = "";
  $("ckptCount").textContent = "compiling…";
  let res: DistillOut;
  try {
    res = await postJSON<DistillOut>(`/api/distill?mode=${MODE}`, { trace_id: null });
  } catch {
    $("ckptCount").textContent = "failed";
    showError("The distiller didn't return a TaskSpec.");
    return;
  }
  clearError();
  state.spec = res.task_spec;
  state.equivSets = res.equivalence_sets || {};
  state.equivOn = {};
  Object.values(state.equivSets).forEach((tools) => tools.forEach((t) => (state.equivOn[t] = true)));

  const cps = state.spec.checkpoints;
  cps.forEach((cp, i) => {
    const el = document.createElement("div");
    el.className = "ckpt";
    el.dataset.id = cp.checkpoint_id;
    el.style.opacity = "0";
    el.innerHTML = ckptInner(cp, i + 1);
    list.appendChild(el);
    requestAnimationFrame(() => {
      el.style.transition = "opacity .3s";
      el.style.opacity = "1";
    });
  });
  $("ckptCount").textContent = `${cps.length} checkpoints`;
  $("mfCount").textContent = String((state.spec.minefields || []).length || "none");
  $("specMeta").style.display = "flex";
  state.distilled = true;
  ($("toScore") as HTMLButtonElement).disabled = false;
  steps[2]?.classList.add("done");
  bindEquiv();
}

function bindEquiv(): void {
  document.querySelectorAll<HTMLElement>(".equiv-tool").forEach((t) => {
    t.onclick = () => {
      const tool = t.dataset.tool;
      if (!tool) return;
      const entry = Object.entries(state.equivSets).find(([, ts]) => ts.includes(tool));
      if (!entry) return;
      const others = entry[1].filter((p) => p !== tool);
      // keep at least one member enabled
      if (state.equivOn[tool] && !others.some((p) => state.equivOn[p])) return;
      state.equivOn[tool] = !state.equivOn[tool];
      document
        .querySelectorAll<HTMLElement>(`.equiv-tool[data-tool="${tool}"]`)
        .forEach((n) => n.classList.toggle("off"));
      if (state.ran) runCandidate(); // live re-score
    };
  });
}
$("toScore").addEventListener("click", () => {
  gotoStep(3);
  void loadCandidates();
});

/* ---------------- stage 4: score ---------------- */
let candidatesLoaded = false;
async function loadCandidates(): Promise<void> {
  if (candidatesLoaded) return;
  candidatesLoaded = true;
  const pick = $("candPick");
  let cands: CandidateCard[];
  try {
    cands = await getJSON<CandidateCard[]>(`/api/candidates?mode=${MODE}`);
  } catch {
    candidatesLoaded = false;
    showError("Couldn't load the candidate agents.");
    return;
  }
  clearError();
  pick.innerHTML = "";
  cands.forEach((c, idx) => {
    const el = document.createElement("div");
    el.className = "cand" + (idx === 0 ? " sel" : "");
    el.innerHTML = `<span class="cand-name">${c.name}</span><span class="cand-note">${c.note}</span>`;
    el.addEventListener("click", () => {
      document.querySelectorAll<HTMLElement>(".cand").forEach((x) => x.classList.remove("sel"));
      el.classList.add("sel");
      state.candidate = c.name;
      resetRun();
    });
    pick.appendChild(el);
    if (idx === 0) state.candidate = c.name;
  });
}

$("modeSeg").addEventListener("click", (e) => {
  const b = (e.target as HTMLElement).closest<HTMLButtonElement>("button");
  if (!b) return;
  state.mode = b.dataset.mode as Mode;
  $("modeSeg")
    .querySelectorAll<HTMLElement>("button")
    .forEach((x) => x.classList.toggle("on", x === b));
  if (state.ran && state.lastDone) renderScore(state.lastDone); // pure re-render, no refetch
});

function resetRun(): void {
  if (state.es) state.es.close();
  state.ran = false;
  state.lastDone = null;
  $("candStream").innerHTML =
    '<div class="empty">Run the candidate to replay its calls against the recorded world.</div>';
  $("candCount").textContent = "0 calls";
  ($("faWrap") as HTMLElement).hidden = true;
  $("ledger").innerHTML = "";
  $("ledgerScore").textContent = "—";
  setVerdict(null);
  $("passk").textContent = "";
  $("scoreNote").innerHTML = "";
}

$("runCand").addEventListener("click", runCandidate);

function equivOverridesParam(): string {
  const enabled = Object.entries(state.equivOn)
    .filter(([, on]) => on)
    .map(([t]) => t);
  // only send when something is disabled (a strict subset of the sets)
  const all = Object.values(state.equivSets).flat();
  return enabled.length && enabled.length < all.length ? enabled.join(",") : "";
}

function runCandidate(): void {
  if (!state.candidate) return;
  if (state.es) state.es.close();
  const btn = $("runCand") as HTMLButtonElement;
  btn.disabled = true;
  const stream = $("candStream");
  stream.innerHTML = "";
  $("ledger").innerHTML = "";
  const dot = $("candDot");
  dot.style.background = "var(--signal)";
  dot.style.boxShadow = "0 0 8px var(--signal-glow)";
  dot.classList.add("pulsing");

  const ov = equivOverridesParam();
  const url =
    `/api/score?mode=${MODE}&candidate=${encodeURIComponent(state.candidate)}&delay=${DELAY}` +
    (ov ? `&equiv_overrides=${encodeURIComponent(ov)}` : "");
  const es = new EventSource(url);
  state.es = es;
  let nCalls = 0;
  es.addEventListener("call", (e) => {
    const c = JSON.parse((e as MessageEvent).data) as ExploreCall;
    nCalls = c.idx;
    stream.appendChild(traceLine(c.idx, c.tool_name, c.arguments, { cls: "ok", txt: "ok" }));
    $("candCount").textContent = `${c.idx} calls`;
  });
  let scoreDone = false;
  es.addEventListener("done", (e) => {
    scoreDone = true;
    es.close();
    dot.classList.remove("pulsing");
    if (nCalls) $("candCount").textContent = `${nCalls} calls`;
    state.lastDone = JSON.parse((e as MessageEvent).data) as ScoreDone;
    state.ran = true;
    ($("faWrap") as HTMLElement).hidden = false;
    renderScore(state.lastDone);
    btn.disabled = false;
  });
  es.onerror = () => {
    es.close();
    dot.classList.remove("pulsing");
    btn.disabled = false;
    if (!scoreDone) showError("The scoring stream was interrupted.");
  };
}

function renderLedger(done: ScoreDone): void {
  const ledger = $("ledger");
  ledger.innerHTML = "";
  if (!state.spec) return;
  done.checkpoints.forEach((v) => {
    const cp = state.spec!.checkpoints[v.n - 1];
    if (!cp) return;
    const el = document.createElement("div");
    el.className = "ckpt " + (v.met ? "met" : "unmet");
    el.innerHTML = ckptInner(cp, v.n).replace(
      '<div class="ckpt-top">',
      `<div class="ckpt-top"><span class="ckpt-verdict" style="order:9">${v.met ? "met" : "unmet"}</span>`,
    );
    ledger.appendChild(el);
  });
  bindEquiv();
}

function renderScore(done: ScoreDone): void {
  renderLedger(done);
  $("ledgerScore").textContent = `${done.met_count}/${done.required} effects`;
  $("passk").textContent = "pass³ · attempt 1 of 3 shown";

  const effectPass = done.effect_pass;
  const answerPass = done.answer_pass;
  let pass: boolean;
  let modeLabel: string;
  let why: string;
  if (state.mode === "effect") {
    pass = effectPass;
    modeLabel = "Effect scoring · grades the trajectory";
    $("finalAnswer").className = "final-answer muted-by-effect";
    if (pass) {
      why = `All <b>${done.required} effects</b> reproduced under deterministic replay — including any equivalence-set tool. The final answer is never read.`;
    } else {
      const missing = done.checkpoints
        .filter((c) => !c.met)
        .map((c) => "#" + c.n)
        .join(", ");
      why = `Checkpoint <b>${missing}</b> never fired. The trajectory stopped short of the required evidence, so the run fails — no matter how complete the prose looks.`;
    }
  } else {
    pass = answerPass;
    modeLabel = "Answer matching · grades the final string";
    $("finalAnswer").className = "final-answer";
    if (!answerPass && effectPass) {
      why = `The prose is correct work, but its live numbers no longer match the stored reference answer, so string-matching <b>fails a genuinely correct run</b>. This is the false penalty effect-scoring avoids.`;
    } else if (pass) {
      why = `The summary mentions the companies and the right financial terms, so a string-matcher <b>accepts it</b> — even when a required tool was never called.`;
    } else {
      why = `The final answer doesn't match the reference string.`;
    }
  }

  // contrast note — infer the case from the (effect, answer) disagreement.
  let note: string;
  if (effectPass !== answerPass) {
    if (answerPass && !effectPass) {
      note = `<b>The disagreement:</b> answer-matching would PASS this run on its confident summary, but a required effect never fired. Effect-scoring catches the missing work — incomplete aggregation, the dominant failure mode in the paper.`;
    } else {
      note = `<b>The disagreement:</b> this agent did everything right, but answer-matching fails it because the live data moved since the reference was recorded. Effect-scoring passes it — exactly why grading the answer is fragile on live data.`;
    }
  } else {
    note = effectPass
      ? `Both modes agree here. The interesting cases are the confident-but-incomplete agent (answer pass, effect fail) and the stale-but-correct agent (answer fail, effect pass).`
      : `Both modes fail this run.`;
  }

  if (MODE === "live") {
    note = `<b>LIVE mode:</b> scoring runs on deterministic replay (the graded path); live drives collect/explore/distill. ${note}`;
  }
  $("finalAnswer").innerHTML = `<span class="fa-lbl">candidate's final answer</span>${done.final_answer}`;
  $("vwMode").textContent = modeLabel;
  $("vwText").innerHTML = why;
  $("scoreNote").innerHTML = note;
  setVerdict(pass);
}

function setVerdict(pass: boolean | null): void {
  const bar = $("verdictBar");
  const chip = $("verdictChip");
  bar.classList.remove("pass", "fail");
  if (pass === null) {
    chip.textContent = "—";
    return;
  }
  bar.classList.add(pass ? "pass" : "fail");
  chip.textContent = pass ? "SOLVED" : "FAILED";
}

/* ---------------- leaderboard ---------------- */
let lbLoaded = false;
$("showLb").addEventListener("click", async () => {
  const panel = $("lbPanel");
  const open = panel.style.display !== "none";
  panel.style.display = open ? "none" : "block";
  $("showLb").textContent = open ? "See the leaderboard →" : "Hide leaderboard";
  if (!open && !lbLoaded) {
    lbLoaded = true;
    let lb: Leaderboard;
    try {
      lb = await getJSON<Leaderboard>(`/api/leaderboard?mode=${MODE}`);
    } catch {
      lbLoaded = false;
      showError("Couldn't load the leaderboard.");
      return;
    }
    const max = Math.max(...lb.rows.map((r) => r.pass3));
    $("lbTable").innerHTML =
      "<tr><th>Model</th><th>Group</th><th style='width:46%'>pass³</th><th>%</th></tr>" +
      lb.rows
        .map(
          (r) => `<tr>
        <td class="m">${r.model}</td>
        <td><span class="grp">${r.group}</span></td>
        <td><div class="bar" style="width:${((r.pass3 / max) * 100).toFixed(0)}%;background:${r.pass3 < 20 ? "var(--alert)" : "var(--signal)"}"></div></td>
        <td class="m">${r.pass3.toFixed(1)}</td></tr>`,
        )
        .join("");
    if (lb.placeholder) {
      $("lbNote").innerHTML =
        "<b>Placeholder numbers</b> — wired to a real export from the parent study before any public demo.";
    }
  }
});

/* ---------------- stage 0: design (Benchmark Advisor) ---------------- */
type DStatus = "approved" | "warning" | "refused" | "needs_clarification";
interface DWarning {
  severity: string;
  code: string;
  message: string;
  statistical_reason: string | null;
  repair_suggestion: string;
}
interface DRefusal {
  code: string;
  reason: string;
  statistical_reason: string;
  repair_options: string[];
}
interface DClar {
  missing_fields: string[];
  questions: string[];
  why_needed: string;
}
interface DEvidence {
  parameter: string;
  value: unknown;
  intent_evidence: string | null;
  statistical_rationale: string;
  guide_references: { rule_id: string }[];
  hover_text: string;
}
interface DResponse {
  status: DStatus;
  warnings: DWarning[];
  refusal: DRefusal | null;
  clarification: DClar | null;
  evidence_ledger: DEvidence[];
  export_config: unknown | null;
  design: unknown | null;
}

const dStage = document.getElementById("stage-design");
const dStepChip = document.getElementById("stepDesign");
let dMode = "pairwise";
let dReqId = 0;
let dDebounce: number | undefined;

const D_VERDICT: Record<DStatus, { chip: string; cls: string; mode: string }> = {
  approved: { chip: "APPROVED", cls: "dv-approved", mode: "design is statistically defensible" },
  warning: { chip: "WARNING", cls: "dv-warning", mode: "usable design, with caveats" },
  refused: { chip: "REFUSED", cls: "dv-refused", mode: "this design would fool you" },
  needs_clarification: { chip: "CLARIFY", cls: "dv-clarify", mode: "needs more to plan" },
};

function esc(s: unknown): string {
  return String(s).replace(
    /[&<>"]/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] as string,
  );
}

function dModels(): string[] {
  return ($("dModels") as HTMLInputElement).value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

function dBuildRequest(): Record<string, unknown> {
  const target = Number(($("dTarget") as HTMLInputElement).value);
  const req: Record<string, unknown> = {
    schema_version: "benchmark_advisor.v1",
    intent: ($("dIntent") as HTMLTextAreaElement).value.trim() || "Compare two agents.",
    mode: dMode,
    task_budget: Number(($("dBudget") as HTMLInputElement).value),
    attempts_per_task: Number(($("dAttempts") as HTMLInputElement).value),
    candidate_models: dModels(),
  };
  if (target > 0) req.target_detectable_effect_pp = target;
  return req;
}

function dCard(kind: string, head: string, body: string, stat: string | null, repairs: string[]): HTMLElement {
  const el = document.createElement("div");
  el.className = "d-card " + kind;
  const repair = repairs.length ? `<div class="d-repair">→ ${repairs.map(esc).join(" · ")}</div>` : "";
  const reason = stat ? `${esc(body)} <span style="color:var(--mute)">(${esc(stat)})</span>` : esc(body);
  el.innerHTML = `<div class="d-card-h">${esc(head)}</div>${reason}${repair}`;
  return el;
}

function dEvRow(e: DEvidence): HTMLElement {
  const el = document.createElement("div");
  el.className = "d-ev";
  const rules = e.guide_references.map((g) => `<span class="d-rule">${esc(g.rule_id)}</span>`).join("");
  const val = typeof e.value === "object" ? JSON.stringify(e.value) : String(e.value);
  el.innerHTML =
    `<div><div class="d-ev-param">${esc(e.parameter)}</div><div class="d-ev-rules">${rules}</div></div>` +
    `<div class="d-ev-val">${esc(val)}</div>` +
    `<div class="d-ev-hover">${esc(e.hover_text)}</div>`;
  return el;
}

function dRender(r: DResponse): void {
  const v = D_VERDICT[r.status];
  const bar = $("dVerdictBar");
  bar.classList.remove("dv-approved", "dv-warning", "dv-refused", "dv-clarify");
  bar.classList.add(v.cls);
  $("dVerdictChip").textContent = v.chip;
  $("dVerdictMode").textContent = v.mode;
  $("dStatusSub").textContent = r.status.replace("_", " ");
  $("dSummary").textContent = `${dMode} · ${dModels().length} model${dModels().length === 1 ? "" : "s"}`;

  let why: string;
  if (r.status === "refused" && r.refusal) why = `${r.refusal.reason} ${r.refusal.statistical_reason}`;
  else if (r.status === "needs_clarification" && r.clarification) why = r.clarification.why_needed;
  else if (r.status === "warning")
    why = `${r.warnings.length} warning${r.warnings.length === 1 ? "" : "s"} — usable, but the claim is bounded.`;
  else why = "The planned design supports the claim within its stated boundary; every parameter cites a guide rule.";
  $("dVerdictText").textContent = why;

  const cards = $("dCards");
  cards.innerHTML = "";
  if (r.refusal)
    cards.appendChild(
      dCard("refuse", "refused · " + r.refusal.code, r.refusal.reason, r.refusal.statistical_reason, r.refusal.repair_options),
    );
  if (r.clarification)
    cards.appendChild(dCard("clarify", "needs clarification", r.clarification.why_needed, null, r.clarification.questions));
  r.warnings.forEach((w) => cards.appendChild(dCard("warn", w.code, w.message, w.statistical_reason, [w.repair_suggestion])));

  const led = $("dLedger");
  led.innerHTML = "";
  if (r.evidence_ledger.length === 0)
    led.innerHTML = '<div class="empty">Rationale appears once a design is proposed.</div>';
  r.evidence_ledger.forEach((e) => led.appendChild(dEvRow(e)));

  $("dExport").textContent = r.export_config
    ? JSON.stringify(r.export_config, null, 2)
    : "— no export (design refused or needs clarification)";
  $("dExportSub").textContent = r.export_config ? "dry-run only · no run launched" : "unavailable";

  ($("dProceed") as HTMLButtonElement).disabled = !(r.status === "approved" || r.status === "warning");
}

async function dRun(): Promise<void> {
  const myId = ++dReqId;
  let resp: DResponse;
  try {
    resp = await postJSON<DResponse>("/api/advisor/design", dBuildRequest());
  } catch {
    $("dVerdictMode").textContent = "advisor unavailable";
    return;
  }
  if (myId !== dReqId) return; // a newer keystroke/drag superseded this request
  dRender(resp);
}

function dScheduleRun(): void {
  window.clearTimeout(dDebounce);
  dDebounce = window.setTimeout(() => void dRun(), 180);
}

function showDesign(): void {
  stages.forEach((s) => s.classList.remove("active"));
  steps.forEach((s) => s.classList.remove("active"));
  dStage?.classList.add("active");
  dStepChip?.classList.add("active");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

dStepChip?.addEventListener("click", showDesign);
$("dMode").addEventListener("click", (e) => {
  const b = (e.target as HTMLElement).closest<HTMLButtonElement>("button");
  if (!b) return;
  dMode = b.dataset.m as string;
  $("dMode")
    .querySelectorAll<HTMLElement>("button")
    .forEach((x) => x.classList.toggle("on", x === b));
  dScheduleRun();
});
($("dIntent") as HTMLTextAreaElement).addEventListener("input", dScheduleRun);
($("dModels") as HTMLInputElement).addEventListener("input", dScheduleRun);
const dBudgetEl = $("dBudget") as HTMLInputElement;
dBudgetEl.addEventListener("input", () => {
  $("dBudgetVal").textContent = dBudgetEl.value;
  dScheduleRun();
});
const dAttemptsEl = $("dAttempts") as HTMLInputElement;
dAttemptsEl.addEventListener("input", () => {
  $("dAttemptsVal").textContent = dAttemptsEl.value;
  dScheduleRun();
});
const dTargetEl = $("dTarget") as HTMLInputElement;
dTargetEl.addEventListener("input", () => {
  const t = Number(dTargetEl.value);
  $("dTargetVal").textContent = t > 0 ? `${t} pp` : "not set";
  dScheduleRun();
});
$("dProceed").addEventListener("click", () => {
  gotoStep(0);
  void loadServers();
});

/* ---------------- init ---------------- */
void dRun(); // populate Stage 0 — Design (active on boot)
void loadServers();
