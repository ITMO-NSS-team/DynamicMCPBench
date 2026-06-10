#!/usr/bin/env bash
# Person 5 — DynamicMCPBench corpus generation (E3.9), FULL coverage.
#   goalgen = anthropic/claude-haiku-4.5   distiller = google/gemini-3.5-flash (+openai fallback)
#   explorers = glm-5.1, kimi-k2.6, nova-pro, minimax-m3
#   validator = deepseek/deepseek-v4-pro
# All captured MCP servers, all 15 strategies, all 3 complexities. Models verified
# on the framework. 4 distinct families per spec. Resumable.
#
# Requires .env with OPENROUTER_API_KEY. Launch detached:
#   setsid nohup bash scripts/run_corpus_p5.sh > data/corpus_p5.log 2>&1 < /dev/null &
set -euo pipefail
cd "$(dirname "$0")/.."
set -a
[ -f .env ] && . ./.env
set +a

exec .venv/bin/python scripts/build_corpus.py \
  --manifest manifests/servers.json \
  --surfaces manifests/surfaces.json \
  --goalgen-model anthropic/claude-haiku-4.5 \
  --explorer-models z-ai/glm-5.1,moonshotai/kimi-k2.6,amazon/nova-pro-v1,minimax/minimax-m3 \
  --distiller-candidates google/gemini-3.5-flash,openai/gpt-5.4-mini \
  --validator-model deepseek/deepseek-v4-pro \
  --complexities simple,medium,hard \
  --per-strategy 8 \
  --budget 12 \
  --concurrency 6 \
  --explore-timeout 600 \
  --resume \
  --out data/corpus_p5 \
  "$@"
