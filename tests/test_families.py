"""E8.6: model-family registry + cross-family pickers.

The corpus must be authored with explorer-family ≠ distiller-family
(`docs/EXPERIMENTS_SUITE.md §2.2`). These tests pin the constraint at the
family-picker level so a future refactor that loosens it fails loudly.
"""

from __future__ import annotations

import pytest

from dmcp.families import (
    UNKNOWN_FAMILY,
    assign_shards,
    cross_family_pick,
    ensure_cross_family,
    family_of,
)

# ---------------------------------------------------------------------------
# family_of — prefix-based lookup
# ---------------------------------------------------------------------------


def test_family_of_known_prefixes():
    assert family_of("openai/gpt-5.5") == "openai"
    assert family_of("anthropic/claude-opus-4.8") == "anthropic"
    assert family_of("google/gemini-3.1-pro-preview") == "google"
    assert family_of("qwen/qwen3.7-max") == "qwen"
    assert family_of("moonshotai/kimi-k2.6") == "moonshot"


def test_family_of_unknown_falls_back_to_sentinel():
    assert family_of("acme/mystery-x") == UNKNOWN_FAMILY


def test_family_of_uses_prefix_not_substring():
    """A model id that *contains* a family slug but doesn't *start* with it
    must not match — otherwise `acme/openai-clone` would be misattributed."""
    assert family_of("acme/openai-clone") == UNKNOWN_FAMILY


# ---------------------------------------------------------------------------
# cross_family_pick — first-different-family wins
# ---------------------------------------------------------------------------


def test_cross_family_pick_returns_first_different_family():
    explorer = "openai/gpt-5.5"
    pick = cross_family_pick(explorer, ["openai/gpt-other", "anthropic/claude-opus-4.8"])
    assert pick == "anthropic/claude-opus-4.8"


def test_cross_family_pick_skips_same_family_at_head_of_list():
    explorer = "anthropic/claude-opus-4.8"
    pick = cross_family_pick(
        explorer,
        ["anthropic/claude-sonnet-4.6", "anthropic/claude-haiku-4.5", "google/gemini-3.1-pro-preview"],
    )
    assert pick == "google/gemini-3.1-pro-preview"


def test_cross_family_pick_raises_when_only_same_family_available():
    explorer = "anthropic/claude-opus-4.8"
    with pytest.raises(ValueError, match="cross-family"):
        cross_family_pick(explorer, ["anthropic/claude-sonnet-4.6", "anthropic/claude-haiku-4.5"])


def test_cross_family_pick_treats_unknown_as_its_own_family():
    """Unknown-vs-known is still cross-family — the picker shouldn't refuse to
    progress just because the registry doesn't recognize the explorer."""
    pick = cross_family_pick("acme/mystery-x", ["acme/sister-y", "openai/gpt-5.5"])
    assert pick == "openai/gpt-5.5"


# ---------------------------------------------------------------------------
# assign_shards — one (explorer, distiller) pair per explorer in the panel
# ---------------------------------------------------------------------------


def test_assign_shards_produces_one_assignment_per_explorer():
    explorers = ["openai/gpt-5.5", "anthropic/claude-opus-4.8", "google/gemini-3.1-pro-preview"]
    candidates = ["anthropic/claude-opus-4.8", "openai/gpt-5.5"]
    assignments = assign_shards(explorers, candidates)
    assert len(assignments) == 3
    families = [(a.explorer_family, a.distiller_family) for a in assignments]
    assert ("openai", "anthropic") in families
    assert ("anthropic", "openai") in families
    assert ("google", "anthropic") in families  # google picks first non-google candidate


def test_assign_shards_rejects_empty_inputs():
    with pytest.raises(ValueError):
        assign_shards([], ["openai/gpt-5.5"])
    with pytest.raises(ValueError):
        assign_shards(["openai/gpt-5.5"], [])


def test_assign_shards_rejects_panel_where_no_distiller_qualifies_for_some_explorer():
    """If every distiller candidate shares a family with one of the explorers,
    that shard cannot be cross-family — raise rather than silently fall back."""
    with pytest.raises(ValueError):
        assign_shards(
            ["openai/gpt-5.5", "anthropic/claude-opus-4.8"],
            ["openai/gpt-other", "openai/gpt-mini"],  # no anthropic-family distiller
        )


def test_assign_shards_stamps_family_slugs_on_each_assignment():
    a = assign_shards(["openai/gpt-5.5"], ["anthropic/claude-opus-4.8"])[0]
    assert a.explorer_family == "openai"
    assert a.distiller_family == "anthropic"


# ---------------------------------------------------------------------------
# ensure_cross_family — direct guard rail for callers without the picker
# ---------------------------------------------------------------------------


def test_ensure_cross_family_passes_for_different_families():
    ensure_cross_family("openai/gpt-5.5", "anthropic/claude-opus-4.8")  # no raise


def test_ensure_cross_family_raises_for_same_family():
    with pytest.raises(ValueError, match="must be in different families"):
        ensure_cross_family("anthropic/claude-opus-4.8", "anthropic/claude-haiku-4.5")
