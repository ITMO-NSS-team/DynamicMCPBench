"""Studio advisor routes: /api/advisor/design and /api/advisor/validate (BA3.1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from backend.app import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(app)

_FIXTURES = Path(__file__).resolve().parents[3] / "docs_benchmark_advisor" / "fixtures"


def _request(fixture_id: str) -> dict:
    return json.loads((_FIXTURES / f"{fixture_id}.json").read_text())["request"]


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
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/servers").status_code == 200
