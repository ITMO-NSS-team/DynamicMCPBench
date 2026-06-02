"""Paper figure / table regenerator (E5.2).

Reads ``paper/figures.md`` as the source-of-truth index, dispatches each
row to a per-id renderer, and writes one LaTeX artifact per row under
``paper/figures/<slug>.tex`` (for ``fig:*`` ids) or
``paper/tables/<slug>.tex`` (for ``tab:*`` ids). Section files in
``paper/sections/`` then ``\\input`` the artifacts.

Renderers consume already-committed data
(``docs/experiments/<id>_numbers.json``, ``manifests/*.json``, ...) so
the regenerator runs in CI, in a fresh clone, and in a minimal env
without LLM calls. Rows whose backing data isn't on disk yet emit a
clearly-marked placeholder ``figure``/``table`` whose caption flags the
missing data — the ``\\ref{...}`` still resolves so cross-references in
the draft don't go dangling.

A cross-reference validator walks ``paper/sections/*.tex`` for
``\\input{figures/...}`` and ``\\input{tables/...}`` directives and
verifies every referenced id appears in ``paper/figures.md``.

Per CLAUDE.md the regenerator stays dep-free (no matplotlib / pandas /
scipy) — every artifact is plain LaTeX. PNG / PDF plotting can be added
per-renderer later by swapping the body for ``\\includegraphics``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
PAPER_DIR = REPO_ROOT / "paper"
FIGURES_INDEX = PAPER_DIR / "figures.md"
SECTIONS_DIR = PAPER_DIR / "sections"
FIGURES_OUT = PAPER_DIR / "figures"
TABLES_OUT = PAPER_DIR / "tables"

VALID_STATUSES = {"ready", "partial", "pending", "manual"}

# ``\input{figures/<slug>}`` or ``\input{tables/<slug>}`` (no extension).
_INPUT_RE = re.compile(r"\\input\{(figures|tables)/([A-Za-z0-9_\-]+)\}")


# ---------------------------------------------------------------------------
# figures.md parsing (unchanged from the markdown era — the index stays md)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FigureRow:
    """One row of ``paper/figures.md`` (figures or tables)."""

    id: str  # e.g. "fig:rq1_kendall" or "tab:rq2_comparison"
    kind: str  # "fig" | "tab"
    caption: str
    status: str
    gating_step: str
    data_source: str
    section: str  # "Figures" | "Tables"

    @property
    def slug(self) -> str:
        """Stable LaTeX-safe stem (no colon)."""
        return self.id.split(":", 1)[1]


class IndexError_(ValueError):
    """Raised by the parser when figures.md violates its contract."""


def _table_row(line: str) -> list[str] | None:
    s = line.strip()
    if not s.startswith("|") or not s.endswith("|"):
        return None
    return [c.strip() for c in s.strip("|").split("|")]


def _is_separator(cells: list[str]) -> bool:
    return all(re.fullmatch(r":?-{3,}:?", c) for c in cells)


def parse_figures_index(path: Path = FIGURES_INDEX) -> list[FigureRow]:
    """Parse ``paper/figures.md`` into a list of ``FigureRow``s."""
    text = path.read_text(encoding="utf-8")
    rows: list[FigureRow] = []
    section: str | None = None
    table_state = 0
    columns: list[str] = []
    for raw in text.splitlines():
        if raw.startswith("## "):
            heading = raw[3:].strip()
            section = heading if heading in {"Figures", "Tables"} else None
            table_state = 0
            columns = []
            continue
        cells = _table_row(raw)
        if cells is None:
            table_state = 0
            columns = []
            continue
        if section not in {"Figures", "Tables"}:
            continue
        if table_state == 0:
            columns = [c.lower() for c in cells]
            table_state = 1
            continue
        if table_state == 1 and _is_separator(cells):
            table_state = 2
            continue
        if table_state != 2:
            continue
        if len(cells) < len(columns):
            cells = cells + [""] * (len(columns) - len(cells))
        row = dict(zip(columns, cells, strict=False))
        rid = row.get("id", "").strip("`")
        if not rid:
            continue
        if ":" not in rid:
            raise IndexError_(f"figures.md row id {rid!r} must be prefixed with `fig:` or `tab:`")
        kind = rid.split(":", 1)[0]
        if kind not in {"fig", "tab"}:
            raise IndexError_(f"figures.md row id {rid!r} has unknown kind {kind!r}")
        status = row.get("status", "").strip().lower()
        if status not in VALID_STATUSES:
            raise IndexError_(
                f"figures.md row {rid!r}: status must be one of {VALID_STATUSES}; got {status!r}"
            )
        rows.append(
            FigureRow(
                id=rid,
                kind=kind,
                caption=row.get("caption", ""),
                status=status,
                gating_step=row.get("gating step", "").strip(),
                data_source=row.get("data source / notes", "")
                or row.get("data source", "")
                or row.get("notes", ""),
                section=section,
            )
        )
    return rows


def find_section_inputs(sections_dir: Path = SECTIONS_DIR) -> list[str]:
    """Return the ids referenced by ``\\input{figures/...}`` / ``\\input{tables/...}``
    directives across every ``paper/sections/*.tex`` file."""
    out: list[str] = []
    if not sections_dir.is_dir():
        return out
    for tex in sorted(sections_dir.glob("*.tex")):
        for kind, slug in _INPUT_RE.findall(tex.read_text(encoding="utf-8")):
            out.append(f"{'fig' if kind == 'figures' else 'tab'}:{slug}")
    return out


def validate_cross_references(rows: list[FigureRow], references: list[str]) -> list[str]:
    """Return a list of cross-reference violations (empty list = OK)."""
    by_id = {r.id for r in rows}
    return [
        f"sections reference {ref!r} but no figures.md row has that id"
        for ref in references
        if ref not in by_id
    ]


# ---------------------------------------------------------------------------
# Renderer infrastructure
# ---------------------------------------------------------------------------


@dataclass
class RenderResult:
    id: str
    body: str  # raw LaTeX
    used_data_source: bool
    pending: bool = False
    note: str = ""


@dataclass
class RegenerateOutcome:
    rendered: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    manual: list[str] = field(default_factory=list)
    cross_ref_errors: list[str] = field(default_factory=list)


Renderer = Callable[[FigureRow, Path], RenderResult]


# LaTeX special characters that must be escaped in arbitrary text. Backslash
# is handled specially because the naive substitution would loop.
_TEX_SUBST = (
    ("\\", r"\textbackslash{}"),
    ("&", r"\&"),
    ("%", r"\%"),
    ("$", r"\$"),
    ("#", r"\#"),
    ("_", r"\_"),
    ("{", r"\{"),
    ("}", r"\}"),
    ("~", r"\textasciitilde{}"),
    ("^", r"\textasciicircum{}"),
)


# Unicode characters that the default pdfLaTeX engine cannot typeset; map
# them to LaTeX commands so captions / paths copied verbatim from
# figures.md or experiment JSONs still compile.
_UNICODE_SUBST = (
    (" ", "~"),  # NBSP
    ("—", "---"),  # em-dash
    ("–", "--"),  # en-dash
    ("…", r"\ldots{}"),  # ellipsis
    ("×", r"$\times$"),  # multiplication sign
    ("→", r"$\to$"),  # rightwards arrow
    ("←", r"$\leftarrow$"),
    ("≥", r"$\geq$"),
    ("≤", r"$\leq$"),
    ("≠", r"$\neq$"),
    ("±", r"$\pm$"),
    ("α", r"$\alpha$"),
    ("β", r"$\beta$"),
    ("δ", r"$\delta$"),
    ("ε", r"$\epsilon$"),
    ("κ", r"$\kappa$"),
    ("λ", r"$\lambda$"),
    ("μ", r"$\mu$"),
    ("π", r"$\pi$"),
    ("σ", r"$\sigma$"),
    ("τ", r"$\tau$"),
    ("φ", r"$\phi$"),
    ("χ", r"$\chi$"),
    ("ψ", r"$\psi$"),
    ("ω", r"$\omega$"),
)


def tex_escape(s: str) -> str:
    """Escape LaTeX-special characters and translate common Unicode glyphs.

    Walks the input character-by-character so the LaTeX commands we inject
    for Unicode glyphs (e.g. ``$\\tau$``) aren't themselves re-escaped by
    the special-character pass.
    """
    text = s.replace("&#124;", "|")
    unicode_map = dict(_UNICODE_SUBST)
    special_map = dict(_TEX_SUBST)
    out: list[str] = []
    for ch in text:
        if ch in unicode_map:
            out.append(unicode_map[ch])
        elif ch in special_map:
            out.append(special_map[ch])
        else:
            out.append(ch)
    return "".join(out)


def _wrap_caption(row: FigureRow) -> str:
    return tex_escape(row.caption)


def _placeholder_body(row: FigureRow, reason: str) -> str:
    """Emit a minimal figure/table block so ``\\ref{...}`` still resolves
    even when the data isn't on disk yet."""
    env_open, env_close = ("figure", "figure") if row.kind == "fig" else ("table", "table")
    safe_id = tex_escape(row.id)
    return (
        f"% AUTO-GENERATED by paper/regenerate.py -- do not hand-edit.\n"
        f"% id: {row.id}\n"
        f"% status: {row.status}\n"
        f"% reason: {reason}\n"
        f"\\begin{{{env_open}}}[t]\n"
        f"  \\centering\n"
        f"  \\fbox{{\\parbox{{0.9\\columnwidth}}{{\\centering "
        f"\\textbf{{{safe_id}}} -- placeholder.\\\\\n"
        f"  Status: {tex_escape(row.status)}.\\\\\n"
        f"  Gating step: {tex_escape(row.gating_step or '-')}}}}}\n"
        f"  \\caption{{{_wrap_caption(row)}}}\n"
        f"  \\label{{{row.id}}}\n"
        f"\\end{{{env_close}}}\n"
    )


def _placeholder(row: FigureRow, reason: str) -> RenderResult:
    return RenderResult(
        id=row.id,
        body=_placeholder_body(row, reason),
        used_data_source=False,
        pending=row.status != "manual",
        note=reason,
    )


def _missing_data(row: FigureRow, path: Path) -> RenderResult:
    try:
        rel: Path | str = path.relative_to(REPO_ROOT)
    except ValueError:
        rel = path
    return _placeholder(
        row,
        f"data source `{rel}` not on disk yet -- the gating step listed in figures.md has not produced it.",
    )


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Concrete renderers
# ---------------------------------------------------------------------------


def _tex_header(row: FigureRow) -> str:
    return (
        f"% AUTO-GENERATED by paper/regenerate.py -- do not hand-edit.\n"
        f"% id: {row.id}\n"
        f"% status: {row.status}\n"
        f"% caption: {row.caption}\n"
    )


def render_tab_rq2_comparison(row: FigureRow, root: Path) -> RenderResult:
    path = root / "docs" / "experiments" / "e4.3_numbers.json"
    data = _load_json(path)
    if data is None:
        return _missing_data(row, path)
    methods = data.get("methods") or []
    cols = [
        ("method", "method"),
        ("n_specs", "n"),
        ("mean_eq_set_size", r"mean $|eq\_set|$"),
        ("fraction_singleton_eq_set", "singleton"),
        ("fraction_missing_arg_predicate", "missing arg-pred."),
        ("coverage", "coverage"),
        ("filter_pass_rate", "filter pass"),
    ]
    header = " & ".join(label for _, label in cols) + r" \\"
    rows_out: list[str] = []
    for m in methods:
        cells = []
        for key, _ in cols:
            v = m.get(key)
            if v is None:
                cells.append("--")
            elif isinstance(v, float):
                if key.startswith("fraction_") or key in {"coverage", "filter_pass_rate"}:
                    cells.append(f"{v * 100:.1f}\\%")
                else:
                    cells.append(f"{v:.3f}")
            else:
                cells.append(str(v))
        rows_out.append(" & ".join(cells) + r" \\")
    body = (
        _tex_header(row)
        + "\\begin{table*}[t]\n"
        + "  \\centering\n"
        + "  \\small\n"
        + "  \\begin{tabular}{lrrrrrr}\n"
        + "    \\toprule\n"
        + f"    {header}\n"
        + "    \\midrule\n"
        + "\n".join(f"    {r}" for r in rows_out)
        + "\n"
        + "    \\bottomrule\n"
        + "  \\end{tabular}\n"
        + f"  \\caption{{{_wrap_caption(row)}}}\n"
        + f"  \\label{{{row.id}}}\n"
        + "\\end{table*}\n"
    )
    return RenderResult(id=row.id, body=body, used_data_source=True)


def render_fig_rq1_kendall(row: FigureRow, root: Path) -> RenderResult:
    path = root / "docs" / "experiments" / "e4.4_numbers.json"
    data = _load_json(path)
    if data is None:
        return _missing_data(row, path)
    models = sorted(
        data.get("models") or [],
        key=lambda m: m.get("trace_accuracy", 0.0),
        reverse=True,
    )
    tau = data.get("kendall_tau_rankings", 0.0)
    fp = data.get("overall_false_pass_rate", 0.0)
    ff = data.get("overall_false_fail_rate", 0.0)
    rows_out: list[str] = []
    for m in models:
        ta = m.get("trace_accuracy", 0.0)
        am = m.get("answer_accuracy", 0.0)
        rows_out.append(f"\\texttt{{{tex_escape(m['model'])}}} & {ta * 100:.1f}\\% & {am * 100:.1f}\\% \\\\")
    body = (
        _tex_header(row)
        + "\\begin{figure}[t]\n"
        + "  \\centering\n"
        + "  \\small\n"
        + "  \\begin{tabular}{lrr}\n"
        + "    \\toprule\n"
        + "    model & trace-align & answer-match \\\\\n"
        + "    \\midrule\n"
        + "\n".join(f"    {r}" for r in rows_out)
        + "\n"
        + "    \\bottomrule\n"
        + "  \\end{tabular}\n"
        + "  \\par\\vspace{0.5em}\n"
        + (
            f"  Kendall's $\\tau$ between rankings: "
            f"$\\mathbf{{{tau:+.3f}}}$. "
            f"Overall false-pass: \\textbf{{{fp * 100:.1f}\\%}}. "
            f"False-fail: \\textbf{{{ff * 100:.1f}\\%}}.\n"
        )
        + f"  \\caption{{{_wrap_caption(row)}}}\n"
        + f"  \\label{{{row.id}}}\n"
        + "\\end{figure}\n"
    )
    return RenderResult(id=row.id, body=body, used_data_source=True)


def render_tab_rq3_failure_drivers(row: FigureRow, root: Path) -> RenderResult:
    path = root / "docs" / "experiments" / "e4.5_numbers.json"
    data = _load_json(path)
    if data is None:
        return _missing_data(row, path)
    pooled = next((f for f in data.get("fits") or [] if f.get("label") == "pooled"), None)
    if pooled is None:
        return _placeholder(row, "e4.5_numbers.json present but no `pooled` fit.")
    importances = sorted(
        pooled.get("importances", []),
        key=lambda i: float(i.get("drop_loglik_loss") or 0.0),
        reverse=True,
    )
    rows_out: list[str] = []
    for imp in importances:
        rows_out.append(
            f"\\texttt{{{tex_escape(imp['name'])}}} & "
            f"${imp.get('coefficient', 0.0):+.3f}$ & "
            f"{imp.get('odds_ratio', 1.0):.3f} & "
            f"${imp.get('drop_loglik_loss', 0.0):+.3f}$ \\\\"
        )
    body = (
        _tex_header(row)
        + "\\begin{table}[t]\n"
        + "  \\centering\n"
        + "  \\small\n"
        + "  \\begin{tabular}{lrrr}\n"
        + "    \\toprule\n"
        + r"    feature & $\beta$ & odds ratio & drop-loglik loss \\"
        + "\n"
        + "    \\midrule\n"
        + "\n".join(f"    {r}" for r in rows_out)
        + "\n"
        + "    \\bottomrule\n"
        + "  \\end{tabular}\n"
        + f"  \\caption{{{_wrap_caption(row)}}}\n"
        + f"  \\label{{{row.id}}}\n"
        + "\\end{table}\n"
    )
    return RenderResult(id=row.id, body=body, used_data_source=True)


def render_tab_substrate(row: FigureRow, root: Path) -> RenderResult:
    path = root / "manifests" / "local.json"
    if not path.is_file():
        return _missing_data(row, path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    servers = raw.get("servers") or []
    by_dyn: dict[str, int] = {"static": 0, "live_read": 0, "stateful_write": 0}
    by_tag: dict[str, int] = {}
    for s in servers:
        dyn = s.get("dynamism", "")
        by_dyn[dyn] = by_dyn.get(dyn, 0) + 1
        for tag in s.get("tags") or []:
            by_tag[tag] = by_tag.get(tag, 0) + 1
    dyn_lines = [
        f"    \\texttt{{{tex_escape(k)}}} & {by_dyn.get(k, 0)} \\\\"
        for k in ("static", "live_read", "stateful_write")
    ]
    top_tags = sorted(by_tag.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
    tag_lines = [f"    \\texttt{{{tex_escape(tag)}}} & {n} \\\\" for tag, n in top_tags]
    body = (
        _tex_header(row)
        + "\\begin{table}[t]\n"
        + "  \\centering\n"
        + "  \\small\n"
        + "  \\textbf{By dynamism class}\\par\\vspace{0.3em}\n"
        + "  \\begin{tabular}{lr}\n"
        + "    \\toprule\n"
        + "    class & count \\\\\n"
        + "    \\midrule\n"
        + "\n".join(dyn_lines)
        + "\n"
        + "    \\bottomrule\n"
        + "  \\end{tabular}\n"
        + "  \\par\\vspace{0.7em}\n"
        + "  \\textbf{Top tags}\\par\\vspace{0.3em}\n"
        + "  \\begin{tabular}{lr}\n"
        + "    \\toprule\n"
        + "    tag & servers \\\\\n"
        + "    \\midrule\n"
        + "\n".join(tag_lines)
        + "\n"
        + "    \\bottomrule\n"
        + "  \\end{tabular}\n"
        + f"  \\caption{{Substrate breakdown: {len(servers)} vetted servers. {_wrap_caption(row)}}}\n"
        + f"  \\label{{{row.id}}}\n"
        + "\\end{table}\n"
    )
    return RenderResult(id=row.id, body=body, used_data_source=True)


def render_fig_perf_by_dynamism_depth(row: FigureRow, root: Path) -> RenderResult:
    spec_path = root / "specs" / "v3.jsonl"
    if not spec_path.is_file():
        return _missing_data(row, spec_path)
    eval_paths = {
        "haiku-3.5": root / "evals" / "v3_haiku35.jsonl",
        "haiku-4.5": root / "evals" / "v3_haiku45.jsonl",
        "qwen3-8b": root / "evals" / "v3_qwen3.jsonl",
    }
    missing = [p for p in eval_paths.values() if not p.is_file()]
    if missing:
        return _placeholder(
            row,
            "v3 eval JSONLs missing on disk (git-ignored): "
            + ", ".join(str(p.relative_to(root)) for p in missing),
        )
    by_task: dict[str, tuple[str, str]] = {}
    with spec_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            tid = str(d.get("task_id"))
            dyn = str(d.get("dynamism", ""))
            depth = int((d.get("complexity") or {}).get("trace_depth", 0))
            bin_ = "1" if depth <= 1 else "2" if depth == 2 else "3-4" if depth <= 4 else "5+"
            by_task[tid] = (dyn, bin_)
    grid: dict[str, dict[tuple[str, str], list[int]]] = {}
    for model, ep in eval_paths.items():
        grid.setdefault(model, {})
        with ep.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                tid = str(d.get("task_id"))
                key = by_task.get(tid)
                if key is None:
                    continue
                grid[model].setdefault(key, []).append(int(bool(d.get("passed"))))
    dyn_order = ["static", "live_read", "stateful_write"]
    bin_order = ["1", "2", "3-4", "5+"]
    header_groups = " & ".join(
        rf"\multicolumn{{{len(bin_order)}}}{{c}}{{{tex_escape(d)}}}" for d in dyn_order
    )
    sub_header = " & ".join(b for b in bin_order * len(dyn_order))
    body_rows: list[str] = []
    for model in sorted(grid.keys()):
        cells = [f"\\texttt{{{tex_escape(model)}}}"]
        for d in dyn_order:
            for b in bin_order:
                vals = grid[model].get((d, b))
                if not vals:
                    cells.append("--")
                else:
                    cells.append(f"{sum(vals) / len(vals) * 100:.0f}\\%")
        body_rows.append(" & ".join(cells) + r" \\")
    cols_spec = "l" + ("r" * len(bin_order)) * len(dyn_order)
    body = (
        _tex_header(row)
        + "\\begin{figure*}[t]\n"
        + "  \\centering\n"
        + "  \\footnotesize\n"
        + f"  \\begin{{tabular}}{{{cols_spec}}}\n"
        + "    \\toprule\n"
        + f"    model & {header_groups} \\\\\n"
        + f"    & {sub_header} \\\\\n"
        + "    \\midrule\n"
        + "\n".join(f"    {r}" for r in body_rows)
        + "\n"
        + "    \\bottomrule\n"
        + "  \\end{tabular}\n"
        + f"  \\caption{{{_wrap_caption(row)}}}\n"
        + f"  \\label{{{row.id}}}\n"
        + "\\end{figure*}\n"
    )
    return RenderResult(id=row.id, body=body, used_data_source=True)


def render_p_alt_degradation(row: FigureRow, root: Path) -> RenderResult:
    return _placeholder(
        row,
        "no docs/experiments/e2.7_numbers.json committed yet -- the P_alt driver "
        "(dmcp curve) is in place but the experiment doc has not been run "
        "end-to-end.",
    )


def render_decay_curve(row: FigureRow, root: Path) -> RenderResult:
    return _placeholder(
        row,
        "no docs/experiments/e1.5_numbers.json committed yet -- the refresh decay "
        "driver is in place but the experiment doc has not been run end-to-end.",
    )


def render_capability_profile(row: FigureRow, root: Path) -> RenderResult:
    path = root / "docs" / "experiments" / "e4.7_numbers.json"
    data = _load_json(path)
    if data is None:
        return _missing_data(row, path)
    models = data.get("models") or []
    rows_out: list[str] = []
    for m in models:
        pr = m.get("pass_rate")
        sr = m.get("sae_rate")
        pk = m.get("pass_k")
        rows_out.append(
            f"\\texttt{{{tex_escape(m['model'])}}} & {m.get('n', 0)} & "
            + (f"{pr * 100:.1f}\\%" if pr is not None else "--")
            + " & "
            + (f"{sr * 100:.1f}\\%" if sr is not None else "--")
            + " & "
            + (f"{pk * 100:.1f}\\%" if pk is not None else "--")
            + r" \\"
        )
    body = (
        _tex_header(row)
        + "\\begin{table}[t]\n"
        + "  \\centering\n"
        + "  \\small\n"
        + "  \\begin{tabular}{lrrrr}\n"
        + "    \\toprule\n"
        + r"    model & $n$ & pass-rate & SAE-rate & pass\textsuperscript{$k$} \\"
        + "\n"
        + "    \\midrule\n"
        + "\n".join(f"    {r}" for r in rows_out)
        + "\n"
        + "    \\bottomrule\n"
        + "  \\end{tabular}\n"
        + f"  \\caption{{{_wrap_caption(row)}}}\n"
        + f"  \\label{{{row.id}}}\n"
        + "\\end{table}\n"
    )
    return RenderResult(id=row.id, body=body, used_data_source=True)


def render_fig_difficulty_curve(row: FigureRow, root: Path) -> RenderResult:
    path = root / "docs" / "experiments" / "e4.10_numbers.json"
    data = _load_json(path)
    if data is None:
        return _missing_data(row, path)
    models = data.get("models") or []
    bin_order = ["1-2 (simple)", "3-4 (medium)", "5+ (hard)"]
    present = [b for b in bin_order if any(any(x.get("bin") == b for x in m.get("bins", [])) for m in models)]
    rows_out: list[str] = []
    for m in models:
        bm = {x["bin"]: x for x in m.get("bins", [])}
        cells = [f"\\texttt{{{tex_escape(m['model'])}}}"]
        for b in present:
            x = bm.get(b)
            pr = x.get("pass_rate") if x else None
            cells.append(f"{pr * 100:.0f}\\%" if pr is not None else "--")
        rows_out.append(" & ".join(cells) + r" \\")
    cols_spec = "l" + "r" * len(present)
    header = "model & " + " & ".join(tex_escape(b) for b in present) + r" \\"
    body = (
        _tex_header(row)
        + "\\begin{figure}[t]\n"
        + "  \\centering\n"
        + "  \\small\n"
        + f"  \\begin{{tabular}}{{{cols_spec}}}\n"
        + "    \\toprule\n"
        + f"    {header}\n"
        + "    \\midrule\n"
        + "\n".join(f"    {r}" for r in rows_out)
        + "\n"
        + "    \\bottomrule\n"
        + "  \\end{tabular}\n"
        + "  \\par\\vspace{0.4em}\n"
        + "  \\footnotesize Pass rate by trace-depth difficulty bin; degradation tracks chain "
        + "length and same-tool density.\n"
        + f"  \\caption{{{_wrap_caption(row)}}}\n"
        + f"  \\label{{{row.id}}}\n"
        + "\\end{figure}\n"
    )
    return RenderResult(id=row.id, body=body, used_data_source=True)


def render_tab_gen_strategy_ablation(row: FigureRow, root: Path) -> RenderResult:
    path = root / "docs" / "experiments" / "e4.9_numbers.json"
    data = _load_json(path)
    if data is None:
        return _missing_data(row, path)
    strategies = data.get("strategies") or []
    rows_out: list[str] = []
    for s in strategies:
        pr, sr, pk = s.get("pass_rate"), s.get("sae_rate"), s.get("pass_k")
        rows_out.append(
            f"\\texttt{{{tex_escape(s['strategy'])}}} & {s.get('n', 0)} & "
            + (f"{pr * 100:.1f}\\%" if pr is not None else "--")
            + " & "
            + (f"{sr * 100:.1f}\\%" if sr is not None else "--")
            + " & "
            + (f"{pk * 100:.1f}\\%" if pk is not None else "--")
            + r" \\"
        )
    body = (
        _tex_header(row)
        + "\\begin{table}[t]\n"
        + "  \\centering\n"
        + "  \\small\n"
        + "  \\begin{tabular}{lrrrr}\n"
        + "    \\toprule\n"
        + r"    generation strategy & $n$ & pass-rate & SAE-rate & pass\textsuperscript{$k$} \\"
        + "\n"
        + "    \\midrule\n"
        + "\n".join(f"    {r}" for r in rows_out)
        + "\n"
        + "    \\bottomrule\n"
        + "  \\end{tabular}\n"
        + f"  \\caption{{{_wrap_caption(row)}}}\n"
        + f"  \\label{{{row.id}}}\n"
        + "\\end{table}\n"
    )
    return RenderResult(id=row.id, body=body, used_data_source=True)


def render_fig_gen_eval_sae_heatmap(row: FigureRow, root: Path) -> RenderResult:
    path = root / "docs" / "experiments" / "e4.9_numbers.json"
    data = _load_json(path)
    if data is None:
        return _missing_data(row, path)
    matrix = data.get("matrix") or []
    if not matrix:
        return _placeholder(row, "e4.9_numbers.json present but `matrix` is empty.")
    strategies = sorted({c["strategy"] for c in matrix})
    conds = data.get("conditions") or sorted({c["condition"] for c in matrix})
    lookup = {(c["strategy"], c["condition"]): c for c in matrix}
    cols_spec = "l" + "r" * len(conds)
    header = (
        "gen \\textbackslash{} eval & " + " & ".join(f"\\texttt{{{tex_escape(c)}}}" for c in conds) + r" \\"
    )
    rows_out: list[str] = []
    for st in strategies:
        cells = [f"\\texttt{{{tex_escape(st)}}}"]
        for c in conds:
            v = lookup.get((st, c))
            sr = v.get("sae_rate") if v else None
            cells.append(f"{sr * 100:.0f}\\%" if sr is not None else "--")
        rows_out.append(" & ".join(cells) + r" \\")
    body = (
        _tex_header(row)
        + "\\begin{figure*}[t]\n"
        + "  \\centering\n"
        + "  \\footnotesize\n"
        + f"  \\begin{{tabular}}{{{cols_spec}}}\n"
        + "    \\toprule\n"
        + f"    {header}\n"
        + "    \\midrule\n"
        + "\n".join(f"    {r}" for r in rows_out)
        + "\n"
        + "    \\bottomrule\n"
        + "  \\end{tabular}\n"
        + "  \\par\\vspace{0.4em}\n"
        + "  \\footnotesize SAE rate (\\%) per generation strategy (rows) "
        + "$\\times$ eval condition (columns).\n"
        + f"  \\caption{{{_wrap_caption(row)}}}\n"
        + f"  \\label{{{row.id}}}\n"
        + "\\end{figure*}\n"
    )
    return RenderResult(id=row.id, body=body, used_data_source=True)


def render_rq4_agreement(row: FigureRow, root: Path) -> RenderResult:
    return _placeholder(
        row,
        "human annotation pass not completed yet -- pre-registered in "
        "docs/experiments/e4.6-rq4-scorer-vs-human.md; harness ready to consume "
        "docs/experiments/e4.6_numbers.json once it lands.",
    )


def render_ablation(row: FigureRow, root: Path) -> RenderResult:
    return _placeholder(
        row,
        "ablation report JSON not committed yet -- the harness landed with E2.8 "
        "(dmcp/ablation.py); ship an experiment doc + numbers JSON to populate.",
    )


def render_pipeline(row: FigureRow, root: Path) -> RenderResult:
    return _placeholder(
        row,
        "manual block diagram -- author from method section. Source-of-truth: docs/CONCEPT.md.",
    )


def render_trace_distill_example(row: FigureRow, root: Path) -> RenderResult:
    return _placeholder(
        row,
        "manual worked example -- pick one v3 trace (preferably cross-server) "
        "and show its TaskSpec side-by-side.",
    )


# Registry of id -> renderer. Ids absent from this map fall through to the
# generic placeholder so missing renderers are obvious in the output.
RENDERERS: dict[str, Renderer] = {
    "tab:rq2_comparison": render_tab_rq2_comparison,
    "fig:rq1_kendall": render_fig_rq1_kendall,
    "tab:rq3_failure_drivers": render_tab_rq3_failure_drivers,
    "tab:substrate": render_tab_substrate,
    "fig:perf_by_dynamism_depth": render_fig_perf_by_dynamism_depth,
    "fig:p_alt_degradation": render_p_alt_degradation,
    "fig:decay_curve": render_decay_curve,
    "tab:capability_profile": render_capability_profile,
    "fig:difficulty_curve": render_fig_difficulty_curve,
    "tab:gen_strategy_ablation": render_tab_gen_strategy_ablation,
    "fig:gen_eval_sae_heatmap": render_fig_gen_eval_sae_heatmap,
    "tab:rq4_agreement": render_rq4_agreement,
    "tab:ablation": render_ablation,
    "fig:pipeline": render_pipeline,
    "fig:trace_distill_example": render_trace_distill_example,
}


# ---------------------------------------------------------------------------
# Top-level regenerate
# ---------------------------------------------------------------------------


def _output_path(row: FigureRow, root: Path) -> Path:
    if row.kind == "fig":
        return root / "paper" / "figures" / f"{row.slug}.tex"
    return root / "paper" / "tables" / f"{row.slug}.tex"


def regenerate(
    *,
    root: Path = REPO_ROOT,
    verbose: bool = False,
) -> RegenerateOutcome:
    """Re-render every row of ``paper/figures.md`` into LaTeX artifacts."""
    rows = parse_figures_index(root / "paper" / "figures.md")
    refs = find_section_inputs(root / "paper" / "sections")
    outcome = RegenerateOutcome(cross_ref_errors=validate_cross_references(rows, refs))
    (root / "paper" / "figures").mkdir(parents=True, exist_ok=True)
    (root / "paper" / "tables").mkdir(parents=True, exist_ok=True)
    for row in rows:
        renderer = RENDERERS.get(row.id)
        result = (
            renderer(row, root)
            if renderer is not None
            else _placeholder(row, "no renderer registered for this id yet.")
        )
        artifact = _output_path(row, root)
        artifact.write_text(result.body, encoding="utf-8")
        if result.pending:
            outcome.pending.append(row.id)
        elif row.status == "manual":
            outcome.manual.append(row.id)
        else:
            outcome.rendered.append(row.id)
        if verbose:
            tag = (
                "rendered"
                if not result.pending and row.status != "manual"
                else "manual"
                if row.status == "manual"
                else "pending"
            )
            print(f"  [{tag:>8}] {row.id} -> {artifact.relative_to(root)}")
    return outcome
