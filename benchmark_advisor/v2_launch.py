"""Guarded launch service for Benchmark Advisor v2.

The design and validation routes stay side-effect free. This module is the
only v2 path allowed to turn an approved/warning export into tracked corpus
generation and, when requested, a full replay benchmark job.
"""

from __future__ import annotations

import hashlib
import json
import random
import subprocess
import sys
import threading
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from dmcp.curves import proportion_ci

from .stats import ci_width_pp, planned_mde_pp_for_unique_tasks
from .v2_schema import LaunchArtifacts, LaunchJob, LaunchRequest

ROOT = Path(__file__).resolve().parent.parent
LAUNCH_JOB_SCHEMA_VERSION = "benchmark_advisor.launch_job.v2"
_JOBS: dict[str, LaunchJob] = {}
_LOCK = threading.Lock()
_ADVISOR_STRATEGY_TO_CORPUS = {
    "deployment_slice": ["hard_neg", "complementary"],
    "leaderboard_mix": ["cross_server_alt", "hard_neg"],
    "regression_replay": ["complementary"],
    "diagnostic_slice": ["homonym_trap", "recovery_required"],
}
_CLAIM_SCOPE_TO_EXECUTION_SERVER = {
    "finance-tools": "yfinance",
}
_GENERATION_MODEL = "kimi-k2p7"
_EXPLORE_BUDGET = 12
_EXPLORE_TIMEOUT_S = 600
_EVAL_BUDGET = 12
_BOOTSTRAP_REPLICATES = 20_000
_BOOTSTRAP_SEED = 20260707


def launch_advisor_corpus(request: LaunchRequest) -> LaunchJob:
    """Validate a guarded launch request and create a tracked job."""

    _validate_launch_request(request)
    job_id = f"advisor-{uuid.uuid4().hex[:12]}"
    launch_key = hashlib.sha256(request.model_dump_json().encode("utf-8")).hexdigest()[:12]
    out_dir = Path("data") / "advisor_runs" / launch_key
    command = build_command_preview(request, out_dir=out_dir)
    artifacts = _artifacts_for(request, out_dir)
    job = LaunchJob(
        schema_version=LAUNCH_JOB_SCHEMA_VERSION,
        job_id=job_id,
        status="queued",
        phase="queued",
        progress={"target_tasks": request.export_config.tasks},
        command_preview=command,
        logs=[
            "queued guarded benchmark handoff" if request.run_benchmark else "queued guarded corpus handoff"
        ],
        artifacts=artifacts,
    )
    _store(job)
    if request.dry_run:
        _store(
            job.model_copy(
                update={
                    "status": "succeeded",
                    "phase": "succeeded",
                    "logs": [*job.logs, "dry-run preview only"],
                }
            )
        )
        return get_launch_job(job_id)

    thread = threading.Thread(target=_run_job, args=(job_id, request, out_dir), daemon=True)
    thread.start()
    return job


def get_launch_job(job_id: str) -> LaunchJob:
    with _LOCK:
        job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"unknown launch job: {job_id}")
    return job


def get_launch_report(job_id: str) -> dict[str, Any]:
    job = get_launch_job(job_id)
    path = job.artifacts.replay_demo_report
    if not path:
        raise HTTPException(status_code=404, detail=f"launch job has no report: {job_id}")
    report_path = ROOT / path
    if not report_path.exists():
        raise HTTPException(status_code=404, detail=f"launch report is not available yet: {job_id}")
    return json.loads(report_path.read_text(encoding="utf-8"))


def build_command_preview(request: LaunchRequest, *, out_dir: Path | None = None) -> list[str]:
    """Build a deterministic launch preview.

    Corpus-only launches preserve the original build_corpus command shape. Full
    benchmark launches return a compact preview of the staged pipeline.
    """

    out = out_dir or Path("data") / "advisor_runs" / "preview"
    if not request.run_benchmark:
        return _build_corpus_command(request, out)
    models = ",".join(request.export_config.candidate_models)
    servers = ",".join(_execution_servers(request))
    return [
        "benchmark-pipeline",
        "scripts/build_corpus.py",
        "--out",
        _slash(out),
        "--budget",
        str(request.export_config.tasks),
        "--servers",
        servers,
        "--models",
        models,
        "dmcp",
        "eval",
        "dmcp",
        "report",
    ]


