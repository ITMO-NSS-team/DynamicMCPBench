"""E8.4 / B4: multi-window decay runner aggregator tests.

The `dmcp refresh` dispatch hits live servers — only the pure-Python aggregator
is unit-tested here. End-to-end smoke uses --skip-refresh on a fixture, so no
subprocess to `dmcp refresh` is launched.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import decay_run  # noqa: E402  (script imported as a module for testing)


def _report(
    *,
    server: str,
    identical: int = 0,
    drifted: int = 0,
    broken: int = 0,
    skipped: int = 0,
    spec_likely_stale: bool | None = None,
) -> dict:
    """Synthesize a `RefreshReport`-shaped dict for one spec.

    Each non-zero outcome class becomes an entry in `call_outcomes` so the
    per-server aggregator sees the right `server_id`. The counts dict mirrors
    `dmcp.refresh.refresh_one`'s output so we can exercise both axes of the
    aggregator from the same fixture row.
    """
    call_outcomes = []
    step = 0
    for cls, n in (
        ("identical", identical),
        ("drifted", drifted),
        ("broken", broken),
        ("skipped", skipped),
    ):
        for _ in range(n):
            call_outcomes.append({"server_id": server, "classification": cls, "step_id": step})
            step += 1
    counts = {
        "identical": identical,
        "drifted": drifted,
        "broken": broken,
        "skipped": skipped,
        "total": identical + drifted + broken + skipped,
    }
    stale = broken > 0 if spec_likely_stale is None else spec_likely_stale
    return {
        "counts": counts,
        "call_outcomes": call_outcomes,
        "spec_likely_stale": stale,
    }


def _write(path: Path, reports: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in reports:
            fh.write(json.dumps(r))
            fh.write("\n")


# ---------------------------------------------------------------------------
# Per-window roll-up
# ---------------------------------------------------------------------------


def test_window_metrics_excludes_skipped_from_rate_denominator():
    """Drift rate denominator = live = identical + drifted + broken; skipped
    must not deflate it (refresh.py docstring is the contract)."""
    reports = [
        _report(server="fs", identical=8, drifted=2, broken=0, skipped=5),
    ]
    m = decay_run._window_metrics(reports)
    assert m["live_calls"] == 10
    assert m["identical_rate"] == 0.8
    assert m["drift_rate"] == 0.2
    assert m["broken_rate"] == 0.0
    assert m["skipped"] == 5
    assert m["total_calls"] == 15


def test_window_metrics_handles_empty_window():
    m = decay_run._window_metrics([])
    assert m["n_specs"] == 0
    assert m["live_calls"] == 0
    assert m["identical_rate"] is None  # honest "undefined", not a fake zero
    assert m["drift_rate"] is None
    assert m["broken_rate"] is None
    assert m["stale_rate"] is None


def test_window_metrics_counts_stale_specs():
    reports = [
        _report(server="fs", identical=3, broken=1),  # stale (any broken)
        _report(server="fs", identical=3),  # not stale
        _report(server="fs", identical=2, drifted=1),  # not stale (drift only)
    ]
    m = decay_run._window_metrics(reports)
    assert m["n_specs"] == 3
    assert m["n_specs_stale"] == 1
    assert abs(m["stale_rate"] - 1 / 3) < 1e-9


# ---------------------------------------------------------------------------
# Per-server within one window
# ---------------------------------------------------------------------------


def test_per_server_window_splits_outcomes_by_server():
    reports = [
        _report(server="fs", identical=5, drifted=1),
        _report(server="git", identical=2, broken=2),
        _report(server="fs", identical=3),
    ]
    ps = decay_run._per_server_window(reports)
    assert set(ps) == {"fs", "git"}
    fs = ps["fs"]
    assert fs["refreshes"] == 2  # two specs touched fs
    assert fs["identical"] == 8
    assert fs["drifted"] == 1
    assert fs["live_calls"] == 9
    assert abs(fs["drift_rate"] - 1 / 9) < 1e-9
    git = ps["git"]
    assert git["broken"] == 2
    assert git["broken_rate"] == 0.5


def test_per_server_window_returns_none_rates_for_skipped_only_server():
    """A server with only skipped calls has zero live → rates undefined (None)."""
    reports = [_report(server="stateful_db", skipped=4)]
    ps = decay_run._per_server_window(reports)
    s = ps["stateful_db"]
    assert s["live_calls"] == 0
    assert s["drift_rate"] is None


# ---------------------------------------------------------------------------
# Multi-window aggregation
# ---------------------------------------------------------------------------


def test_aggregate_windows_orders_by_path_position(tmp_path: Path):
    """The window index is the position in `window_paths`; aggregation must
    preserve that order so the figure shows true temporal monotonicity."""
    w0 = tmp_path / "window_0.jsonl"
    w1 = tmp_path / "window_1.jsonl"
    w2 = tmp_path / "window_2.jsonl"
    _write(w0, [_report(server="fs", identical=10)])
    _write(w1, [_report(server="fs", identical=9, drifted=1)])
    _write(w2, [_report(server="fs", identical=7, drifted=2, broken=1)])
    agg = decay_run.aggregate_windows([w0, w1, w2])
    assert agg["n_windows"] == 3
    drifts = [w["drift_rate"] for w in agg["windows"]]
    assert drifts == [0.0, 0.1, 0.2]
    fs_series = agg["per_server"]["fs"]
    assert [r["window"] for r in fs_series] == [0, 1, 2]
    assert fs_series[2]["broken_rate"] == 0.1


def test_aggregate_windows_per_server_carries_all_windows_a_server_appeared_in(tmp_path: Path):
    w0 = tmp_path / "window_0.jsonl"
    w1 = tmp_path / "window_1.jsonl"
    _write(w0, [_report(server="fs", identical=3), _report(server="git", identical=3)])
    _write(w1, [_report(server="git", identical=2, drifted=1)])  # fs absent
    agg = decay_run.aggregate_windows([w0, w1])
    assert len(agg["per_server"]["fs"]) == 1  # only window 0
    assert len(agg["per_server"]["git"]) == 2
    git2 = agg["per_server"]["git"][1]
    assert git2["window"] == 1
    assert abs(git2["drift_rate"] - 1 / 3) < 1e-9


def test_aggregate_windows_handles_missing_window_file_gracefully(tmp_path: Path):
    """A window file that didn't write becomes an empty cell, not a crash."""
    present = tmp_path / "window_0.jsonl"
    missing = tmp_path / "window_1.jsonl"  # never created
    _write(present, [_report(server="fs", identical=4)])
    agg = decay_run.aggregate_windows([present, missing])
    assert agg["windows"][1]["n_specs"] == 0
    assert agg["windows"][1]["drift_rate"] is None
    # Per-server map only mentions servers we actually saw.
    assert "fs" in agg["per_server"] and len(agg["per_server"]["fs"]) == 1


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------


