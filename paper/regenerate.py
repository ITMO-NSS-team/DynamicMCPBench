"""Paper figure / table regenerator (E5.2).

Reads `paper/figures.md` as the source-of-truth index, dispatches each
row to a per-id renderer, and writes one markdown artifact under
`paper/figures/<id>.md`. Idempotent: re-running with the same inputs
produces byte-identical outputs.

Renderers consume **already-committed** data (`docs/experiments/<id>_numbers.json`,
`manifests/*.json`, …) so the regenerator can run in CI, in a fresh
clone, or in a minimal env without LLM calls. Rows whose backing data
isn't on disk yet emit a clearly-marked "pending" placeholder that
points at the gating plan step.

A cross-reference validator confirms every `[Fig … here — …]` /
`[Tbl … here — …]` placeholder in `paper/draft.md` resolves to exactly
one row in `paper/figures.md`. This is the contract that keeps the
paper draft from referencing non-existent artifacts.

Per CLAUDE.md the regenerator stays dep-free (no matplotlib / pandas /
scipy) — every artifact is markdown so the paper round-trips with the
rest of `docs/`. PNG / PDF rendering is a future step when we commit to
a venue's LaTeX template.
"""

from __future__ import annotations

import json
import re
import textwrap
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
PAPER_DIR = REPO_ROOT / "paper"
FIGURES_INDEX = PAPER_DIR / "figures.md"
DRAFT = PAPER_DIR / "draft.md"
OUT_DIR = PAPER_DIR / "figures"

VALID_STATUSES = {"ready", "partial", "pending", "manual"}

# Match `[Fig <n> here — …]` and `[Tbl <n> here — …]` markers in the draft.
_DRAFT_MARKER_RE = re.compile(
    r"\[(?:Fig|Tbl)\s+\d+\s*here\s*—\s*[^\]]*figures\.md::([A-Za-z0-9_:\-]+)[^\]]*\]"
)


# ---------------------------------------------------------------------------
# figures.md parsing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FigureRow:
    """One row of paper/figures.md (figures or tables)."""

    id: str  # e.g. "fig:rq1_kendall" or "tab:rq2_comparison"
    kind: str  # "fig" | "tab" (derived from id prefix)
    caption: str
    status: str
    gating_step: str
    data_source: str
    section: str  # "Figures" | "Tables" — which subtable in figures.md the row was in


class IndexError_(ValueError):
    """Raised by the parser when figures.md violates its contract."""


def _table_row(line: str) -> list[str] | None:
    """Parse one markdown-table row into its trimmed cells, or None if not a row."""
    s = line.strip()
    if not s.startswith("|") or not s.endswith("|"):
        return None
    cells = [c.strip() for c in s.strip("|").split("|")]
    return cells


def _is_separator(cells: list[str]) -> bool:
    return all(re.fullmatch(r":?-{3,}:?", c) for c in cells)


def parse_figures_index(path: Path = FIGURES_INDEX) -> list[FigureRow]:
    """Parse `paper/figures.md` into a list of `FigureRow`s.

    The file has two markdown tables (Figures, Tables); we walk it
    section-by-section so rows are attributed to the right section even if
    a future hand-edit reorders things.
    """
    text = path.read_text(encoding="utf-8")
    rows: list[FigureRow] = []
    section: str | None = None
    table_state: int = 0  # 0=outside, 1=saw header, 2=inside body
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


def find_draft_references(path: Path = DRAFT) -> list[str]:
    """Return the ids referenced by `[Fig … here]` / `[Tbl … here]` markers."""
    text = path.read_text(encoding="utf-8")
    return _DRAFT_MARKER_RE.findall(text)


def validate_cross_references(rows: list[FigureRow], references: list[str]) -> list[str]:
    """Return a list of cross-reference violations (empty list = OK)."""
    by_id = {r.id for r in rows}
    errors: list[str] = []
    for ref in references:
        if ref not in by_id:
            errors.append(f"draft references {ref!r} but no figures.md row has that id")
    return errors


# ---------------------------------------------------------------------------
# Renderer infrastructure
# ---------------------------------------------------------------------------


@dataclass
class RenderResult:
    """Output of one renderer call."""

    id: str
    body: str
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


def _wrap_header(row: FigureRow) -> str:
    return textwrap.dedent(
        f"""\
        <!-- AUTO-GENERATED by paper/regenerate.py — do not hand-edit.
             id:      {row.id}
             status:  {row.status}
             caption: {row.caption}
        -->
        # {row.id}

        _{row.caption}_

        """
    )