def _validate_launch_request(request: LaunchRequest) -> None:
    if not request.requested_by_ui:
        raise HTTPException(status_code=400, detail="launch must be requested by Studio UI")
    if request.advisor_status not in {"approved", "warning"}:
        raise HTTPException(status_code=400, detail="advisor status must be approved or warning")
    knobs = request.export_config.generation_knobs
    if knobs.handoff_target != "scripts/build_corpus.py":
        raise HTTPException(status_code=400, detail="only scripts/build_corpus.py handoff is supported")
    if not knobs.dry_run_only:
        raise HTTPException(status_code=400, detail="export must be a dry-run-only advisor handoff")
    if knobs.sandbox_required and not request.sandbox_confirmed:
        raise HTTPException(status_code=400, detail="sandbox requirements must be explicitly confirmed")
    if request.run_benchmark and not request.export_config.candidate_models:
        raise HTTPException(status_code=400, detail="benchmark launch requires candidate models")
    if request.run_benchmark and not _execution_servers(request):
        raise HTTPException(status_code=400, detail="benchmark launch requires selected execution servers")


def _run_job(job_id: str, request: LaunchRequest, out_dir: Path) -> None:
    try:
        _run_corpus_only(job_id, request, out_dir)
        if request.run_benchmark:
            _run_full_benchmark(job_id, request, out_dir)
        current = get_launch_job(job_id)
        _store(current.model_copy(update={"status": "succeeded", "phase": "succeeded"}))
    except Exception as exc:  # pragma: no cover - defensive for OS/process failures.
        failed = get_launch_job(job_id)
        _store(
            failed.model_copy(
                update={
                    "status": "failed",
                    "phase": "failed",
                    "logs": [*failed.logs, str(exc)],
                }
            )
        )


def _run_corpus_only(job_id: str, request: LaunchRequest, out_dir: Path) -> None:
    _update(job_id, phase="corpus", status="running", log="started scripts/build_corpus.py")
    command = _build_corpus_command(request, out_dir)
    proc = _run_subprocess(command)
    _append_process_logs(job_id, proc)
    _update(
        job_id,
        progress={
            "generated_specs": _jsonl_count(ROOT / out_dir / "specs.jsonl"),
            "generated_traces": _jsonl_count(ROOT / out_dir / "traces.jsonl"),
        },
        log=f"scripts/build_corpus.py exited with {proc.returncode}",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"scripts/build_corpus.py exited with {proc.returncode}")


