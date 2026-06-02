#!/usr/bin/env bash
# The mandatory local gate. Must pass before any commit / auto-merge.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
echo "gate: OK"
