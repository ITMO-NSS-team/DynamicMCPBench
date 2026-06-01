# Contributing to DynamicMCPBench

This repo is developed by people *and* by Claude Code agents. **`CLAUDE.md` is the
single source of truth** for conventions, hard invariants, code style, and the
collaboration workflow — for humans too. Read it first. This file is the short
practical entry point.

## Setup

```bash
uv pip install -e ".[servers,dev]"   # package + substrate MCP servers + dev tools
cp .env.example .env                 # then fill in OPENROUTER_API_KEY (see the file)
```

`OPENROUTER_API_KEY` is required for any generation/evaluation. Credentialed MCP
servers (Bucket A) need additional keys — see `docs/credentials_bucket_a.md` and
the commented section of `.env.example`. **Never commit `.env`** (it is git-ignored).

## Workflow

1. Branch off the latest `main`: `git switch -c feat/<short-slug>` (`feat/ fix/
   docs/ chore/`). **Never commit to `main` directly.**
2. `git pull --rebase origin main` before you start and before you push.
3. Keep the change **small and single-purpose**, so parallel work doesn't collide.
4. **Run the local gate before every commit** (there is no CI yet, so this is the
   only guard):
   ```bash
   ruff check . && ruff format --check . && pytest -q
   ```
5. Imperative commit subjects ("Add …", "Fix …", "Tighten …"). Update the
   `README.md` roadmap checkbox(es) and any touched docs in the same PR.
6. Open a PR against `main` and get a review.

## Using Claude Code here

Claude auto-loads `CLAUDE.md` and should read `memory/*.md` at session start. If
you change personal Claude settings, put them in `.claude/settings.local.json`
(git-ignored), not the shared `.claude/settings.json`.

## What never goes in git

Secrets (`.env`), and generated artifacts: `traces/ specs/ evals/ reports/
crawled/ goals/auto*.json manifests/crawled*.json` (already git-ignored). Only
hand-authored manifests and `goals/{local,scaled,recovery}.json` are tracked.

## Don't undo the thesis

Before changing the generator or scorer, read `docs/CONCEPT.md` and
`memory/feedback_agb_orthogonality.md`. The benchmark grades **effects, not final
answers**, and is built from **traces, not dependency graphs** — these are
load-bearing, not stylistic.