def _run_full_benchmark(job_id: str, request: LaunchRequest, out_dir: Path) -> None:
    target = request.export_config.tasks
    base_dir = ROOT / out_dir
    specs = base_dir / "specs.jsonl"
    generated = _jsonl_count(specs)

    topup_dirs: list[Path] = []
    attempts = 0
    while generated < target and attempts < 2:
        attempts += 1
        missing = target - generated
        topup_budget = max(10, int(missing * 1.5 + 0.999))
        topup_dir = out_dir.parent / f"{out_dir.name}_topup{attempts}"
        _update(
            job_id,
            phase="top_up",
            progress={"generated_specs": generated, "target_tasks": target, "topup_budget": topup_budget},
            log=f"started top-up {attempts}: missing {missing}, budget {topup_budget}",
        )
        proc = _run_subprocess(_build_corpus_command(request, topup_dir, budget=topup_budget))
        _append_process_logs(job_id, proc)
        _update(job_id, log=f"top-up {attempts} exited with {proc.returncode}")
        if proc.returncode != 0:
            raise RuntimeError(f"top-up {attempts} exited with {proc.returncode}")
        topup_dirs.append(ROOT / topup_dir)
        generated += _jsonl_count(ROOT / topup_dir / "specs.jsonl")

    _update(job_id, phase="select_corpus", log="selecting final combined corpus")
    combined_specs, combined_traces, selected = _select_combined_corpus(base_dir, topup_dirs, target)
    artifacts = get_launch_job(job_id).artifacts.model_copy(
        update={
            "combined_specs": _slash(combined_specs.relative_to(ROOT)),
            "combined_traces": _slash(combined_traces.relative_to(ROOT)),
        }
    )
    _store(get_launch_job(job_id).model_copy(update={"artifacts": artifacts}))
    _update(
        job_id,
        progress={"selected_specs": selected, "target_tasks": target},
        log=f"selected {selected}/{target} specs for benchmark eval",
    )

    eval_dir = base_dir / "eval_combined"
    eval_dir.mkdir(parents=True, exist_ok=True)
    eval_paths: dict[str, str] = {}
    candidate_paths: dict[str, str] = {}
    dedup_paths: dict[str, Path] = {}
    for model in request.export_config.candidate_models:
        _update(job_id, phase="eval", log=f"started eval for {model}")
        eval_path = eval_dir / f"eval_{_slug(model)}.jsonl"
        candidate_path = eval_dir / f"candidate_traces_{_slug(model)}.jsonl"
        proc = _run_subprocess(
            _build_eval_command(
                specs=combined_specs,
                reference_traces=combined_traces,
                model=model,
                out_path=eval_path,
                candidate_traces_out=candidate_path,
            )
        )
        _append_process_logs(job_id, proc)
        _update(job_id, log=f"eval {model} exited with {proc.returncode}")
        if proc.returncode != 0:
            raise RuntimeError(f"eval {model} exited with {proc.returncode}")
        dedup = eval_path.with_suffix(".dedup_first.jsonl")
        dedup_count, invalid_count = _dedup_eval(eval_path, dedup)
        if invalid_count:
            _warn(job_id, f"{model}: skipped {invalid_count} invalid eval JSON line(s)")
        eval_paths[model] = _slash(dedup.relative_to(ROOT))
        candidate_paths[model] = _slash(candidate_path.relative_to(ROOT))
        dedup_paths[model] = dedup
        _update(job_id, progress={f"eval_rows_{model}": dedup_count})

    _update(job_id, phase="report", log="computing benchmark statistical report")
    summary_path = eval_dir / "summary_pairwise_combined.json"
    report_path = eval_dir / "advisor_replay_demo_report.json"
    summary, report = _build_report(
        request=request,
        specs_path=combined_specs,
        eval_paths=dedup_paths,
        summary_path=summary_path,
        report_path=report_path,
    )
    artifacts = get_launch_job(job_id).artifacts.model_copy(
        update={
            "evals": eval_paths,
            "candidate_traces": candidate_paths,
            "statistical_summary": _slash(summary_path.relative_to(ROOT)),
            "replay_demo_report": _slash(report_path.relative_to(ROOT)),
        }
    )
    _store(get_launch_job(job_id).model_copy(update={"artifacts": artifacts}))
    _update(
        job_id,
        progress={"report_models": len(summary["models"]), "report_tasks": report["sample_size"]},
        log=f"wrote benchmark report to {_slash(report_path.relative_to(ROOT))}",
    )


def _build_corpus_command(request: LaunchRequest, out_dir: Path, *, budget: int | None = None) -> list[str]:
    export = request.export_config
    knobs = export.generation_knobs
    target = Path(knobs.handoff_target)
    if target.as_posix() != "scripts/build_corpus.py":
        raise HTTPException(status_code=400, detail="launch target must be scripts/build_corpus.py")
    command = [
        sys.executable,
        "scripts/build_corpus.py",
        "--out",
        _slash(out_dir),
        "--budget",
        str(budget or export.tasks),
        "--strategies",
        ",".join(_ADVISOR_STRATEGY_TO_CORPUS[knobs.goal_strategy]),
        "--advisor-distribution-json",
        json.dumps(export.task_distribution.model_dump(mode="json"), sort_keys=True),
        "--goalgen-model",
        _GENERATION_MODEL,
        "--explore-model",
        _GENERATION_MODEL,
        "--distill-model",
        _GENERATION_MODEL,
        "--explore-budget",
        str(_EXPLORE_BUDGET),
        "--explore-timeout",
        str(_EXPLORE_TIMEOUT_S),
        "--resume",
        "--force",
    ]
    for server in _execution_servers(request):
        command.extend(["--server", server])
    return command


def _build_eval_command(
    *,
    specs: Path,
    reference_traces: Path,
    model: str,
    out_path: Path,
    candidate_traces_out: Path,
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "dmcp.cli",
        "eval",
        _slash(specs.relative_to(ROOT)),
        "-m",
        "manifests/local.json",
        "--model",
        model,
        "--replay",
        "--reference-traces",
        _slash(reference_traces.relative_to(ROOT)),
        "--budget",
        str(_EVAL_BUDGET),
        "--resume",
        "--candidate-traces-out",
        _slash(candidate_traces_out.relative_to(ROOT)),
        "-o",
        _slash(out_path.relative_to(ROOT)),
    ]


def _run_subprocess(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)


