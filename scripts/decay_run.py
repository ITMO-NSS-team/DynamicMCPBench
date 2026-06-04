#!/usr/bin/env python3
"""E8.4 / B4: multi-window decay runner — wraps `dmcp refresh` over N windows.

Each window re-executes every spec's reference trace against the live manifest
(via `dmcp refresh`); the resulting `RefreshReport` JSONL is written to
`<snapshots>/window_<i>.jsonl`. The aggregator then reads all windows in
order and produces:

  - a markdown table: per-window identical / drift / broken rates
  - a per-server breakdown over time (shape of `fig:decay_curve`)
  - a numbers JSON suitable for `docs/experiments/e1.5_numbers.json`

The dispatch to `dmcp refresh` hits live MCP servers and (per CLAUDE.md hard
invariant 4) MUST skip `stateful_write` unless the human explicitly passes
`--refresh-stateful` — we forward that flag and default to OFF. The aggregator
is pure Python so the smoke test runs offline via `--skip-refresh` over a
fixture, no LLM/network calls.

Living-bench loop: the wait between windows is configurable in seconds for
ergonomics here; the headline figure in the paper uses real-world windows
(hours/days), which are realized by re-invoking this script later, not by
sleeping inside it.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DMCP = str(ROOT / ".venv" / "bin" / "dmcp")
if not Path(DMCP).exists():
    DMCP = "dmcp"


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _ratio(num: int, denom: int) -> float | None:
    return (num / denom) if denom else None


def _live_count(counts: dict[str, int]) -> int:
    """Excludes skipped — `live = identical + drifted + broken` (refresh.py docstring)."""
    return int(counts.get("identical", 0)) + int(counts.get("drifted", 0)) + int(counts.get("broken", 0))


def _window_metrics(reports: list[dict]) -> dict[str, Any]:
    """Roll up all RefreshReports for one window into per-window outcome rates."""
    identical = drifted = broken = skipped = stale = 0
    for r in reports:
        c = r.get("counts") or {}
        identical += int(c.get("identical", 0))
        drifted += int(c.get("drifted", 0))
        broken += int(c.get("broken", 0))
        skipped += int(c.get("skipped", 0))
        if r.get("spec_likely_stale"):
            stale += 1
    live = identical + drifted + broken
    return {
        "n_specs": len(reports),
        "n_specs_stale": stale,
        "total_calls": identical + drifted + broken + skipped,
        "live_calls": live,
        "identical": identical,
        "drifted": drifted,
        "broken": broken,
        "skipped": skipped,
        "identical_rate": _ratio(identical, live),
        "drift_rate": _ratio(drifted, live),
        "broken_rate": _ratio(broken, live),
        "stale_rate": _ratio(stale, len(reports)),
    }


def _per_server_window(reports: list[dict]) -> dict[str, dict[str, Any]]:
    """Per-server outcome counts within one window."""
    by_server: dict[str, dict[str, Any]] = {}
    for r in reports:
        seen: set[str] = set()
        for o in r.get("call_outcomes", []) or []:
            sid = o.get("server_id")
            cls = o.get("classification")
            if not sid or not cls:
                continue
            bucket = by_server.setdefault(
                sid,
                {"refreshes": 0, "identical": 0, "drifted": 0, "broken": 0, "skipped": 0},
            )
            if sid not in seen:
                bucket["refreshes"] += 1
                seen.add(sid)
            if cls in bucket:
                bucket[cls] += 1
    for b in by_server.values():
        live = b["identical"] + b["drifted"] + b["broken"]
        b["live_calls"] = live
        b["identical_rate"] = _ratio(b["identical"], live)
        b["drift_rate"] = _ratio(b["drifted"], live)
        b["broken_rate"] = _ratio(b["broken"], live)
    return by_server


def aggregate_windows(window_paths: list[Path]) -> dict[str, Any]:
    """Compose per-window + per-server-over-time metrics from N RefreshReport JSONLs.

    `window_paths` is the ordered list (window 0 first). Output shape matches
    `fig:decay_curve` expectations: a `windows` series + a `per_server` map
    holding one row per server per window, ordered by window index.
    """
    windows: list[dict[str, Any]] = []
    per_server: dict[str, list[dict[str, Any]]] = {}
    for i, path in enumerate(window_paths):
        reports = _read_jsonl(path)
        wmetrics = _window_metrics(reports)
        wmetrics["window"] = i
        wmetrics["source"] = path.name
        windows.append(wmetrics)
        for sid, b in _per_server_window(reports).items():
            entry = dict(b)
            entry["window"] = i
            per_server.setdefault(sid, []).append(entry)
    return {"n_windows": len(windows), "windows": windows, "per_server": per_server}


def _fmt_rate(r: float | None) -> str:
    return "-" if r is None else f"{r * 100:.1f}%"


def render_markdown(agg: dict[str, Any]) -> str:
    windows = agg["windows"]
    if not windows:
        return "# Decay curve (E8.4)\n\n_No RefreshReport rows found._\n"
    lines = [
        "# Decay curve (E8.4)",
        "",
        f"n_windows = {agg['n_windows']}",
        "",
        "## Per-window outcome rates (live calls)",
        "",
        "| window | specs | live calls | identical | drift | broken | stale specs |",
        "|---|---|---|---|---|---|---|",
    ]
    for w in windows:
        lines.append(
            f"| {w['window']} | {w['n_specs']} | {w['live_calls']} | "
            f"{_fmt_rate(w['identical_rate'])} | {_fmt_rate(w['drift_rate'])} | "
            f"{_fmt_rate(w['broken_rate'])} | "
            f"{w['n_specs_stale']}/{w['n_specs']} ({_fmt_rate(w['stale_rate'])}) |"
        )
    per_server = agg["per_server"]
    if per_server:
        lines += ["", "## Per-server drift / broken rate over windows", ""]
        for sid in sorted(per_server):
            rows = per_server[sid]
            lines.append(f"### `{sid}`")
            lines.append("")
            lines.append("| window | live calls | identical | drift | broken |")
            lines.append("|---|---|---|---|---|")
            for r in rows:
                lines.append(
                    f"| {r['window']} | {r['live_calls']} | "
                    f"{_fmt_rate(r['identical_rate'])} | "
                    f"{_fmt_rate(r['drift_rate'])} | "
                    f"{_fmt_rate(r['broken_rate'])} |"
                )
            lines.append("")
    return "\n".join(lines) + "\n"


def _refresh_cmd(
    *,
    specs: Path,
    manifest: Path,
    reference_traces: Path,
    out_path: Path,
    refresh_stateful: bool,
    retries: int,
    retry_backoff: float,
) -> list[str]:
    """Build the `dmcp refresh` invocation for one window."""
    cmd = [
        DMCP,
        "refresh",
        str(specs),
        "-m",
        str(manifest),
        "--reference-traces",
        str(reference_traces),
        "-o",
        str(out_path),
        "--retries",
        str(retries),
        "--retry-backoff",
        str(retry_backoff),
    ]
    if refresh_stateful:
        cmd.append("--refresh-stateful")
    return cmd


def _run(cmd: list[str]) -> int:
    print("+ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=False).returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--specs", required=True, help="TaskSpec JSONL")
    ap.add_argument("--reference-traces", required=True, help="Reference traces JSONL")
    ap.add_argument("--manifest", default="manifests/servers.json")
    ap.add_argument("--windows", type=int, default=3, help="Number of refresh windows to run.")
    ap.add_argument("--wait-s", type=float, default=0.0, help="Seconds to sleep between consecutive windows.")
    ap.add_argument("--retries", type=int, default=2, help="Transient-error retry count per refresh call.")
    ap.add_argument(
        "--retry-backoff", type=float, default=0.5, help="Initial backoff seconds for transient retries."
    )
    ap.add_argument(
        "--refresh-stateful",
        action="store_true",
        help="Forward to `dmcp refresh`; DANGEROUS — only for sandboxed servers.",
    )
    ap.add_argument(
        "--snapshots-dir",
        default="reports/decay/snapshots",
        help="Directory for per-window RefreshReport JSONLs (window_<i>.jsonl).",
    )
    ap.add_argument(
        "--report",
        default="reports/decay/decay_curve.md",
        help="Markdown report output path.",
    )
    ap.add_argument(
        "--json",
        default=None,
        help="Numbers JSON path (e.g. docs/experiments/e1.5_numbers.json — paper renderer input).",
    )
    ap.add_argument(
        "--skip-refresh",
        action="store_true",
        help="Skip the dmcp refresh dispatch; aggregate over existing window_<i>.jsonl files only.",
    )
    a = ap.parse_args()

    if a.windows <= 0:
        raise SystemExit("--windows must be > 0")

    specs = Path(a.specs)
    manifest = Path(a.manifest)
    reference_traces = Path(a.reference_traces)
    snapshots_dir = Path(a.snapshots_dir)
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    window_paths: list[Path] = []
    for i in range(a.windows):
        path = snapshots_dir / f"window_{i}.jsonl"
        window_paths.append(path)
        if not a.skip_refresh:
            cmd = _refresh_cmd(
                specs=specs,
                manifest=manifest,
                reference_traces=reference_traces,
                out_path=path,
                refresh_stateful=a.refresh_stateful,
                retries=a.retries,
                retry_backoff=a.retry_backoff,
            )
            rc = _run(cmd)
            if rc != 0:
                print(f"[warn] window {i} exited {rc}; continuing", flush=True)
            if i + 1 < a.windows and a.wait_s > 0:
                time.sleep(a.wait_s)

    agg = aggregate_windows(window_paths)
    md = render_markdown(agg)

    report_path = Path(a.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(md, encoding="utf-8")
    print(f"wrote {report_path}")

    if a.json:
        jp = Path(a.json)
        jp.parent.mkdir(parents=True, exist_ok=True)
        jp.write_text(json.dumps(agg, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {jp}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
