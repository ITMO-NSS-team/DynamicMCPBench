#!/usr/bin/env bash
# Demo: prove the full pipeline (goal-gen -> generate -> eval -> report) on a small
# subset of the canonical manifest. Read-only public-API servers, no creds.
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
cd ~/galyukshev/dmcp/DynamicMCPBench
mkdir -p examples/demo

echo "=== build demo manifest (4 reliable public-API servers from servers.json) ==="
uv run python - <<'PY'
import json
servers = json.load(open("manifests/servers.json"))["servers"]
pick = {"wikipedia", "yfinance", "osm", "worldbank"}
chosen = [s for s in servers if s["server_id"] in pick]
json.dump({"manifest_version": "0.1.0", "servers": chosen},
          open("examples/demo/manifest.json", "w"), indent=2)
print("demo manifest:", [s["server_id"] for s in chosen])
PY

echo "=== 1) goal-gen ==="
uv run dmcp goal-gen -m examples/demo/manifest.json --per-server 1 --cross-pairs 1 \
  -o examples/demo/goals.json 2>&1 | tail -3

echo "=== 2) generate (explore + distill) ==="
uv run dmcp generate examples/demo/goals.json -m examples/demo/manifest.json \
  --traces-out examples/demo/traces.jsonl --specs-out examples/demo/specs.jsonl 2>&1 | tail -4

echo "=== 3) eval (gold pool, 1 attempt) ==="
uv run dmcp eval examples/demo/specs.jsonl -m examples/demo/manifest.json \
  --pool gold --repeat 1 -o examples/demo/eval.jsonl 2>&1 | tail -4

echo "=== 4) report ==="
uv run dmcp report --specs examples/demo/specs.jsonl --evals examples/demo/eval.jsonl -o examples/demo/report.md 2>&1 | tail -2

echo "=== demo artifacts ==="
wc -l examples/demo/goals.json examples/demo/specs.jsonl examples/demo/eval.jsonl 2>/dev/null
echo "DEMO DONE"