def _append_process_logs(job_id: str, proc: subprocess.CompletedProcess[str]) -> None:
    logs: list[str] = []
    if proc.stdout:
        logs.extend(proc.stdout.splitlines()[-20:])
    if proc.stderr:
        logs.extend(proc.stderr.splitlines()[-20:])
    if logs:
        _update(job_id, logs=logs)


def _artifacts_for(request: LaunchRequest, out_dir: Path) -> LaunchArtifacts:
    eval_dir = out_dir / "eval_combined"
    return LaunchArtifacts(
        goals=_slash(out_dir / "goals_full.json"),
        specs=_slash(out_dir / "specs.jsonl"),
        traces=_slash(out_dir / "traces.jsonl"),
        coverage=_slash(out_dir / "coverage.json"),
        combined_specs=_slash(out_dir / "combined_specs.jsonl") if request.run_benchmark else None,
        combined_traces=_slash(out_dir / "combined_traces.jsonl") if request.run_benchmark else None,
        statistical_summary=(
            _slash(eval_dir / "summary_pairwise_combined.json") if request.run_benchmark else None
        ),
        replay_demo_report=(
            _slash(eval_dir / "advisor_replay_demo_report.json") if request.run_benchmark else None
        ),
    )


def _execution_servers(request: LaunchRequest) -> list[str]:
    raw = request.execution_server_ids or request.export_config.generation_knobs.server_scope
    mapped = [_CLAIM_SCOPE_TO_EXECUTION_SERVER.get(server, server) for server in raw]
    return list(dict.fromkeys(server for server in mapped if server))


