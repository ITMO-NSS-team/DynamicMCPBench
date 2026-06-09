"""The shard stamp must not clobber the distiller's per-spec explorer provenance.

The distiller stamps explorer_model/explorer_family from the trace ground truth;
build_corpus's shard stamp must only add shard_id. Regression: it used to pass
the shard's explorer assignment too, which relabelled 39 opus-explored specs as
sonnet after a --resume explorer swap.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("build_corpus", ROOT / "scripts" / "build_corpus.py")
build_corpus = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_corpus)


def test_shard_stamp_only_adds_shard_id(tmp_path):
    p = tmp_path / "specs.jsonl"
    p.write_text(
        json.dumps(
            {
                "provenance": {
                    "explorer_model": "anthropic/claude-opus-4.8",
                    "explorer_family": "anthropic",
                    "goal_id": "g1",
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    # the real call site now passes only shard_id
    n = build_corpus.stamp_provenance_in_jsonl(p, {"shard_id": 1})
    assert n == 1
    prov = json.loads(p.read_text(encoding="utf-8").strip())["provenance"]
    assert prov["explorer_model"] == "anthropic/claude-opus-4.8"  # untouched
    assert prov["shard_id"] == 1  # added
