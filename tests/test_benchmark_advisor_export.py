"""Tests for the Benchmark Advisor export handoff (BA3.3 / T07)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from benchmark_advisor.export import build_export_config, export_violations, is_exportable
from benchmark_advisor.planner import plan
from benchmark_advisor.schema import AdvisorRequest, ExportConfig
from tests import advisor_fixtures as fx


def _design(fixture_id: str):
    req = AdvisorRequest.model_validate(fx.load(fixture_id)["request"])
    pr = plan(req)
    return pr.design, pr.sandbox_required


def test_exportability_by_status():
    assert is_exportable("approved")
    assert is_exportable("warning")
    assert not is_exportable("refused")
    assert not is_exportable("needs_clarification")


def test_approved_design_builds_valid_export():
    design, sandbox = _design("pairwise-finance-valid")
    cfg = build_export_config(design, [], sandbox_required=sandbox)
    assert isinstance(cfg, ExportConfig)
    assert cfg.tasks == design.task_budget
    assert cfg.generation_knobs.dry_run_only is True
    assert cfg.generation_knobs.handoff_target == "scripts/build_corpus.py"
    assert export_violations(cfg) == []


def test_warning_export_preserves_warnings():
    from benchmark_advisor.validator import validate_design

    design, sandbox = _design("leaderboard-small-budget-warning")
    outcome = validate_design(design, sandbox_required=sandbox)
    cfg = build_export_config(design, outcome.warnings, sandbox_required=sandbox)
    assert cfg.warnings, "warnings must be preserved inside the export"
    assert export_violations(cfg) == []


def test_export_round_trips_through_json():
    design, sandbox = _design("pairwise-finance-valid")
    cfg = build_export_config(design, [], sandbox_required=sandbox)
    reloaded = ExportConfig.model_validate(json.loads(cfg.model_dump_json()))
    assert reloaded == cfg


def test_distractors_mirror_task_distribution():
    design, sandbox = _design("pairwise-finance-valid")
    cfg = build_export_config(design, [], sandbox_required=sandbox)
    assert cfg.distractors == cfg.task_distribution.distractors


def test_dry_run_false_is_a_schema_error():
    design, sandbox = _design("pairwise-finance-valid")
    cfg = build_export_config(design, [], sandbox_required=sandbox)
    data = json.loads(cfg.model_dump_json())
    data["generation_knobs"]["dry_run_only"] = False
    with pytest.raises(ValidationError):
        ExportConfig.model_validate(data)


def test_missing_generation_knobs_is_a_schema_error():
    design, sandbox = _design("pairwise-finance-valid")
    cfg = build_export_config(design, [], sandbox_required=sandbox)
    data = json.loads(cfg.model_dump_json())
    del data["generation_knobs"]
    with pytest.raises(ValidationError):
        ExportConfig.model_validate(data)


def test_export_carries_claim_boundary():
    design, sandbox = _design("pairwise-finance-valid")
    cfg = build_export_config(design, [], sandbox_required=sandbox)
    assert cfg.claim_boundary.strip()
