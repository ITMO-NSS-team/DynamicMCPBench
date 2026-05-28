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

from dmcp.distiller import DistillationError
from dmcp.distiller import distill as run_distill
from dmcp.evaluator import evaluate as run_eval
from dmcp.explorer import explore as run_exploration
from dmcp.explorer import stash_exploration_in_trace
from dmcp.goals import Goals
from dmcp.llm import DEFAULT_MODEL, OpenRouterClient
from dmcp.manifest import Manifest
from dmcp.recorder import (
    SseServer,
    StdioServer,
    StreamableHttpServer,
    TraceRecorder,
)
from dmcp.replay import TraceReplayRecorder
from dmcp.report import aggregate_markdown
from dmcp.spec import TaskSpec
from dmcp.trace import Trace, TransportKind

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
    arguments_json: Annotated[
        str, typer.Option("--args", help="JSON object of tool arguments")
    ] = "{}",
    output: Annotated[
        Path, typer.Option("--output", "-o", help="Destination JSONL file")
    ] = Path("traces.jsonl"),
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
def report(
    specs: Annotated[Path, typer.Option("--specs", help="TaskSpec JSONL produced by `dmcp distill` or `dmcp generate`")],
    evals: Annotated[list[Path], typer.Option("--evals", help="Repeatable: EvaluationResult JSONL files (one per candidate model)")],
    output: Annotated[Path, typer.Option("--output", "-o", help="Markdown output path")] = Path("reports/leaderboard.md"),
) -> None:
    """Aggregate one or more `dmcp eval` runs into a markdown leaderboard."""
    md = aggregate_markdown(specs_path=specs, eval_paths=evals)
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
def crawl() -> None:
    """[planned] Vet live MCP servers from the registry."""
    _not_yet("crawl")


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
    output: Annotated[
        Path, typer.Option("--output", "-o", help="Trace JSONL output path")
    ] = Path("traces/explore.jsonl"),
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
    manifest: Annotated[Path, typer.Option("--manifest", "-m", help="Manifest used for dynamism tagging")] = Path(
        "manifests/local.json"
    ),
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
    explore_model: Annotated[str, typer.Option("--explore-model", help="LLM for exploration")] = DEFAULT_MODEL,
    distill_model: Annotated[str, typer.Option("--distill-model", help="LLM for distillation")] = DEFAULT_MODEL,
    budget: Annotated[int, typer.Option("--budget", help="Default per-goal LLM turn budget")] = 12,
    traces_out: Annotated[Path, typer.Option("--traces-out", help="JSONL: every recorded trace, success or not")] = Path("traces/generated.jsonl"),
    specs_out: Annotated[Path, typer.Option("--specs-out", help="JSONL: distilled TaskSpecs only")] = Path("specs/generated.jsonl"),
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
                    f"goal {entry.goal_id!r} references unknown server {sid!r} "
                    f"(not in manifest {manifest})"
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
                    f"  explored: outcome={result.outcome} successful_calls="
                    f"{result.successful_tool_calls}"
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
    output: Annotated[
        Path, typer.Option("--output", "-o", help="EvaluationResult JSONL output")
    ] = Path("evals/results.jsonl"),
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
    if replay and reference_traces is None:
        raise typer.BadParameter("--replay requires --reference-traces")

    m = Manifest.load(manifest)
    configs = m.configs(servers)
    llm = OpenRouterClient(model=model)

    reference_index: dict[str, Trace] = {}
    if replay:
        assert reference_traces is not None
        reference_index = _load_traces_by_id(reference_traces)
        typer.echo(f"replay mode: indexed {len(reference_index)} reference trace(s)")

    async def _run() -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        if candidate_traces_out:
            candidate_traces_out.parent.mkdir(parents=True, exist_ok=True)
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
                    typer.echo(f"[task {spec.task_id}] prompt: {spec.prompt[:90]}{'…' if len(spec.prompt) > 90 else ''}")

                    if replay:
                        ref = reference_index.get(str(spec.source_trace_id))
                        if ref is None:
                            typer.echo(f"  skip: no reference trace for source_trace_id={spec.source_trace_id}")
                            continue
                        cand_recorder = TraceReplayRecorder(
                            cache_traces=[ref],
                            goal=spec.prompt,
                        )
                        result = await run_exploration(
                            goal=spec.prompt,
                            recorder=cand_recorder,
                            llm=llm,
                            budget=budget,
                        )
                    else:
                        result = await run_exploration(
                            goal=spec.prompt,
                            servers=configs,
                            llm=llm,
                            budget=budget,
                        )
                    stash_exploration_in_trace(result)
                    ev = run_eval(
                        spec,
                        result.trace,
                        candidate_model=model,
                        evaluation_mode="replay" if replay else "live",
                    )
                    fout.write(ev.to_jsonl())
                    fout.write("\n")
                    if cand_fh is not None:
                        cand_fh.write(result.trace.to_jsonl())
                        cand_fh.write("\n")
                    if ev.passed:
                        passed += 1
                    miss_count = sum(
                        1 for s in result.trace.steps
                        if s.result is not None and s.result.get("replay_cache_miss")
                    )
                    cache_miss_steps += miss_count
                    typer.echo(
                        f"  → {'PASS' if ev.passed else 'FAIL'} "
                        f"checkpoints={ev.summary['checkpoints_passed']}/{ev.summary['checkpoints_total']} "
                        f"minefields={ev.summary['minefields_hit']}/{ev.summary['minefields_total']} "
                        f"ordering={'ok' if ev.ordering_ok else 'fail'}"
                        + (f" misses={miss_count}" if replay and miss_count else "")
                    )
                    for cr in ev.checkpoint_results:
                        flag = "✓" if cr.passed else "✗"
                        typer.echo(f"    {flag} [{cr.kind}] {cr.checkpoint_id}: {cr.reason}")
            finally:
                if cand_fh is not None:
                    cand_fh.close()
        suffix = f" (cache misses total: {cache_miss_steps})" if replay else ""
        typer.echo(f"done: {passed}/{total} specs passed → {output}{suffix}")

    asyncio.run(_run())


if __name__ == "__main__":
    app()
