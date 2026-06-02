"""E5.2: paper figure / table regenerator — LaTeX renderers + cross-ref."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from paper.regenerate import (
    RENDERERS,
    FigureRow,
    IndexError_,
    find_section_inputs,
    parse_figures_index,
    regenerate,
    render_fig_rq1_kendall,
    render_tab_rq2_comparison,
    render_tab_rq3_failure_drivers,
    render_tab_substrate,
    tex_escape,
    validate_cross_references,
)

# ---------------------------------------------------------------------------
# tex_escape
# ---------------------------------------------------------------------------


def test_tex_escape_handles_special_chars():
    assert tex_escape("100%") == r"100\%"
    assert tex_escape("a_b") == r"a\_b"
    assert tex_escape("a&b") == r"a\&b"
    assert tex_escape("$1") == r"\$1"
    # HTML pipe escape from figures.md captions should decode back to `|`.
    assert tex_escape("&#124;eq_set&#124;") == r"|eq\_set|"


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
    assert rows[0].slug == "rq1_kendall"
    assert rows[2].slug == "rq2_comparison"
    assert rows[1].status == "manual"
    assert rows[3].status == "pending"


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


def test_find_section_inputs_walks_tex_files(tmp_path: Path):
    sections = tmp_path / "sections"
    sections.mkdir()
    (sections / "introduction.tex").write_text(r"Some text. \input{figures/rq1_kendall} more text." + "\n")
    (sections / "experiments.tex").write_text(
        r"\input{tables/rq2_comparison}"
        + "\n"
        + r"\input{figures/missing}"
        + "\n"
        + r"\input{somethingelse/notapaper}"
        + "\n"  # NOT a figures/tables include
    )
    refs = find_section_inputs(sections)
    assert sorted(refs) == [
        "fig:missing",
        "fig:rq1_kendall",
        "tab:rq2_comparison",
    ]


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
# LaTeX renderers — happy paths and missing-data fallbacks
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


def test_render_tab_rq2_comparison_emits_latex_table(tmp_path: Path):
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
    assert r"\begin{table*}" in r.body
    assert r"\end{table*}" in r.body
    assert r"\label{tab:rq2_comparison}" in r.body
    assert "forward" in r.body
    assert "graph" in r.body
    assert "1.420" in r.body
    # filter_pass_rate=1.0 → "100.0\%"
    assert r"100.0\%" in r.body


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
    assert r"\begin{figure}" in r.body
    assert r"\label{fig:rq1_kendall}" in r.body
    # haiku-4.5 has the highest trace_accuracy → must appear before haiku-3.5
    idx_45 = r.body.find("haiku-4.5")
    idx_35 = r.body.find("haiku-3.5")
    assert 0 <= idx_45 < idx_35
    # τ is rendered as a math-mode signed float with 3 digits
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
    assert r"\begin{table}" in r.body
    assert r"\label{tab:rq3_failure_drivers}" in r.body
    # Underscores in feature names must be LaTeX-escaped.
    assert r"dynamism\_live" in r.body
    # Sorted by drop_loglik_loss descending → dynamism_live before trace_depth.
    assert r.body.find("dynamism") < r.body.find("trace") < r.body.find("cross")


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
    assert r"\begin{table}" in r.body
    assert r"\label{tab:substrate}" in r.body
    # All three dynamism rows should appear.
    assert r"\texttt{static}" in r.body
    assert r"\texttt{live\_read}" in r.body
    assert r"\texttt{stateful\_write}" in r.body
    # Top tag should be rendered.
    assert "public-api" in r.body
    # The total count appears in the caption.
    assert "3 vetted servers" in r.body


def test_renderer_returns_placeholder_when_data_missing(tmp_path: Path):
    r = render_tab_rq2_comparison(_fake_row("tab:rq2_comparison"), tmp_path)
    assert r.used_data_source is False
    assert r.pending is True
    # Placeholder still emits a labeled figure/table so \ref{} resolves.
    assert r"\label{tab:rq2_comparison}" in r.body
    assert r"\begin{table}" in r.body


# ---------------------------------------------------------------------------
# Top-level regenerate end-to-end
# ---------------------------------------------------------------------------


def test_regenerate_writes_separate_files_per_kind(tmp_path: Path):
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
    sections = paper / "sections"
    sections.mkdir()
    (sections / "intro.tex").write_text(
        r"\input{figures/pipeline}" + "\n" + r"\input{tables/rq2_comparison}" + "\n"
    )
    outcome = regenerate(root=tmp_path)
    # The RQ2 row is pending here (no e4.3 JSON in tmpdir).
    assert "tab:rq2_comparison" in outcome.pending
    assert "fig:pipeline" in outcome.manual
    assert outcome.cross_ref_errors == []
    # fig:* goes to paper/figures/, tab:* goes to paper/tables/
    assert (paper / "figures" / "pipeline.tex").is_file()
    assert (paper / "tables" / "rq2_comparison.tex").is_file()
    body = (paper / "figures" / "pipeline.tex").read_text(encoding="utf-8")
    assert r"\begin{figure}" in body
    assert r"\label{fig:pipeline}" in body


def test_regenerate_flags_dangling_section_inputs(tmp_path: Path):
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
    sections = paper / "sections"
    sections.mkdir()
    (sections / "intro.tex").write_text(r"\input{figures/does_not_exist}" + "\n")
    outcome = regenerate(root=tmp_path)
    assert any("fig:does_not_exist" in e for e in outcome.cross_ref_errors)


def test_regenerate_is_idempotent(tmp_path: Path):
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
    (paper / "sections").mkdir()
    regenerate(root=tmp_path)
    first = (paper / "figures" / "pipeline.tex").read_text(encoding="utf-8")
    regenerate(root=tmp_path)
    second = (paper / "figures" / "pipeline.tex").read_text(encoding="utf-8")
    assert first == second


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
