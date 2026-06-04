"""E8.3 / B3: tool-scaling runner aggregator tests.

The dmcp-eval dispatch in `scripts/tool_scaling.py` is paid LLM compute — only
the pure-Python aggregator is unit-tested here. End-to-end smoke uses --skip-eval
on a fixture so no subprocess is launched.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import tool_scaling  # noqa: E402  (script imported as a module for testing)


def _row(passed: bool, had_sae: bool) -> dict:
    return {"candidate_model": "test/model", "passed": passed, "had_sae": had_sae, "summary": {}}


# ---------------------------------------------------------------------------
# _parse_sizes — argument validation
# ---------------------------------------------------------------------------


def test_parse_sizes_keeps_numeric_and_full():
    assert tool_scaling._parse_sizes("4,8,16,32,full") == ["4", "8", "16", "32", "full"]


def test_parse_sizes_ignores_blank_tokens():
    assert tool_scaling._parse_sizes(" 4 , , 8 , ") == ["4", "8"]


def test_parse_sizes_rejects_non_positive():
    with pytest.raises(ValueError):
        tool_scaling._parse_sizes("0")
    with pytest.raises(ValueError):
        tool_scaling._parse_sizes("-3")


def test_parse_sizes_rejects_garbage():
    with pytest.raises(ValueError):
        tool_scaling._parse_sizes("4,banana,8")


def test_parse_sizes_requires_at_least_one_cell():
    with pytest.raises(ValueError):
        tool_scaling._parse_sizes("")


# ---------------------------------------------------------------------------
# _cell_metrics — per-N rollup with Wilson CIs
# ---------------------------------------------------------------------------


def test_cell_metrics_empty_is_zero_with_zero_ci():
    m = tool_scaling._cell_metrics([])
    assert m["n"] == 0
    assert m["accuracy"] == 0.0
    assert m["accuracy_ci"] == [0.0, 0.0]
    assert m["sae_rate"] == 0.0


def test_cell_metrics_counts_pass_and_sae_independently():
    rows = [
        _row(passed=True, had_sae=False),
        _row(passed=True, had_sae=True),
        _row(passed=False, had_sae=True),
        _row(passed=False, had_sae=False),
    ]
    m = tool_scaling._cell_metrics(rows)
    assert m["n"] == 4
    assert m["passed"] == 2 and m["accuracy"] == 0.5
    assert m["sae"] == 2 and m["sae_rate"] == 0.5
    # Wilson CI for 2/4 must strictly contain 0.5 and stay inside [0,1].
    lo, hi = m["accuracy_ci"]
    assert 0.0 < lo < 0.5 < hi < 1.0


def test_cell_metrics_wilson_matches_reference_for_known_inputs():
    # 8/10 → Wilson 95% ~ [0.490, 0.943] — anchor the formula so a future
    # refactor that changes the math fails loudly.
    rows = [_row(True, False)] * 8 + [_row(False, False)] * 2
    m = tool_scaling._cell_metrics(rows)
    lo, hi = m["accuracy_ci"]
    assert abs(lo - 0.4902) < 5e-3
    assert abs(hi - 0.9432) < 5e-3


# ---------------------------------------------------------------------------
# aggregate_sweep — ordering + monotone-degradation visible in fixture
# ---------------------------------------------------------------------------


def test_aggregate_sweep_sorts_by_size_with_full_pinned_last():
    cells = {
        "32": [_row(True, False)],
        "4": [_row(True, False)],
        "full": [_row(True, False)],
        "16": [_row(True, False)],
        "8": [_row(True, False)],
    }
    agg = tool_scaling.aggregate_sweep(cells)
    assert [p["pool_size"] for p in agg["points"]] == ["4", "8", "16", "32", "full"]
    assert agg["n_cells"] == 5


def test_aggregate_sweep_shows_expected_monotone_drop():
    """Synthetic case: pass-rate falls and SAE rises as the pool grows."""
    cells = {
        "4": [_row(True, False)] * 9 + [_row(False, False)],  # 90% pass, 0% SAE
        "8": [_row(True, False)] * 7 + [_row(False, True)] * 3,  # 70% pass, 30% SAE
        "32": [_row(True, False)] * 4 + [_row(False, True)] * 6,  # 40% pass, 60% SAE
    }
    agg = tool_scaling.aggregate_sweep(cells)
    accs = [p["accuracy"] for p in agg["points"]]
    saes = [p["sae_rate"] for p in agg["points"]]
    assert accs == [0.9, 0.7, 0.4]
    assert saes == [0.0, 0.3, 0.6]


def test_aggregate_sweep_handles_missing_cell_gracefully():
    """Empty cell becomes a zero-CI row, not a crash — keeps the sweep readable
    when one --pool-size errored out and we still want to see the others."""
    cells = {
        "4": [_row(True, False), _row(True, False)],
        "8": [],  # cell errored upstream
    }
    agg = tool_scaling.aggregate_sweep(cells)
    by_label = {p["pool_size"]: p for p in agg["points"]}
    assert by_label["8"]["n"] == 0
    assert by_label["8"]["accuracy_ci"] == [0.0, 0.0]


# ---------------------------------------------------------------------------
# _eval_cmd — flag composition for the dmcp eval dispatch
# ---------------------------------------------------------------------------


def test_eval_cmd_target_pool_passes_size_and_p_alt(tmp_path: Path):
    cmd = tool_scaling._eval_cmd(
        specs=tmp_path / "s.jsonl",
        manifest=tmp_path / "m.json",
        model="openai/gpt-5.5",
        reference_traces=tmp_path / "r.jsonl",
        pool_label="16",
        p_alt=0.5,
        budget=12,
        repeat=3,
        out_path=tmp_path / "out.jsonl",
    )
    assert "--pool" in cmd and cmd[cmd.index("--pool") + 1] == "target"
    assert "--pool-size" in cmd and cmd[cmd.index("--pool-size") + 1] == "16"
    assert "--p-alt" in cmd and cmd[cmd.index("--p-alt") + 1] == "0.5"
    assert "--replay" in cmd


def test_eval_cmd_full_drops_size_and_p_alt(tmp_path: Path):
    """`full` means no distractors — the alternative density is meaningless there."""
    cmd = tool_scaling._eval_cmd(
        specs=tmp_path / "s.jsonl",
        manifest=tmp_path / "m.json",
        model="openai/gpt-5.5",
        reference_traces=tmp_path / "r.jsonl",
        pool_label="full",
        p_alt=0.5,
        budget=12,
        repeat=1,
        out_path=tmp_path / "out.jsonl",
    )
    assert "--pool" in cmd and cmd[cmd.index("--pool") + 1] == "full"
    assert "--pool-size" not in cmd
    assert "--p-alt" not in cmd


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------


def test_render_markdown_lists_each_cell():
    cells = {"4": [_row(True, False), _row(False, False)], "full": [_row(True, False)]}
    agg = tool_scaling.aggregate_sweep(cells)
    md = tool_scaling._render_markdown(agg, model="m/x", specs_label="tiny.jsonl")
    assert "| 4 | 2 |" in md
    assert "| full | 1 |" in md
    assert "tool-scaling" in md.lower()


def test_render_markdown_handles_no_data():
    md = tool_scaling._render_markdown({"points": [], "n_cells": 0}, model="m", specs_label="x")
    assert "No EvaluationResult rows" in md


# ---------------------------------------------------------------------------
# End-to-end smoke: --skip-eval over a fixture, no subprocess to dmcp eval
# ---------------------------------------------------------------------------


def test_skip_eval_smoke_aggregates_fixture(tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    # Two pre-existing eval cells: 4 → 100%, 16 → 50%.
    with (out / "eval_pool4.jsonl").open("w", encoding="utf-8") as fh:
        for r in [_row(True, False), _row(True, False)]:
            fh.write(json.dumps(r))
            fh.write("\n")
    with (out / "eval_pool16.jsonl").open("w", encoding="utf-8") as fh:
        for r in [_row(True, False), _row(False, True)]:
            fh.write(json.dumps(r))
            fh.write("\n")
    json_path = tmp_path / "numbers.json"
    script = Path(__file__).resolve().parent.parent / "scripts" / "tool_scaling.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--specs",
            "/dev/null",  # unused under --skip-eval
            "--reference-traces",
            "/dev/null",
            "--manifest",
            "/dev/null",
            "--model",
            "test/model",
            "--pool-sizes",
            "4,16",
            "--out",
            str(out),
            "--json",
            str(json_path),
            "--skip-eval",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "tool_scaling.md" in proc.stdout
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    by_label = {p["pool_size"]: p for p in payload["points"]}
    assert by_label["4"]["accuracy"] == 1.0
    assert by_label["16"]["accuracy"] == 0.5
    assert by_label["16"]["sae_rate"] == 0.5
