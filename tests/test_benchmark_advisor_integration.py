"""End-to-end integration smoke for the Benchmark Advisor (BA4.1 / T09).

Drives the demo scenario from intent to a user-approvable export preview across
core -> planner -> validator -> service -> export, asserts the negative paths are
not exportable, and guards the hard invariant that nothing here launches a
benchmark run. The browser-level smoke lives in capture_screenshot.py; here we do
a static check that the Stage-0 UI is wired to the advisor API.
"""

from __future__ import annotations

from pathlib import Path

import benchmark_advisor as ba_pkg
from benchmark_advisor.export import export_violations
from benchmark_advisor.schema import AdvisorRequest, response_state_violations
from benchmark_advisor.service import advisor_design
from tests import advisor_fixtures as fx

ADVISOR_DIR = Path(ba_pkg.__file__).resolve().parent
FRONTEND = Path(__file__).resolve().parents[1] / "dmcp-studio" / "frontend"

# advisor modules may use dmcp's lightweight stats helpers (curves/ablation) but
# must never reach generation/evaluation pipeline modules.
_FORBIDDEN_IMPORTS = (
    "goal_gen",
    "evaluator",
    "explorer",
    "recorder",
    "distiller",
    "refresh",
    "build_corpus",
    "discovery",
)


def _req(fixture_id: str) -> AdvisorRequest:
    return AdvisorRequest.model_validate(fx.load(fixture_id)["request"])


def test_intent_to_export_preview_smoke():
    resp = advisor_design(_req("pairwise-finance-valid"))
    assert resp.status in ("approved", "warning")
    assert response_state_violations(resp) == []
    cfg = resp.export_config
    assert cfg is not None
    assert export_violations(cfg) == []
    # export is a dry-run preview with a target TaskSpec count, never a task list.
    assert cfg.generation_knobs.dry_run_only is True
    assert cfg.generation_knobs.handoff_target == "scripts/build_corpus.py"
    assert isinstance(cfg.tasks, int) and cfg.tasks >= 1
    assert cfg.claim_boundary.strip()


def test_warning_scenario_still_exports():
    resp = advisor_design(_req("leaderboard-small-budget-warning"))
    assert resp.status == "warning"
    assert resp.export_config is not None
    assert resp.export_config.warnings  # preserved inside the export


def test_refused_design_is_not_exportable():
    resp = advisor_design(_req("underpowered-refusal"))
    assert resp.status == "refused"
    assert resp.export_config is None


def test_needs_clarification_design_is_not_exportable():
    resp = advisor_design(_req("ambiguous-intent-clarification"))
    assert resp.status == "needs_clarification"
    assert resp.export_config is None


def test_advisor_never_imports_generation_or_eval_modules():
    offenders = []
    for py in ADVISOR_DIR.glob("*.py"):
        for line in py.read_text().splitlines():
            s = line.strip()
            if s.startswith(("import ", "from ")):
                for bad in _FORBIDDEN_IMPORTS:
                    if bad in s:
                        offenders.append(f"{py.name}: {s}")
    assert not offenders, "advisor must not import generation/eval modules:\n" + "\n".join(offenders)


def test_stage0_ui_is_wired_to_the_advisor_api():
    # The studio frontend is a React (Vite) SPA; the Stage-0 wiring lives in the
    # source, not in a hand-written index.html. Assert the advisor route is called
    # from the API client, the Design stage drives it with its controls, and the
    # store registers the design view.
    src = FRONTEND / "src"
    client = (src / "api" / "client.ts").read_text()
    assert "/api/advisor/design" in client, "API client does not call the advisor design route"

    design = (src / "stages" / "Design.tsx").read_text()
    assert "advisorDesign" in design, "Design stage does not call the advisor"
    for control in (
        "task budget",
        "attempts / task",
        "target detectable effect",
        "Carry this design into Collect",
    ):
        assert control in design, f"Design stage missing control: {control!r}"

    reducer = (src / "store" / "reducer.ts").read_text()
    assert '"design"' in reducer, "store does not register the Stage-0 design view"
