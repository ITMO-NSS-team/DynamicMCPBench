"""Studio advisor routes: /api/advisor/design and /api/advisor/validate (BA3.1)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from backend.app import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(app)

_FIXTURES = Path(__file__).resolve().parents[3] / "docs_benchmark_advisor" / "fixtures"


def _request(fixture_id: str) -> dict:
    return json.loads((_FIXTURES / f"{fixture_id}.json").read_text())["request"]


def _v2_request(**overrides: object) -> dict:
    request = {
        "schema_version": "benchmark_advisor.v2",
        "intent": "Compare two local agents on short step finance workflows.",
        "mode": "pairwise",
        "task_budget": 70,
        "attempts_per_task": 1,
        "candidate_models": ["agent-a", "agent-b"],
        "server_scope": ["finance-tools"],
    }
    request.update(overrides)
    return request


def _launch_request(**overrides: object) -> dict:
    response = client.post("/api/advisor/v2/design", json=_v2_request()).json()
    request = {
        "schema_version": "benchmark_advisor.launch.v2",
        "export_config": response["export_config"],
        "advisor_status": response["status"],
        "confirmation": True,
        "sandbox_confirmed": False,
        "dry_run": True,
        "requested_by_ui": True,
    }
    request.update(overrides)
    return request


def test_design_route_returns_schema_valid_approved_response():
    r = client.post("/api/advisor/design", json=_request("pairwise-finance-valid"))
    assert r.status_code == 200
    body = r.json()
    assert body["schema_version"] == "benchmark_advisor.v1"
    assert body["status"] == "approved"
    assert body["export_config"] is not None
    assert body["validation_report_stub"]["implemented"] is False


def test_design_route_tunes_short_finance_hard_negative_query():
    r = client.post("/api/advisor/design", json=_request("pairwise-short-finance-hard-negative"))
    assert r.status_code == 200
    body = r.json()
    td = body["design"]["task_distribution"]
    assert body["status"] == "approved"
    assert {"finance", "short_chain", "same_name", "near_miss", "hard_negative"}.issubset(
        set(td["categories"])
    )
    assert td["short_chain"] > td["medium_chain"]
    assert td["short_chain"] > td["long_chain"]
    assert td["distractors"]["same_name_fraction"] > 0.1
    assert td["distractors"]["near_miss_fraction"] > 0.1
    assert body["export_config"] is not None


def test_design_route_warning_includes_cards():
    r = client.post("/api/advisor/design", json=_request("leaderboard-small-budget-warning"))
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "warning"
    assert any(w["code"] == "underpowered_design" for w in body["warnings"])


def test_design_route_refused_has_refusal_and_no_export():
    r = client.post("/api/advisor/design", json=_request("underpowered-refusal"))
    body = r.json()
    assert body["status"] == "refused"
    assert body["refusal"] is not None
    assert body["export_config"] is None


def test_design_route_clarification_has_no_export():
    r = client.post("/api/advisor/design", json=_request("ambiguous-intent-clarification"))
    body = r.json()
    assert body["status"] == "needs_clarification"
    assert body["clarification"] is not None
    assert body["export_config"] is None


def test_validate_route_revalidates_edited_design():
    # Get a design from the design route, edit the budget down, re-validate.
    design = client.post("/api/advisor/design", json=_request("pairwise-finance-valid")).json()["design"]
    design["task_budget"] = 70
    r = client.post(
        "/api/advisor/validate",
        json={"schema_version": "benchmark_advisor.v1", "design": design, "edited_fields": ["task_budget"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "warning"
    assert any(w["code"] == "underpowered_design" for w in body["warnings"])


def test_malformed_request_is_rejected():
    r = client.post("/api/advisor/design", json={"intent": "missing required fields"})
    assert r.status_code == 422


def test_existing_routes_still_work():
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["capabilities"]["advisor_v2"] is True
    assert client.get("/api/servers").status_code == 200


def test_v2_design_route_returns_engine_scored_statistical_plan():
    r = client.post(
        "/api/advisor/v2/design",
        json={
            "schema_version": "benchmark_advisor.v2",
            "intent": "Compare two local agents on short step finance workflows.",
            "mode": "pairwise",
            "task_budget": 70,
            "attempts_per_task": 1,
            "candidate_models": ["agent-a", "agent-b"],
            "server_scope": ["finance-tools"],
        },
    )
    assert r.status_code == 200
    body = r.json()
    plan = body["statistical_plan"]
    assert body["status"] == "approved"
    assert plan["engine_decision"]["recommended_candidate_id"]
    assert plan["design"]["task_budget"] == 100
    assert body["export_config"]["tasks"] == 100


def test_v2_validate_route_refreshes_edited_plan_and_refuses_invalid_candidate_count():
    request = {
        "schema_version": "benchmark_advisor.v2",
        "intent": "Compare two local agents on short step finance workflows.",
        "mode": "pairwise",
        "task_budget": 70,
        "attempts_per_task": 1,
        "candidate_models": ["agent-a", "agent-b"],
        "server_scope": ["finance-tools"],
    }
    plan = client.post("/api/advisor/v2/design", json=request).json()["statistical_plan"]
    plan["design"]["candidate_models"].append("agent-c")

    r = client.post(
        "/api/advisor/v2/validate",
        json={
            "schema_version": "benchmark_advisor.v2",
            "statistical_plan": plan,
            "original_request": request,
            "edited_fields": ["design.candidate_models"],
        },
    )

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "refused"
    assert body["export_config"] is None
    assert body["launchable"] is False
    assert any(issue["code"] == "unsupported_candidate_model_count" for issue in body["issues"])


def test_v2_report_route_returns_scoped_statistical_report():
    tensor = {
        "schema_version": "benchmark_advisor.outcome_tensor.v2",
        "shape": "X[task, model, attempt, metric, slice]",
        "tasks": [
            {"axis_id": "task.1", "label": "task 1", "metadata": {}},
            {"axis_id": "task.2", "label": "task 2", "metadata": {}},
        ],
        "models": [
            {"axis_id": "model-a", "label": "model A", "metadata": {}},
            {"axis_id": "model-b", "label": "model B", "metadata": {}},
        ],
        "attempts": [{"axis_id": "attempt.0", "label": "attempt 0", "metadata": {}}],
        "metrics": [{"axis_id": "trace_effect_pass_rate", "label": "pass", "metadata": {}}],
        "slices": [{"axis_id": "all", "label": "all tasks", "metadata": {}}],
        "values": [
            {
                "task_id": task,
                "model_id": model,
                "attempt_id": "attempt.0",
                "metric_id": "trace_effect_pass_rate",
                "slice_id": "all",
                "value": value,
                "missing_reason": None,
            }
            for task, model, value in [
                ("task.1", "model-a", True),
                ("task.2", "model-a", False),
                ("task.1", "model-b", True),
                ("task.2", "model-b", True),
            ]
        ],
    }

    r = client.post(
        "/api/advisor/v2/report",
        json={"schema_version": "benchmark_advisor.v2", "outcome_tensor": tensor},
    )

    assert r.status_code == 200
    body = r.json()
    report = body["report"]
    assert report["schema_version"] == "benchmark_advisor.report.v2"
    assert report["mode"] == "pairwise"
    assert report["effect_sizes"][0]["estimate_pp"] == 50.0
    assert "universal best-model claim" in report["not_allowed_claims"]


def test_v2_replay_demo_report_uses_corrected_leaderboard_provenance():
    r = client.get("/api/advisor/v2/replay-demo-report")
    assert r.status_code == 200
    body = r.json()
    assert body["schema_version"] == "benchmark_advisor.replay_demo_report.v1"
    assert body["experiment_id"] == "E8.10d.qwen-vs-glm.workflow-stress"
    assert body["sample_size"] == 200
    assert body["model_count"] == 2
    assert body["report"]["mode"] == "pairwise"
    assert body["report"]["status"] == "warning"
    assert body["provenance"]["generated_by_current_handoff"] is False
    assert body["provenance"]["server_filter_available"] is False
    assert "docs/experiments/e8.10d-corrected-leaderboard.md" in body["provenance"]["source_docs"]
    assert "docs/experiments/e8.8b-leaderboard-cleaned-750.md" in body["provenance"]["discarded_sources"]
    assert body["leaderboard"][0]["model"] == "qwen3.7-max"
    assert body["leaderboard"][1]["model"] == "glm-5.1"
    assert body["focus_slices"][0]["slice_id"] == "long_similar_chain"
    assert any("current corpus handoff" in claim for claim in body["report"]["not_allowed_claims"])
    assert any(issue["code"] == "server_axis_unavailable_in_source_artifacts" for issue in body["report"]["issues"])


def test_v2_replay_demo_report_serves_only_allowlisted_figures():
    ok = client.get("/api/advisor/v2/replay-demo-report/figures/before_after.png")
    assert ok.status_code == 200
    assert ok.headers["content-type"] == "image/png"

    missing = client.get("/api/advisor/v2/replay-demo-report/figures/../e8.10d_numbers.json")
    assert missing.status_code == 404


def test_v2_launch_refuses_without_explicit_confirmation():
    request = _launch_request()
    request["confirmation"] = False
    r = client.post("/api/advisor/v2/launch", json=request)
    assert r.status_code == 422


def test_v2_launch_refuses_refused_or_clarification_status():
    request = _launch_request(advisor_status="refused")
    r = client.post("/api/advisor/v2/launch", json=request)
    assert r.status_code == 422


def test_v2_launch_refuses_when_sandbox_requirements_are_unmet():
    request = _launch_request()
    request["export_config"]["generation_knobs"]["sandbox_required"] = True
    r = client.post("/api/advisor/v2/launch", json=request)
    assert r.status_code == 400
    assert "sandbox" in r.json()["detail"]


def test_v2_launch_refuses_non_ui_origin_with_actionable_detail():
    request = _launch_request(requested_by_ui=False)
    r = client.post("/api/advisor/v2/launch", json=request)
    assert r.status_code == 400
    assert r.json()["detail"] == "launch must be requested by Studio UI"


def test_v2_launch_dry_run_command_preview_is_deterministic_and_tracked():
    request = _launch_request()
    first = client.post("/api/advisor/v2/launch", json=request)
    second = client.post("/api/advisor/v2/launch", json=request)
    assert first.status_code == 200
    assert second.status_code == 200

    first_body = first.json()
    second_body = second.json()
    assert first_body["status"] == "succeeded"
    assert first_body["schema_version"] == "benchmark_advisor.launch_job.v2"
    assert "scripts/build_corpus.py" in first_body["command_preview"]
    assert "--strategies" in first_body["command_preview"]
    assert "hard_neg,complementary" in first_body["command_preview"]
    distribution = json.loads(
        first_body["command_preview"][first_body["command_preview"].index("--advisor-distribution-json") + 1]
    )
    assert distribution["cross_server_ratio"] >= 0
    assert "distractors" in distribution
    assert first_body["command_preview"] == second_body["command_preview"]
    assert first_body["artifacts"]["specs"].endswith("/specs.jsonl")

    status = client.get(f"/api/advisor/v2/launch/{first_body['job_id']}")
    assert status.status_code == 200
    assert status.json()["job_id"] == first_body["job_id"]


def test_v2_launch_non_dry_run_starts_tracked_background_job(monkeypatch):
    from benchmark_advisor import v2_launch

    class ImmediateThread:
        def __init__(self, *, target, args, daemon):
            self.target = target
            self.args = args
            self.daemon = daemon

        def start(self):
            self.target(*self.args)

    def fake_run(command, *, cwd, capture_output, text, check):
        assert command[1] == "scripts/build_corpus.py"
        assert cwd == v2_launch.ROOT
        assert capture_output is True
        assert text is True
        assert check is False
        return SimpleNamespace(returncode=0, stdout="generated corpus\n", stderr="")

    monkeypatch.setattr(v2_launch.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(v2_launch.subprocess, "run", fake_run)

    request = _launch_request(dry_run=False)
    r = client.post("/api/advisor/v2/launch", json=request)

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "queued"
    assert body["artifacts"]["goals"].endswith("/goals_full.json")

    status = client.get(f"/api/advisor/v2/launch/{body['job_id']}").json()
    assert status["status"] == "succeeded"
    assert "started scripts/build_corpus.py" in status["logs"]
    assert "generated corpus" in status["logs"]


def test_v2_launch_first_handoff_is_corpus_only():
    request = _launch_request()
    r = client.post("/api/advisor/v2/launch", json=request)
    assert r.status_code == 200
    command = r.json()["command_preview"]
    joined = " ".join(command)
    assert "scripts/build_corpus.py" in command
    assert "dmcp bench" not in joined
    assert "run_leaderboard" not in joined
    assert "eval" not in joined


def test_v2_design_route_remains_side_effect_free_for_launch_jobs():
    from benchmark_advisor import v2_launch

    before = set(v2_launch._JOBS)
    r = client.post("/api/advisor/v2/design", json=_v2_request())
    assert r.status_code == 200
    assert set(v2_launch._JOBS) == before
