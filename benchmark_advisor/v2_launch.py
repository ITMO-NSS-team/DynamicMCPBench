"""Guarded corpus launch service for Benchmark Advisor v2 (BA6/T17).

The design and validation routes stay side-effect free. This module is the
only v2 path allowed to turn an approved/warning export into a tracked corpus
generation job.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import threading
import uuid
from pathlib import Path

from fastapi import HTTPException

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


def launch_advisor_corpus(request: LaunchRequest) -> LaunchJob:
    """Validate a guarded launch request and create a tracked job."""

    _validate_launch_request(request)
    job_id = f"advisor-{uuid.uuid4().hex[:12]}"
    launch_key = hashlib.sha256(request.model_dump_json().encode("utf-8")).hexdigest()[:12]
    out_dir = Path("data") / "advisor_runs" / launch_key
    command = build_command_preview(request, out_dir=out_dir)
    artifacts = LaunchArtifacts(
        goals=_slash(out_dir / "goals_full.json"),
        specs=_slash(out_dir / "specs.jsonl"),
        traces=_slash(out_dir / "traces.jsonl"),
        coverage=_slash(out_dir / "coverage.json"),
    )
    job = LaunchJob(
        schema_version=LAUNCH_JOB_SCHEMA_VERSION,
        job_id=job_id,
        status="queued",
        command_preview=command,
        logs=["queued guarded corpus handoff"],
        artifacts=artifacts,
    )
    _store(job)
    if request.dry_run:
        _store(job.model_copy(update={"status": "succeeded", "logs": [*job.logs, "dry-run preview only"]}))
        return get_launch_job(job_id)

    thread = threading.Thread(target=_run_job, args=(job_id, command), daemon=True)
    thread.start()
    return job


def get_launch_job(job_id: str) -> LaunchJob:
    with _LOCK:
        job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"unknown launch job: {job_id}")
    return job


def build_command_preview(request: LaunchRequest, *, out_dir: Path | None = None) -> list[str]:
    """Build a deterministic corpus-only command for scripts/build_corpus.py."""

    export = request.export_config
    knobs = export.generation_knobs
    target = Path(knobs.handoff_target)
    if target.as_posix() != "scripts/build_corpus.py":
        raise HTTPException(status_code=400, detail="launch target must be scripts/build_corpus.py")
    out = out_dir or Path("data") / "advisor_runs" / "preview"
    command = [
        sys.executable,
        "scripts/build_corpus.py",
        "--out",
        _slash(out),
        "--budget",
        str(export.tasks),
        "--strategies",
        ",".join(_ADVISOR_STRATEGY_TO_CORPUS[knobs.goal_strategy]),
        "--advisor-distribution-json",
        json.dumps(export.task_distribution.model_dump(mode="json"), sort_keys=True),
    ]
    for server in knobs.server_scope:
        command.extend(["--server", server])
    return command


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


def _run_job(job_id: str, command: list[str]) -> None:
    job = get_launch_job(job_id)
    _store(
        job.model_copy(
            update={"status": "running", "logs": [*job.logs, "started scripts/build_corpus.py"]}
        )
    )
    try:
        proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    except Exception as exc:  # pragma: no cover - defensive for OS/process failures.
        failed = get_launch_job(job_id)
        _store(failed.model_copy(update={"status": "failed", "logs": [*failed.logs, str(exc)]}))
        return
    current = get_launch_job(job_id)
    logs = [*current.logs]
    if proc.stdout:
        logs.extend(proc.stdout.splitlines()[-20:])
    if proc.stderr:
        logs.extend(proc.stderr.splitlines()[-20:])
    status = "succeeded" if proc.returncode == 0 else "failed"
    logs.append(f"scripts/build_corpus.py exited with {proc.returncode}")
    _store(current.model_copy(update={"status": status, "logs": logs}))


def _store(job: LaunchJob) -> None:
    with _LOCK:
        _JOBS[job.job_id] = job


def _slash(path: Path) -> str:
    return str(path).replace("\\", "/")
