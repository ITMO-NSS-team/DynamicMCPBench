#!/usr/bin/env python3
"""Reconcile per-spec explorer provenance from trace ground truth + clean JSONL.

A corpus built before the stamp_provenance_in_jsonl setdefault fix can carry a
wrong provenance.explorer_model on any shard whose explorer changed across a
--resume run (the old build_corpus re-stamped the whole shard file with the
current assignment). This re-derives explorer_model/explorer_family on every
spec from its own trace's seed_metadata.llm_model, and rewrites trace/spec/merged
JSONL one-object-per-line (repairing crash-era concatenated records). Idempotent;
writes *.prerec.bak once.

    python scripts/reconcile_explorer_provenance.py --out data/corpus_paid_sota
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dmcp.families import family_of  # noqa: E402

_DEC = json.JSONDecoder()


def iter_json(path: str):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            raw = raw.strip()
            while raw:
                try:
                    obj, end = _DEC.raw_decode(raw)
                except json.JSONDecodeError:
                    break
                yield obj
                raw = raw[end:].lstrip()


def rewrite(path: str, objs: list[dict]) -> None:
    bak = path + ".prerec.bak"
    if os.path.exists(path) and not os.path.exists(bak):
        shutil.copy(path, bak)
    with open(path, "w", encoding="utf-8") as fh:
        for o in objs:
            fh.write(json.dumps(o, ensure_ascii=False) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/corpus_paid_sota", help="corpus directory")
    a = ap.parse_args()
    d = a.out
    changed = 0
    for tf in sorted(glob.glob(f"{d}/traces_shard_*.jsonl")):
        sf = tf.replace("traces_shard_", "specs_shard_")
        traces = list(iter_json(tf))
        if traces:
            rewrite(tf, traces)
        succ, any_ = {}, {}
        for t in traces:
            sm = t.get("seed_metadata") or {}
            gid, llm = sm.get("goal_id"), sm.get("llm_model")
            if not (gid and llm):
                continue
            any_.setdefault(gid, Counter())[llm] += 1
            if ((sm.get("exploration") or {}).get("successful_tool_calls", 0) or 0) > 0:
                succ.setdefault(gid, Counter())[llm] += 1
        specs = list(iter_json(sf))
        sh = 0
        for sp in specs:
            prov = sp.get("provenance") or {}
            votes = succ.get(prov.get("goal_id")) or any_.get(prov.get("goal_id"))
            if votes:
                real = votes.most_common(1)[0][0]
                if prov.get("explorer_model") != real:
                    prov["explorer_model"] = real
                    prov["explorer_family"] = family_of(real)
                    sp["provenance"] = prov
                    sh += 1
        if specs:
            rewrite(sf, specs)
        print(f"  {os.path.basename(sf)}: {sh} relabeled / {len(specs)} specs")
        changed += sh
    for name in ("traces", "specs"):
        p = f"{d}/{name}.jsonl"
        objs = list(iter_json(p))
        if objs:
            rewrite(p, objs)
    print(f"TOTAL relabeled: {changed}")


if __name__ == "__main__":
    main()