def test_render_markdown_lists_windows_and_servers(tmp_path: Path):
    w0 = tmp_path / "window_0.jsonl"
    w1 = tmp_path / "window_1.jsonl"
    _write(w0, [_report(server="fs", identical=8, drifted=2)])
    _write(w1, [_report(server="fs", identical=5, drifted=4, broken=1)])
    md = decay_run.render_markdown(decay_run.aggregate_windows([w0, w1]))
    assert "Per-window outcome rates" in md
    assert "| 0 | 1 |" in md  # window 0 had 1 spec
    assert "### `fs`" in md
    assert "20.0%" in md  # window-0 drift was 2/10 = 20%


def test_render_markdown_handles_no_windows():
    md = decay_run.render_markdown({"n_windows": 0, "windows": [], "per_server": {}})
    assert "No RefreshReport rows" in md


# ---------------------------------------------------------------------------
# _refresh_cmd — flag composition
# ---------------------------------------------------------------------------


def test_refresh_cmd_passes_retries_and_backoff(tmp_path: Path):
    cmd = decay_run._refresh_cmd(
        specs=tmp_path / "s.jsonl",
        manifest=tmp_path / "m.json",
        reference_traces=tmp_path / "r.jsonl",
        out_path=tmp_path / "w0.jsonl",
        refresh_stateful=False,
        retries=3,
        retry_backoff=1.5,
    )
    assert "--retries" in cmd and cmd[cmd.index("--retries") + 1] == "3"
    assert "--retry-backoff" in cmd and cmd[cmd.index("--retry-backoff") + 1] == "1.5"
    # Hard invariant: stateful_write is off by default.
    assert "--refresh-stateful" not in cmd


def test_refresh_cmd_forwards_stateful_flag_only_when_set(tmp_path: Path):
    cmd = decay_run._refresh_cmd(
        specs=tmp_path / "s.jsonl",
        manifest=tmp_path / "m.json",
        reference_traces=tmp_path / "r.jsonl",
        out_path=tmp_path / "w0.jsonl",
        refresh_stateful=True,
        retries=0,
        retry_backoff=0.5,
    )
    assert "--refresh-stateful" in cmd


# ---------------------------------------------------------------------------
# End-to-end smoke: --skip-refresh over a fixture, no subprocess to dmcp refresh
# ---------------------------------------------------------------------------


def test_skip_refresh_smoke_aggregates_fixture(tmp_path: Path):
    snaps = tmp_path / "snaps"
    _write(snaps / "window_0.jsonl", [_report(server="fs", identical=8, drifted=2)])
    _write(snaps / "window_1.jsonl", [_report(server="fs", identical=4, drifted=5, broken=1)])
    json_path = tmp_path / "numbers.json"
    script = Path(__file__).resolve().parent.parent / "scripts" / "decay_run.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--specs",
            "/dev/null",  # unused under --skip-refresh
            "--reference-traces",
            "/dev/null",
            "--manifest",
            "/dev/null",
            "--windows",
            "2",
            "--snapshots-dir",
            str(snaps),
            "--report",
            str(tmp_path / "decay.md"),
            "--json",
            str(json_path),
            "--skip-refresh",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "decay.md" in proc.stdout
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    drifts = [w["drift_rate"] for w in payload["windows"]]
    assert drifts == [0.2, 0.5]
    fs = payload["per_server"]["fs"]
    assert [r["window"] for r in fs] == [0, 1]
