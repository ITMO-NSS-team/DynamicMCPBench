#!/usr/bin/env bash
# Launch DMCP Studio (REPLAY by default) with one command.
#
#   dmcp-studio/scripts/run_demo.sh            # serves on http://127.0.0.1:8000
#   PORT=9000 dmcp-studio/scripts/run_demo.sh  # custom port
#
# Builds the React + Geist (Vercel) frontend with Vite if Node is present;
# otherwise serves a previously built frontend/dist. The backend serves the
# built SPA same-origin, so the demo runs without a separate dev server.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STUDIO="$(cd "$HERE/.." && pwd)"
ROOT="$(cd "$STUDIO/.." && pwd)"
PORT="${PORT:-8000}"

cd "$ROOT"

SERVER_STATUS="$(uv run python "$STUDIO/scripts/check_studio_server.py" --port "$PORT")"
if [ "$SERVER_STATUS" = "stale" ]; then
  echo "✗ A stale DMCP Studio backend is already running on http://127.0.0.1:${PORT}." >&2
  echo "  Stop that process before rebuilding the frontend, or start this demo with PORT=…" >&2
  echo "  This prevents a new frontend bundle from calling routes that the old backend does not have." >&2
  exit 1
elif [ "$SERVER_STATUS" = "occupied" ]; then
  echo "✗ Port ${PORT} is already in use by a non-current service." >&2
  echo "  Stop that process or start this demo with PORT=…" >&2
  exit 1
fi

# 1) Build the frontend if Node is available (a committed/prior dist is the fallback).
if command -v npm >/dev/null 2>&1; then
  echo "› building frontend (vite)…"
  ( cd "$STUDIO/frontend" && npm install --silent && npm run build >/dev/null )
elif [ ! -d "$STUDIO/frontend/dist" ]; then
  echo "✗ Node/npm not found and no prebuilt frontend/dist — install Node 20+ and retry." >&2
  exit 1
else
  echo "› npm not found — serving the existing frontend/dist"
fi

# 2) Ensure the REPLAY fixtures exist (build them if missing).
if [ ! -f "$STUDIO/backend/fixtures/showcase_aapl.json" ]; then
  echo "› building REPLAY fixtures…"
  uv run python "$STUDIO/experiments/e3_curate.py"
fi

# 3) Serve the backend (it serves the SPA same-origin from frontend/dist).
if [ "$SERVER_STATUS" = "current" ]; then
  echo "› DMCP Studio is already running at http://127.0.0.1:${PORT} with v2 advisor routes loaded"
  exit 0
fi

echo "› DMCP Studio → http://127.0.0.1:${PORT}  (REPLAY; Ctrl-C to stop)"
cd "$STUDIO"
exec uv run uvicorn backend.app:app --host 127.0.0.1 --port "$PORT"
