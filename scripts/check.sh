#!/usr/bin/env bash
# The mandatory local gate. Must pass before any commit / auto-merge.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
uv run ruff check .
uv run pytest -q
# Formatting is advisory until the repo is baselined (PLAN step CC.3). New code
# should still be formatted: run `uv run ruff format <your changed files>`.
uv run ruff format --check . >/dev/null 2>&1 || \
  echo "NOTE: some files are not ruff-formatted yet (pre-existing; see PLAN CC.3)"
echo "gate: OK"
