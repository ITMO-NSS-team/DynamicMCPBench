/* ============================================================
   DMCP Studio — frontend wired to the REPLAY backend.
   Stages call fetch()/EventSource against /api/*; verdicts come
   from the server (effect = real evaluate(); answer = demo foil).
   ============================================================ */

const MODE = "replay";           // LIVE toggle lands in A3
const DELAY = 0.4;               // SSE pacing hint (server-side sleep, seconds)
const $ = (id) => document.getElementById(id);

const state = {
  step: 0,
  servers: new Set(),
  explored: false,
  distilled: false,
  refCalls: [],                  // streamed reference-trace calls (for the mirror)
  spec: null,
  equivSets: {},                 // checkpoint_id -> [tool names]
  equivOn: {},                   // tool name -> bool (editable equivalence members)
  candidate: null,
  mode: "effect",                // effect | answer (display toggle)
  ran: false,
  lastDone: null,                // last /api/score `done` payload
  es: null,                      // active EventSource
};

/* ---------------- nav ---------------- */
const stages = [...document.querySelectorAll(".stage")];
const steps = [...document.querySelectorAll(".step")];
function gotoStep(i) {
  state.step = i;
  stages.forEach((s, k) => s.classList.toggle("active", k === i));
  steps.forEach((s, k) => {
    s.classList.toggle("active", k === i);
    s.classList.toggle("done", k < i || (k === 1 && state.explored) || (k === 2 && state.distilled));
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}
$("stepper").addEventListener("click", (e) => {
  const s = e.target.closest(".step");
  if (!s) return;
  const i = +s.dataset.step;
  if (i === 1 && state.servers.size === 0) return;
  if (i === 2 && !state.explored) return;
  if (i === 3 && !state.distilled) return;
  if (i === 1) ensureGoal();
  gotoStep(i);
});
document.querySelectorAll("[data-goto]").forEach((b) =>
  b.addEventListener("click", () => gotoStep(+b.dataset.goto)),
);

/* ---------------- stage 1: servers ---------------- */
async function loadServers() {
  const grid = $("serverGrid");
  const servers = await (await fetch(`/api/servers?mode=${MODE}`)).json();
  grid.innerHTML = "";
  servers.forEach((s, idx) => {
    const isWrite = s.dynamism === "stateful_write";
    const sel = idx === 0;                       // pre-select the first (yfinance)
    if (sel) state.servers.add(s.server_id);
    const el = document.createElement("div");
    el.className = "server-card" + (sel ? " sel" : "");
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
      $("toExplore").disabled = state.servers.size === 0;
    });
    grid.appendChild(el);
  });
  $("toExplore").disabled = state.servers.size === 0;
}
$("toExplore").addEventListener("click", () => {
  ensureGoal();
  gotoStep(1);
});

