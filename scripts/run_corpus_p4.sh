#!/usr/bin/env bash
# Person 4 — DynamicMCPBench corpus generation (E3.9), FULL coverage.
#   goalgen = google/gemini-2.5-flash   distiller = openai/gpt-5.4-mini (+anthropic fallback)
#   explorers = deepseek-v4-pro, minimax-m3, mistral-large-2512, grok-4.3
#   validator = z-ai/glm-5.1
# All captured MCP servers (manifests/surfaces.json), all 15 strategies, all 3
# complexities. Every model empirically verified on the framework (named
# tool_choice for goalgen/distiller, real tool-use for explorers, real verdicts
# for the validator). 4 distinct families per spec. Resumable.
#
# Requires .env with OPENROUTER_API_KEY. Launch detached (laptop can close):
#   setsid nohup bash scripts/run_corpus_p4.sh > data/corpus_p4.log 2>&1 < /dev/null &
set -euo pipefail
cd "$(dirname "$0")/.."
set -a
[ -f .env ] && . ./.env
set +a

exec .venv/bin/python scripts/build_corpus.py \
  --manifest manifests/servers.json \
  --surfaces manifests/surfaces.json \
  --goalgen-model google/gemini-2.5-flash \
  --explorer-models deepseek/deepseek-v4-pro,minimax/minimax-m3,mistralai/mistral-large-2512,x-ai/grok-4.3 \
  --distiller-candidates openai/gpt-5.4-mini,anthropic/claude-haiku-4.5 \
  --validator-model z-ai/glm-5.1 \
  --complexities simple,medium,hard \
  --per-strategy 8 \
  --budget 12 \
  --concurrency 6 \
  --explore-timeout 600 \
  --resume \
  --out data/corpus_p4 \
  "$@"
