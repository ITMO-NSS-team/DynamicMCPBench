"""E5.2: paper figure / table regenerator — parser, dispatch, renderers, cross-ref."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from paper.regenerate import (
    RENDERERS,
    FigureRow,
    IndexError_,
    find_draft_references,
    parse_figures_index,
    regenerate,
    render_fig_rq1_kendall,
    render_tab_rq2_comparison,
    render_tab_rq3_failure_drivers,
    render_tab_substrate,
    validate_cross_references,
)

# ---------------------------------------------------------------------------
# figures.md parser
# ---------------------------------------------------------------------------


def _write_index(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body), encoding="utf-8")


def test_parse_figures_index_round_trip(tmp_path: Path):
    p = tmp_path / "figures.md"
    _write_index(
        p,
        """\
        # ignored heading

        ## Figures

        | id | caption | status | gating step | data source / notes |
        |---|---|---|---|---|
        | `fig:rq1_kendall` | RQ1 kendall plot | ready | — | `docs/experiments/e4.4_numbers.json` |
        | `fig:pipeline` | block diagram | manual | — | hand-drawn |

        ## Tables

        | id | caption | status | gating step | data source / notes |
        |---|---|---|---|---|
        | `tab:rq2_comparison` | RQ2 comparison | ready | — | `docs/experiments/e4.3_numbers.json` |
        | `tab:rq4_agreement` | scorer vs human | pending | E4.6 | annotation pass |
        """,
    )
    rows = parse_figures_index(p)
    assert [r.id for r in rows] == [
        "fig:rq1_kendall",
        "fig:pipeline",
        "tab:rq2_comparison",
        "tab:rq4_agreement",
    ]
    assert rows[0].kind == "fig"
    assert rows[2].kind == "tab"
    assert rows[1].status == "manual"
    assert rows[3].status == "pending"
    assert rows[2].section == "Tables"
    assert rows[0].section == "Figures"


def test_parse_figures_index_rejects_invalid_status(tmp_path: Path):
    p = tmp_path / "figures.md"
    _write_index(
        p,
        """\
        ## Figures

        | id | caption | status | gating step | data source / notes |
        |---|---|---|---|---|
        | `fig:bad` | x | maybe | — | x |
        """,
    )
    with pytest.raises(IndexError_):
        parse_figures_index(p)


def test_parse_figures_index_rejects_unprefixed_id(tmp_path: Path):
    p = tmp_path / "figures.md"
    _write_index(
        p,
        """\
        ## Figures

        | id | caption | status | gating step | data source / notes |
        |---|---|---|---|---|
        | `notafig_or_tab` | x | ready | — | x |
        """,
    )
    with pytest.raises(IndexError_):
        parse_figures_index(p)


# ---------------------------------------------------------------------------
# Cross-reference validator
# ---------------------------------------------------------------------------


def test_find_draft_references_and_validate(tmp_path: Path):
    draft = tmp_path / "draft.md"
    draft.write_text(
        textwrap.dedent(
            """\
            Some text.

            [Fig 3 here — answer-match vs trace-align. See `figures.md::fig:rq1_kendall`.]

            More text.

            [Tbl 1 here — RQ2 comparison. See `figures.md::tab:rq2_comparison`.]

            [Fig 9 here — does not exist. See `figures.md::fig:missing`.]
            """
        )
    )
    refs = find_draft_references(draft)
    assert refs == ["fig:rq1_kendall", "tab:rq2_comparison", "fig:missing"]


def test_validate_cross_references_flags_missing():
    rows = [
        FigureRow(
            id="fig:rq1_kendall",
            kind="fig",
            caption="x",
            status="ready",
            gating_step="—",
            data_source="x",
            section="Figures",
        )
    ]
    errs = validate_cross_references(rows, ["fig:rq1_kendall", "fig:missing"])
    assert any("fig:missing" in e for e in errs)


# ---------------------------------------------------------------------------
# Renderers — ready-row happy paths and missing-data fallbacks
# ---------------------------------------------------------------------------


def _fake_row(id_: str, status: str = "ready") -> FigureRow:
    return FigureRow(
        id=id_,
        kind=id_.split(":", 1)[0],
        caption="x",
        status=status,
        gating_step="—",
        data_source="x",
        section="Figures" if id_.startswith("fig:") else "Tables",
    )


def test_render_tab_rq2_comparison_emits_per_method_row(tmp_path: Path):
    root = tmp_path
    (root / "docs" / "experiments").mkdir(parents=True)
    (root / "docs" / "experiments" / "e4.3_numbers.json").write_text(
        json.dumps(
            {
                "catalog_size": 34,
                "methods": [
                    {
                        "method": "forward",
                        "n_specs": 9,
                        "mean_eq_set_size": 1.42,
                        "fraction_singleton_eq_set": 0.58,
                        "fraction_missing_arg_predicate": 0.21,
                        "coverage": 0.65,
                        "filter_pass_rate": None,
                    },
                    {
                        "method": "graph",
                        "n_specs": 6,
                        "mean_eq_set_size": 1.0,
                        "fraction_singleton_eq_set": 1.0,
                        "fraction_missing_arg_predicate": 1.0,
                        "coverage": 0.44,
                        "filter_pass_rate": 1.0,
                    },
                ],
            }
        )
    )
    r = render_tab_rq2_comparison(_fake_row("tab:rq2_comparison"), root)
    assert r.used_data_source is True
    assert "forward" in r.body
    assert "graph" in r.body
    assert "1.420" in r.body  # mean_eq_set_size, 3 dp
    assert "100.0%" in r.body  # graph filter_pass_rate


def test_render_fig_rq1_kendall_sorts_by_trace_accuracy(tmp_path: Path):
    root = tmp_path
    (root / "docs" / "experiments").mkdir(parents=True)
    (root / "docs" / "experiments" / "e4.4_numbers.json").write_text(
        json.dumps(
            {
                "kendall_tau_rankings": -0.816,
                "overall_false_pass_rate": 0.631,
                "overall_false_fail_rate": 0.018,
                "models": [
                    {"model": "haiku-3.5", "trace_accuracy": 0.21, "answer_accuracy": 0.95},
                    {"model": "haiku-4.5", "trace_accuracy": 0.45, "answer_accuracy": 0.89},
                    {"model": "qwen3", "trace_accuracy": 0.23, "answer_accuracy": 0.89},
                ],
            }
        )
    )
    r = render_fig_rq1_kendall(_fake_row("fig:rq1_kendall"), root)
    # haiku-4.5 has the highest trace_accuracy → must appear before haiku-3.5
    idx_haiku45 = r.body.find("haiku-4.5")
    idx_haiku35 = r.body.find("haiku-3.5")
    assert 0 <= idx_haiku45 < idx_haiku35
    # τ value is rendered with sign + 3 digits
    assert "-0.816" in r.body


def test_render_tab_rq3_failure_drivers_sorted_by_loss(tmp_path: Path):
    root = tmp_path
    (root / "docs" / "experiments").mkdir(parents=True)
    importances = [
        {
            "name": "cross_server",
            "coefficient": -0.76,
            "odds_ratio": 0.47,
            "drop_loglik_loss": 0.87,
        },
        {
            "name": "dynamism_live",
            "coefficient": -3.11,
            "odds_ratio": 0.045,
            "drop_loglik_loss": 6.61,
        },
        {
            "name": "trace_depth",
            "coefficient": -0.10,
            "odds_ratio": 0.91,
            "drop_loglik_loss": 1.68,
        },
    ]
    (root / "docs" / "experiments" / "e4.5_numbers.json").write_text(
        json.dumps(
            {
                "ridge": 1e-3,
                "fits": [
                    {
                        "label": "pooled",
                        "n_samples": 168,
                        "pass_rate": 0.298,
                        "loglik": -83.79,
                        "importances": importances,
                    }
                ],
            }
        )
    )
    r = render_tab_rq3_failure_drivers(_fake_row("tab:rq3_failure_drivers"), root)
    assert "dynamism_live" in r.body
    # Sorted by drop_loglik_loss descending → dynamism_live appears before trace_depth
    assert r.body.find("dynamism_live") < r.body.find("trace_depth")
    assert r.body.find("trace_depth") < r.body.find("cross_server")


def test_render_tab_substrate_counts_dynamism(tmp_path: Path):
    root = tmp_path
    (root / "manifests").mkdir()
    servers = [
        {
            "server_id": "time",
            "transport": "stdio",
            "command": "x",
            "dynamism": "static",
            "tags": ["util"],
        },
        {
            "server_id": "wiki",
            "transport": "stdio",
            "command": "x",
            "dynamism": "live_read",
            "tags": ["knowledge", "public-api"],
        },
        {
            "server_id": "git",
            "transport": "stdio",
            "command": "x",
            "dynamism": "stateful_write",
            "sandbox": True,
            "tags": ["vcs"],
        },
    ]
    (root / "manifests" / "local.json").write_text(
        json.dumps({"manifest_version": "0.1.0", "servers": servers})
    )
    r = render_tab_substrate(_fake_row("tab:substrate"), root)
    assert "3" in r.body  # total
    assert "static" in r.body
    assert "live_read" in r.body
    assert "stateful_write" in r.body
    assert "public-api" in r.body


def test_renderer_returns_placeholder_when_data_missing(tmp_path: Path):
    r = render_tab_rq2_comparison(_fake_row("tab:rq2_comparison"), tmp_path)
    assert r.used_data_source is False
    assert r.pending is True
    assert "pending" in r.body.lower() or "placeholder" in r.body.lower()


# ---------------------------------------------------------------------------
# Top-level regenerate end-to-end
# ---------------------------------------------------------------------------


def test_regenerate_writes_one_file_per_row_and_marks_pending(tmp_path: Path):
    paper = tmp_path / "paper"
    paper.mkdir()
    _write_index(
        paper / "figures.md",
        """\
        ## Figures

        | id | caption | status | gating step | data source / notes |
        |---|---|---|---|---|
        | `fig:pipeline` | block diagram | manual | — | hand-drawn |

        ## Tables

        | id | caption | status | gating step | data source / notes |
        |---|---|---|---|---|
        | `tab:rq2_comparison` | RQ2 comparison | ready | — | e4.3 |
        """,
    )
    (paper / "draft.md").write_text(
        "[Fig 1 here — pipeline overview. See `figures.md::fig:pipeline`.]\n"
        "[Tbl 1 here — RQ2. See `figures.md::tab:rq2_comparison`.]\n"
    )
    out = paper / "figures"
    outcome = regenerate(root=tmp_path, out_dir=out)
    # The RQ2 row will be pending here (no e4.3 JSON in this tmpdir).
    assert "tab:rq2_comparison" in outcome.pending
    assert "fig:pipeline" in outcome.manual
    assert outcome.cross_ref_errors == []
    # One artifact per row
    assert (out / "fig__pipeline.md").exists()
    assert (out / "tab__rq2_comparison.md").exists()
    # Manual row gets a placeholder marked "manual"
    pipeline_body = (out / "fig__pipeline.md").read_text(encoding="utf-8")
    assert "manual" in pipeline_body.lower()


def test_regenerate_flags_dangling_draft_references(tmp_path: Path):
    paper = tmp_path / "paper"
    paper.mkdir()
    _write_index(
        paper / "figures.md",
        """\
        ## Figures

        | id | caption | status | gating step | data source / notes |
        |---|---|---|---|---|
        | `fig:pipeline` | block diagram | manual | — | — |
        """,
    )
    (paper / "draft.md").write_text("[Fig 99 here — missing. See `figures.md::fig:does_not_exist`.]\n")
    outcome = regenerate(root=tmp_path, out_dir=paper / "figures")
    assert any("fig:does_not_exist" in e for e in outcome.cross_ref_errors)


# ---------------------------------------------------------------------------
# Renderer registry is exhaustive
# ---------------------------------------------------------------------------


def test_renderers_cover_every_committed_figures_md_row():
    """Every id committed in the real `paper/figures.md` must have a registered
    renderer — otherwise re-running `dmcp paper-figures` would emit
    "no renderer registered" placeholders for known artifacts."""
    rows = parse_figures_index(Path(__file__).resolve().parent.parent / "paper" / "figures.md")
    for r in rows:
        assert r.id in RENDERERS, f"no renderer registered for {r.id!r}"
