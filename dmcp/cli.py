"""DynamicMCPBench CLI.

v0 ships only `dmcp record`, which connects to one MCP server, calls
tools/list, optionally invokes a single tool, and writes the resulting Trace
as JSONL. It exists so we can validate the trace schema end-to-end against a
real server before building the explorer, distiller, and evaluator on top.

Future commands (per the rev. 3 plan):
    dmcp crawl     # vet live MCP servers from the registry
    dmcp explore   # goal-seeded forward exploration → traces
    dmcp distill   # traces → task specs
    dmcp eval      # score a candidate agent against a task spec
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated, Any

import typer

from dmcp.ablation import compare_strategies, power_n
from dmcp.baselines.compare import (
    catalog_from_trace_jsonl,
    compare_methods,
    load_catalog,
)
from dmcp.baselines.compare import (
    render_markdown as render_compare_markdown,
)
from dmcp.baselines.compare import (
    report_to_json as compare_report_to_json,
)
from dmcp.baselines.direct_generation import GenerationError
from dmcp.baselines.direct_generation import generate_direct as run_direct_gen
from dmcp.baselines.failure_model import (
    fit_per_model_and_pooled,
    load_features_by_task,
    load_samples_for_model,
)
from dmcp.baselines.failure_model import (
    render_markdown as render_rq3_markdown,
)
from dmcp.baselines.failure_model import (
    report_to_json as rq3_report_to_json,
)
from dmcp.baselines.graph_sampling import (
    VALID_MOTIFS,
    ToolGraph,
    sample_subgraph,
)
from dmcp.baselines.graph_sampling import (
    back_instruct as run_back_instruct,
)
from dmcp.baselines.rq1_compare import (
    DEFAULT_THRESHOLD as RQ1_DEFAULT_THRESHOLD,
)
from dmcp.baselines.rq1_compare import (
    aggregate_rq1,
    build_decisions,
    load_candidate_final_messages,
    load_evals,
    load_reference_final_messages_by_trace_id,
    load_spec_to_reference_trace,
)
from dmcp.baselines.rq1_compare import (
    render_markdown as render_rq1_markdown,
)
from dmcp.baselines.rq1_compare import (
    report_to_json as rq1_report_to_json,
)
from dmcp.baselines.rq4_agreement import (
    build_report as build_rq4_agreement_report,
)
from dmcp.baselines.rq4_agreement import (
    load_evals as load_evals_for_rq4,
)
from dmcp.baselines.rq4_agreement import (
    render_markdown as render_rq4_markdown,
)
from dmcp.baselines.rq4_agreement import (
    report_to_json as rq4_report_to_json,
)
from dmcp.baselines.rq4_agreement import (
    write_consensus,
)
from dmcp.baselines.rq4_subset import (
    DEFAULT_SUBSET_N,
    build_subset,
    compute_consensus,
    load_annotations,
    write_annotation_template,
    write_subset_jsonl,
)
from dmcp.curves import aggregate_curve, complexity_bin
from dmcp.discovery import MCPRegistryClient
from dmcp.distiller import DistillationError
from dmcp.distiller import distill as run_distill
from dmcp.evaluator import evaluate as run_eval
from dmcp.explorer import explore as run_exploration
from dmcp.explorer import stash_exploration_in_trace
from dmcp.goal_gen import _fetch_tool_specs
from dmcp.goal_gen import generate_goals as run_goal_gen
from dmcp.goals import Goals
from dmcp.install import InstallStatus, install_server
from dmcp.judge import upgrade_with_judge
from dmcp.llm import DEFAULT_MODEL, OpenRouterClient
from dmcp.manifest import Manifest, ServerEntry
from dmcp.normalize import apply_normalization
from dmcp.pools import build_eval_pool, build_strategy_pool, pool_to_tool_surface
from dmcp.recorder import (
    SseServer,
    StdioServer,
    StreamableHttpServer,
    TraceRecorder,
)
from dmcp.refresh import decay_summary, refresh_one
from dmcp.replay import TraceReplayRecorder
from dmcp.report import aggregate_markdown
from dmcp.sampling import ToolCatalog
from dmcp.spec import TaskSpec
from dmcp.trace import Trace, TransportKind
from dmcp.verify import verify_server
from dmcp.vet import VetStatus, vet_one, vet_result_summary

app = typer.Typer(
    name="dmcp",
    help="DynamicMCPBench: trace-grounded benchmark generation from live MCP servers.",
    no_args_is_help=True,
)


def _build_config(
    server_id: str,
    transport: TransportKind,
    endpoint: str,
    headers: dict[str, str] | None,
    stdio_args: list[str] | None,
):
    if transport is TransportKind.stdio:
        command, *args = [endpoint, *(stdio_args or [])]
        return StdioServer(server_id=server_id, command=command, args=args)
    if transport is TransportKind.sse:
        return SseServer(server_id=server_id, url=endpoint, headers=headers)
    if transport is TransportKind.streamable_http:
        return StreamableHttpServer(server_id=server_id, url=endpoint, headers=headers)
    raise typer.BadParameter(f"unsupported transport: {transport}")


@app.command()
def record(
    endpoint: Annotated[str, typer.Argument(help="URL (for sse/http) or executable (for stdio)")],
    transport: Annotated[
        TransportKind, typer.Option("--transport", "-t", help="MCP transport")
    ] = TransportKind.streamable_http,
    server_id: Annotated[str, typer.Option("--server-id", "-s")] = "server",
    tool: Annotated[
        str | None,
        typer.Option("--tool", help="Optional tool name to invoke after listing tools"),
    ] = None,
    arguments_json: Annotated[str, typer.Option("--args", help="JSON object of tool arguments")] = "{}",
    output: Annotated[Path, typer.Option("--output", "-o", help="Destination JSONL file")] = Path(
        "traces.jsonl"
    ),
    goal: Annotated[str | None, typer.Option("--goal", help="Free-text session goal")] = None,
    header: Annotated[
        list[str] | None,
        typer.Option("--header", "-H", help="Repeatable: name:value HTTP header"),
    ] = None,
    stdio_arg: Annotated[
        list[str] | None,
        typer.Option("--stdio-arg", help="Repeatable: argv entry for stdio transport"),
    ] = None,
) -> None:
    """Smoke-record one session against a single MCP server."""
    headers: dict[str, str] | None = None
    if header:
        headers = {}
        for h in header:
            if ":" not in h:
                raise typer.BadParameter(f"header must be name:value, got {h!r}")
            k, v = h.split(":", 1)
            headers[k.strip()] = v.strip()

    try:
        arguments = json.loads(arguments_json)
    except json.JSONDecodeError as e:
        raise typer.BadParameter(f"--args must be valid JSON: {e}") from e
    if not isinstance(arguments, dict):
        raise typer.BadParameter("--args must be a JSON object")

    cfg = _build_config(server_id, transport, endpoint, headers, stdio_arg)

    async def _run() -> None:
        recorder = TraceRecorder(servers=[cfg], goal=goal)
        async with recorder:
            tools = await recorder.list_tools(server_id)
            typer.echo(f"[{server_id}] {len(tools)} tools discovered")
            for t in tools[:25]:
                typer.echo(f"  - {t.name}")
            if tool is not None:
                typer.echo(f"[{server_id}] calling {tool}({arguments_json}) ...")
                result = await recorder.call_tool(server_id, tool, arguments)
                typer.echo(json.dumps(result, indent=2)[:2000])
        recorder.write_jsonl(output)
        typer.echo(f"wrote trace → {output}")

    asyncio.run(_run())


@app.command()
def refresh(
    specs: Annotated[Path, typer.Argument(help="TaskSpec JSONL")],
    reference_traces: Annotated[Path, typer.Option("--reference-traces", help="JSONL of reference traces")],
    manifest: Annotated[Path, typer.Option("--manifest", "-m")] = Path("manifests/local.json"),
    refresh_stateful: Annotated[
        bool,
        typer.Option(
            "--refresh-stateful",
            help="Also re-run stateful_write servers (DANGEROUS — may mutate live state).",
        ),
    ] = False,
    transient_retries: Annotated[
        int,
        typer.Option(
            "--retries",
            help="Retry exception-raising live calls this many times with exponential backoff before classifying as broken.",
        ),
    ] = 2,
    initial_backoff_s: Annotated[
        float,
        typer.Option("--retry-backoff", help="Initial backoff in seconds (doubles each retry)"),
    ] = 0.5,
    output: Annotated[Path, typer.Option("--output", "-o", help="RefreshReport JSONL output")] = Path(
        "evals/refresh.jsonl"
    ),
) -> None:
    """Re-execute each spec's reference trace against live servers and report drift.

    Classifies every reference tool call as identical / drifted / broken / skipped.
    Skips stateful_write servers by default — re-running git_create_branch with
    the same name would just fail; pass --refresh-stateful to override only when
    you know the server is sandboxed for refresh.
    """
    m = Manifest.load(manifest)
    refs = _load_traces_by_id(reference_traces)

    async def _run() -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        reports = []
        with specs.open("r", encoding="utf-8") as fin, output.open("a", encoding="utf-8") as fout:
            for raw in fin:
                raw = raw.strip()
                if not raw:
                    continue
                spec = TaskSpec.model_validate_json(raw)
                ref = refs.get(str(spec.source_trace_id))
                if ref is None:
                    typer.echo(f"[task {spec.task_id}] skip: no reference trace")
                    continue
                report = await refresh_one(
                    reference=ref,
                    task_id=spec.task_id,
                    manifest=m,
                    refresh_stateful=refresh_stateful,
                    transient_retries=transient_retries,
                    initial_backoff_s=initial_backoff_s,
                )
                fout.write(report.to_jsonl())
                fout.write("\n")
                reports.append(report)
                c = report.counts
                flag = "STALE" if report.spec_likely_stale else "ok"
                typer.echo(
                    f"[task {spec.task_id}] {flag}  "
                    f"identical={c['identical']} drifted={c['drifted']} "
                    f"broken={c['broken']} skipped={c['skipped']}"
                )
        summary = decay_summary(reports)
        typer.echo("")
        typer.echo("decay summary:")
        typer.echo(f"  specs refreshed : {summary['specs_refreshed']}")
        typer.echo(f"  specs stale     : {summary['specs_stale']} ({summary['stale_rate'] * 100:.0f}%)")
        typer.echo(f"  call outcomes   : {summary['call_outcomes']}")
        typer.echo(f"\nwrote refresh report → {output}")

    asyncio.run(_run())


@app.command(name="goal-gen")
def goal_gen(
    manifest: Annotated[Path, typer.Option("--manifest", "-m")] = Path("manifests/local.json"),
    servers: Annotated[
        list[str] | None,
        typer.Option("--server", help="Repeatable: restrict to specific server_ids (default all)"),
    ] = None,
    single_per_server: Annotated[
        int, typer.Option("--per-server", help="Single-server goals to generate per server")
    ] = 2,
    cross_pairs: Annotated[
        int, typer.Option("--cross-pairs", help="Cross-server pairs to generate goals for")
    ] = 5,
    model: Annotated[str, typer.Option("--model")] = DEFAULT_MODEL,
    seed: Annotated[int, typer.Option("--seed")] = 0,
    no_personas: Annotated[
        bool,
        typer.Option("--no-personas", help="Disable persona seeding (free-form baseline)."),
    ] = False,
    output: Annotated[Path, typer.Option("--output", "-o", help="Goals JSON output")] = Path(
        "goals/auto.json"
    ),
) -> None:
    """Auto-generate goals.json from a manifest by feeding each server's tool
    surface to an LLM. Default: 2 single-server + 5 cross-server pairs."""
    m = Manifest.load(manifest)
    chosen = servers or [s.server_id for s in m.servers]
    llm = OpenRouterClient(model=model)

    async def _run() -> None:
        typer.echo(f"generating goals for {len(chosen)} server(s) via {model}")
        goals = await run_goal_gen(
            manifest=m,
            server_ids=chosen,
            llm=llm,
            single_per_server=single_per_server,
            cross_pairs=cross_pairs,
            seed=seed,
            use_personas=not no_personas,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(goals.model_dump_json(indent=2), encoding="utf-8")
        typer.echo(f"wrote {len(goals.entries)} goals → {output}")
        single = sum(1 for g in goals.entries if len(g.servers) == 1)
        cross = sum(1 for g in goals.entries if len(g.servers) > 1)
        typer.echo(f"  single-server: {single}   cross-server: {cross}")

    asyncio.run(_run())


@app.command()
def report(
    specs: Annotated[
        Path, typer.Option("--specs", help="TaskSpec JSONL produced by `dmcp distill` or `dmcp generate`")
    ],
    evals: Annotated[
        list[Path],
        typer.Option("--evals", help="Repeatable: EvaluationResult JSONL files (one per candidate model)"),
    ],
    output: Annotated[Path, typer.Option("--output", "-o", help="Markdown output path")] = Path(
        "reports/leaderboard.md"
    ),
    refresh: Annotated[
        list[Path] | None,
        typer.Option(
            "--refresh",
            help="Repeatable: RefreshReport JSONL file(s) from `dmcp refresh` (one per refresh run); appends a per-server decay table.",
        ),
    ] = None,
) -> None:
    """Aggregate one or more `dmcp eval` runs into a markdown leaderboard."""
    md = aggregate_markdown(specs_path=specs, eval_paths=evals, refresh_paths=refresh)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(md, encoding="utf-8")
    typer.echo(f"wrote report → {output}")
    typer.echo("")
    typer.echo(md)


@app.command(name="baseline-graph")
def baseline_graph(
    manifest: Annotated[Path, typer.Option("--manifest", "-m")] = Path("manifests/local.json"),
    servers: Annotated[
        list[str] | None,
        typer.Option("--server", help="Repeatable: restrict to specific server_ids (default all)"),
    ] = None,
    motif: Annotated[
        list[str] | None,
        typer.Option(
            "--motif",
            help="Repeatable: subgraph motif (chain|hub). Default: both.",
        ),
    ] = None,
    size: Annotated[int, typer.Option("--size", help="Tools per sampled subgraph (default 3)")] = 3,
    samples: Annotated[
        int,
        typer.Option("--samples", help="Subgraphs to sample per motif (default 5)"),
    ] = 5,
    seed: Annotated[int, typer.Option("--seed", help="Base RNG seed")] = 0,
    model: Annotated[str, typer.Option("--model", help="LLM for back-instruction")] = DEFAULT_MODEL,
    output: Annotated[Path, typer.Option("--output", "-o", help="TaskSpec JSONL output")] = Path(
        "specs/baseline_graph.jsonl"
    ),
) -> None:
    """Generate TaskSpecs via the RQ2 graph-sampling baseline (NOT the headline).

    Reads the manifest, captures each server's live tool surface (one stdio
    session per server), builds an inferred tool-dependency graph from JSON
    Schema property-name overlap, samples connected subgraphs per motif, and
    asks an LLM to back-instruct a user prompt for each. Emits TaskSpec JSONL
    in the same format as `dmcp distill`, but every spec is tagged
    `distiller_version="baseline-graph-sampling-…"` so reports cannot confuse
    forward-distilled and baseline specs.

    Per `memory/feedback_agb_orthogonality.md`: this exists ONLY to make RQ2
    comparable; nothing on the headline path consumes its output.
    """
    motifs = motif or list(VALID_MOTIFS)
    for mname in motifs:
        if mname not in VALID_MOTIFS:
            raise typer.BadParameter(f"--motif must be one of {VALID_MOTIFS}; got {mname!r}")
    m = Manifest.load(manifest)
    chosen = servers or [s.server_id for s in m.servers]
    entries = []
    for sid in chosen:
        try:
            entries.append(m.by_id(sid))
        except KeyError as e:
            raise typer.BadParameter(f"unknown server_id {sid!r}") from e
    llm = OpenRouterClient(model=model)

    async def _run() -> None:
        typer.echo(
            f"baseline-graph: {len(entries)} server(s), motifs={motifs}, size={size}, "
            f"samples={samples}, seed={seed}"
        )
        surfaces = {}
        for entry in entries:
            try:
                specs = await _fetch_tool_specs(entry)
            except Exception as e:
                typer.echo(f"  skip {entry.server_id}: tool-surface fetch failed: {e}")
                continue
            if not specs:
                typer.echo(f"  skip {entry.server_id}: 0 tools")
                continue
            surfaces[entry.server_id] = specs
            typer.echo(f"  {entry.server_id}: {len(specs)} tools")
        if not surfaces:
            typer.echo("no tool surfaces available; nothing to sample.")
            return
        graph = ToolGraph.from_tool_surfaces(surfaces)
        edge_count = sum(len(v) for v in graph.adj.values()) // 2
        typer.echo(f"graph: {len(graph)} nodes, {edge_count} edges")

        output.parent.mkdir(parents=True, exist_ok=True)
        kept = attempted = 0
        with output.open("a", encoding="utf-8") as fout:
            for mname in motifs:
                for s_idx in range(samples):
                    attempted += 1
                    sample_seed = seed * 1000 + hash(mname) % 1000 + s_idx
                    try:
                        subgraph = sample_subgraph(graph, size=size, motif=mname, seed=sample_seed)
                    except Exception as e:
                        typer.echo(f"  [{mname}#{s_idx}] sample error: {e}")
                        continue
                    try:
                        spec = await run_back_instruct(subgraph, graph, llm=llm, manifest=m)
                    except Exception as e:
                        typer.echo(f"  [{mname}#{s_idx}] back-instruct error: {e}")
                        continue
                    fout.write(spec.to_jsonl())
                    fout.write("\n")
                    kept += 1
                    typer.echo(
                        f"  [{mname}#{s_idx}] task {spec.task_id} "
                        f"servers={spec.servers_used} cps={len(spec.checkpoints)}"
                    )
        typer.echo(f"\nwrote {kept}/{attempted} baseline specs → {output}")

    asyncio.run(_run())


@app.command(name="baseline-direct")
def baseline_direct(
    manifest: Annotated[Path, typer.Option("--manifest", "-m")] = Path("manifests/local.json"),
    servers: Annotated[
        list[str] | None,
        typer.Option("--server", help="Repeatable: restrict to specific server_ids (default all)"),
    ] = None,
    samples: Annotated[int, typer.Option("--samples", help="Direct-generated proposals per server")] = 3,
    max_attempts: Annotated[
        int,
        typer.Option(
            "--max-attempts",
            help="Per-sample attempts: LLM proposes, verifier checks, retry on failure.",
        ),
    ] = 2,
    model: Annotated[str, typer.Option("--model", help="LLM for direct generation")] = DEFAULT_MODEL,
    output: Annotated[Path, typer.Option("--output", "-o", help="TaskSpec JSONL output")] = Path(
        "specs/baseline_direct.jsonl"
    ),
) -> None:
    """Generate TaskSpecs via the RQ2 direct generate-then-verify baseline (NOT the headline).

    Captures each server's live tool surface, asks an LLM to propose a task
    using only those tools, and mechanically verifies the proposal (every tool
    exists; every argument key is a real top-level parameter) before emitting
    a TaskSpec. Specs are tagged `distiller_version="baseline-direct-generation-…"`
    and `notes` start with `[BASELINE:direct_generation]` so reports cannot
    conflate them with forward-distilled specs.

    Per `memory/feedback_agb_orthogonality.md`: comparison-only; nothing on
    the headline path consumes this module's output.
    """
    m = Manifest.load(manifest)
    chosen = servers or [s.server_id for s in m.servers]
    entries = []
    for sid in chosen:
        try:
            entries.append(m.by_id(sid))
        except KeyError as e:
            raise typer.BadParameter(f"unknown server_id {sid!r}") from e
    llm = OpenRouterClient(model=model)

    async def _run() -> None:
        typer.echo(
            f"baseline-direct: {len(entries)} server(s), samples/server={samples}, "
            f"max_attempts={max_attempts}"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        kept = attempted = 0
        with output.open("a", encoding="utf-8") as fout:
            for entry in entries:
                try:
                    specs = await _fetch_tool_specs(entry)
                except Exception as e:
                    typer.echo(f"  skip {entry.server_id}: tool-surface fetch failed: {e}")
                    continue
                if not specs:
                    typer.echo(f"  skip {entry.server_id}: 0 tools")
                    continue
                surfaces = {entry.server_id: specs}
                for s_idx in range(samples):
                    attempted += 1
                    try:
                        spec = await run_direct_gen(surfaces, llm=llm, manifest=m, max_attempts=max_attempts)
                    except GenerationError as e:
                        typer.echo(f"  [{entry.server_id}#{s_idx}] generation error: {e}")
                        continue
                    fout.write(spec.to_jsonl())
                    fout.write("\n")
                    kept += 1
                    typer.echo(
                        f"  [{entry.server_id}#{s_idx}] task {spec.task_id} "
                        f"servers={spec.servers_used} cps={len(spec.checkpoints)}"
                    )
        typer.echo(f"\nwrote {kept}/{attempted} baseline specs → {output}")

    asyncio.run(_run())


@app.command(name="compare-generators")
def compare_generators(
    forward: Annotated[
        Path | None,
        typer.Option("--forward", help="Forward-distilled TaskSpec JSONL"),
    ] = None,
    graph: Annotated[
        Path | None,
        typer.Option("--graph", help="Graph-sampling baseline TaskSpec JSONL"),
    ] = None,
    direct: Annotated[
        Path | None,
        typer.Option("--direct", help="Direct-generation baseline TaskSpec JSONL"),
    ] = None,
    reference_traces: Annotated[
        Path | None,
        typer.Option(
            "--reference-traces",
            help="JSONL of reference traces; tool_specs are unioned to build the catalog.",
        ),
    ] = None,
    catalog: Annotated[
        Path | None,
        typer.Option(
            "--catalog",
            help="JSON list of [server_id, tool_name] pairs (alternative to --reference-traces).",
        ),
    ] = None,
    proposals_forward: Annotated[
        int | None,
        typer.Option(
            "--proposals-forward",
            help="Total forward proposals attempted (for the filter pass rate).",
        ),
    ] = None,
    proposals_graph: Annotated[
        int | None,
        typer.Option("--proposals-graph", help="Total graph proposals attempted."),
    ] = None,
    proposals_direct: Annotated[
        int | None,
        typer.Option("--proposals-direct", help="Total direct proposals attempted."),
    ] = None,
    title: Annotated[
        str | None,
        typer.Option("--title", help="Report title override."),
    ] = None,
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Markdown comparison report"),
    ] = Path("reports/rq2_comparison.md"),
    json_out: Annotated[
        Path | None,
        typer.Option(
            "--json-out",
            help="Optional JSON dump of the distilled numbers (committable).",
        ),
    ] = None,
) -> None:
    """RQ2: compare forward distillation vs the graph and direct baselines.

    Reads TaskSpec JSONL for whichever methods you supply and emits a
    self-contained markdown report. Per `memory/feedback_agb_orthogonality.md`,
    this is a comparison-only tool — the headline scoring path does not
    consume its output.

    The harness only computes axes that are a pure function of the spec files
    + an optional tool catalog. Live re-execution axes (executable-on-first-try
    for baselines; the trace-grounded unnecessary-tool rate; the execution-side
    error-type taxonomy) are reported as deferred — see the report's "Deferred
    axes" section.
    """
    spec_paths: dict[str, Path] = {}
    if forward is not None:
        spec_paths["forward"] = forward
    if graph is not None:
        spec_paths["graph"] = graph
    if direct is not None:
        spec_paths["direct"] = direct
    if not spec_paths:
        raise typer.BadParameter("supply at least one of --forward/--graph/--direct")

    catalog_set: set[tuple[str, str]] | None = None
    if catalog is not None:
        catalog_set = load_catalog(catalog)
    elif reference_traces is not None:
        catalog_set = catalog_from_trace_jsonl(reference_traces)

    proposals = {
        "forward": proposals_forward,
        "graph": proposals_graph,
        "direct": proposals_direct,
    }
    proposals_clean = {k: v for k, v in proposals.items() if v is not None}

    report = compare_methods(
        spec_paths,
        catalog=catalog_set,
        proposals_attempted=proposals_clean or None,
    )
    md = render_compare_markdown(report, title=title)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(md, encoding="utf-8")
    typer.echo(f"wrote report → {output}")
    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(
            json.dumps(compare_report_to_json(report), indent=2) + "\n",
            encoding="utf-8",
        )
        typer.echo(f"wrote json   → {json_out}")
    typer.echo("")
    typer.echo(md)


def _parse_pair(raw: str, *, label: str) -> tuple[str, Path]:
    if ":" not in raw:
        raise typer.BadParameter(f"--{label} must be 'name:path', got {raw!r}")
    name, p = raw.split(":", 1)
    return name.strip(), Path(p.strip())


@app.command(name="rq1-compare")
def rq1_compare(
    evals: Annotated[
        list[str],
        typer.Option(
            "--evals",
            help=(
                "Repeatable: 'model_label:path/to/evals.jsonl' for the trace-align arm. "
                "Pass once per candidate model."
            ),
        ),
    ],
    candidate_traces: Annotated[
        list[str],
        typer.Option(
            "--candidate-traces",
            help="Repeatable: 'model_label:path/to/candidate_traces.jsonl'.",
        ),
    ],
    specs: Annotated[
        Path,
        typer.Option("--specs", help="TaskSpec JSONL — used to join task_id → source_trace_id."),
    ],
    reference_traces: Annotated[
        Path,
        typer.Option(
            "--reference-traces",
            help="JSONL of reference traces; provides reference final messages.",
        ),
    ],
    rerun: Annotated[
        list[str] | None,
        typer.Option(
            "--rerun",
            help=(
                "Optional repeatable: 'model_label:evals_run2.jsonl' to add an "
                "over-time stability column for that model."
            ),
        ),
    ] = None,
    rerun_candidate_traces: Annotated[
        list[str] | None,
        typer.Option(
            "--rerun-candidate-traces",
            help="Optional repeatable: 'model_label:candidate_traces_run2.jsonl'.",
        ),
    ] = None,
    threshold: Annotated[
        float,
        typer.Option("--threshold", help="Answer-match token-Jaccard threshold."),
    ] = RQ1_DEFAULT_THRESHOLD,
    title: Annotated[
        str | None,
        typer.Option("--title", help="Report title override."),
    ] = None,
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Markdown report path."),
    ] = Path("reports/rq1_comparison.md"),
    json_out: Annotated[
        Path | None,
        typer.Option(
            "--json-out",
            help="Optional JSON dump of the distilled numbers (committable).",
        ),
    ] = None,
) -> None:
    """RQ1: trace/effect alignment vs final-answer string match.

    Joins per-model `EvaluationResult` JSONL (the trace-align arm) with the
    same model's candidate trace JSONL (for `final_assistant_message`) and
    the reference traces, then scores each (model, task) cell under both
    methods. Reports per-model accuracies, Kendall's τ between the two
    rankings, false-fail / false-pass disagreement rates, and optional
    over-time stability when `--rerun` is supplied for a model.

    The answer-match scorer (`dmcp/baselines/answer_match.py`) is a labeled
    comparison baseline per `memory/feedback_agb_orthogonality.md`. It is
    never imported by the headline scoring path.
    """
    spec_to_source = load_spec_to_reference_trace(specs)
    refs_by_trace_id = load_reference_final_messages_by_trace_id(reference_traces)

    eval_paths: dict[str, Path] = dict(_parse_pair(s, label="evals") for s in evals)
    cand_paths: dict[str, Path] = dict(_parse_pair(s, label="candidate-traces") for s in candidate_traces)
    if set(eval_paths) != set(cand_paths):
        raise typer.BadParameter(
            "the model labels under --evals and --candidate-traces must match: "
            f"evals={sorted(eval_paths)}, candidate_traces={sorted(cand_paths)}"
        )

    decisions_by_model: dict[str, list] = {}
    for model in sorted(eval_paths):
        ev_list = load_evals(eval_paths[model])
        cand_msgs = load_candidate_final_messages(cand_paths[model])
        decisions_by_model[model] = build_decisions(
            model=model,
            evals=ev_list,
            candidate_final_messages=cand_msgs,
            reference_final_messages_by_trace_id=refs_by_trace_id,
            spec_to_source_trace=spec_to_source,
            threshold=threshold,
        )
        typer.echo(f"  [{model}] joined {len(ev_list)} evals, {len(cand_msgs)} candidate final-messages")

    over_time_runs: dict[str, list[list]] = {}
    if rerun:
        rerun_paths = dict(_parse_pair(s, label="rerun") for s in rerun)
        rerun_cand_paths = (
            dict(_parse_pair(s, label="rerun-candidate-traces") for s in rerun_candidate_traces)
            if rerun_candidate_traces
            else {}
        )
        for model, run2_path in rerun_paths.items():
            run1 = decisions_by_model.get(model)
            if run1 is None:
                typer.echo(f"  [{model}] --rerun supplied but no run-1 evals; skipping")
                continue
            ev2 = load_evals(run2_path)
            cand2_path = rerun_cand_paths.get(model)
            cand2_msgs = load_candidate_final_messages(cand2_path) if cand2_path else {}
            run2 = build_decisions(
                model=model,
                evals=ev2,
                candidate_final_messages=cand2_msgs,
                reference_final_messages_by_trace_id=refs_by_trace_id,
                spec_to_source_trace=spec_to_source,
                threshold=threshold,
            )
            over_time_runs[model] = [run1, run2]
            typer.echo(f"  [{model}] rerun loaded ({len(ev2)} evals)")

    report = aggregate_rq1(decisions_by_model, threshold=threshold, over_time_runs=over_time_runs or None)
    md = render_rq1_markdown(report, title=title)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(md, encoding="utf-8")
    typer.echo(f"\nwrote report → {output}")
    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(
            json.dumps(rq1_report_to_json(report), indent=2) + "\n",
            encoding="utf-8",
        )
        typer.echo(f"wrote json   → {json_out}")
    typer.echo("")
    typer.echo(md)


@app.command(name="rq3-failure-model")
def rq3_failure_model(
    evals: Annotated[
        list[str],
        typer.Option(
            "--evals",
            help=("Repeatable: 'model_label:path/to/evals.jsonl'. Joined to --specs on task_id."),
        ),
    ],
    specs: Annotated[
        Path,
        typer.Option(
            "--specs",
            help="TaskSpec JSONL with ComplexityProfile fields for each task.",
        ),
    ],
    ridge: Annotated[
        float,
        typer.Option(
            "--ridge",
            help="L2 ridge λ on non-intercept coefficients (handles near-separability).",
        ),
    ] = 1e-3,
    title: Annotated[
        str | None,
        typer.Option("--title", help="Report title override."),
    ] = None,
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Markdown report path."),
    ] = Path("reports/rq3_failure_model.md"),
    json_out: Annotated[
        Path | None,
        typer.Option(
            "--json-out",
            help="Optional JSON dump of the distilled numbers (committable).",
        ),
    ] = None,
) -> None:
    """RQ3: fit pass/fail ~ (depth, branching, state_coupling, cross_server, dynamism) per model.

    Joins per-model `EvaluationResult` JSONL with the TaskSpec JSONL on
    `task_id`, extracts the ComplexityProfile + dynamism features, fits a
    ridge-regularized logistic regression per candidate model AND a pooled
    fit, and reports per-feature coefficients, odds ratios, and a
    drop-column permutation importance (log-likelihood loss when the column
    is removed and the model refit). Pure-Python IRLS — no new dependency.
    """
    eval_paths: dict[str, Path] = {}
    for raw in evals:
        if ":" not in raw:
            raise typer.BadParameter(f"--evals must be 'model:path', got {raw!r}")
        name, p = raw.split(":", 1)
        eval_paths[name.strip()] = Path(p.strip())
    features_by_task = load_features_by_task(specs)
    typer.echo(f"loaded features for {len(features_by_task)} task(s) from {specs}")

    samples_by_model: dict[str, list] = {}
    for model, ep in sorted(eval_paths.items()):
        samples = load_samples_for_model(ep, features_by_task, model_label=model)
        samples_by_model[model] = samples
        n_pass = sum(s.pass_flag for s in samples)
        typer.echo(
            f"  [{model}] joined {len(samples)} samples ({n_pass} pass / {len(samples) - n_pass} fail)"
        )

    report = fit_per_model_and_pooled(samples_by_model, ridge=ridge)
    md = render_rq3_markdown(report, title=title)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(md, encoding="utf-8")
    typer.echo(f"\nwrote report → {output}")
    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(
            json.dumps(rq3_report_to_json(report), indent=2) + "\n",
            encoding="utf-8",
        )
        typer.echo(f"wrote json   → {json_out}")
    typer.echo("")
    typer.echo(md)


@app.command(name="rq4-subset")
def rq4_subset(
    specs: Annotated[Path, typer.Argument(help="TaskSpec JSONL input")],
    candidate_traces: Annotated[
        list[Path] | None,
        typer.Option(
            "--candidate-traces",
            help="Repeatable: JSONL of candidate traces to seed the annotation template with.",
        ),
    ] = None,
    raters: Annotated[
        list[str] | None,
        typer.Option(
            "--rater",
            help="Repeatable: rater_id for the annotation template (e.g. -r alice -r bob).",
        ),
    ] = None,
    n: Annotated[int, typer.Option("--n", help="Target subset size.")] = DEFAULT_SUBSET_N,
    seed: Annotated[int, typer.Option("--seed", help="Sampling seed.")] = 0,
    subset_out: Annotated[
        Path,
        typer.Option(
            "--subset-out",
            help="JSONL: chosen task subset + per-row stratum tag.",
        ),
    ] = Path("evals/rq4_subset.jsonl"),
    annotation_out: Annotated[
        Path | None,
        typer.Option(
            "--annotation-out",
            help=(
                "JSONL: annotation-template rows (one per task × candidate × rater). "
                "Requires --candidate-traces and at least one --rater."
            ),
        ),
    ] = None,
) -> None:
    """RQ4: emit a deterministic stratified validation subset + annotation template.

    Builds a balanced sample of `n` tasks across the (dynamism × complexity_bin)
    grid (every non-empty stratum gets ≥ 1). When `--candidate-traces` and
    `--rater` are supplied, also emits an annotation template JSONL with one
    empty row per (task_id, candidate_trace_id, rater_id) the human will fill in.

    Per `memory/feedback_agb_orthogonality.md`, this is RQ4 instrumentation —
    no scorer change.
    """
    spec_list: list[TaskSpec] = []
    with specs.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            spec_list.append(TaskSpec.model_validate_json(line))
    manifest = build_subset(spec_list, n=n, seed=seed)
    write_subset_jsonl(manifest, subset_out)
    typer.echo(f"wrote subset → {subset_out} (target={manifest.target_n}, achieved={manifest.achieved_n})")
    typer.echo("stratum counts:")
    for k, v in sorted(manifest.stratum_counts.items()):
        typer.echo(f"  {k}: {v}")
    if manifest.notes:
        typer.echo("notes:")
        for note in manifest.notes:
            typer.echo(f"  - {note}")

    if annotation_out is not None:
        if not candidate_traces or not raters:
            raise typer.BadParameter("--annotation-out requires --candidate-traces and at least one --rater")
        cand_rows: list[dict[str, Any]] = []
        for cpath in candidate_traces:
            with cpath.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    d = json.loads(line)
                    tid = (d.get("seed_metadata") or {}).get("task_id") or d.get("task_id")
                    cand_rows.append(
                        {
                            "task_id": str(tid) if tid is not None else "",
                            "candidate_trace_id": str(d.get("trace_id") or ""),
                            "candidate_model": str((d.get("seed_metadata") or {}).get("llm_model") or ""),
                        }
                    )
        written = write_annotation_template(
            manifest.rows, cand_rows, rater_ids=list(raters), path=annotation_out
        )
        typer.echo(f"wrote annotation template ({written} rows) → {annotation_out}")


@app.command(name="rq4-agreement")
def rq4_agreement(
    annotations: Annotated[
        Path,
        typer.Option(
            "--annotations",
            help="Annotation JSONL (filled-in template) from `dmcp rq4-subset`.",
        ),
    ],
    tier1_evals: Annotated[
        Path,
        typer.Option(
            "--tier1-evals",
            help="Tier-1 EvaluationResult JSONL (judge off) used to derive scorer verdicts.",
        ),
    ],
    tier2_evals: Annotated[
        Path | None,
        typer.Option(
            "--tier2-evals",
            help="Optional: Tier-2 EvaluationResult JSONL (judge on) for the Tier-2 column.",
        ),
    ] = None,
    replay_run_b_evals: Annotated[
        Path | None,
        typer.Option(
            "--replay-run-b",
            help="Optional: second Tier-1 run for the replay-determinism flip-rate.",
        ),
    ] = None,
    consensus_out: Annotated[
        Path | None,
        typer.Option(
            "--consensus-out",
            help="Optional: write the human-consensus aggregate JSONL here.",
        ),
    ] = None,
    subset_size_hint: Annotated[
        int,
        typer.Option(
            "--subset-size",
            help="Subset size for the report header (default: distinct task_ids in annotations).",
        ),
    ] = 0,
    title: Annotated[str | None, typer.Option("--title", help="Report title override.")] = None,
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Markdown report path."),
    ] = Path("reports/rq4_agreement.md"),
    json_out: Annotated[
        Path | None,
        typer.Option(
            "--json-out",
            help="Optional JSON dump of the distilled numbers (committable).",
        ),
    ] = None,
) -> None:
    """RQ4: report scorer-vs-human agreement (Cohen's κ, Krippendorff's α) + replay determinism.

    Consumes a filled-in annotation JSONL plus per-tier Tier-1 / Tier-2
    `EvaluationResult` JSONL. Optional second Tier-1 run feeds the
    replay-determinism flip-rate. Pre-registered thresholds (κ / α ≥ 0.7;
    replay flip rate < 5 %) come from the experiment doc.
    """
    ann_rows = load_annotations(annotations)
    consensus = compute_consensus(ann_rows)
    if consensus_out is not None:
        write_consensus(consensus, consensus_out)
        typer.echo(f"wrote consensus → {consensus_out}")
    t1 = load_evals_for_rq4(tier1_evals)
    t2 = load_evals_for_rq4(tier2_evals) if tier2_evals else None
    rb = load_evals_for_rq4(replay_run_b_evals) if replay_run_b_evals else None
    subset_size = subset_size_hint or len({a.task_id for a in ann_rows})
    report = build_rq4_agreement_report(
        subset_size=subset_size,
        annotations=ann_rows,
        consensus=consensus,
        tier1_evals=t1,
        tier2_evals=t2,
        replay_run_b_evals=rb,
    )
    md = render_rq4_markdown(report, title=title)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(md, encoding="utf-8")
    typer.echo(f"\nwrote report → {output}")
    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(
            json.dumps(rq4_report_to_json(report), indent=2) + "\n",
            encoding="utf-8",
        )
        typer.echo(f"wrote json   → {json_out}")
    typer.echo("")
    typer.echo(md)


@app.command(name="paper-figures")
def paper_figures(
    root: Annotated[
        Path,
        typer.Option(
            "--root",
            help="Repository root (default: the current working directory).",
        ),
    ] = Path("."),
    fail_on_pending: Annotated[
        bool,
        typer.Option(
            "--fail-on-pending",
            help="Exit non-zero if any figures.md row is still pending after a run.",
        ),
    ] = False,
) -> None:
    """Regenerate the paper's LaTeX figure/table artifacts from committed data.

    Reads `paper/figures.md`, dispatches each row to a renderer (see
    `paper/regenerate.py`), and writes one `.tex` file per row under
    `paper/figures/` (for `fig:*` ids) or `paper/tables/` (for `tab:*`
    ids). Rows whose backing data isn't on disk yet emit a clearly-marked
    placeholder figure / table so `\\ref{...}` still resolves.

    A cross-reference validator confirms every `\\input{figures/<slug>}`
    / `\\input{tables/<slug>}` directive in `paper/sections/*.tex`
    resolves to a `figures.md` row — violations are printed and (with
    `--fail-on-pending`) make the run exit non-zero.
    """
    # Imported lazily so importing dmcp.cli on a minimal install doesn't
    # require the paper/ directory to exist.
    from paper.regenerate import regenerate

    outcome = regenerate(root=root.resolve(), verbose=True)
    typer.echo("")
    typer.echo(
        f"rendered={len(outcome.rendered)} ・ pending={len(outcome.pending)} ・ manual={len(outcome.manual)}"
    )
    if outcome.cross_ref_errors:
        typer.echo("cross-reference errors:")
        for e in outcome.cross_ref_errors:
            typer.echo(f"  - {e}")
    failed = (fail_on_pending and outcome.pending) or outcome.cross_ref_errors
    if failed:
        raise typer.Exit(code=1)


def _not_yet(name: str) -> None:
    raise typer.Exit(
        code=2,
    ) from typer.BadParameter(f"`dmcp {name}` is not implemented yet (rev. 3 plan, future phase).")


@app.command()
def crawl(
    limit: Annotated[
        int,
        typer.Option("--limit", help="Max number of no-creds installable servers to attempt"),
    ] = 50,
    discovered_out: Annotated[
        Path,
        typer.Option("--discovered-out", help="Raw discovery JSONL output"),
    ] = Path("crawled/discovered.jsonl"),
    vet_out: Annotated[
        Path,
        typer.Option("--vet-out", help="Vet result JSONL output"),
    ] = Path("crawled/vetted.jsonl"),
    manifest_out: Annotated[
        Path,
        typer.Option("--manifest-out", help="Generated runnable manifest"),
    ] = Path("manifests/crawled.json"),
    install_timeout_s: Annotated[
        float,
        typer.Option("--install-timeout", help="Per-server install timeout"),
    ] = 120.0,
    smoke_timeout_s: Annotated[
        float,
        typer.Option("--smoke-timeout", help="Per-server initialize+list_tools timeout"),
    ] = 30.0,
    no_install: Annotated[
        bool,
        typer.Option(
            "--no-install",
            help="Discovery only — do not install or smoke-test servers (safe preview)",
        ),
    ] = False,
) -> None:
    """Crawl the official MCP Registry, install + smoke-test no-creds servers,
    emit a runnable manifest of those that initialize and expose ≥1 tool.

    Security note: this runs `uv pip install` and `npx -y` on third-party
    code identified by the public catalog. Package install scripts and the
    server processes themselves can execute arbitrary code. Use --no-install
    for safe discovery preview; only run the full pipeline when you've
    decided the catalog is acceptable.
    """
    discovered_out.parent.mkdir(parents=True, exist_ok=True)
    vet_out.parent.mkdir(parents=True, exist_ok=True)
    manifest_out.parent.mkdir(parents=True, exist_ok=True)

    typer.echo("phase 1 — discovering servers from registry.modelcontextprotocol.io")
    client = MCPRegistryClient()
    discovered: list = []
    seen_packages: set[tuple[str, str]] = set()  # dedup by (pkg_kind, identifier)
    n_examined = 0
    with discovered_out.open("w", encoding="utf-8") as fd:
        for srv in client.iter_all():
            n_examined += 1
            fd.write(srv.to_jsonl())
            fd.write("\n")
            picks = srv.no_creds_installable_packages
            if not picks:
                continue
            p = picks[0]
            key = (p.kind.value, p.identifier)
            if key in seen_packages:
                continue
            seen_packages.add(key)
            discovered.append(srv)
            if len(discovered) >= limit:
                break
    typer.echo(
        f"  examined {n_examined} server records; selected {len(discovered)} "
        f"unique no-creds installable candidates"
    )

    if no_install:
        typer.echo("--no-install set: stopping after discovery.")
        return

    typer.echo("\nphase 2 — install + smoke")
    vet_results = []
    with vet_out.open("w", encoding="utf-8") as fv:
        for i, srv in enumerate(discovered, 1):
            inst = install_server(srv, install_timeout_s=install_timeout_s)
            typer.echo(
                f"  [{i:>3}/{len(discovered)}] {srv.name:<55s} install={inst.status.value}"
                + (f" ({inst.reason})" if inst.status is not InstallStatus.success else "")
            )
            if inst.status is not InstallStatus.success:
                vr = vet_one(srv, inst, smoke_timeout_s=smoke_timeout_s)
                vet_results.append(vr)
                fv.write(json.dumps(vet_result_summary(vr)) + "\n")
                continue
            vr = vet_one(srv, inst, smoke_timeout_s=smoke_timeout_s)
            vet_results.append(vr)
            fv.write(json.dumps(vet_result_summary(vr)) + "\n")
            flag = "✓" if vr.status is VetStatus.success else "✗"
            typer.echo(
                f"           ↳ smoke {flag} {vr.status.value} "
                f"tools={vr.tool_count} dynamism={vr.dynamism.value if vr.dynamism else '-'} "
                f"({vr.elapsed_s:.1f}s) {vr.reason[:80]}"
            )

    entries = [vr.manifest_entry for vr in vet_results if vr.manifest_entry]
    typer.echo(f"\nphase 3 — manifest: {len(entries)} servers passed smoke (of {len(discovered)} attempted)")

    from dmcp.manifest import Manifest

    manifest = Manifest(servers=entries)
    manifest.dump(manifest_out)
    by_dyn: dict[str, int] = {}
    for e in entries:
        by_dyn[e.dynamism.value] = by_dyn.get(e.dynamism.value, 0) + 1
    typer.echo(f"  by dynamism: {by_dyn}")
    typer.echo(f"\nwrote manifest → {manifest_out}")
    typer.echo(f"wrote vet log  → {vet_out}")
    typer.echo(f"wrote discovery → {discovered_out}")


@app.command()
def explore(
    goal: Annotated[str, typer.Argument(help="Natural-language goal for the explorer to pursue")],
    manifest: Annotated[Path, typer.Option("--manifest", "-m", help="Path to server manifest JSON")] = Path(
        "manifests/local.json"
    ),
    servers: Annotated[
        list[str] | None,
        typer.Option("--server", help="Repeatable: server_id to include. Defaults to all in manifest."),
    ] = None,
    model: Annotated[str, typer.Option("--model", help="OpenRouter model id")] = DEFAULT_MODEL,
    budget: Annotated[int, typer.Option("--budget", help="Max LLM turns")] = 12,
    persona: Annotated[str | None, typer.Option("--persona", help="Optional persona prefix")] = None,
    output: Annotated[Path, typer.Option("--output", "-o", help="Trace JSONL output path")] = Path(
        "traces/explore.jsonl"
    ),
) -> None:
    """Run goal-seeded forward exploration and write the trace as JSONL."""
    m = Manifest.load(manifest)
    configs = m.configs(servers)
    llm = OpenRouterClient(model=model)

    async def _run() -> None:
        typer.echo(f"exploring goal: {goal!r}")
        typer.echo(f"servers: {[c.server_id for c in configs]}  model: {model}  budget: {budget}")
        result = await run_exploration(
            goal=goal,
            servers=configs,
            llm=llm,
            budget=budget,
            persona=persona,
        )
        stash_exploration_in_trace(result)
        typer.echo(
            f"outcome={result.outcome} tool_calls={result.tool_call_count} "
            f"successful={result.successful_tool_calls}"
        )
        if result.final_message:
            preview = result.final_message[:400]
            typer.echo(f"final: {preview}{'…' if len(result.final_message) > 400 else ''}")
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("a", encoding="utf-8") as f:
            f.write(result.trace.to_jsonl())
            f.write("\n")
        typer.echo(f"wrote trace → {output}")

    asyncio.run(_run())


@app.command()
def distill(
    traces: Annotated[Path, typer.Argument(help="Traces JSONL input")],
    manifest: Annotated[
        Path, typer.Option("--manifest", "-m", help="Manifest used for dynamism tagging")
    ] = Path("manifests/local.json"),
    model: Annotated[str, typer.Option("--model", help="OpenRouter model for distillation")] = DEFAULT_MODEL,
    output: Annotated[Path, typer.Option("--output", "-o", help="TaskSpec JSONL output")] = Path(
        "specs/specs.jsonl"
    ),
) -> None:
    """Compile traces into TaskSpecs (prompt + checkpoints + minefields)."""
    m = Manifest.load(manifest)
    llm = OpenRouterClient(model=model)

    async def _run() -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        total = kept = 0
        with traces.open("r", encoding="utf-8") as fin, output.open("a", encoding="utf-8") as fout:
            for raw in fin:
                raw = raw.strip()
                if not raw:
                    continue
                total += 1
                trace = Trace.model_validate_json(raw)
                try:
                    spec = await run_distill(trace, llm=llm, manifest=m)
                except DistillationError as e:
                    typer.echo(f"skip trace {trace.trace_id}: {e}")
                    continue
                fout.write(spec.to_jsonl())
                fout.write("\n")
                kept += 1
                typer.echo(
                    f"distilled {trace.trace_id} → task {spec.task_id} "
                    f"(checkpoints={len(spec.checkpoints)}, dynamism={spec.dynamism.value})"
                )
        typer.echo(f"done: {kept}/{total} traces distilled → {output}")

    asyncio.run(_run())


@app.command()
def generate(
    goals: Annotated[Path, typer.Argument(help="Goals seed JSON")],
    manifest: Annotated[Path, typer.Option("--manifest", "-m")] = Path("manifests/local.json"),
    explore_model: Annotated[
        str, typer.Option("--explore-model", help="LLM for exploration")
    ] = DEFAULT_MODEL,
    distill_model: Annotated[
        str, typer.Option("--distill-model", help="LLM for distillation")
    ] = DEFAULT_MODEL,
    budget: Annotated[int, typer.Option("--budget", help="Default per-goal LLM turn budget")] = 12,
    traces_out: Annotated[
        Path, typer.Option("--traces-out", help="JSONL: every recorded trace, success or not")
    ] = Path("traces/generated.jsonl"),
    specs_out: Annotated[Path, typer.Option("--specs-out", help="JSONL: distilled TaskSpecs only")] = Path(
        "specs/generated.jsonl"
    ),
) -> None:
    """Batch: for each goal, explore → distill → emit a TaskSpec.

    Writes every trace (so failed explorations can still be inspected) and
    only the successfully-distilled specs. Prints a stratification summary
    at the end (cross_server, state_coupling, recovery_required counts).
    """
    m = Manifest.load(manifest)
    g = Goals.load(goals)
    explore_llm = OpenRouterClient(model=explore_model)
    distill_llm = OpenRouterClient(model=distill_model)

    # Validate all goals' servers exist up front.
    for entry in g.entries:
        for sid in entry.servers:
            try:
                m.by_id(sid)
            except KeyError as e:
                raise typer.BadParameter(
                    f"goal {entry.goal_id!r} references unknown server {sid!r} (not in manifest {manifest})"
                ) from e

    async def _run() -> None:
        traces_out.parent.mkdir(parents=True, exist_ok=True)
        specs_out.parent.mkdir(parents=True, exist_ok=True)
        spec_count = trace_count = 0
        stratification = {
            "cross_server": 0,
            "state_coupling": 0,
            "recovery_required": 0,
            "runtime_branching": 0,
            "by_dynamism": {"static": 0, "live_read": 0, "stateful_write": 0},
            "by_depth": {},
        }
        with traces_out.open("a", encoding="utf-8") as ft, specs_out.open("a", encoding="utf-8") as fs:
            for entry in g.entries:
                typer.echo(f"[{entry.goal_id}] servers={entry.servers} budget={entry.budget or budget}")
                cfgs = m.configs(entry.servers)
                try:
                    result = await run_exploration(
                        goal=entry.goal,
                        servers=cfgs,
                        llm=explore_llm,
                        budget=entry.budget or budget,
                        persona=entry.persona,
                        extra_seed={"goal_id": entry.goal_id, "goal_tags": entry.tags},
                    )
                except Exception as e:
                    typer.echo(f"  exploration error: {type(e).__name__}: {e}")
                    continue
                stash_exploration_in_trace(result)
                ft.write(result.trace.to_jsonl())
                ft.write("\n")
                trace_count += 1
                typer.echo(
                    f"  explored: outcome={result.outcome} successful_calls={result.successful_tool_calls}"
                )
                if result.successful_tool_calls == 0:
                    typer.echo("  skip distill: no successful tool calls")
                    continue
                try:
                    spec = await run_distill(result.trace, llm=distill_llm, manifest=m)
                except DistillationError as e:
                    typer.echo(f"  distill error: {e}")
                    continue
                fs.write(spec.to_jsonl())
                fs.write("\n")
                spec_count += 1
                c = spec.complexity
                if c.cross_server:
                    stratification["cross_server"] += 1
                if c.state_coupling:
                    stratification["state_coupling"] += 1
                if c.recovery_required:
                    stratification["recovery_required"] += 1
                if c.runtime_branching:
                    stratification["runtime_branching"] += 1
                stratification["by_dynamism"][spec.dynamism.value] += 1
                stratification["by_depth"][c.trace_depth] = (
                    stratification["by_depth"].get(c.trace_depth, 0) + 1
                )
                typer.echo(
                    f"  distilled: task {spec.task_id} dynamism={spec.dynamism.value} "
                    f"depth={c.trace_depth} cs={c.cross_server} sc={c.state_coupling} "
                    f"rec={c.recovery_required} rb={c.runtime_branching}"
                )
        typer.echo(f"\ngenerated {spec_count}/{trace_count} specs ({spec_count} traces became specs)")
        typer.echo("stratification:")
        typer.echo(f"  cross_server      : {stratification['cross_server']}")
        typer.echo(f"  state_coupling    : {stratification['state_coupling']}")
        typer.echo(f"  recovery_required : {stratification['recovery_required']}")
        typer.echo(f"  runtime_branching : {stratification['runtime_branching']}")
        typer.echo(f"  by_dynamism       : {stratification['by_dynamism']}")
        typer.echo(f"  by_depth          : {dict(sorted(stratification['by_depth'].items()))}")
        typer.echo(f"\nwrote traces → {traces_out}")
        typer.echo(f"wrote specs  → {specs_out}")

    asyncio.run(_run())


def _load_traces_by_id(path: Path) -> dict[str, Trace]:
    index: dict[str, Trace] = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            t = Trace.model_validate_json(line)
            index[str(t.trace_id)] = t
    return index


def index_candidate_traces(path: Path) -> tuple[dict[str, list[Trace]], dict[str, list[Trace]]]:
    """Index externally-produced candidate traces for `dmcp eval --candidate-traces`.

    Returns (by_task, by_prompt): by_task maps str(seed_metadata['task_id']) -> traces;
    by_prompt maps trace.goal -> traces. A spec is matched to its candidates by task_id
    first, falling back to its prompt. Multiple traces per task are kept (→ pass^k).
    """
    by_task: dict[str, list[Trace]] = {}
    by_prompt: dict[str, list[Trace]] = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            t = Trace.model_validate_json(line)
            tid = t.seed_metadata.get("task_id")
            if tid is not None:
                by_task.setdefault(str(tid), []).append(t)
            if t.goal is not None:
                by_prompt.setdefault(t.goal, []).append(t)
    return by_task, by_prompt


@app.command(name="eval")
def evaluate(
    specs: Annotated[Path, typer.Argument(help="TaskSpec JSONL input")],
    manifest: Annotated[Path, typer.Option("--manifest", "-m")] = Path("manifests/local.json"),
    model: Annotated[str, typer.Option("--model", help="Candidate agent's LLM")] = DEFAULT_MODEL,
    budget: Annotated[int, typer.Option("--budget", help="Max turns per candidate run")] = 12,
    servers: Annotated[
        list[str] | None,
        typer.Option("--server", help="Repeatable: restrict the candidate's server pool (live mode only)"),
    ] = None,
    replay: Annotated[
        bool,
        typer.Option(
            "--replay",
            help="Use deterministic replay against reference traces instead of live MCP servers",
        ),
    ] = False,
    reference_traces: Annotated[
        Path | None,
        typer.Option(
            "--reference-traces",
            help="JSONL of reference traces (e.g. traces/generated.jsonl). Required with --replay.",
        ),
    ] = None,
    judge: Annotated[
        bool,
        typer.Option(
            "--judge",
            help="After tier-1, run a tier-2 LLM effect-equivalence judge over failed tool_effect checkpoints.",
        ),
    ] = False,
    tier2_threshold: Annotated[
        float,
        typer.Option(
            "--tier2-threshold",
            help="Replay Tier-2 fuzzy-match threshold (0..1). Set to 1.0 to disable Tier-2 fallback.",
        ),
    ] = 0.75,
    simulate_misses: Annotated[
        bool,
        typer.Option(
            "--simulate-misses",
            help="Replay Tier-3: on a cache miss, an LLM synthesizes a plausible result flagged simulated=true (OFF by default; non-deterministic).",
        ),
    ] = False,
    judge_model: Annotated[
        str,
        typer.Option("--judge-model", help="LLM used by the tier-2 judge"),
    ] = DEFAULT_MODEL,
    repeat: Annotated[
        int,
        typer.Option(
            "--repeat",
            help="Run each spec K times and report pass^k (fraction of specs whose K runs all pass).",
        ),
    ] = 1,
    pool: Annotated[
        str | None,
        typer.Option(
            "--pool",
            help="Candidate tool-pool mode (replay only): gold | target | full. Default: the reference trace's own tools.",
        ),
    ] = None,
    p_alt: Annotated[
        float,
        typer.Option(
            "--p-alt",
            help="Target pool: fraction of distractors that are direct alternatives (same name, other server).",
        ),
    ] = 0.5,
    pool_size: Annotated[
        int,
        typer.Option("--pool-size", help="Target pool: number of distractor tools."),
    ] = 8,
    desc_level: Annotated[
        str | None,
        typer.Option(
            "--desc-level",
            help="Normalize offered tool descriptions (replay): a (surface) | b (semantic, LLM). Default: raw.",
        ),
    ] = None,
    output: Annotated[Path, typer.Option("--output", "-o", help="EvaluationResult JSONL output")] = Path(
        "evals/results.jsonl"
    ),
    candidate_traces: Annotated[
        Path | None,
        typer.Option(
            "--candidate-traces",
            help="Score externally-produced candidate trajectories from this JSONL instead of running an agent (matched to specs by seed_metadata.task_id, else by prompt).",
        ),
    ] = None,
    candidate_traces_out: Annotated[
        Path | None,
        typer.Option(
            "--candidate-traces-out",
            help="If set, also write the candidate trajectories here for inspection",
        ),
    ] = Path("evals/candidate_traces.jsonl"),
) -> None:
    """Run each candidate agent against its TaskSpec and score the trajectory.

    Two modes:

      live    (default) — candidate hits the manifest's MCP servers directly.
                          Subject to upstream nondeterminism (time, web data,
                          server state). Use for one-shot debugging.

      --replay          — candidate runs against a TraceReplayRecorder built
                          from each spec's source trace. Fully deterministic,
                          reproducible across re-runs and across candidates.
                          Required for fair multi-agent comparison.
    """
    if replay and reference_traces is None and candidate_traces is None:
        raise typer.BadParameter("--replay requires --reference-traces")
    if pool is not None and pool not in ("gold", "target", "full"):
        raise typer.BadParameter("--pool must be gold | target | full")
    if desc_level is not None and desc_level not in ("a", "b"):
        raise typer.BadParameter("--desc-level must be a | b")

    m = Manifest.load(manifest)
    configs = m.configs(servers)
    llm = OpenRouterClient(model=model)
    judge_llm = OpenRouterClient(model=judge_model) if judge else None
    server_tags = {e.server_id: list(e.tags) for e in m.servers}

    reference_index: dict[str, Trace] = {}
    if replay:
        assert reference_traces is not None
        reference_index = _load_traces_by_id(reference_traces)
        typer.echo(f"replay mode: indexed {len(reference_index)} reference trace(s)")
    if judge:
        typer.echo(f"tier-2 judge enabled: {judge_model}")

    async def _run() -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        if candidate_traces_out:
            candidate_traces_out.parent.mkdir(parents=True, exist_ok=True)

        # ---- ingestion mode: score external candidate traces, no agent run ----
        if candidate_traces is not None:
            by_task, by_prompt = index_candidate_traces(candidate_traces)
            typer.echo(
                f"ingestion mode: indexed candidate traces "
                f"({len(by_task)} by task_id, {len(by_prompt)} by prompt)"
            )
            passed = total = 0
            with specs.open("r", encoding="utf-8") as fin, output.open("a", encoding="utf-8") as fout:
                for raw in fin:
                    raw = raw.strip()
                    if not raw:
                        continue
                    spec = TaskSpec.model_validate_json(raw)
                    cands = by_task.get(str(spec.task_id)) or by_prompt.get(spec.prompt) or []
                    if not cands:
                        typer.echo(f"[task {spec.task_id}] skip: no candidate trace provided")
                        continue
                    total += 1
                    run_passes: list[bool] = []
                    for i, ctrace in enumerate(cands):
                        ev = run_eval(
                            spec,
                            ctrace,
                            candidate_model=ctrace.seed_metadata.get("llm_model") or model,
                            evaluation_mode="ingested",
                            server_tags=server_tags,
                        )
                        if judge_llm is not None:
                            ev.checkpoint_results = await upgrade_with_judge(
                                spec.checkpoints, ctrace, ev.checkpoint_results, llm=judge_llm
                            )
                            all_cps_pass = all(cr.passed for cr in ev.checkpoint_results)
                            no_mines = not any(mr.hit for mr in ev.minefield_results)
                            ev.passed = all_cps_pass and no_mines and ev.ordering_ok
                            ev.summary["checkpoints_passed"] = sum(
                                1 for cr in ev.checkpoint_results if cr.passed
                            )
                        ev.repeat_index = i
                        fout.write(ev.to_jsonl())
                        fout.write("\n")
                        run_passes.append(ev.passed)
                        typer.echo(
                            f"[task {spec.task_id}] trace {i + 1}/{len(cands)} → "
                            f"{'PASS' if ev.passed else 'FAIL'} "
                            f"checkpoints={ev.summary['checkpoints_passed']}/{ev.summary['checkpoints_total']}"
                        )
                    if run_passes and all(run_passes):
                        passed += 1
            typer.echo(f"done (ingested): {passed}/{total} specs passed → {output}")
            return

        catalog = (
            ToolCatalog.from_traces(reference_index.values(), manifest=m)
            if (pool is not None and replay)
            else None
        )

        async def _single_run(spec: TaskSpec):
            """One candidate run for `spec`. Returns (ev, trace, miss_count) or None to skip."""
            if replay:
                ref = reference_index.get(str(spec.source_trace_id))
                if ref is None:
                    return None
                cand_recorder = TraceReplayRecorder(
                    cache_traces=[ref],
                    goal=spec.prompt,
                    tier2_threshold=tier2_threshold,
                    simulator_llm=(llm if simulate_misses else None),
                )
                tool_surface = None
                if pool is not None and catalog is not None:
                    pool_entries = build_eval_pool(
                        spec,
                        catalog,
                        mode=pool,
                        p_alt=p_alt,
                        pool_size=pool_size,
                        seed=spec.task_id.int % (2**31),
                    )
                    tool_surface = pool_to_tool_surface(pool_entries, ref.tool_specs)
                if desc_level is not None:
                    base = (
                        tool_surface
                        if tool_surface is not None
                        else {sid: list(specs) for sid, specs in ref.tool_specs.items()}
                    )
                    tool_surface = await apply_normalization(base, desc_level, llm)
                result = await run_exploration(
                    goal=spec.prompt,
                    recorder=cand_recorder,
                    llm=llm,
                    budget=budget,
                    tool_surface=tool_surface,
                )
            else:
                result = await run_exploration(goal=spec.prompt, servers=configs, llm=llm, budget=budget)
            stash_exploration_in_trace(result)
            mode_tag = "replay" if replay else "live"
            if judge:
                mode_tag = f"{mode_tag}+judge"
            ev = run_eval(
                spec,
                result.trace,
                candidate_model=model,
                evaluation_mode=mode_tag,
                server_tags=server_tags,
            )
            if judge_llm is not None:
                ev.checkpoint_results = await upgrade_with_judge(
                    spec.checkpoints, result.trace, ev.checkpoint_results, llm=judge_llm
                )
                all_cps_pass = all(cr.passed for cr in ev.checkpoint_results)
                no_mines = not any(mr.hit for mr in ev.minefield_results)
                ev.passed = all_cps_pass and no_mines and ev.ordering_ok
                ev.summary["checkpoints_passed"] = sum(1 for cr in ev.checkpoint_results if cr.passed)
                ev.summary["tier2_judgments"] = sum(1 for cr in ev.checkpoint_results if cr.tier == 2)
                ev.summary["tier2_upgrades"] = sum(
                    1 for cr in ev.checkpoint_results if cr.tier == 2 and cr.passed
                )
            miss_count = sum(
                1 for s in result.trace.steps if s.result is not None and s.result.get("replay_cache_miss")
            )
            return ev, result.trace, miss_count

        passed = total = 0
        cache_miss_steps = 0
        with specs.open("r", encoding="utf-8") as fin, output.open("a", encoding="utf-8") as fout:
            cand_fh = candidate_traces_out.open("a", encoding="utf-8") if candidate_traces_out else None
            try:
                for raw in fin:
                    raw = raw.strip()
                    if not raw:
                        continue
                    total += 1
                    spec = TaskSpec.model_validate_json(raw)
                    typer.echo(
                        f"[task {spec.task_id}] prompt: {spec.prompt[:90]}{'…' if len(spec.prompt) > 90 else ''}"
                    )
                    run_passes: list[bool] = []
                    for _rep in range(max(1, repeat)):
                        out = await _single_run(spec)
                        if out is None:
                            typer.echo(
                                f"  skip: no reference trace for source_trace_id={spec.source_trace_id}"
                            )
                            break
                        ev, ctrace, miss_count = out
                        ev.repeat_index = _rep
                        ctrace.seed_metadata.setdefault("task_id", str(spec.task_id))
                        fout.write(ev.to_jsonl())
                        fout.write("\n")
                        if cand_fh is not None:
                            cand_fh.write(ctrace.to_jsonl())
                            cand_fh.write("\n")
                        cache_miss_steps += miss_count
                        run_passes.append(ev.passed)
                        rep_tag = f" [run {_rep + 1}/{repeat}]" if repeat > 1 else ""
                        typer.echo(
                            f"  → {'PASS' if ev.passed else 'FAIL'}{rep_tag} "
                            f"checkpoints={ev.summary['checkpoints_passed']}/{ev.summary['checkpoints_total']} "
                            f"minefields={ev.summary['minefields_hit']}/{ev.summary['minefields_total']} "
                            f"ordering={'ok' if ev.ordering_ok else 'fail'}"
                            + (f" misses={miss_count}" if replay and miss_count else "")
                        )
                        if repeat == 1:
                            for cr in ev.checkpoint_results:
                                flag = "✓" if cr.passed else "✗"
                                typer.echo(f"    {flag} [{cr.kind}] {cr.checkpoint_id}: {cr.reason}")
                    spec_passk = bool(run_passes) and all(run_passes)
                    if spec_passk:
                        passed += 1
                    if repeat > 1:
                        c = sum(1 for p in run_passes if p)
                        typer.echo(
                            f"  pass^{repeat} = {'PASS' if spec_passk else 'fail'} ({c}/{repeat} runs passed)"
                        )
            finally:
                if cand_fh is not None:
                    cand_fh.close()
        suffix = f" (cache misses total: {cache_miss_steps})" if replay else ""
        label = f"pass^{repeat}" if repeat > 1 else "passed"
        typer.echo(f"done: {passed}/{total} specs {label} → {output}{suffix}")

    asyncio.run(_run())


@app.command()
def curve(
    specs: Annotated[Path, typer.Argument(help="TaskSpec JSONL")],
    reference_traces: Annotated[
        Path, typer.Option("--reference-traces", help="JSONL of reference traces (required)")
    ],
    manifest: Annotated[Path, typer.Option("--manifest", "-m")] = Path("manifests/local.json"),
    model: Annotated[str, typer.Option("--model", help="Candidate LLM")] = DEFAULT_MODEL,
    budget: Annotated[int, typer.Option("--budget")] = 12,
    p_alts: Annotated[
        str, typer.Option("--p-alts", help="Comma-separated P_alt grid")
    ] = "0,0.25,0.5,0.75,1.0",
    pool_size: Annotated[int, typer.Option("--pool-size")] = 8,
    desc_level: Annotated[str | None, typer.Option("--desc-level", help="a | b | (raw)")] = None,
    output: Annotated[Path, typer.Option("--output", "-o")] = Path("reports/curve.md"),
) -> None:
    """Sweep P_alt in Target-pool replay and emit accuracy/SAE degradation curves.

    For each P_alt point, every spec is run with a target pool of that alternative
    density and scored; results aggregate into accuracy/SAE-vs-P_alt with Wilson
    CIs, complexity-bin normalized. Replay-only (deterministic world)."""
    m = Manifest.load(manifest)
    server_tags = {e.server_id: list(e.tags) for e in m.servers}
    refs = _load_traces_by_id(reference_traces)
    catalog = ToolCatalog.from_traces(refs.values(), manifest=m)
    llm = OpenRouterClient(model=model)
    grid = [float(x) for x in p_alts.split(",") if x.strip()]
    spec_list = [
        TaskSpec.model_validate_json(line)
        for line in specs.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    async def _run() -> None:
        samples: list[dict] = []
        for p in grid:
            ran = passed = 0
            for spec in spec_list:
                ref = refs.get(str(spec.source_trace_id))
                if ref is None:
                    continue
                pool_entries = build_eval_pool(
                    spec,
                    catalog,
                    mode="target",
                    p_alt=p,
                    pool_size=pool_size,
                    seed=spec.task_id.int % (2**31),
                )
                surface = pool_to_tool_surface(pool_entries, ref.tool_specs)
                if desc_level is not None:
                    surface = await apply_normalization(surface, desc_level, llm)
                rec = TraceReplayRecorder(cache_traces=[ref], goal=spec.prompt)
                result = await run_exploration(
                    goal=spec.prompt, recorder=rec, llm=llm, budget=budget, tool_surface=surface
                )
                stash_exploration_in_trace(result)
                ev = run_eval(
                    spec,
                    result.trace,
                    candidate_model=model,
                    evaluation_mode="curve",
                    server_tags=server_tags,
                )
                samples.append(
                    {
                        "p_alt": p,
                        "passed": ev.passed,
                        "had_sae": ev.had_sae,
                        "bin": complexity_bin(spec.complexity.trace_depth),
                    }
                )
                ran += 1
                passed += int(ev.passed)
            typer.echo(f"P_alt={p:.2f}: {passed}/{ran} passed")

        cv = aggregate_curve(samples)
        output.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# P_alt degradation curve",
            "",
            f"specs={len(spec_list)} model=`{model}` desc_level={desc_level or 'raw'} pool_size={pool_size}",
            "",
            "| P_alt | n | accuracy [95% CI] | SAE rate [95% CI] | macro-acc |",
            "|---|---|---|---|---|",
        ]
        for pt in cv["points"]:
            lo, hi = pt["accuracy_ci"]
            slo, shi = pt["sae_ci"]
            lines.append(
                f"| {pt['p_alt']:.2f} | {pt['n']} | {pt['accuracy'] * 100:.0f}% "
                f"[{lo * 100:.0f}-{hi * 100:.0f}] | {pt['sae_rate'] * 100:.0f}% "
                f"[{slo * 100:.0f}-{shi * 100:.0f}] | {pt['macro_accuracy'] * 100:.0f}% |"
            )
        text = "\n".join(lines) + "\n"
        output.write_text(text, encoding="utf-8")
        typer.echo("\n" + text)
        typer.echo(f"wrote curve -> {output}")

    asyncio.run(_run())


@app.command()
def ablate(
    specs: Annotated[Path, typer.Argument(help="TaskSpec JSONL")],
    reference_traces: Annotated[
        Path, typer.Option("--reference-traces", help="JSONL of reference traces (required)")
    ],
    manifest: Annotated[Path, typer.Option("--manifest", "-m")] = Path("manifests/local.json"),
    model: Annotated[str, typer.Option("--model")] = DEFAULT_MODEL,
    budget: Annotated[int, typer.Option("--budget")] = 12,
    pool_size: Annotated[int, typer.Option("--pool-size")] = 8,
    output: Annotated[Path, typer.Option("--output", "-o")] = Path("reports/ablation.md"),
) -> None:
    """Run the 6 distractor strategies in replay; compare SAE rates with Holm."""
    m = Manifest.load(manifest)
    server_tags = {e.server_id: list(e.tags) for e in m.servers}
    refs = _load_traces_by_id(reference_traces)
    catalog = ToolCatalog.from_traces(refs.values(), manifest=m)
    llm = OpenRouterClient(model=model)
    strategies = ["random", "hard_neg", "cross_domain", "same_name", "sibling", "stratified"]
    spec_list = [
        TaskSpec.model_validate_json(line)
        for line in specs.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    async def _run() -> None:
        sae_stats = {s: [0, 0] for s in strategies}
        acc_stats = {s: [0, 0] for s in strategies}
        for strat in strategies:
            for spec in spec_list:
                ref = refs.get(str(spec.source_trace_id))
                if ref is None:
                    continue
                pool = build_strategy_pool(
                    spec,
                    catalog,
                    strategy=strat,
                    pool_size=pool_size,
                    seed=spec.task_id.int % (2**31),
                )
                surface = pool_to_tool_surface(pool, ref.tool_specs)
                rec = TraceReplayRecorder(cache_traces=[ref], goal=spec.prompt)
                result = await run_exploration(
                    goal=spec.prompt, recorder=rec, llm=llm, budget=budget, tool_surface=surface
                )
                stash_exploration_in_trace(result)
                ev = run_eval(
                    spec,
                    result.trace,
                    candidate_model=model,
                    evaluation_mode=f"ablate:{strat}",
                    server_tags=server_tags,
                )
                sae_stats[strat][0] += int(ev.had_sae)
                sae_stats[strat][1] += 1
                acc_stats[strat][0] += int(ev.passed)
                acc_stats[strat][1] += 1
            typer.echo(
                f"{strat}: SAE {sae_stats[strat][0]}/{sae_stats[strat][1]}  "
                f"pass {acc_stats[strat][0]}/{acc_stats[strat][1]}"
            )

        contrasts = compare_strategies({s: (sae_stats[s][0], sae_stats[s][1]) for s in strategies})
        output.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# Sampling-strategy ablation (SAE)",
            "",
            f"specs={len(spec_list)} model=`{model}` pool_size={pool_size}",
            "",
            "Mixed-effects logistic regression is deferred (needs statsmodels); "
            "per-contrast Fisher/chi-square + Holm below.",
            "",
            "| strategy | SAE rate | accuracy |",
            "|---|---|---|",
        ]
        for s in strategies:
            sae = sae_stats[s][0] / sae_stats[s][1] if sae_stats[s][1] else 0.0
            ac = acc_stats[s][0] / acc_stats[s][1] if acc_stats[s][1] else 0.0
            lines.append(
                f"| {s} | {sae * 100:.0f}% ({sae_stats[s][0]}/{sae_stats[s][1]}) | {ac * 100:.0f}% |"
            )
        lines += [
            "",
            "| contrast | SAE A | SAE B | test | p | p(Holm) | sig |",
            "|---|---|---|---|---|---|---|",
        ]
        for c in contrasts:
            lines.append(
                f"| {c['a']} vs {c['b']} | {c['sae_rate_a'] * 100:.0f}% | {c['sae_rate_b'] * 100:.0f}% | "
                f"{c['test']} | {c['p']:.3g} | {c['p_holm']:.3g} | {'yes' if c['significant'] else 'no'} |"
            )
        lines += [
            "",
            f"Power note: ~{power_n(0.5, 0.65)} specs/cell to detect a 15pp SAE difference "
            "(0.50 vs 0.65, two-sided α=0.05, power=0.80).",
        ]
        text = "\n".join(lines) + "\n"
        output.write_text(text, encoding="utf-8")
        typer.echo("\n" + text)
        typer.echo(f"wrote ablation -> {output}")

    asyncio.run(_run())


@app.command()
def verify(
    manifest: Annotated[Path, typer.Option("--manifest", "-m")] = Path("manifests/local.json"),
    servers: Annotated[
        list[str] | None, typer.Option("--server", help="Repeatable: restrict to specific server_ids")
    ] = None,
    server_timeout: Annotated[float, typer.Option("--server-timeout")] = 90.0,
    min_pass_rate: Annotated[float, typer.Option("--min-pass-rate")] = 0.5,
    use_llm: Annotated[
        bool, typer.Option("--llm", help="Synthesize tool args with an LLM (realistic values)")
    ] = False,
    model: Annotated[str, typer.Option("--model")] = DEFAULT_MODEL,
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Treat auth/credential/not-found messages in tool RESULTS as failures"),
    ] = False,
    require_all: Annotated[
        bool,
        typer.Option(
            "--require-all", help="Keep a server only if ALL exercised (non-destructive) tools pass"
        ),
    ] = False,
    output: Annotated[Path, typer.Option("--output", "-o")] = Path("reports/verification.md"),
    json_out: Annotated[Path | None, typer.Option("--json-out")] = Path("reports/verification.jsonl"),
) -> None:
    """Boot each manifest server and exercise every tool; report pass/fail.

    A server passes if it initializes, exposes >=1 tool, and >= --min-pass-rate of
    its non-skipped tools return without error (destructive tools are skipped
    unless sandboxed)."""
    m = Manifest.load(manifest)
    runnable, skipped_creds = m.gate_credentials(servers)
    for sid, missing in skipped_creds:
        typer.echo(f"  SKIP  {sid:18s} missing env: {', '.join(missing)}")
    configs = [e.to_config() for e in runnable]
    sandbox_by_id = {e.server_id: e.sandbox for e in runnable}
    vllm = OpenRouterClient(model=model) if use_llm else None

    async def _run() -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        if json_out:
            json_out.parent.mkdir(parents=True, exist_ok=True)
        reps: list[dict] = []
        jf = json_out.open("w", encoding="utf-8") if json_out else None
        try:
            for cfg in configs:
                try:
                    rep = await asyncio.wait_for(
                        verify_server(
                            cfg,
                            sandbox=sandbox_by_id.get(cfg.server_id, False),
                            min_tool_pass_rate=min_pass_rate,
                            llm=vllm,
                            strict=strict,
                            require_all=require_all,
                        ),
                        timeout=server_timeout,
                    )
                except TimeoutError:
                    rep = {
                        "server_id": cfg.server_id,
                        "ok": False,
                        "initialized": False,
                        "tools": [],
                        "reason": f"server timeout >{server_timeout:.0f}s",
                    }
                except Exception as e:
                    rep = {
                        "server_id": cfg.server_id,
                        "ok": False,
                        "initialized": False,
                        "tools": [],
                        "reason": f"{type(e).__name__}: {str(e)[:140]}",
                    }
                reps.append(rep)
                if jf:
                    jf.write(json.dumps(rep) + "\n")
                typer.echo(
                    f"  {'PASS' if rep['ok'] else 'FAIL'}  {cfg.server_id:18s} {rep.get('reason', '')}"
                )
        finally:
            if jf:
                jf.close()
        npass = sum(1 for r in reps if r["ok"])
        lines = [
            "# Server verification",
            "",
            f"{npass}/{len(reps)} servers passed (initialized + tools exercised).",
            "",
            "| server | ok | tools ok | reason |",
            "|---|---|---|---|",
        ]
        for r in reps:
            lines.append(
                f"| `{r['server_id']}` | {'OK' if r['ok'] else 'X'} | "
                f"{r.get('ok_count', 0)}/{r.get('tool_count', 0)} | {r.get('reason', '')} |"
            )
        output.write_text("\n".join(lines) + "\n", encoding="utf-8")
        typer.echo(f"\n{npass}/{len(reps)} passed -> {output}")

    asyncio.run(_run())


@app.command()
def subset(
    manifest: Annotated[Path, typer.Option("--manifest", "-m")] = Path("manifests/servers.json"),
    domain: Annotated[
        list[str] | None, typer.Option("--domain", help="Repeatable: keep servers tagged domain:<x>")
    ] = None,
    dyn: Annotated[
        list[str] | None,
        typer.Option("--dyn", help="Repeatable: dynamism in {static,live_read,stateful_write}"),
    ] = None,
    pkg: Annotated[str | None, typer.Option("--pkg", help="Package kind: npm | pypi")] = None,
    size: Annotated[
        list[str] | None, typer.Option("--size", help="Repeatable: small | medium | large")
    ] = None,
    has_deps: Annotated[
        bool, typer.Option("--has-deps", help="Only servers with discovered tool-dependencies")
    ] = False,
    has_alt: Annotated[
        bool, typer.Option("--has-alt", help="Only servers with a cross-server alternative (SAE)")
    ] = False,
    tag: Annotated[
        list[str] | None, typer.Option("--tag", help="Repeatable: an arbitrary tag that must be present")
    ] = None,
    exclude_tag: Annotated[
        list[str] | None, typer.Option("--exclude-tag", help="Repeatable: drop servers carrying this tag")
    ] = None,
    limit: Annotated[int | None, typer.Option("--limit", help="Cap to the first N (stable order)")] = None,
    output: Annotated[Path, typer.Option("--output", "-o")] = Path("manifests/subset.json"),
) -> None:
    """Filter a server manifest by tag axes (domain / dyn / pkg / size / deps / alt)
    into a subset manifest you can pass to goal-gen / explore / eval via --manifest.
    All predicates AND together; repeatable options OR within an axis."""
    m = Manifest.load(manifest)

    def keep(e: ServerEntry) -> bool:
        tags = set(e.tags)
        if domain and not ({f"domain:{d}" for d in domain} & tags):
            return False
        if dyn and e.dynamism.value not in set(dyn):
            return False
        if pkg and f"pkg:{pkg}" not in tags:
            return False
        if size and not ({f"size:{s}" for s in size} & tags):
            return False
        if has_deps and "deps:yes" not in tags:
            return False
        if has_alt and "alt:yes" not in tags:
            return False
        if tag and not set(tag) <= tags:
            return False
        if exclude_tag and (set(exclude_tag) & tags):
            return False
        return True

    chosen = [e for e in m.servers if keep(e)]
    if limit is not None:
        chosen = chosen[:limit]
    output.parent.mkdir(parents=True, exist_ok=True)
    Manifest(manifest_version=m.manifest_version, servers=chosen).dump(output)
    typer.echo(f"subset: {len(chosen)}/{len(m.servers)} servers -> {output}")


if __name__ == "__main__":
    app()
