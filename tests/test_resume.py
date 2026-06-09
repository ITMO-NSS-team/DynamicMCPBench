"""E8.0c: JSONL resume helpers + paper-pricing aliases.

Pins the contract that long runs can be killed and restarted without losing
work, and that the per-row stamp the resumer reads (provenance.goal_id,
top-level task_id) survives the round-trip through dmcp generate / eval.
"""

from __future__ import annotations

import json
from pathlib import Path

from dmcp.openrouter_prices import LivePrice
from dmcp.paper_pricing import FREE_TO_OR_ALIAS, paper_cost_for
from dmcp.providers import FREE_MODELS
from dmcp.resume import file_row_count, seen_goal_ids, seen_task_ids


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r))
            fh.write("\n")


# ---------------------------------------------------------------------------
# seen_task_ids — used by `dmcp eval --resume`
# ---------------------------------------------------------------------------


def test_seen_task_ids_collects_top_level_id(tmp_path: Path):
    p = tmp_path / "evals.jsonl"
    _write(p, [{"task_id": "a"}, {"task_id": "b"}, {"task_id": "c"}])
    assert seen_task_ids(p) == {"a", "b", "c"}


def test_seen_task_ids_missing_file_is_empty(tmp_path: Path):
    """Fresh runs cleanly degrade to 'skip nothing' instead of erroring."""
    assert seen_task_ids(tmp_path / "never_written.jsonl") == set()


def test_seen_task_ids_swallows_trailing_partial_line(tmp_path: Path):
    """A hard kill mid-write leaves a partial last line. Resume must not
    abort on that single byte of stale tail — the prior 99% of work would
    be silently abandoned."""
    p = tmp_path / "evals.jsonl"
    p.write_text(
        json.dumps({"task_id": "a"}) + "\n" + json.dumps({"task_id": "b"}) + "\n{partial",
        encoding="utf-8",
    )
    assert seen_task_ids(p) == {"a", "b"}


def test_seen_task_ids_ignores_blank_lines(tmp_path: Path):
    p = tmp_path / "evals.jsonl"
    p.write_text(
        '\n{"task_id": "a"}\n\n{"task_id": "b"}\n\n',
        encoding="utf-8",
    )
    assert seen_task_ids(p) == {"a", "b"}


# ---------------------------------------------------------------------------
# seen_goal_ids — used by `dmcp generate --resume`
# ---------------------------------------------------------------------------


def test_seen_goal_ids_reads_provenance_goal_id(tmp_path: Path):
    """The canonical resume key is `provenance.goal_id` (E8.6 + this PR).
    The distiller stamps it via provenance kwarg per goal."""
    p = tmp_path / "specs.jsonl"
    _write(p, [{"task_id": "t1", "provenance": {"goal_id": "g1"}}, {"provenance": {"goal_id": "g2"}}])
    assert seen_goal_ids(p) == {"g1", "g2"}


def test_seen_goal_ids_falls_back_to_seed_metadata(tmp_path: Path):
    """Traces (not specs) carry goal_id under seed_metadata. The helper works
    on either, so a unified resume index doesn't have to special-case."""
    p = tmp_path / "traces.jsonl"
    _write(p, [{"seed_metadata": {"goal_id": "g_trace"}}])
    assert seen_goal_ids(p) == {"g_trace"}


def test_seen_goal_ids_specs_without_goal_id_dont_pollute_set(tmp_path: Path):
    """Pre-E8.0c specs lack provenance.goal_id. Resume should keep working
    against them but ignore their rows — those goals will re-run on resume,
    which is the safe choice."""
    p = tmp_path / "specs.jsonl"
    _write(p, [{"task_id": "old1"}, {"task_id": "old2", "provenance": {}}])
    assert seen_goal_ids(p) == set()


# ---------------------------------------------------------------------------
# file_row_count — used by per-cell skip in cost_calibration.py
# ---------------------------------------------------------------------------


def test_file_row_count_excludes_blanks_and_bad_json(tmp_path: Path):
    p = tmp_path / "evals.jsonl"
    p.write_text(
        '\n{"task_id":"a"}\n{"task_id":"b"}\n{garbage\n{"task_id":"c"}\n',
        encoding="utf-8",
    )
    assert file_row_count(p) == 3


def test_file_row_count_missing_is_zero(tmp_path: Path):
    assert file_row_count(tmp_path / "no.jsonl") == 0


# ---------------------------------------------------------------------------
# paper_pricing — every free model has an OR equivalent registered
# ---------------------------------------------------------------------------


def test_every_free_model_has_a_paper_alias():
    """Hard contract: the paper must be able to quote an OR-equivalent cost
    for each free model. Missing aliases would force a 'no paper equivalent'
    annotation that's a footnote regression."""
    missing = [m for m in FREE_MODELS if m not in FREE_TO_OR_ALIAS]
    assert not missing, f"free models missing paper-pricing alias: {missing}"


def test_paper_cost_resolves_via_alias_to_live_price():
    """1M input + 1M output on `deepseek-v4-pro` (alias deepseek/deepseek-v4-pro
    priced at $2 in + $10 out) → $12 total. Alias resolution + price math
    pinned in one assertion."""
    live = {"deepseek/deepseek-v4-pro": LivePrice(2.0, 10.0)}
    pc = paper_cost_for("deepseek-v4-pro", 1_000_000, 1_000_000, live)
    assert pc.alias == "deepseek/deepseek-v4-pro"
    assert pc.usd is not None and abs(pc.usd - 12.0) < 1e-9


def test_paper_cost_returns_none_when_alias_missing_and_not_or_native():
    """Unrelated bare-name model → no alias → usd=None so the caller can
    surface 'no paper equivalent' instead of pretending the cost is $0."""
    pc = paper_cost_for("mystery-x", 1000, 1000, {})
    assert pc.alias is None
    assert pc.usd is None


def test_paper_cost_for_or_native_models_uses_own_price():
    """A model already on OR (vendor/slash form) paper-costs itself —
    short-circuits the alias lookup so paid models in mixed pools don't
    need an entry in FREE_TO_OR_ALIAS."""
    live = {"anthropic/claude-haiku-4.5": LivePrice(0.80, 4.0)}
    pc = paper_cost_for("anthropic/claude-haiku-4.5", 1_000_000, 0, live)
    assert pc.alias == "anthropic/claude-haiku-4.5"
    assert pc.usd is not None and abs(pc.usd - 0.80) < 1e-9


def test_paper_cost_alias_resolves_to_static_pricing_table():
    """Alias hits the static `dmcp/pricing.py` PRICES when live doesn't have
    it — same fallback chain as `get_effective_price`. kimi-k2p6 → kimi-k2.6
    which IS in static at $0.68 / $3.42."""
    # No live → falls back to static (kimi-k2.6 is pinned).
    pc = paper_cost_for("kimi-k2p6", 1_000_000, 0, {})
    assert pc.alias == "moonshotai/kimi-k2.6"
    assert pc.usd is not None and abs(pc.usd - 0.68) < 1e-9