/* ---------------- stage 2: goal + explore ---------------- */
let goalLoaded = false;
async function ensureGoal() {
  if (goalLoaded) return;
  goalLoaded = true;
  const body = { server_ids: [...state.servers] };
  const g = await (
    await fetch(`/api/goal?mode=${MODE}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  ).json();
  $("goalText").textContent = g.goal;
  if (g.persona) $("goalPersona").textContent = g.persona;
}

function traceLine(idx, tool, args, status) {
  const row = document.createElement("div");
  row.className = "trace-line";
  row.innerHTML = `<span class="trace-idx">${idx}</span>
    <span class="trace-call"><span class="tool">${tool}</span>(<span class="args">${fmtArgs(args)}</span>)</span>
    <span class="trace-status ${status.cls}">${status.txt}</span>`;
  return row;
}
function fmtArgs(args) {
  return Object.entries(args || {})
    .map(([k, v]) => `${k}=${Array.isArray(v) ? "[" + v.join(",") + "]" : v}`)
    .join(", ");
}

$("runExplore").addEventListener("click", () => {
  const btn = $("runExplore");
  btn.disabled = true;
  const stream = $("traceStream");
  stream.innerHTML = "";
  state.refCalls = [];
  const dot = $("exploreDot");
  dot.style.background = "var(--signal)";
  dot.style.boxShadow = "0 0 8px var(--signal-glow)";
  dot.classList.add("pulsing");

  const es = new EventSource(`/api/explore?mode=${MODE}&delay=${DELAY}`);
  state.es = es;
  es.addEventListener("call", (e) => {
    const c = JSON.parse(e.data);
    state.refCalls.push(c);
    stream.appendChild(traceLine(c.idx, c.tool_name, c.arguments, { cls: "ok", txt: "200 ok" }));
    $("exploreCount").textContent = `${c.idx} calls`;
  });
  es.addEventListener("done", (e) => {
    const d = JSON.parse(e.data);
    es.close();
    dot.classList.remove("pulsing");
    $("exploreCount").textContent = `${d.n_calls} calls · ${d.success ? "success" : "incomplete"}`;
    state.explored = true;
    $("toDistill").disabled = false;
    steps[1].classList.add("done");
    btn.disabled = false;
  });
  es.onerror = () => {
    es.close();
    dot.classList.remove("pulsing");
    btn.disabled = false;
  };
});
$("toDistill").addEventListener("click", () => {
  gotoStep(2);
  runDistill();
});

/* ---------------- stage 3: distill ---------------- */
function renderTraceMirror() {
  const m = $("traceMirror");
  m.innerHTML = "";
  state.refCalls.forEach((c, i) => {
    const row = traceLine(c.idx, c.tool_name, c.arguments, { cls: "ok", txt: "ok" });
    row.style.animationDelay = i * 0.04 + "s";
    m.appendChild(row);
  });
  $("traceMirrorCount").textContent = `${state.refCalls.length} calls`;
}

function ckptKindLabel(kind) {
  return kind === "value_produced" ? "value produced" : "tool effect";
}
function ckptInner(cp, n) {
  const eq = state.equivSets[cp.checkpoint_id];
  let body = `<span class="t">${cp.checkpoint_id}</span> — ${cp.description}`;
  if (eq && eq.length > 1) {
    const tools = eq
      .map(
        (t) =>
          `<span class="equiv-tool ${state.equivOn[t] ? "" : "off"}" data-tool="${t}">${t}</span>`,
      )
      .join('<span class="equiv-or">or</span>');
    body += `<div class="equiv">${tools}</div>
      <div class="equiv-hint">↑ equivalence set — any enabled tool satisfies this effect. Click to toggle and re-score.</div>`;
  }
  const isValue = cp.kind === "value_produced";
  return `<div class="ckpt-top">
      <span class="ckpt-num">${n}</span>
      <span class="ckpt-kind ${isValue ? "value" : ""}">${ckptKindLabel(cp.kind)}</span>
      ${eq && eq.length > 1 ? '<span class="ckpt-kind" style="color:var(--amber);border-color:var(--amber-dim)">path-agnostic</span>' : ""}
    </div>
    <div class="ckpt-body">${body}</div>`;
}

async function runDistill() {
  renderTraceMirror();
  const list = $("ckptList");
  list.innerHTML = "";
  $("ckptCount").textContent = "compiling…";
  const res = await (
    await fetch(`/api/distill?mode=${MODE}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ trace_id: null }),
    })
  ).json();
  state.spec = res.task_spec;
  state.equivSets = res.equivalence_sets || {};
  state.equivOn = {};
  Object.values(state.equivSets).forEach((tools) => tools.forEach((t) => (state.equivOn[t] = true)));

  const cps = state.spec.checkpoints;
  cps.forEach((cp, i) => {
    const el = document.createElement("div");
    el.className = "ckpt";
    el.dataset.id = cp.checkpoint_id;
    el.style.opacity = 0;
    el.innerHTML = ckptInner(cp, i + 1);
    list.appendChild(el);
    requestAnimationFrame(() => {
      el.style.transition = "opacity .3s";
      el.style.opacity = 1;
    });
  });
  $("ckptCount").textContent = `${cps.length} checkpoints`;
  $("mfCount").textContent = (state.spec.minefields || []).length || "none";
  $("specMeta").style.display = "flex";
  state.distilled = true;
  $("toScore").disabled = false;
  steps[2].classList.add("done");
  bindEquiv();
}

function bindEquiv() {
  document.querySelectorAll(".equiv-tool").forEach((t) => {
    t.onclick = () => {
      const tool = t.dataset.tool;
      const peers = Object.entries(state.equivSets).find(([, ts]) => ts.includes(tool))[1];
      const others = peers.filter((p) => p !== tool);
      // keep at least one member enabled
      if (state.equivOn[tool] && !others.some((p) => state.equivOn[p])) return;
      state.equivOn[tool] = !state.equivOn[tool];
      document.querySelectorAll(`.equiv-tool[data-tool="${tool}"]`).forEach((n) => n.classList.toggle("off"));
      if (state.ran) runCandidate(); // live re-score
    };
  });
}
$("toScore").addEventListener("click", () => {
  gotoStep(3);
  loadCandidates();
});

