# T12 - Local Statistical Knowledge Base

## Objective

Create a local, reproducible statistical knowledge layer that can explain and
support v2 advisor proposals without becoming the authority for verdicts.

## Dependencies

- T03a
- T11

## Scope

- Build a local retrieval corpus from `STATISTICAL_GUIDE.md` and
  human-approved statistical references.
- Store source ids, source titles, section labels, evidence status, and stable
  retrieval snippets.
- Add deterministic retrieval by rule id, method family, and advisor mode.
- Expose retrieved citations to the v2 planner and UI.
- Document that retrieved text can justify/explain proposals, while deterministic
  validators still decide approval, warning, refusal, export, and launch.

## Out Of Scope

- Network retrieval at runtime.
- Letting RAG override validator thresholds or guide rule ids.
- Adding unreviewed papers or web text.

## Allowed Files/Directories

- `docs_benchmark_advisor/planning/STATISTICAL_GUIDE.md`
- new local knowledge files under `docs_benchmark_advisor/planning/`
- advisor retrieval module and tests

## Required Tests

- Retrieval is deterministic and offline.
- Every returned citation maps to a known guide rule id or approved source key.
- Missing source keys fail tests.
- Validator behavior is unchanged when retrieval text changes.

## Acceptance Criteria

- The advisor can show source-backed statistical explanations without relying on
  external services.
- The RAG layer is auditable and reproducible.
