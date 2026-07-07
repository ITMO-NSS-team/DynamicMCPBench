import { useEffect, useState } from "react";
import { Button } from "../ui";
import { api } from "../api/client";
import { useStudio } from "../store/context";
import type { DStatus, LaunchJob, ReplayDemoReport, ServerCard } from "../types";

function isLaunchStatus(status: DStatus): status is "approved" | "warning" {
  return status === "approved" || status === "warning";
}

function serverTag(srv: ServerCard): string {
  if (srv.dynamism === "stateful_write")
    return srv.sandbox ? "stateful · sandboxed" : "stateful · unsandboxed";
  return srv.dynamism === "static" ? "static" : "live-read";
}

function replayOnlyLaunchJob(): LaunchJob {
  return {
    schema_version: "benchmark_advisor.launch_job.v2",
    job_id: "replay-demo-report-local",
    status: "succeeded",
    command_preview: [
      "replay-only",
      "no-corpus-handoff",
      "load",
      "/api/advisor/v2/replay-demo-report",
    ],
    logs: [
      "replay mode: no real corpus handoff was launched",
      "replay mode: loading frozen Benchmark Advisor post-run report fixture",
      "source: /api/advisor/v2/replay-demo-report",
    ],
    artifacts: {
      goals: null,
      specs: null,
      traces: null,
      coverage: null,
    },
  };
}