/* ---------------- stage 4: score ---------------- */
let candidatesLoaded = false;
async function loadCandidates() {
  if (candidatesLoaded) return;
  candidatesLoaded = true;
  const pick = $("candPick");
  const cands = await (await fetch(`/api/candidates?mode=${MODE}`)).json();
  pick.innerHTML = "";
  cands.forEach((c, idx) => {
    const el = document.createElement("div");
    el.className = "cand" + (idx === 0 ? " sel" : "");
    el.innerHTML = `<span class="cand-name">${c.name}</span><span class="cand-note">${c.note}</span>`;
    el.addEventListener("click", () => {
      document.querySelectorAll(".cand").forEach((x) => x.classList.remove("sel"));
      el.classList.add("sel");
      state.candidate = c.name;
      resetRun();
    });
    pick.appendChild(el);
    if (idx === 0) state.candidate = c.name;
  });
}

$("modeSeg").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  state.mode = b.dataset.mode;
  $("modeSeg")
    .querySelectorAll("button")
    .forEach((x) => x.classList.toggle("on", x === b));
  if (state.ran && state.lastDone) renderScore(state.lastDone); // pure re-render, no refetch
});

function resetRun() {
  if (state.es) state.es.close();
  state.ran = false;
  state.lastDone = null;
  $("candStream").innerHTML =
    '<div class="empty">Run the candidate to replay its calls against the recorded world.</div>';
  $("candCount").textContent = "0 calls";
  $("faWrap").hidden = true;
  $("ledger").innerHTML = "";
  $("ledgerScore").textContent = "—";
  setVerdict(null);
  $("passk").textContent = "";
  $("scoreNote").innerHTML = "";
}

$("runCand").addEventListener("click", runCandidate);

function equivOverridesParam() {
  const enabled = Object.entries(state.equivOn)
    .filter(([, on]) => on)
    .map(([t]) => t);
  // only send when something is disabled (a strict subset of the sets)
  const all = Object.values(state.equivSets).flat();
  return enabled.length && enabled.length < all.length ? enabled.join(",") : "";
}

function runCandidate() {
  if (!state.candidate) return;
  if (state.es) state.es.close();
  const btn = $("runCand");
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
    const c = JSON.parse(e.data);
    nCalls = c.idx;
    stream.appendChild(traceLine(c.idx, c.tool_name, c.arguments, { cls: "ok", txt: "ok" }));
    $("candCount").textContent = `${c.idx} calls`;
  });
  es.addEventListener("done", (e) => {
    es.close();
    dot.classList.remove("pulsing");
    if (nCalls) $("candCount").textContent = `${nCalls} calls`;
    state.lastDone = JSON.parse(e.data);
    state.ran = true;
    $("faWrap").hidden = false;
    renderScore(state.lastDone);
    btn.disabled = false;
  });
  es.onerror = () => {
    es.close();
    dot.classList.remove("pulsing");
    btn.disabled = false;
  };
}

function renderLedger(done) {
  const ledger = $("ledger");
  ledger.innerHTML = "";
  done.checkpoints.forEach((v) => {
    const cp = state.spec.checkpoints[v.n - 1];
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

function renderScore(done) {
  renderLedger(done);
  $("ledgerScore").textContent = `${done.met_count}/${done.required} effects`;
  $("passk").textContent = "pass³ · attempt 1 of 3 shown";

  const effectPass = done.effect_pass;
  const answerPass = done.answer_pass;
  let pass, modeLabel, why;
  if (state.mode === "effect") {
    pass = effectPass;
    modeLabel = "Effect scoring · grades the trajectory";
    $("finalAnswer").className = "final-answer muted-by-effect";
    if (pass) {
      why = `All <b>${done.required} effects</b> reproduced under deterministic replay — including any equivalence-set tool. The final answer is never read.`;
    } else {
      const missing = done.checkpoints.filter((c) => !c.met).map((c) => "#" + c.n).join(", ");
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
  let note;
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

  $("finalAnswer").innerHTML = `<span class="fa-lbl">candidate's final answer</span>${done.final_answer}`;
  $("vwMode").textContent = modeLabel;
  $("vwText").innerHTML = why;
  $("scoreNote").innerHTML = note;
  setVerdict(pass);
}

function setVerdict(pass) {
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
const showLb = $("showLb");
let lbLoaded = false;
showLb.addEventListener("click", async () => {
  const panel = $("lbPanel");
  const open = panel.style.display !== "none";
  panel.style.display = open ? "none" : "block";
  showLb.textContent = open ? "See the leaderboard →" : "Hide leaderboard";
  if (!open && !lbLoaded) {
    lbLoaded = true;
    const lb = await (await fetch(`/api/leaderboard?mode=${MODE}`)).json();
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

/* ---------------- init ---------------- */
loadServers();
