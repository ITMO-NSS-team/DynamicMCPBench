# Contributing to DynamicMCPBench

Thanks for helping improve DynamicMCPBench. This is the short practical entry
point; the design rationale lives in [`docs/CONCEPT.md`](docs/CONCEPT.md).

## Setup

```bash
uv pip install -e ".[servers,dev]"   # package + substrate MCP servers + dev tools
cp .env.example .env                 # then fill in OPENROUTER_API_KEY (see the file)
```

`OPENROUTER_API_KEY` is required for any generation/evaluation. Credentialed MCP
servers need additional keys — see the commented section of `.env.example`.
**Never commit `.env`** (it is git-ignored).

## Workflow

1. Branch off the latest `main`: `git switch -c feat/<short-slug>` (`feat/ fix/
   docs/ chore/`).
2. `git pull --rebase origin main` before you start and before you push.
3. Keep the change **small and single-purpose**, so parallel work doesn't collide.
4. **Run the gate before every commit** (also enforced in CI):
   ```bash
   ruff check . && ruff format --check . && pytest -q
   ```
   or simply `bash scripts/check.sh`.
5. Imperative commit subjects ("Add …", "Fix …", "Tighten …"). Update any touched
   docs in the same PR.
6. Open a PR against `main` and get a review.

## Code style

- Python ≥ 3.11; `from __future__ import annotations`; modern typing (`X | None`,
  `list[...]`).
- **Ruff is the single source of truth** — `ruff check .` and `ruff format .`
  (config in `pyproject.toml`).
- Pydantic v2 for on-disk schemas (`ConfigDict(extra="forbid")`); bump the
  relevant `*_version` on any schema/behavior change.

## What never goes in git

Secrets (`.env`), and generated artifacts: `traces/ specs/ evals/ reports/
crawled/ goals/auto*.json manifests/crawled*.json` (already git-ignored). Only
hand-authored manifests and `goals/{local,scaled,recovery}.json` are tracked.

## Don't undo the thesis

Before changing the generator or scorer, read [`docs/CONCEPT.md`](docs/CONCEPT.md).
The benchmark grades **effects, not final answers**, and is built from **traces,
not dependency graphs** — these are load-bearing, not stylistic.
