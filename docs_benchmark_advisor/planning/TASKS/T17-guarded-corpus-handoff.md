# T17 - Guarded Corpus Handoff

## Objective

Connect approved advisor export to corpus generation through an explicit,
guarded background job layer.

## Dependencies

- T11
- T13
- T16

## Scope

- Add a v2 launch endpoint that accepts an approved or warning export plus
  explicit user confirmation.
- Build a command preview for `scripts/build_corpus.py`.
- Keep the first execution target corpus/specs/traces only; no leaderboard/eval.
- Add job status: queued, running, succeeded, failed, cancelled if supported.
- Capture logs and artifact paths for goals, specs, traces, and coverage output.
- Enforce sandbox and stateful-write guards.
- Keep `/api/advisor/v2/design` side-effect free.

## Out Of Scope

- Full `dmcp bench` launch.
- Paid evaluation without separate approval.
- Changing `scripts/build_corpus.py` generation algorithms.

## Allowed Files/Directories

- Studio backend job layer
- advisor launch schema/service
- Studio frontend launch/status UI
- launch tests

## Required Tests

- Launch is refused without confirmation.
- Launch is refused for refused or clarification designs.
- Launch is refused when sandbox requirements are unmet.
- Dry-run command preview is deterministic.
- Job status and artifacts render in Studio.
- v2 design route still has no side effects.

## Acceptance Criteria

- Users can safely move from advisor design to corpus generation without hidden
  execution.
- First handoff produces only corpus/specs/traces artifacts.
