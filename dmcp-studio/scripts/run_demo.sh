#!/usr/bin/env bash
# Launch DMCP Studio (REPLAY by default) with one command.
#
#   dmcp-studio/scripts/run_demo.sh            # serves on http://127.0.0.1:8000
#   PORT=9000 dmcp-studio/scripts/run_demo.sh  # custom port
#
# Rebuilds the TypeScript + Tailwind/daisyUI frontend if Bun is present; otherwise
# serves the committed bundles (frontend/app.js + app.css), so the demo runs
# without a build step.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STUDIO="$(cd "$HERE/.." && pwd)"
ROOT="$(cd "$STUDIO/.." && pwd)"
PORT="${PORT:-8000}"

cd "$ROOT"

# 1) Build the frontend if Bun is available (committed app.js + app.css are the fallback).
if command -v bun >/dev/null 2>&1; then
  echo "› building frontend (bun)…"
  ( cd "$STUDIO/frontend" && bun install --silent && bun run build >/dev/null )
else
  echo "› bun not found — serving the committed frontend/app.js + app.css"
fi

# 2) Ensure the REPLAY fixtures exist (build them if missing).
if [ ! -f "$STUDIO/backend/fixtures/showcase_aapl.json" ]; then
  echo "› building REPLAY fixtures…"
  uv run python "$STUDIO/experiments/e3_curate.py"
fi

# 3) Serve the backend (it serves the SPA same-origin).
echo "› DMCP Studio → http://127.0.0.1:${PORT}  (REPLAY; Ctrl-C to stop)"
cd "$STUDIO"
exec uv run uvicorn backend.app:app --host 127.0.0.1 --port "$PORT"