def _placeholder(row: FigureRow, reason: str) -> RenderResult:
    body = _wrap_header(row) + textwrap.dedent(
        f"""\
        > **status: {row.status} — placeholder.** {reason}

        - **Gating step:** {row.gating_step or "—"}
        - **Data source:** {row.data_source}

        Re-run `dmcp paper-figures` once the gating step lands its data
        under the data-source path above; the renderer will replace this
        placeholder with the real artifact.
        """
    )
    return RenderResult(
        id=row.id,
        body=body,
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
        f"data source `{rel}` not on disk yet — the gating step listed above has not produced it.",
    )


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Concrete renderers
# ---------------------------------------------------------------------------


def _ascii_bar(value: float, *, width: int = 30, vmin: float = 0.0, vmax: float = 1.0) -> str:
    span = vmax - vmin
    if span <= 0:
        return ""
    frac = (value - vmin) / span
    frac = max(0.0, min(1.0, frac))
    filled = round(frac * width)
    return "█" * filled + "·" * (width - filled)


def render_tab_rq2_comparison(row: FigureRow, root: Path) -> RenderResult:
    path = root / "docs" / "experiments" / "e4.3_numbers.json"
    data = _load_json(path)
    if data is None:
        return _missing_data(row, path)
    cols = [
        "method",
        "n_specs",
        "mean_eq_set_size",
        "fraction_singleton_eq_set",
        "fraction_missing_arg_predicate",
        "coverage",
        "filter_pass_rate",
    ]
    pretty = {
        "method": "method",
        "n_specs": "n",
        "mean_eq_set_size": "mean &#124;eq_set&#124;",
        "fraction_singleton_eq_set": "singleton rate",
        "fraction_missing_arg_predicate": "missing arg_pred rate",
        "coverage": "coverage",
        "filter_pass_rate": "filter pass",
    }
    methods = data.get("methods") or []
    lines = [_wrap_header(row).rstrip(), ""]
    lines.append(f"_catalog_: {data.get('catalog_size', '—')} unique (server, tool) pairs")
    lines.append("")
    lines.append("| " + " | ".join(pretty[c] for c in cols) + " |")
    lines.append("| " + " | ".join("---" for _ in cols) + " |")
    for m in methods:
        cells = []
        for c in cols:
            v = m.get(c)
            if v is None:
                cells.append("—")
            elif isinstance(v, float):
                if c.startswith("fraction_") or c == "filter_pass_rate" or c == "coverage":
                    cells.append(f"{v * 100:.1f}%")
                else:
                    cells.append(f"{v:.3f}")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    lines.append(
        "_source_: `docs/experiments/e4.3_numbers.json` "
        "(see `docs/experiments/e4.3-rq2-comparison.md` for the decision rule)."
    )
    return RenderResult(id=row.id, body="\n".join(lines) + "\n", used_data_source=True)


def render_fig_rq1_kendall(row: FigureRow, root: Path) -> RenderResult:
    path = root / "docs" / "experiments" / "e4.4_numbers.json"
    data = _load_json(path)
    if data is None:
        return _missing_data(row, path)
    models = sorted(data.get("models") or [], key=lambda m: m.get("trace_accuracy", 0.0), reverse=True)
    lines = [_wrap_header(row).rstrip(), ""]
    lines.append(
        f"Kendall's τ between trace-align and answer-match rankings: "
        f"**{data.get('kendall_tau_rankings', 0.0):+.3f}**"
    )
    lines.append("")
    lines.append("| model | trace-align | answer-match |")
    lines.append("| --- | --- | --- |")
    for m in models:
        ta = m.get("trace_accuracy", 0.0)
        am = m.get("answer_accuracy", 0.0)
        lines.append(
            f"| `{m['model']}` | {ta * 100:5.1f}% `{_ascii_bar(ta)}` | {am * 100:5.1f}% `{_ascii_bar(am)}` |"
        )
    lines.append("")
    lines.append(
        f"Overall false-pass rate (answer ✓, trace ✗): "
        f"**{data.get('overall_false_pass_rate', 0.0) * 100:.1f}%** ・ "
        f"overall false-fail rate (trace ✓, answer ✗): "
        f"**{data.get('overall_false_fail_rate', 0.0) * 100:.1f}%**"
    )
    lines.append("")
    lines.append(
        "_source_: `docs/experiments/e4.4_numbers.json` "
        "(see `docs/experiments/e4.4-rq1-comparison.md` for the decision rule)."
    )
    return RenderResult(id=row.id, body="\n".join(lines) + "\n", used_data_source=True)


