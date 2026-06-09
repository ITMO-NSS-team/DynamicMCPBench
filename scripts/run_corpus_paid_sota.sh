#!/usr/bin/env bash
# Reproduce / resume the paid SOTA corpus run (E3.9).
#
# Resumable: re-run to recover crash-skipped goals. Exploration is
# subprocess-isolated (PR #79), so a flaky MCP server can no longer abort a
# shard — a re-run with --resume sweeps up every goal the original crashed past.
#
# Cross-family by construction: each explorer is paired with the first
# cross-family distiller from --distiller-candidates; goals are authored by a
# separate cross-family goalgen panel. Shards map to --explorer-models in order
# (shard 5 = deepseek-v4-pro).
#
# Requires .env with OPENROUTER_API_KEY. Launch detached, e.g.:
#   setsid nohup bash scripts/run_corpus_paid_sota.sh > data/corpus_paid_sota.log 2>&1 &
set -euo pipefail
cd "$(dirname "$0")/.."
set -a
[ -f .env ] && . ./.env
set +a

exec .venv/bin/python scripts/build_corpus.py \
  --manifest manifests/servers.json \
  --surfaces manifests/surfaces.json \
  --explorer-models openai/gpt-5.5,anthropic/claude-sonnet-4.6,google/gemini-3.1-pro-preview,qwen/qwen3.7-max,x-ai/grok-4.3,deepseek/deepseek-v4-pro \
  --distiller-candidates openai/gpt-5.5,anthropic/claude-sonnet-4.6 \
  --goalgen-models openai/gpt-5.4-mini,anthropic/claude-haiku-4.5,google/gemini-3.5-flash \
  --per-strategy 6 \
  --complexities simple \
  --budget 12 \
  --concurrency 6 \
  --explore-timeout 600 \
  --resume \
  --out data/corpus_paid_sota \
  "$@"
