"""REPLAY adapter: the three showcase verdicts come from the real evaluate()."""

from __future__ import annotations

import pytest
from backend import dmcp_adapter as adapter


def test_showcase_verdicts():
    """case 1 effect-pass, case 2 effect-fail (incomplete agg.), case 3 effect-pass."""
    assert adapter.score("replay", None, "qwen3.7-max").effect_pass is True
    assert adapter.score("replay", None, "hermes3-8b").effect_pass is False
    assert adapter.score("replay", None, "grok-4.3 (stale)").effect_pass is True


def test_effect_answer_disagreement():
    """The two cases the toggle is built around: the verdicts disagree."""
    hermes = adapter.score("replay", None, "hermes3-8b")
    assert hermes.effect_pass is False and hermes.answer_pass is True  # answer-pass / effect-fail
    grok = adapter.score("replay", None, "grok-4.3 (stale)")
    assert grok.effect_pass is True and grok.answer_pass is False  # answer-fail / effect-pass


def test_equivalence_override_flips_clean_pass():
    """Disabling get_price_history (the tool qwen used for cp3) fails it; download keeps it."""
    base = adapter.score("replay", None, "qwen3.7-max")
    assert base.effect_pass is True
    only_download = adapter.score("replay", None, "qwen3.7-max", equiv_overrides={"download"})
    assert only_download.effect_pass is False  # qwen used get_price_history, now disabled
    cp3 = next(v for v in only_download.checkpoints if v.checkpoint_id == "cp3")
    assert cp3.met is False


def test_explore_and_candidate_calls_filter_agent_steps():
    calls, trace_id = adapter.explore_calls("replay")
    assert len(calls) == 7 and trace_id
    assert all(c["tool_name"] for c in calls)
    cand = adapter.candidate_calls("replay", "hermes3-8b")
    assert len(cand) == 6  # skips the income-statement call


def test_distill_exposes_editable_equivalence_set():
    spec = adapter.distill("replay")
    eq = adapter.equivalence_tools(spec)
    assert eq["cp3"] == ["download", "get_price_history"]


def test_leaderboard_marked_placeholder():
    lb = adapter.leaderboard("replay")
    assert lb.placeholder is True and lb.rows  # not presented as real numbers


def test_live_mode_not_yet_supported():
    with pytest.raises(NotImplementedError):
        adapter.list_servers("live")
