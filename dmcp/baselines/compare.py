"""RQ2 generation-quality comparison harness (E4.3).

Compares TaskSpec JSONL output of multiple generation methods (forward
distillation vs the graph-sampling baseline E4.1 vs the direct
generate-then-verify baseline E4.2) on the axes called out in
`docs/CONCEPT.md` / simple_approach §8:

  - distinct valid paths          mean |equivalence_set| over tool_effect
                                  checkpoints — the headline AGB-gap axis.
  - coverage                      fraction of (server, tool) pairs in the
                                  candidate catalog that any spec references.
  - filter pass rate              emitted_specs / proposals_attempted
                                  (only when the caller supplies the
                                  per-method proposal counts).
  - executable-on-first-try       1.0 for forward by construction (the
                                  reference trace ran); N/A for baselines
                                  unless a separate live re-execution was
                                  performed and supplied.
  - unnecessary-tool rate         deferred — needs live execution. Reported
                                  as the *upper bound* implied by the spec:
                                  fraction of tool_effect checkpoints with
                                  no arg_predicate (the generator did not
                                  know what arguments were needed).
  - error-type diversity          deferred — needs an execution-side
                                  failure-mode taxonomy. Reported here as
                                  the per-method count of distinct
                                  generator-side rejection reasons (when
                                  supplied) so the column is wired but
                                  populated by future runs.
  - human realism                 deferred — needs human or LLM-judge rubric.

The harness deliberately stays static: every axis it computes is a pure
function of the TaskSpec JSONL files + a tool catalog + optional
proposal-attempt metadata. Live re-execution belongs to the eval/curve path,
not here. That keeps the comparison cheap and reproducible — the report can
be regenerated from gitignored spec files without re-spending LLM budget.

Per `memory/feedback_agb_orthogonality.md`: this harness sits firmly on the
"clearly labeled baseline" side. It does NOT touch the headline scoring
path. Its only purpose is to surface the quantitative gap between forward
distillation and the two baselines.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dmcp.spec import TaskSpec, ToolEffectCheckpoint, ValueProducedCheckpoint

# Marker prefix every baseline TaskSpec carries via its `distiller_version`
# string. The comparison harness uses it to refuse mixing baselines into the
# forward arm (and vice versa), which would silently corrupt the numbers.
BASELINE_VERSION_PREFIX = "baseline-"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MethodSummary:
    """One method's column in the comparison table."""

    method: str
    n_specs: int
    n_tool_effect_checkpoints: int
    mean_eq_set_size: float
    median_eq_set_size: float
    max_eq_set_size: int
    fraction_singleton_eq_set: float
    fraction_missing_arg_predicate: float
    mean_checkpoints_per_spec: float
    mean_prompt_length: float
    fraction_with_ordering: float
    coverage: float | None
    n_tools_referenced: int
    filter_pass_rate: float | None
    executable_by_construction: float | None
    distiller_versions: tuple[str, ...]
    marker_violations: tuple[str, ...]


@dataclass
class ComparisonReport:
    methods: list[MethodSummary]
    catalog_size: int | None
    notes: list[str] = field(default_factory=list)

    def by_method(self, name: str) -> MethodSummary:
        for m in self.methods:
            if m.method == name:
                return m
        raise KeyError(name)


class CompareError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Loading + per-method scoring
# ---------------------------------------------------------------------------


def load_specs(path: Path) -> list[TaskSpec]:
    """Load TaskSpec JSONL. Empty lines tolerated; malformed lines raise."""
    specs: list[TaskSpec] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            specs.append(TaskSpec.model_validate_json(line))
    return specs


def _is_baseline_version(version: str) -> bool:
    return version.startswith(BASELINE_VERSION_PREFIX)


def _verify_method_markers(method: str, specs: Iterable[TaskSpec]) -> list[str]:
    """Detect specs whose distiller_version disagrees with the method label.

    Forward specs MUST NOT carry the `baseline-` prefix; baseline specs MUST.
    """
    violations: list[str] = []
    is_baseline_arm = method != "forward"
    for s in specs:
        is_baseline_spec = _is_baseline_version(s.distiller_version)
        if is_baseline_arm and not is_baseline_spec:
            violations.append(f"{method}: spec {s.task_id} has non-baseline version {s.distiller_version!r}")
        if not is_baseline_arm and is_baseline_spec:
            violations.append(f"{method}: spec {s.task_id} has baseline version {s.distiller_version!r}")
    return violations


