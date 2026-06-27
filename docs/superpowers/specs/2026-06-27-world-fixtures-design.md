# Design: World storage — snapshot/restore for live stateful eval

**Date:** 2026-06-27
**Status:** v0 shipped (minimal storage layer)
**Branch:** `feat/world-fixtures`

## Problem

Live (non-`--replay`) eval runs candidates against the real
`docker-compose-mcp.yaml` substrate, whose `stateful_write` servers mutate
backing stores behind named volumes. With no reset layer, candidate _N+1_ sees
_N_'s mutations (non-reproducible), and a task may assume world state (a
collection, a file) that was never materialised. We want to snapshot the world
when a task is created and restore it before each agent run.

## v0 scope (what shipped)

A minimal, uniform **storage** layer in `dmcp/world.py`:

- **`WorldStore.capture(fixture_id, volumes=None)`** — tars every docker named
  volume of the compose project into `worlds/<fixture_id>/<volume>.tar`, plus a
  `manifest.json` (`WorldFixture`: project, per-volume real name + sha256).
- **`WorldStore.restore(fixture_id)`** — verifies each sha256, then wipes and
  untars each volume back to the captured state.
- **`WorldStore.list()`** — fixture ids on disk.
- **CLI:** `dmcp world capture <id> [--volume ...]`, `dmcp world restore <id>`,
  `dmcp world list`.

Mechanism is **uniform and schema-agnostic**: a throwaway `alpine` helper
container mounts each volume and `tar`s it — no per-store tooling, no knowledge
of mongo/postgres internals. Reset volumes while services are idle for a
consistent snapshot. `worlds/` is git-ignored (regenerable artifact).

Deliberately **out of v0**: per-store logical dumps, manifest/`TaskSpec` schema
changes, automatic bracketing inside `dmcp eval`. The operator brackets a run by
hand (`capture` once → `restore` before each candidate). The `--replay` path is
untouched and stays deterministic/offline.

## Deferred (next iterations, only if needed)

- **Eval bracketing + `--require-fixture` gate** — auto-restore before each live
  candidate; record `TaskSpec.world_fixture_id`.
- **Per-store logical dumps** — swap the volume-tar mechanism for
  `mongodump`/`pg_dump`/etc. if volume-level reset proves too coarse or slow.
- **Clarification fairness (B2)** — agents that ask a clarifying question instead
  of acting currently fail unfairly. Intended fix: the distiller emits a
  `clarification_context` on the spec; at eval time the harness answers the
  question from it and lets the agent continue without penalty. Open problem:
  detecting "this turn is a clarifying question" deterministically without
  adding a model to the scoring loop (invariant 3 permits only the Tier-2
  judge). A structured `ask_clarification` tool would make detection a
  deterministic tool-call check. Recorded here; not solved now.
