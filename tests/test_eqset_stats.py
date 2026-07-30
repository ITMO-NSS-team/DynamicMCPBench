"""CR 5.3 / E9.13 — the equivalence-set figures the paper reports.

The released corpus is git-ignored study data, so the counting rules are pinned
on synthetic specs and the committed numbers block is guarded for shape and
internal consistency. The point of the guard is that the paper quotes this
share in two places; if the block and the prose ever diverge again, the
divergence should surface here rather than in review.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import eqset_stats  # noqa: E402  (script imported as a module for testing)


def _spec(*sizes: int, extra_kinds: tuple[str, ...] = ()) -> dict:
    """A spec whose tool-effect checkpoints have the given equivalence-set sizes."""
    cps = [{"kind": "tool_effect", "equivalence_set": [f"s__t{i}" for i in range(n)]} for n in sizes]
    cps += [{"kind": kind} for kind in extra_kinds]
    return {"checkpoints": cps}


def test_only_tool_effect_checkpoints_are_counted():
    dist = eqset_stats.eqset_distribution([_spec(1, 3, extra_kinds=("value_produced", "value_produced"))])
    assert dict(dist) == {1: 1, 3: 1}


def test_a_missing_equivalence_set_counts_as_size_zero_not_one():
    """A malformed checkpoint must not be silently promoted into the singleton bucket."""
    dist = eqset_stats.eqset_distribution([{"checkpoints": [{"kind": "tool_effect"}]}])
    assert dict(dist) == {0: 1}


def test_summary_matches_a_hand_counted_corpus():
    specs = [_spec(1, 1, 2), _spec(3, 7)]
    s = eqset_stats.summarize(eqset_stats.eqset_distribution(specs), len(specs))
    assert s["specs"] == 2
    assert s["tool_effect_checkpoints"] == 5
    assert s["multi_tool_checkpoints"] == 3  # sizes 2, 3, 7
    assert s["multi_tool_pct"] == pytest.approx(60.0)
    assert s["mean_size"] == pytest.approx((1 + 1 + 2 + 3 + 7) / 5)
    assert s["max_size"] == 7


def test_the_tail_bucket_folds_everything_above_four():
    specs = [_spec(5, 6, 12, 4)]
    s = eqset_stats.summarize(eqset_stats.eqset_distribution(specs), 1)
    assert s["buckets"] == {"1": 0, "2": 0, "3": 0, "4": 1, ">=5": 3}


def test_an_empty_corpus_is_an_error_not_a_division_by_zero():
    with pytest.raises(ValueError):
        eqset_stats.summarize(eqset_stats.eqset_distribution([]), 0)


def test_load_specs_tolerates_blank_lines(tmp_path: Path):
    p = tmp_path / "specs.jsonl"
    p.write_text(json.dumps(_spec(1)) + "\n\n" + json.dumps(_spec(2)) + "\n", encoding="utf-8")
    assert len(eqset_stats.load_specs(p)) == 2


def test_check_against_numbers_flags_a_drifted_figure(tmp_path: Path):
    s = eqset_stats.summarize(eqset_stats.eqset_distribution([_spec(1, 2)]), 1)

    good = tmp_path / "good.json"
    good.write_text(json.dumps(s), encoding="utf-8")
    assert eqset_stats.check_against_numbers(s, good) == []

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({**s, "multi_tool_checkpoints": 99}), encoding="utf-8")
    assert any("multi_tool_checkpoints" in p for p in eqset_stats.check_against_numbers(s, bad))


def test_published_block_is_internally_consistent():
    """Guards the single source for the share quoted in Sec. 3.4 and Appendix I."""
    d = json.loads(eqset_stats.NUMBERS.read_text(encoding="utf-8"))
    buckets = d["buckets"]
    assert sum(buckets.values()) == d["tool_effect_checkpoints"]
    assert d["multi_tool_checkpoints"] == d["tool_effect_checkpoints"] - buckets["1"]
    pct = 100 * d["multi_tool_checkpoints"] / d["tool_effect_checkpoints"]
    assert d["multi_tool_pct"] == pytest.approx(pct, abs=0.01)
    assert d["max_size"] >= eqset_stats.TAIL_FROM


def test_missing_corpus_exits_with_a_pointer_not_a_traceback(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(eqset_stats, "ROOT", tmp_path)
    assert eqset_stats.main([]) == 2
    assert "--pull" in capsys.readouterr().err
