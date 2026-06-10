#!/usr/bin/env bash
# Person 6 — DynamicMCPBench corpus generation (E3.9), FULL coverage.
#   goalgen = openai/gpt-5.4-mini   distiller = anthropic/claude-haiku-4.5 (+google fallback)
#   explorers = qwen3.7-max, grok-4.3, nova-pro, mistral-large-2512
#   validator = minimax/minimax-m3
# All captured MCP servers, all 15 strategies, all 3 complexities. Models verified
# on the framework. 4 distinct families per spec. Resumable.
#
# Requires .env with OPENROUTER_API_KEY. Launch detached:
#   setsid nohup bash scripts/run_corpus_p6.sh > data/corpus_p6.log 2>&1 < /dev/null &
set -euo pipefail
cd "$(dirname "$0")/.."
set -a
[ -f .env ] && . ./.env
set +a

exec .venv/bin/python scripts/build_corpus.py \
  --manifest manifests/servers.json \
  --surfaces manifests/surfaces.json \
  --goalgen-model openai/gpt-5.4-mini \
  --explorer-models qwen/qwen3.7-max,x-ai/grok-4.3,amazon/nova-pro-v1,mistralai/mistral-large-2512 \
  --distiller-candidates anthropic/claude-haiku-4.5,google/gemini-2.5-flash \
  --validator-model minimax/minimax-m3 \
  --complexities simple,medium,hard \
  --per-strategy 8 \
  --budget 12 \
  --concurrency 6 \
  --explore-timeout 600 \
  --resume \
  --out data/corpus_p6 \
  "$@"