def render_tab_rq3_failure_drivers(row: FigureRow, root: Path) -> RenderResult:
    path = root / "docs" / "experiments" / "e4.5_numbers.json"
    data = _load_json(path)
    if data is None:
        return _missing_data(row, path)
    pooled = next((f for f in data.get("fits") or [] if f.get("label") == "pooled"), None)
    if pooled is None:
        return _placeholder(
            row,
            "`docs/experiments/e4.5_numbers.json` is present but has no `pooled` fit.",
        )
    lines = [_wrap_header(row).rstrip(), ""]
    lines.append(
        f"_pooled fit_: n = {pooled.get('n_samples')} ・ "
        f"pass rate {pooled.get('pass_rate', 0.0) * 100:.1f}% ・ "
        f"ridge λ {data.get('ridge'):.0e} ・ "
        f"loglik {pooled.get('loglik', 0.0):.3f}"
    )
    lines.append("")
    lines.append("| feature | β | odds ratio | drop-loglik loss |")
    lines.append("| --- | --- | --- | --- |")
    importances = sorted(
        pooled.get("importances", []),
        key=lambda i: float(i.get("drop_loglik_loss") or 0.0),
        reverse=True,
    )
    for imp in importances:
        coef = imp.get("coefficient", 0.0)
        odds = imp.get("odds_ratio", 1.0)
        loss = imp.get("drop_loglik_loss", 0.0)
        lines.append(f"| `{imp['name']}` | {coef:+.3f} | {odds:.3f} | {loss:+.3f} |")
    lines.append("")
    lines.append(
        "_source_: `docs/experiments/e4.5_numbers.json` "
        "(see `docs/experiments/e4.5-rq3-failure-model.md` for the decision rule)."
    )
    return RenderResult(id=row.id, body="\n".join(lines) + "\n", used_data_source=True)


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
    lines = [_wrap_header(row).rstrip(), ""]
    lines.append(f"_local manifest_: **{len(servers)}** vetted servers")
    lines.append("")
    lines.append("### By dynamism class")
    lines.append("")
    lines.append("| class | count |")
    lines.append("| --- | --- |")
    for k in ("static", "live_read", "stateful_write"):
        lines.append(f"| `{k}` | {by_dyn.get(k, 0)} |")
    lines.append("")
    lines.append("### Top tags (domain hint)")
    lines.append("")
    top = sorted(by_tag.items(), key=lambda kv: (-kv[1], kv[0]))[:15]
    lines.append("| tag | servers |")
    lines.append("| --- | --- |")
    for tag, n in top:
        lines.append(f"| `{tag}` | {n} |")
    lines.append("")
    lines.append("### Per-server breakdown")
    lines.append("")
    lines.append("| server_id | dynamism | sandbox | tags |")
    lines.append("| --- | --- | --- | --- |")
    for s in sorted(servers, key=lambda x: x.get("server_id", "")):
        sandbox = "✓" if s.get("sandbox") else "—"
        tags = ", ".join(s.get("tags") or [])
        lines.append(f"| `{s.get('server_id', '')}` | {s.get('dynamism', '')} | {sandbox} | {tags} |")
    lines.append("")
    lines.append(
        "_source_: `manifests/local.json`. The paper-target substrate is "
        "≥ 100 vetted servers (E3.1); this table is regenerated against the "
        "manifest then-current."
    )
    return RenderResult(id=row.id, body="\n".join(lines) + "\n", used_data_source=True)