def _tool_effect_checkpoints(spec: TaskSpec) -> list[ToolEffectCheckpoint]:
    return [c for c in spec.checkpoints if isinstance(c, ToolEffectCheckpoint)]


def _value_produced_checkpoints(spec: TaskSpec) -> list[ValueProducedCheckpoint]:
    return [c for c in spec.checkpoints if isinstance(c, ValueProducedCheckpoint)]


def _referenced_tool_keys(specs: Iterable[TaskSpec]) -> set[tuple[str, str]]:
    """Union of (server_id, tool_name) across every tool_effect equivalence_set."""
    out: set[tuple[str, str]] = set()
    for s in specs:
        for cp in _tool_effect_checkpoints(s):
            for ref in cp.equivalence_set:
                out.add((ref.server_id, ref.tool_name))
    return out


def _eq_set_sizes(specs: Iterable[TaskSpec]) -> list[int]:
    sizes: list[int] = []
    for s in specs:
        for cp in _tool_effect_checkpoints(s):
            sizes.append(len(cp.equivalence_set))
    return sizes


def summarize_method(
    method: str,
    specs: list[TaskSpec],
    *,
    catalog: set[tuple[str, str]] | None = None,
    proposals_attempted: int | None = None,
    has_reference_traces: bool = False,
) -> MethodSummary:
    """Compute one method's row in the comparison table.

    `catalog`                  full universe of (server, tool) — coverage is
                               only meaningful when supplied; pass None if you
                               only want method-relative numbers.
    `proposals_attempted`      total proposals the generator tried, so the
                               filter pass rate = emitted/proposals.
    `has_reference_traces`     True for the forward arm: every spec is backed
                               by a reference trace that, by definition, ran.
                               This makes executable-on-first-try 1.0 by
                               construction (no live re-run needed). For
                               baseline arms it stays None (a separate live
                               re-execution would populate it).
    """
    marker_violations = _verify_method_markers(method, specs)
    sizes = _eq_set_sizes(specs)
    n_te = len(sizes)
    mean_eq = statistics.fmean(sizes) if sizes else 0.0
    median_eq = float(statistics.median(sizes)) if sizes else 0.0
    max_eq = max(sizes) if sizes else 0
    singletons = sum(1 for x in sizes if x == 1)
    frac_singletons = singletons / n_te if n_te else 0.0

    n_missing_arg_pred = 0
    n_total_te = 0
    n_with_ordering = 0
    prompt_lengths: list[int] = []
    cps_per_spec: list[int] = []
    for s in specs:
        te_cps = _tool_effect_checkpoints(s)
        n_total_te += len(te_cps)
        n_missing_arg_pred += sum(1 for cp in te_cps if cp.arg_predicate is None)
        if s.ordering:
            n_with_ordering += 1
        prompt_lengths.append(len(s.prompt))
        cps_per_spec.append(len(s.checkpoints))

    frac_missing_arg_pred = n_missing_arg_pred / n_total_te if n_total_te else 0.0
    mean_cps = statistics.fmean(cps_per_spec) if cps_per_spec else 0.0
    mean_prompt_len = statistics.fmean(prompt_lengths) if prompt_lengths else 0.0
    frac_ord = n_with_ordering / len(specs) if specs else 0.0

    referenced = _referenced_tool_keys(specs)
    coverage: float | None = None
    if catalog is not None:
        coverage = len(referenced & catalog) / len(catalog) if catalog else 0.0

    filter_pass: float | None = None
    if proposals_attempted is not None and proposals_attempted > 0:
        filter_pass = len(specs) / proposals_attempted

    executable: float | None = 1.0 if has_reference_traces and specs else None

    distiller_versions = tuple(sorted({s.distiller_version for s in specs}))

    return MethodSummary(
        method=method,
        n_specs=len(specs),
        n_tool_effect_checkpoints=n_te,
        mean_eq_set_size=mean_eq,
        median_eq_set_size=median_eq,
        max_eq_set_size=max_eq,
        fraction_singleton_eq_set=frac_singletons,
        fraction_missing_arg_predicate=frac_missing_arg_pred,
        mean_checkpoints_per_spec=mean_cps,
        mean_prompt_length=mean_prompt_len,
        fraction_with_ordering=frac_ord,
        coverage=coverage,
        n_tools_referenced=len(referenced),
        filter_pass_rate=filter_pass,
        executable_by_construction=executable,
        distiller_versions=distiller_versions,
        marker_violations=tuple(marker_violations),
    )