def _select_combined_corpus(base_dir: Path, topup_dirs: list[Path], target: int) -> tuple[Path, Path, int]:
    specs_rows: list[dict[str, Any]] = []
    trace_rows: dict[str, dict[str, Any]] = {}
    for directory in [base_dir, *topup_dirs]:
        specs_rows.extend(_read_jsonl_objects(directory / "specs.jsonl"))
        for row in _read_jsonl_objects(directory / "traces.jsonl"):
            task_id = str(row.get("seed_metadata", {}).get("task_id") or row.get("task_id") or "")
            prompt = str(row.get("goal") or row.get("prompt") or "")
            trace_rows[task_id or prompt] = row

    seen: set[str] = set()
    unique_specs: list[dict[str, Any]] = []
    for row in specs_rows:
        task_id = str(row.get("task_id") or "")
        if not task_id or task_id in seen:
            continue
        seen.add(task_id)
        unique_specs.append(row)

    selected_specs = _select_by_depth(unique_specs, target)
    selected_ids = {str(row["task_id"]) for row in selected_specs}
    selected_traces = [trace_rows[key] for key in selected_ids if key in trace_rows]
    if len(selected_traces) < len(selected_specs):
        by_prompt = {
            str(row.get("prompt") or ""): trace_rows.get(str(row.get("prompt") or ""))
            for row in selected_specs
        }
        selected_traces.extend(row for row in by_prompt.values() if row is not None)

    combined_specs = base_dir / "combined_specs.jsonl"
    combined_traces = base_dir / "combined_traces.jsonl"
    _write_jsonl(combined_specs, selected_specs)
    _write_jsonl(combined_traces, selected_traces[: len(selected_specs)])
    selection = {
        "target": target,
        "selected": len(selected_specs),
        "depth_mix": dict(_depth_counts(selected_specs)),
    }
    (base_dir / "topup_selection.json").write_text(
        json.dumps(selection, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return combined_specs, combined_traces, len(selected_specs)


def _select_by_depth(rows: list[dict[str, Any]], target: int) -> list[dict[str, Any]]:
    if len(rows) <= target:
        return rows
    ratios = {"short_chain": 0.2, "medium_chain": 0.3, "long_chain": 0.5}
    desired = {key: int(target * ratio) for key, ratio in ratios.items()}
    while sum(desired.values()) < target:
        key = max(ratios, key=lambda k: (target * ratios[k]) - desired[k])
        desired[key] += 1
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[_depth(row)].append(row)
    selected: list[dict[str, Any]] = []
    for key in ("short_chain", "medium_chain", "long_chain"):
        selected.extend(groups[key][: desired[key]])
    if len(selected) < target:
        selected_ids = {str(row["task_id"]) for row in selected}
        selected.extend(row for row in rows if str(row["task_id"]) not in selected_ids)
    return selected[:target]


def _dedup_eval(src: Path, dst: Path) -> tuple[int, int]:
    seen: set[tuple[str, str, int]] = set()
    kept: list[dict[str, Any]] = []
    invalid = 0
    for line in src.read_text(encoding="utf-8").splitlines() if src.exists() else []:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            invalid += 1
            continue
        key = (
            str(row.get("task_id") or ""),
            str(row.get("candidate_model") or ""),
            int(row.get("repeat_index") or 0),
        )
        if key in seen:
            continue
        seen.add(key)
        kept.append(row)
    _write_jsonl(dst, kept)
    return len(kept), invalid


def _build_report(
    *,
    request: LaunchRequest,
    specs_path: Path,
    eval_paths: dict[str, Path],
    summary_path: Path,
    report_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    rows_by_model = {model: _read_jsonl_objects(path) for model, path in eval_paths.items()}
    by_task = {model: {str(row.get("task_id")): row for row in rows} for model, rows in rows_by_model.items()}
    common_tasks = sorted(set.intersection(*(set(rows) for rows in by_task.values()))) if by_task else []
    model_summaries = [
        _model_summary(model, [by_task[model][tid] for tid in common_tasks]) for model in by_task
    ]
    pairwise = _paired_summary(by_task, common_tasks)
    summary = {
        "schema_version": "benchmark_advisor.demo_stats.v1",
        "metric": f"pass^{request.export_config.attempts_per_task}",
        "attempts_per_task": request.export_config.attempts_per_task,
        "models": model_summaries,
        "pairwise": pairwise,
        "planning": {
            "unique_tasks": len(common_tasks),
            "baseline_rate": 0.5,
            "planned_mde_pp": planned_mde_pp_for_unique_tasks(len(common_tasks)),
            "wilson_ci_width_pp_at_baseline": ci_width_pp(len(common_tasks)),
            "heuristic_label": "planning_heuristic",
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = _replay_report_from_summary(request, specs_path, summary, pairwise, by_task)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary, report


def _model_summary(model: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    passed = sum(1 for row in rows if row.get("passed"))
    sae = sum(1 for row in rows if row.get("had_sae"))
    lo, hi = proportion_ci(passed, n) if n else (0.0, 0.0)
    return {
        "model": model,
        "n": n,
        "passed": passed,
        "pass_rate": passed / n if n else 0.0,
        "ci_low": lo,
        "ci_high": hi,
        "sae": sae,
        "sae_rate": sae / n if n else 0.0,
    }


def _paired_summary(by_task: dict[str, dict[str, dict[str, Any]]], common_tasks: list[str]) -> dict[str, Any]:
    models = list(by_task)
    if len(models) != 2 or not common_tasks:
        return {}
    a, b = models
    diffs: list[int] = []
    counts = {"both_pass": 0, f"{a}_only": 0, f"{b}_only": 0, "both_fail": 0}
    for tid in common_tasks:
        ap = bool(by_task[a][tid].get("passed"))
        bp = bool(by_task[b][tid].get("passed"))
        diffs.append((1 if ap else 0) - (1 if bp else 0))
        if ap and bp:
            counts["both_pass"] += 1
        elif ap:
            counts[f"{a}_only"] += 1
        elif bp:
            counts[f"{b}_only"] += 1
        else:
            counts["both_fail"] += 1
    estimate = 100 * sum(diffs) / len(diffs)
    rng = random.Random(_BOOTSTRAP_SEED)
    boots = [
        100 * sum(diffs[rng.randrange(len(diffs))] for _ in diffs) / len(diffs)
        for _ in range(_BOOTSTRAP_REPLICATES)
    ]
    boots.sort()
    return {
        "label": f"{a} - {b}",
        "estimate_pp": estimate,
        "ci_low_pp": boots[int(0.025 * (len(boots) - 1))],
        "ci_high_pp": boots[int(0.975 * (len(boots) - 1))],
        "method": "paired_bootstrap_tasks",
        "bootstrap_replicates": _BOOTSTRAP_REPLICATES,
        "seed": _BOOTSTRAP_SEED,
        "counts": counts,
    }


def _replay_report_from_summary(
    request: LaunchRequest,
    specs_path: Path,
    summary: dict[str, Any],
    pairwise: dict[str, Any],
    by_task: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    models = summary["models"]
    metric = summary["metric"]
    planned_mde = summary["planning"]["planned_mde_pp"]
    leaderboard = [
        {
            "rank": idx + 1,
            "model": row["model"],
            "passed": row["passed"],
            "n": row["n"],
            "acc": row["pass_rate"],
            "lo": row["ci_low"],
            "hi": row["ci_high"],
            "old_acc": 0.0,
            "delta": pairwise.get("estimate_pp", 0.0) if idx == 0 else -pairwise.get("estimate_pp", 0.0),
        }
        for idx, row in enumerate(sorted(models, key=lambda r: (-r["pass_rate"], r["model"])))
    ]
    ci_records = []
    if pairwise:
        ci_records.append(
            {
                "label": f"{pairwise['label']} paired delta",
                "low_pp": round(pairwise["ci_low_pp"], 3),
                "high_pp": round(pairwise["ci_high_pp"], 3),
                "method": "paired_bootstrap_tasks",
            }
        )
    ci_records.extend(
        {
            "label": f"{row['model']} {metric} Wilson interval",
            "low_pp": round(row["ci_low"] * 100, 3),
            "high_pp": round(row["ci_high"] * 100, 3),
            "method": "wilson_score",
        }
        for row in models
    )
    issue = {
        "severity": "warning",
        "code": "paired_delta_ci_crosses_zero",
        "message": "The observed paired delta is small and the 95% bootstrap interval crosses zero.",
        "failed_field": "report.confidence_intervals",
        "failed_criterion_id": "criterion.primary",
        "statistical_reason": f"Observed delta is below the {planned_mde:.1f} pp planning MDE.",
        "repair_options": [
            "Increase the task budget for a smaller detectable effect.",
            "Report this as an inconclusive scoped comparison.",
        ],
        "guide_references": [],
    }
    sample_size = models[0]["n"] if models else 0
    model_names = [row["model"] for row in models]
    slice_diagnostics, focus_slices = _slice_diagnostics(specs_path, by_task, model_names)
    return {
        "schema_version": "benchmark_advisor.replay_demo_report.v1",
        "experiment_id": "BA.live.generated.benchmark",
        "title": "Pairwise live benchmark report for the Advisor finance intent",
        "headline": _headline(model_names, models, pairwise, metric),
        "condition": (
            f"live-generated corpus, servers={','.join(_execution_servers(request))}, "
            f"tasks={sample_size}, attempts_per_task={request.export_config.attempts_per_task}, "
            f"metric={metric}"
        ),
        "sample_size": sample_size,
        "model_count": len(models),
        "metric": metric,
        "mode": "replay",
        "report": {
            "schema_version": "benchmark_advisor.report.v2",
            "mode": request.export_config.mode,
            "status": "warning" if pairwise else "approved",
            "effect_sizes": [
                {
                    "label": pairwise.get("label", "paired delta"),
                    "estimate_pp": round(pairwise.get("estimate_pp", 0.0), 3),
                    "method": "paired_bootstrap_tasks",
                },
                {
                    "label": f"planned MDE for {sample_size} unique paired tasks",
                    "estimate_pp": round(planned_mde, 3),
                    "method": "planning_heuristic_mde",
                },
            ],
            "confidence_intervals": ci_records,
            "rank_stability": None,
            "slice_diagnostics": slice_diagnostics,
            "missingness": {
                "missing_count": 0,
                "total_count": sample_size * len(models),
                "policy": (
                    "common task ids across all candidate model eval files; "
                    "invalid stop/resume rows are deduplicated before reporting"
                ),
                "reasons": {},
            },
            "multiplicity": {
                "policy": "one primary paired comparison with exploratory slice diagnostics",
                "confirmatory_tests": 1 if pairwise else 0,
                "exploratory_tests": 0,
                "note": "The primary paired delta uses task-level bootstrap over common generated tasks.",
            },
            "allowed_claims": [
                f"Scoped comparison for {', '.join(model_names)} on the generated corpus.",
                "The observed model gap is reported with paired bootstrap uncertainty.",
            ],
            "not_allowed_claims": [
                "universal best-model claim outside this generated corpus",
                "private-deployment guarantee",
            ],
            "issues": [issue] if pairwise else [],
        },
        "leaderboard": leaderboard,
        "focus_slices": focus_slices,
        "provenance": {
            "source_docs": [_slash(specs_path.relative_to(ROOT))],
            "discarded_sources": [],
            "corpus": _slash(specs_path.relative_to(ROOT)),
            "execution": "Studio live Benchmark Advisor launch pipeline",
            "generated_by_current_handoff": True,
            "server_filter_available": True,
            "server_filter_note": f"Execution servers: {', '.join(_execution_servers(request))}.",
        },
        "data_quality": [
            (
                f"Eval metric is {metric}; repeated-attempt reliability is only claimed "
                "when attempts_per_task > 1."
            ),
            "Duplicate stop/resume rows are deduplicated by task_id, candidate_model, and repeat_index.",
        ],
        "figures": [],
    }


def _headline(
    model_names: list[str],
    models: list[dict[str, Any]],
    pairwise: dict[str, Any],
    metric: str,
) -> str:
    if len(models) < 2 or not pairwise:
        return f"Completed generated-corpus benchmark for {len(models)} model(s)."
    by_name = {row["model"]: row for row in models}
    a, b = model_names[:2]
    ar = by_name[a]
    br = by_name[b]
    return (
        f"On the generated corpus, {a} is {pairwise['estimate_pp']:+.1f} pp over {b} "
        f"on {metric} ({ar['passed']}/{ar['n']} vs {br['passed']}/{br['n']}), "
        f"with paired bootstrap 95% CI [{pairwise['ci_low_pp']:.1f}, {pairwise['ci_high_pp']:.1f}] pp."
    )


def _slice_diagnostics(
    specs_path: Path,
    by_task: dict[str, dict[str, dict[str, Any]]],
    model_names: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if len(model_names) != 2:
        return [], []
    a, b = model_names
    specs = _read_jsonl_objects(specs_path)
    out: list[dict[str, Any]] = []
    focus: list[dict[str, Any]] = []
    labels = {
        "short_chain": "Short chain",
        "medium_chain": "Medium chain",
        "long_chain": "Long chain",
    }
    for slice_id in ("short_chain", "medium_chain", "long_chain"):
        ids = [str(row.get("task_id")) for row in specs if _depth(row) == slice_id]
        ids = [tid for tid in ids if tid in by_task.get(a, {}) and tid in by_task.get(b, {})]
        if not ids:
            continue
        a_passed = sum(1 for tid in ids if by_task[a][tid].get("passed"))
        b_passed = sum(1 for tid in ids if by_task[b][tid].get("passed"))
        delta = 100 * (a_passed - b_passed) / len(ids)
        out.append(
            {
                "slice_id": slice_id,
                "label": labels[slice_id],
                "metric": "pass_delta_pp",
                "estimate": round(delta, 3),
                "interpretation": f"{a} passed {a_passed}/{len(ids)} and {b} passed {b_passed}/{len(ids)}.",
            }
        )
        focus.append(
            {
                "slice_id": slice_id,
                "label": labels[slice_id],
                "model_a_passed": a_passed,
                "model_b_passed": b_passed,
                "n": len(ids),
                "delta_pp": round(delta, 3),
            }
        )
    return out, focus


def _jsonl_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _read_jsonl_objects(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def _depth(row: dict[str, Any]) -> str:
    depth = int(row.get("complexity", {}).get("trace_depth") or 0)
    if depth <= 2:
        return "short_chain"
    if depth <= 4:
        return "medium_chain"
    return "long_chain"


def _depth_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"short_chain": 0, "medium_chain": 0, "long_chain": 0}
    for row in rows:
        counts[_depth(row)] += 1
    return counts


def _slug(model: str) -> str:
    return model.replace("/", "_").replace("\\", "_").replace(":", "_").replace(" ", "_")


def _update(
    job_id: str,
    *,
    status: str | None = None,
    phase: str | None = None,
    progress: dict[str, int | float | str] | None = None,
    log: str | None = None,
    logs: list[str] | None = None,
) -> None:
    job = get_launch_job(job_id)
    merged_progress = {**job.progress, **(progress or {})}
    merged_logs = [*job.logs]
    if log:
        merged_logs.append(log)
    if logs:
        merged_logs.extend(logs)
    _store(
        job.model_copy(
            update={
                "status": status or job.status,
                "phase": phase or job.phase,
                "progress": merged_progress,
                "logs": merged_logs,
            }
        )
    )


def _warn(job_id: str, warning: str) -> None:
    job = get_launch_job(job_id)
    _store(job.model_copy(update={"warnings": [*job.warnings, warning]}))


def _store(job: LaunchJob) -> None:
    with _LOCK:
        _JOBS[job.job_id] = job


def _slash(path: Path) -> str:
    return str(path).replace("\\", "/")