def render_fig_perf_by_dynamism_depth(row: FigureRow, root: Path) -> RenderResult:
    """Partial render: pulls v3 evals + specs from disk if available; otherwise
    emits a placeholder linking to the full-scale leaderboard (E4.7)."""
    spec_path = root / "specs" / "v3.jsonl"
    if not spec_path.is_file():
        return _missing_data(row, spec_path)
    eval_paths = {
        "anthropic/claude-haiku-3.5": root / "evals" / "v3_haiku35.jsonl",
        "anthropic/claude-haiku-4.5": root / "evals" / "v3_haiku45.jsonl",
        "qwen/qwen3-8b": root / "evals" / "v3_qwen3.jsonl",
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
    lines = [_wrap_header(row).rstrip(), ""]
    lines.append("**Pass rate by (dynamism, complexity bin) — v3 substrate (56 specs × 3 models).**")
    lines.append("")
    dyn_order = ["static", "live_read", "stateful_write"]
    bin_order = ["1", "2", "3-4", "5+"]
    lines.append("| model | " + " | ".join(f"{d}/{b}" for d in dyn_order for b in bin_order) + " |")
    lines.append("| " + " | ".join("---" for _ in range(1 + len(dyn_order) * len(bin_order))) + " |")
    for model in sorted(grid.keys()):
        cells = [f"`{model}`"]
        for d in dyn_order:
            for b in bin_order:
                vals = grid[model].get((d, b))
                if not vals:
                    cells.append("—")
                else:
                    cells.append(f"{sum(vals) / len(vals) * 100:.0f}% (n={len(vals)})")
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    lines.append(
        "_source_: `specs/v3.jsonl` × `evals/v3_*.jsonl` (git-ignored). "
        "Full ≥ 5-model leaderboard arrives via E4.7."
    )
    return RenderResult(id=row.id, body="\n".join(lines) + "\n", used_data_source=True)


def render_p_alt_degradation(row: FigureRow, root: Path) -> RenderResult:
    return _placeholder(
        row,
        "no `docs/experiments/e2.7_numbers.json` committed yet — the P_alt driver "
        "(`dmcp curve`) is in place but the experiment doc has not been run end-to-end.",
    )


def render_decay_curve(row: FigureRow, root: Path) -> RenderResult:
    return _placeholder(
        row,
        "no `docs/experiments/e1.5_numbers.json` committed yet — the refresh decay "
        "driver is in place but the experiment doc has not been run end-to-end.",
    )


def render_capability_profile(row: FigureRow, root: Path) -> RenderResult:
    return _placeholder(
        row,
        "≥ 5-model leaderboard not produced yet — depends on E4.7 + the larger substrate from E3.1.",
    )


def render_rq4_agreement(row: FigureRow, root: Path) -> RenderResult:
    return _placeholder(
        row,
        "human annotation pass not completed yet — pre-registered in "
        "`docs/experiments/e4.6-rq4-scorer-vs-human.md`; harness ready to "
        "consume `docs/experiments/e4.6_numbers.json` once it lands.",
    )


def render_ablation(row: FigureRow, root: Path) -> RenderResult:
    return _placeholder(
        row,
        "ablation report JSON not committed yet — the harness landed with E2.8 "
        "(`dmcp/ablation.py`); ship an experiment doc + numbers JSON to populate.",
    )


def render_pipeline(row: FigureRow, root: Path) -> RenderResult:
    return _placeholder(
        row,
        "manual block diagram — author from §3.1–§3.4 of `paper/draft.md`. "
        "Source-of-truth: `docs/CONCEPT.md`.",
    )


def render_trace_distill_example(row: FigureRow, root: Path) -> RenderResult:
    return _placeholder(
        row,
        "manual worked example — pick one v3 trace (preferably cross-server) and "
        "show its TaskSpec side-by-side. Source-of-truth: one row of "
        "`traces/v3.jsonl` + the matching row of `specs/v3.jsonl`.",
    )


# Registry of id → renderer. Ids absent from this map fall through to the
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
    "tab:rq4_agreement": render_rq4_agreement,
    "tab:ablation": render_ablation,
    "fig:pipeline": render_pipeline,
    "fig:trace_distill_example": render_trace_distill_example,
}


# ---------------------------------------------------------------------------
# Top-level regenerate
# ---------------------------------------------------------------------------


def regenerate(
    *,
    root: Path = REPO_ROOT,
    out_dir: Path = OUT_DIR,
    verbose: bool = False,
) -> RegenerateOutcome:
    """Re-render every row of `paper/figures.md` into `paper/figures/<id>.md`."""
    rows = parse_figures_index(root / "paper" / "figures.md")
    refs = find_draft_references(root / "paper" / "draft.md")
    outcome = RegenerateOutcome(cross_ref_errors=validate_cross_references(rows, refs))
    out_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        renderer = RENDERERS.get(row.id)
        if renderer is None:
            result = _placeholder(row, "no renderer registered for this id yet.")
        else:
            result = renderer(row, root)
        # Filename: replace ':' with '__' so the path is portable.
        slug = row.id.replace(":", "__")
        artifact = out_dir / f"{slug}.md"
        artifact.write_text(result.body, encoding="utf-8")
        if result.pending:
            outcome.pending.append(row.id)
        elif row.status == "manual":
            outcome.manual.append(row.id)
        else:
            outcome.rendered.append(row.id)
        if verbose:
            status = (
                "rendered"
                if not result.pending and row.status != "manual"
                else "manual"
                if row.status == "manual"
                else "pending"
            )
            print(f"  [{status:>8}] {row.id} → {artifact.relative_to(root)}")
    return outcome