export function Collect() {
  const s = useStudio();
  const carried = s.advisorCarry;
  const replayMode = s.mode === "replay";
  const [launchConfirmed, setLaunchConfirmed] = useState(false);
  const [sandboxConfirmed, setSandboxConfirmed] = useState(false);
  const [launchJob, setLaunchJob] = useState<LaunchJob | null>(null);
  const [launchBusy, setLaunchBusy] = useState(false);
  const [launchError, setLaunchError] = useState<string | null>(null);
  const [demoReport, setDemoReport] = useState<ReplayDemoReport | null>(null);
  const [demoReportBusy, setDemoReportBusy] = useState(false);
  const [demoReportError, setDemoReportError] = useState<string | null>(null);

  useEffect(() => {
    if (!launchJob || !["queued", "running"].includes(launchJob.status)) return;
    const handle = window.setInterval(() => {
      void api
        .advisorV2LaunchJob(launchJob.job_id)
        .then((job) => setLaunchJob(job))
        .catch(() => setLaunchError("Could not refresh the launch job status."));
    }, 1200);
    return () => window.clearInterval(handle);
  }, [launchJob]);

  useEffect(() => {
    if (s.mode !== "replay" || launchJob?.status !== "succeeded") {
      setDemoReport(null);
      setDemoReportError(null);
      setDemoReportBusy(false);
      return;
    }
    let cancelled = false;
    setDemoReportBusy(true);
    setDemoReportError(null);
    void api
      .health()
      .then((health) => {
        if (health.capabilities?.advisor_v2_replay_demo_report !== true) {
          throw new Error(
            "Studio backend is stale. Restart Studio so the replay demo report route is loaded.",
          );
        }
        return api.advisorV2ReplayDemoReport();
      })
      .then((report) => {
        if (!cancelled) setDemoReport(report);
      })
      .catch((err) => {
        if (!cancelled) {
          const detail = err instanceof Error ? err.message : "";
          setDemoReportError(
            detail
              ? `Could not load the replay demo statistical report: ${detail}`
              : "Could not load the replay demo statistical report.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setDemoReportBusy(false);
      });
    return () => {
      cancelled = true;
    };
  }, [launchJob?.status, s.mode]);

  const startLaunch = async () => {
    if (!carried || !launchConfirmed) return;
    if (!carried.launchable || !isLaunchStatus(carried.responseStatus)) {
      setLaunchError(
        "This advisor handoff is not launchable. Return to Stage 0 and repair the design.",
      );
      return;
    }
    setLaunchBusy(true);
    setLaunchError(null);
    if (replayMode) {
      setLaunchJob(replayOnlyLaunchJob());
      setLaunchBusy(false);
      return;
    }
    try {
      setLaunchJob(
        await api.advisorV2Launch({
          schema_version: "benchmark_advisor.launch.v2",
          export_config: carried.exportConfig,
          advisor_status: carried.responseStatus,
          confirmation: true,
          sandbox_confirmed: sandboxConfirmed,
          dry_run: false,
          requested_by_ui: true,
        }),
      );
    } catch (err) {
      const detail = err instanceof Error ? err.message : "";
      setLaunchError(
        detail
          ? `The guarded corpus launch was refused by the backend: ${detail}`
          : "The guarded corpus launch was refused by the backend.",
      );
    } finally {
      setLaunchBusy(false);
    }
  };

  const launchDisabled =
    !carried ||
    !launchConfirmed ||
    launchBusy ||
    !carried.launchable ||
    !isLaunchStatus(carried.responseStatus) ||
    (!replayMode && carried.sandboxRequired && !sandboxConfirmed) ||
    ["queued", "running"].includes(launchJob?.status ?? "");

  return (
    <section className="stage">
      <div className="eyebrow">Stage 1 — substrate</div>
      <h1>Pick the live MCP servers</h1>
      <p className="lede">
        These tools are live, not a fixed dataset. The pipeline reads each server's tool surface and
        tags it by dynamism.
      </p>

      {carried && (
        <div className="panel" style={{ marginTop: 24 }}>
          <div className="panel-head">
            <span className="panel-title">Advisor handoff</span>
            <span className="panel-sub">{carried.responseStatus}</span>
          </div>
          <div className="panel-body stack-gap">
            <div className="metric-strip">
              <div className="metric">
                <span>tasks</span>
                <b>{carried.exportConfig.tasks}</b>
              </div>
              <div className="metric">
                <span>attempts</span>
                <b>{carried.exportConfig.attempts_per_task}</b>
              </div>
              <div className="metric">
                <span>strategy</span>
                <b>{carried.exportConfig.generation_knobs.goal_strategy}</b>
              </div>
              <div className="metric">
                <span>sandbox</span>
                <b>{carried.sandboxRequired ? "required" : "not required"}</b>
              </div>
            </div>
            <div className="info-row">
              <span>server scope</span>
              <b>{carried.serverScope.length ? carried.serverScope.join(", ") : "not set"}</b>
            </div>
            <div className="info-row">
              <span>validation</span>
              <b>
                {carried.launchable
                  ? replayMode
                    ? "replay report available after confirmation"
                    : "launchable after guarded confirmation"
                  : "not launchable"}
              </b>
            </div>
            <div className="note-row">
              {carried.statisticalPlan.assumption_ledger.independence_assumption}
            </div>
            <div className="note-row">
              {carried.statisticalPlan.assumption_ledger.repeated_attempts_policy}
            </div>
            <label className="check-row">
              <input
                type="checkbox"
                checked={launchConfirmed}
                onChange={(event) => setLaunchConfirmed(event.target.checked)}
              />
              <span>
                {replayMode
                  ? "Confirm replay demo report load"
                  : "Confirm guarded corpus/specs/traces launch"}
              </span>
            </label>
            {!replayMode && carried.sandboxRequired && (
              <label className="check-row">
                <input
                  type="checkbox"
                  checked={sandboxConfirmed}
                  onChange={(event) => setSandboxConfirmed(event.target.checked)}
                />
                <span>Sandbox requirements are satisfied</span>
              </label>
            )}
            {launchError && (
              <div className="error-banner" role="alert">
                <b>{launchError}</b>
                <button
                  type="button"
                  className="error-dismiss"
                  onClick={() => setLaunchError(null)}
                >
                  x
                </button>
              </div>
            )}
            <div className="footer-nav" style={{ padding: 0 }}>
              <span className="panel-sub">
                {launchJob
                  ? `job ${launchJob.status}`
                  : replayMode
                    ? "replay mode: no corpus launch"
                    : "no launch job yet"}
              </span>
              <Button type="secondary" scale={0.85} disabled={launchDisabled} onClick={startLaunch}>
                {replayMode ? "Start replay demo" : "Start corpus handoff"}
              </Button>
            </div>
            {launchJob && <LaunchJobPanel job={launchJob} />}
            {s.mode === "replay" && launchJob?.status === "succeeded" && (
              <ReplayDemoReportPanel
                report={demoReport}
                busy={demoReportBusy}
                error={demoReportError}
              />
            )}
          </div>
        </div>
      )}

      <div className="grid servers" style={{ marginTop: 28 }}>
        {s.servers.length === 0 && <div className="empty">Loading servers…</div>}
        {s.servers.map((srv) => {
          const sel = s.selected.includes(srv.server_id);
          return (
            <button
              key={srv.server_id}
              type="button"
              className="pick"
              data-sel={sel}
              aria-pressed={sel}
              onClick={() => s.toggleServer(srv.server_id)}
            >
              <div className="row-between">
                <span className="pick-name">{srv.server_id}</span>
                <span className="tag">{serverTag(srv)}</span>
              </div>
              <div className="pick-note">{srv.description}</div>
              <div
                className="mono faint"
                style={{ fontSize: 11.5, marginTop: 10, lineHeight: 1.6 }}
              >
                {(srv.tools || []).join(" · ")}
              </div>
            </button>
          );
        })}
      </div>

      <div className="footer-nav">
        <span />
        <Button
          type="secondary"
          scale={0.85}
          disabled={s.selected.length === 0}
          onClick={() => s.go("explore")}
        >
          Generate a goal and explore →
        </Button>
      </div>
    </section>
  );
}

function ReplayDemoReportPanel({
  report,
  busy,
  error,
}: {
  report: ReplayDemoReport | null;
  busy: boolean;
  error: string | null;
}) {
  const firstModel = report?.leaderboard[0]?.model ?? "model A";
  const secondModel = report?.leaderboard[1]?.model ?? "model B";
  const pairedEffect = report?.report.effect_sizes.find(
    (effect) => effect.method === "paired_bootstrap_tasks",
  );
  const pairedCi = report?.report.confidence_intervals.find(
    (ci) => ci.method === "paired_bootstrap_tasks",
  );
  const plannedMde = report?.report.effect_sizes.find(
    (effect) => effect.method === "planning_heuristic_mde",
  );

  return (
    <div className="panel replay-report" style={{ marginTop: 8 }}>
      <div className="panel-head">
        <span className="panel-title">Replay statistical report</span>
        <span className="panel-sub">
          {busy ? "loading..." : report ? report.experiment_id : "not loaded"}
        </span>
      </div>
      <div className="panel-body stack-gap">
        {error ? (
          <div className="error-banner" role="alert">
            <b>{error}</b>
          </div>
        ) : !report ? (
          <div className="empty">Loading replay demonstration report...</div>
        ) : (
          <>
            <p className="compact-copy">{report.headline}</p>
            <div className="metric-strip">
              <div className="metric">
                <span>tasks</span>
                <b>{report.sample_size}</b>
              </div>
              <div className="metric">
                <span>models</span>
                <b>{report.model_count}</b>
              </div>
              <div className="metric">
                <span>metric</span>
                <b>{report.metric}</b>
              </div>
              <div className="metric">
                <span>missing</span>
                <b>{report.report.missingness.missing_count}</b>
              </div>
              <div className="metric">
                <span>status</span>
                <b>{report.report.status}</b>
              </div>
              {plannedMde && (
                <div className="metric">
                  <span>MDE</span>
                  <b>{plannedMde.estimate_pp.toFixed(1)} pp</b>
                </div>
              )}
            </div>
            <div className="note-row">
              This card uses completed replay evidence from {report.experiment_id}
              {report.provenance.generated_by_current_handoff
                ? " generated from the current Advisor handoff."
                : "; it is not an eval result produced by the current corpus handoff."}
            </div>
            <div className="section-label">Pairwise workflow-stress result</div>
            <div className="replay-table" role="table" aria-label="Pairwise workflow-stress result">
              <div className="replay-table-row replay-table-head" role="row">
                <span>rank</span>
                <span>model</span>
                <span>pass^3</span>
                <span>95% CI</span>
                <span>delta</span>
              </div>
              {report.leaderboard.map((row) => (
                <div key={row.model} className="replay-table-row" role="row">
                  <span className="mono">#{row.rank}</span>
                  <b>{row.model}</b>
                  <span className="mono">
                    {(row.acc * 100).toFixed(1)}% ({row.passed}/{row.n})
                  </span>
                  <span className="mono">
                    {(row.lo * 100).toFixed(1)}-{(row.hi * 100).toFixed(1)}%
                  </span>
                  <span className="mono">
                    {row.delta >= 0 ? "+" : ""}
                    {row.delta.toFixed(1)} pp
                  </span>
                </div>
              ))}
            </div>
            {pairedEffect && pairedCi && (
              <div className="info-row">
                <span>paired delta</span>
                <b>
                  {pairedEffect.estimate_pp >= 0 ? "+" : ""}
                  {pairedEffect.estimate_pp.toFixed(1)} pp, 95% CI{" "}
                  {pairedCi.low_pp.toFixed(1)} to {pairedCi.high_pp.toFixed(1)} pp
                </b>
              </div>
            )}
            {report.focus_slices && report.focus_slices.length > 0 && (
              <>
                <div className="section-label">Generated corpus slices</div>
                <div
                  className="replay-table replay-slice-table"
                  role="table"
                  aria-label="Generated corpus slices"
                >
                  <div className="replay-table-row replay-table-head" role="row">
                    <span>slice</span>
                    <span>{firstModel}</span>
                    <span>{secondModel}</span>
                    <span>delta</span>
                  </div>
                  {report.focus_slices.map((slice) => (
                    <div key={slice.slice_id} className="replay-table-row" role="row">
                      <b>{slice.label}</b>
                      <span className="mono">
                        {slice.model_a_passed ?? slice.qwen_passed ?? 0}/{slice.n}
                      </span>
                      <span className="mono">
                        {slice.model_b_passed ?? slice.glm_passed ?? 0}/{slice.n}
                      </span>
                      <span className="mono">
                        {slice.delta_pp >= 0 ? "+" : ""}
                        {slice.delta_pp.toFixed(1)} pp
                      </span>
                    </div>
                  ))}
                </div>
              </>
            )}
            {report.report.rank_stability && (
              <div className="info-row">
                <span>rank stability</span>
                <b>{report.report.rank_stability.summary}</b>
              </div>
            )}
            <div className="replay-figures">
              {report.figures.map((figure) => (
                <figure key={figure.figure_id}>
                  <img src={figure.url} alt={figure.alt} />
                  <figcaption>{figure.title}</figcaption>
                </figure>
              ))}
            </div>
            <ClaimList title="Supported report claims" items={report.report.allowed_claims} />
            <ClaimList title="Report boundaries" items={report.report.not_allowed_claims} />
            <div className="section-label">Data quality</div>
            {report.data_quality.map((note) => (
              <div key={note} className="record-row">
                {note}
              </div>
            ))}
            <div className="info-row">
              <span>condition</span>
              <b>{report.condition}</b>
            </div>
            <div className="info-row">
              <span>provenance</span>
              <b className="provenance-list">
                {report.provenance.source_docs.map((source) => (
                  <span key={source} className="provenance-path">
                    {source}
                  </span>
                ))}
              </b>
            </div>
            {report.provenance.server_filter_note && (
              <div className="info-row">
                <span>server filter</span>
                <b>{report.provenance.server_filter_note}</b>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function ClaimList({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <div className="section-label">{title}</div>
      <ul className="claim-list">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function LaunchJobPanel({ job }: { job: LaunchJob }) {
  return (
    <div className="panel" style={{ marginTop: 8 }}>
      <div className="panel-head">
        <span className="panel-title">Launch job</span>
        <span className="panel-sub">{job.status}</span>
      </div>
      <div className="panel-body stack-gap">
        <div className="section-label">command preview</div>
        <pre className="export">{job.command_preview.join(" ")}</pre>
        <div className="section-label">artifacts</div>
        <div className="record-row">goals: {job.artifacts.goals ?? "-"}</div>
        <div className="record-row">specs: {job.artifacts.specs ?? "-"}</div>
        <div className="record-row">traces: {job.artifacts.traces ?? "-"}</div>
        <div className="record-row">coverage: {job.artifacts.coverage ?? "-"}</div>
        <div className="section-label">logs</div>
        {job.logs.length ? (
          <pre className="export">{job.logs.join("\n")}</pre>
        ) : (
          <div className="empty">No logs yet.</div>
        )}
      </div>
    </div>
  );
}
