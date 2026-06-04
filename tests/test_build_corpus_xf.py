"""E8.6: cross-family generation panel — build_corpus.py shard/provenance helpers.

Tests the pure-Python harness pieces (round-robin sharding, in-place provenance
overlay) without launching `dmcp generate` or hitting an LLM. The dispatch
half is paid compute and is exercised in E8.7 with a real corpus.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import build_corpus  # noqa: E402  (script imported as module for testing)

# ---------------------------------------------------------------------------
# shard_goals — deterministic round-robin partition
# ---------------------------------------------------------------------------


def test_shard_goals_round_robin_balances_strategies_across_shards():
    """Round-robin (not contiguous) so strategy/complexity skew can't pile up
    in shard 0. With 6 entries × 3 shards each shard gets exactly 2 entries."""
    entries = [{"goal_id": str(i)} for i in range(6)]
    shards = build_corpus.shard_goals(entries, n_shards=3)
    assert [len(s) for s in shards] == [2, 2, 2]
    # Shard 0 picks 0,3; shard 1 picks 1,4; shard 2 picks 2,5 (round-robin order).
    assert [e["goal_id"] for e in shards[0]] == ["0", "3"]
    assert [e["goal_id"] for e in shards[1]] == ["1", "4"]
    assert [e["goal_id"] for e in shards[2]] == ["2", "5"]


def test_shard_goals_handles_uneven_partition():
    entries = [{"goal_id": str(i)} for i in range(7)]
    shards = build_corpus.shard_goals(entries, n_shards=3)
    # 7 entries → 3, 2, 2 by round-robin distribution.
    assert [len(s) for s in shards] == [3, 2, 2]


def test_shard_goals_empty_input_gives_empty_shards():
    shards = build_corpus.shard_goals([], n_shards=4)
    assert shards == [[], [], [], []]


def test_shard_goals_rejects_non_positive_shard_count():
    with pytest.raises(ValueError):
        build_corpus.shard_goals([{"goal_id": "0"}], n_shards=0)


# ---------------------------------------------------------------------------
# stamp_provenance_in_jsonl — in-place overlay onto each spec
# ---------------------------------------------------------------------------


def _make_spec_row(task_id: str, provenance: dict | None = None) -> dict:
    """A minimal TaskSpec-shaped row — only the keys the harness reads."""
    return {
        "task_id": task_id,
        "prompt": "x",
        "provenance": provenance or {},
    }


def test_stamp_provenance_overlays_new_keys_without_clobbering_existing(tmp_path: Path):
    """The distiller already stamps explorer/distiller families per spec.
    The runner-layer overlay adds shard_id etc; it must not erase what the
    distiller wrote (or we'd lose G0 stratification)."""
    path = tmp_path / "specs.jsonl"
    rows = [
        _make_spec_row("a", {"explorer_family": "openai", "distiller_family": "anthropic"}),
        _make_spec_row("b", {"explorer_family": "openai", "distiller_family": "anthropic"}),
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    n = build_corpus.stamp_provenance_in_jsonl(path, {"shard_id": 0})
    assert n == 2
    out = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for row in out:
        # Existing keys preserved...
        assert row["provenance"]["explorer_family"] == "openai"
        assert row["provenance"]["distiller_family"] == "anthropic"
        # ...new key added.
        assert row["provenance"]["shard_id"] == 0


def test_stamp_provenance_creates_provenance_when_missing(tmp_path: Path):
    """Defensive: a row without a `provenance` key still gets overlaid."""
    path = tmp_path / "specs.jsonl"
    bare = {"task_id": "x", "prompt": "p"}
    path.write_text(json.dumps(bare) + "\n", encoding="utf-8")
    build_corpus.stamp_provenance_in_jsonl(path, {"shard_id": 7})
    out = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert out["provenance"]["shard_id"] == 7


def test_stamp_provenance_overwrites_collisions(tmp_path: Path):
    """If the same provenance key is set in both layers, the runner overlay
    wins (overrides supersede distiller defaults — explicit > implicit)."""
    path = tmp_path / "specs.jsonl"
    row = _make_spec_row("a", {"shard_id": 999})
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    build_corpus.stamp_provenance_in_jsonl(path, {"shard_id": 0})
    out = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert out["provenance"]["shard_id"] == 0


def test_stamp_provenance_on_missing_file_is_a_noop(tmp_path: Path):
    """A shard that errored before writing its specs file shouldn't crash the
    whole corpus build — return 0, log nothing, move on."""
    missing = tmp_path / "shard_2_specs.jsonl"
    assert build_corpus.stamp_provenance_in_jsonl(missing, {"shard_id": 2}) == 0
