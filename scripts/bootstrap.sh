#!/usr/bin/env bash
# Idempotent environment bootstrap. Safe to run repeatedly. See docs/AUTONOMY.md.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"

# 1. uv (package/venv manager)
if ! command -v uv >/dev/null 2>&1; then
  echo "installing uv ..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

# 2. virtualenv + package (with dev + substrate servers; fall back to dev-only)
[ -d .venv ] || uv venv
uv pip install -e ".[servers,dev]" || {
  echo "WARN: '.[servers,dev]' install failed; falling back to '.[dev]' (some MCP servers unavailable)"
  uv pip install -e ".[dev]"
}

# 3. soft prerequisites for the full pipeline (warn, don't fail)
command -v node >/dev/null 2>&1 || \
  echo "WARN: node/npx missing — npm-based MCP servers (fs, memory, cyanheads) will not run"
if command -v gh >/dev/null 2>&1; then
  gh auth status >/dev/null 2>&1 || \
    echo "WARN: gh not authenticated — run 'gh auth login' for PR/auto-merge"
else
  echo "WARN: gh CLI missing — PR/auto-merge unavailable"
fi
{ [ -f .env ] && grep -q '^OPENROUTER_API_KEY=.' .env; } || \
  echo "WARN: OPENROUTER_API_KEY not set in .env — explore/distill/eval/generate steps will fail"

echo "bootstrap: OK"
