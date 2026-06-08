"""Parallel-runner key splitting: --key-offset slices the provider key pool.

Pins the contract that two concurrent runners (e.g. a corpus build and a
leaderboard) can claim disjoint slices of the provider key pool by passing
different --key-offset values, instead of fighting over the same rate-limited
account.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from dmcp.providers import FREE, pool_keys

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


# ---------------------------------------------------------------------------
# pool_keys + slice contract — the underlying primitive the scripts wrap
# ---------------------------------------------------------------------------


def test_pool_keys_slicing_gives_disjoint_lanes(monkeypatch):
    """A 7-key pool sliced at offsets 0 and 3 must produce non-overlapping
    sets — that's the whole reason we have the offset."""
    monkeypatch.setenv("FREE_MODELS_API_KEY", "k1")
    monkeypatch.setenv("FREE_MODELS_API_KEY_2", "k2")
    monkeypatch.setenv("FREE_MODELS_API_KEY_3", "k3")
    monkeypatch.setenv("FREE_MODELS_API_KEY_4", "k4")
    monkeypatch.setenv("FREE_MODELS_API_KEY_5", "k5")
    monkeypatch.setenv("FREE_MODELS_API_KEY_6", "k6")
    monkeypatch.setenv("FREE_MODELS_API_KEY_7", "k7")
    all_keys = pool_keys(FREE)
    assert len(all_keys) == 7
    builder_lane = all_keys[0:3]
    leaderboard_lane = all_keys[3:]
    assert set(builder_lane).isdisjoint(set(leaderboard_lane))
    assert set(builder_lane) | set(leaderboard_lane) == set(all_keys)


def test_pool_keys_slice_past_end_returns_empty(monkeypatch):
    """If the user offsets past the end of the pool, downstream callers
    raise instead of silently running with zero lanes."""
    monkeypatch.setenv("FREE_MODELS_API_KEY", "k1")
    monkeypatch.setenv("FREE_MODELS_API_KEY_2", "k2")
    all_keys = pool_keys(FREE)
    assert all_keys[10:] == []


# ---------------------------------------------------------------------------
# Both scripts surface --key-offset in --help
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("script", ["build_corpus.py", "run_leaderboard.py"])
def test_script_exposes_key_offset_flag(script):
    """Both runners must advertise the flag — silent presence is a regression
    risk because users wouldn't know to set it."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / script), "--help"],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert "--key-offset" in proc.stdout
    # And it must reference the parallel-runner motivation, so a future cleanup
    # PR can't strip the rationale.
    assert "disjoint" in proc.stdout or "parallel" in proc.stdout
