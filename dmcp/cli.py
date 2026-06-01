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
from typing import Annotated

import typer

from dmcp.discovery import MCPRegistryClient
from dmcp.distiller import DistillationError
from dmcp.distiller import distill as run_distill
from dmcp.evaluator import evaluate as run_eval
from dmcp.explorer import explore as run_exploration
from dmcp.explorer import stash_exploration_in_trace
from dmcp.goal_gen import generate_goals as run_goal_gen
from dmcp.goals import Goals
from dmcp.install import InstallStatus, install_server
from dmcp.judge import upgrade_with_judge
from dmcp.llm import DEFAULT_MODEL, OpenRouterClient
from dmcp.manifest import Manifest
from dmcp.recorder import (
    SseServer,
    StdioServer,
    StreamableHttpServer,
    TraceRecorder,
)
from dmcp.refresh import decay_summary, refresh_one
from dmcp.replay import TraceReplayRecorder
from dmcp.report import aggregate_markdown
from dmcp.spec import TaskSpec
from dmcp.trace import Trace, TransportKind
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

    m = Manifest.load(manifest)
    configs = m.configs(servers)
    llm = OpenRouterClient(model=model)
    judge_llm = OpenRouterClient(model=judge_model) if judge else None

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
                result = await run_exploration(
                    goal=spec.prompt, recorder=cand_recorder, llm=llm, budget=budget
                )
            else:
                result = await run_exploration(goal=spec.prompt, servers=configs, llm=llm, budget=budget)
            stash_exploration_in_trace(result)
            mode_tag = "replay" if replay else "live"
            if judge:
                mode_tag = f"{mode_tag}+judge"
            ev = run_eval(spec, result.trace, candidate_model=model, evaluation_mode=mode_tag)
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


if __name__ == "__main__":
    app()