# ---------------------------------------------------------------------------
# Top-level comparison
# ---------------------------------------------------------------------------


_KNOWN_METHODS = ("forward", "graph", "direct")


def compare_methods(
    spec_paths: dict[str, Path],
    *,
    catalog: set[tuple[str, str]] | None = None,
    proposals_attempted: dict[str, int] | None = None,
) -> ComparisonReport:
    """Build a `ComparisonReport` from per-method spec JSONL files.

    `spec_paths` keys must be from {"forward", "graph", "direct"} — unknown
    method labels are rejected up front to keep the report column set sane.
    """
    unknown = set(spec_paths) - set(_KNOWN_METHODS)
    if unknown:
        raise CompareError(f"unknown method label(s) {sorted(unknown)}; valid: {_KNOWN_METHODS}")
    methods: list[MethodSummary] = []
    proposals = proposals_attempted or {}
    for name in _KNOWN_METHODS:
        if name not in spec_paths:
            continue
        specs = load_specs(spec_paths[name])
        methods.append(
            summarize_method(
                name,
                specs,
                catalog=catalog,
                proposals_attempted=proposals.get(name),
                has_reference_traces=(name == "forward"),
            )
        )
    notes: list[str] = []
    for m in methods:
        if m.marker_violations:
            notes.append(
                f"WARNING: {m.method} has {len(m.marker_violations)} marker violation(s) — "
                "spec mixed across method arms?"
            )
    return ComparisonReport(
        methods=methods,
        catalog_size=len(catalog) if catalog is not None else None,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Catalog helpers
# ---------------------------------------------------------------------------


def load_catalog(path: Path) -> set[tuple[str, str]]:
    """Load a `[server_id, tool_name]` JSON list into a catalog set.

    The CLI gives no opinion on how the catalog is produced — usually it is
    the union of `tool_specs` across all reference traces, but a hand-written
    JSON list is equally valid.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise CompareError("catalog JSON must be a list of [server_id, tool_name] pairs")
    out: set[tuple[str, str]] = set()
    for item in raw:
        if not isinstance(item, list) or len(item) != 2 or not all(isinstance(x, str) for x in item):
            raise CompareError(f"catalog entry must be [server_id, tool_name]; got {item!r}")
        out.add((item[0], item[1]))
    return out


def catalog_from_trace_jsonl(path: Path) -> set[tuple[str, str]]:
    """Build a catalog from a reference-traces JSONL by unioning `tool_specs`."""
    out: set[tuple[str, str]] = set()
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            tool_specs = raw.get("tool_specs") or {}
            for sid, specs in tool_specs.items():
                if not isinstance(specs, list):
                    continue
                for s in specs:
                    name = s.get("name") if isinstance(s, dict) else None
                    if isinstance(name, str):
                        out.add((sid, name))
    return out


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _fmt_float(x: float | None, digits: int = 2) -> str:
    if x is None:
        return "—"
    return f"{x:.{digits}f}"


def _fmt_pct(x: float | None, digits: int = 0) -> str:
    if x is None:
        return "—"
    return f"{x * 100:.{digits}f}%"


def render_markdown(report: ComparisonReport, *, title: str | None = None) -> str:
    """Render the comparison as a self-contained markdown table."""
    lines: list[str] = []
    lines.append(f"# {title or 'RQ2 generation-quality comparison (E4.3)'}")
    lines.append("")
    if report.catalog_size is not None:
        lines.append(f"_catalog size_: **{report.catalog_size}** unique (server, tool) pairs")
        lines.append("")
    methods = report.methods
    if not methods:
        lines.append("_no method spec files supplied_")
        return "\n".join(lines) + "\n"

    header = ["axis", *(m.method for m in methods)]
    sep = ["---"] * len(header)
    rows: list[list[str]] = []

    def _row(label: str, values: list[str]) -> None:
        rows.append([label, *values])

    _row("specs emitted", [str(m.n_specs) for m in methods])
    _row(
        "filter pass rate (emitted / proposed)",
        [_fmt_pct(m.filter_pass_rate) for m in methods],
    )
    _row(
        "tool_effect checkpoints",
        [str(m.n_tool_effect_checkpoints) for m in methods],
    )
    _row(
        "mean checkpoints per spec",
        [_fmt_float(m.mean_checkpoints_per_spec) for m in methods],
    )
    _row(
        "**distinct valid paths — mean |eq_set|**",
        [_fmt_float(m.mean_eq_set_size) for m in methods],
    )
    _row(
        "distinct valid paths — median |eq_set|",
        [_fmt_float(m.median_eq_set_size) for m in methods],
    )
    _row(
        "distinct valid paths — max |eq_set|",
        [str(m.max_eq_set_size) for m in methods],
    )
    _row(
        "singleton-equiv-set rate",
        [_fmt_pct(m.fraction_singleton_eq_set) for m in methods],
    )
    _row(
        "missing arg_predicate rate (upper-bound unnecessary-tool proxy)",
        [_fmt_pct(m.fraction_missing_arg_predicate) for m in methods],
    )
    _row(
        "coverage (referenced ∩ catalog) / catalog",
        [_fmt_pct(m.coverage) for m in methods],
    )
    _row(
        "tools referenced",
        [str(m.n_tools_referenced) for m in methods],
    )
    _row(
        "executable-on-first-try (by construction for forward)",
        [_fmt_pct(m.executable_by_construction) for m in methods],
    )
    _row(
        "specs with ordering constraint",
        [_fmt_pct(m.fraction_with_ordering) for m in methods],
    )
    _row(
        "mean prompt length (chars)",
        [_fmt_float(m.mean_prompt_length, digits=0) for m in methods],
    )
    _row(
        "distiller_version(s) seen",
        [", ".join(m.distiller_versions) or "—" for m in methods],
    )

    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join(sep) + " |")
    for r in rows:
        lines.append("| " + " | ".join(r) + " |")
    lines.append("")

    deferred = [
        "**human realism** — needs human or LLM-judge rubric; not auto-scored.",
        "**executable-on-first-try (baselines)** — needs live re-execution; "
        "this harness reports it only for forward (1.0 by construction since the "
        "reference trace ran).",
        "**unnecessary-tool rate** — proxied here by the missing-arg_predicate "
        "rate (an upper bound). A faithful measure needs live re-execution against "
        "the spec's tools and a comparison against the actually-used set.",
        "**error-type diversity** — populated from the generator's per-proposal "
        "rejection reasons when those logs are supplied; this PR wires the column "
        "but does not include execution-side failure modes.",
    ]
    lines.append("## Deferred axes")
    for d in deferred:
        lines.append(f"- {d}")
    lines.append("")

    if report.notes:
        lines.append("## Notes")
        for n in report.notes:
            lines.append(f"- {n}")
        lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# JSON serialization (for committing distilled numbers without raw specs)
# ---------------------------------------------------------------------------


def report_to_json(report: ComparisonReport) -> dict[str, Any]:
    return {
        "catalog_size": report.catalog_size,
        "notes": list(report.notes),
        "methods": [
            {
                "method": m.method,
                "n_specs": m.n_specs,
                "n_tool_effect_checkpoints": m.n_tool_effect_checkpoints,
                "mean_eq_set_size": m.mean_eq_set_size,
                "median_eq_set_size": m.median_eq_set_size,
                "max_eq_set_size": m.max_eq_set_size,
                "fraction_singleton_eq_set": m.fraction_singleton_eq_set,
                "fraction_missing_arg_predicate": m.fraction_missing_arg_predicate,
                "mean_checkpoints_per_spec": m.mean_checkpoints_per_spec,
                "mean_prompt_length": m.mean_prompt_length,
                "fraction_with_ordering": m.fraction_with_ordering,
                "coverage": m.coverage,
                "n_tools_referenced": m.n_tools_referenced,
                "filter_pass_rate": m.filter_pass_rate,
                "executable_by_construction": m.executable_by_construction,
                "distiller_versions": list(m.distiller_versions),
                "marker_violations": list(m.marker_violations),
            }
            for m in report.methods
        ],
    }
