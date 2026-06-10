#!/usr/bin/env bash
# Top-up generation for data/corpus_paid_sota — fills the coverage gaps found in
# the E6.3 report, balanced across OUR paid panel MINUS opus (opus slot -> sonnet,
# which also evens sonnet, currently the lowest explorer at 7).
#
# Targets: (1) intra-server (sibling/same_name/homonym), (2) thin strategies
# (same_name/cross_server_alt/destructive_adjacent), (3) low-yield strategies
# (cross_domain/complementary), (4) explicit medium+hard complexity (run was
# simple-only). Separate --out so the existing 415/290 are untouched; merge the
# valid specs of both afterwards.
#
# Resumable + stoppable (Ctrl-C / kill any time; --resume continues). Launch:
#   setsid nohup bash scripts/run_corpus_topup.sh > data/corpus_topup.log 2>&1 < /dev/null &
set -euo pipefail
cd "$(dirname "$0")/.."
set -a
[ -f .env ] && . ./.env
set +a

exec .venv/bin/python scripts/build_corpus.py \
  --manifest manifests/servers.json \
  --surfaces manifests/surfaces.json \
  --goalgen-models openai/gpt-5.4-mini,anthropic/claude-haiku-4.5,google/gemini-3.5-flash \
  --explorer-models openai/gpt-5.5,anthropic/claude-sonnet-4.6,google/gemini-3.1-pro-preview,qwen/qwen3.7-max,x-ai/grok-4.3,deepseek/deepseek-v4-pro \
  --distiller-candidates openai/gpt-5.5,anthropic/claude-sonnet-4.6 \
  --validator-model minimax/minimax-m3 \
  --strategies same_name,sibling,homonym_trap,cross_server_alt,destructive_adjacent,cross_domain,complementary \
  --complexities simple,medium,hard \
  --per-strategy 10 \
  --budget 12 \
  --concurrency 6 \
  --explore-timeout 600 \
  --resume \
  --out data/corpus_topup \
  "$@"
