#!/usr/bin/env bash
# Stable identity for this clone/agent, used as the claim owner in docs/PLAN.md.
set -euo pipefail
name="$(git config user.name 2>/dev/null || echo unknown)"
name="$(printf '%s' "$name" | tr ' ' '-' | tr -cd 'A-Za-z0-9_-')"
printf '%s@%s\n' "${name:-unknown}" "$(hostname)"
