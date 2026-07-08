#!/usr/bin/env bash
# Launch DMCP Studio (REPLAY by default) with one command.
#
#   dmcp-studio/scripts/run_demo.sh
#   PORT=9000 dmcp-studio/scripts/run_demo.sh
#
# This wrapper delegates to the cross-platform Python launcher. Keeping the
# server under one Python process avoids shell-specific stderr/PATH issues.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
if [ -n "${DMCP_STUDIO_PYTHON:-}" ]; then
  exec "$DMCP_STUDIO_PYTHON" "$HERE/run_demo.py" "$@"
fi
if [ -x "$ROOT/.venv/bin/python" ]; then
  exec "$ROOT/.venv/bin/python" "$HERE/run_demo.py" "$@"
fi
if command -v python3 >/dev/null 2>&1; then
  exec python3 "$HERE/run_demo.py" "$@"
fi
exec python "$HERE/run_demo.py" "$@"
