# T12 - Guide Citation Index And Optional Source Pack

## Objective

Create the smallest useful knowledge layer for the v2 MVP: a deterministic
citation index over `STATISTICAL_GUIDE.md`. A larger local retrieval corpus from
human-approved references is optional follow-up work, not a blocker for the
Statistical Engine.

## Dependencies

- T03a
- T11

## Scope

- Parse or index `STATISTICAL_GUIDE.md` rule ids, section labels, evidence
  status, source keys, validator behavior, and repair suggestions.
- Expose deterministic guide citations by rule id, method family, and advisor
  mode.
- Provide short guide-derived snippets/tooltips for the v2 planner and UI.
- Keep the implementation offline and file-based; passing the full guide or a
  selected section into an LLM prompt is allowed only as optional explanation
  support.
- Document the optional future path for a larger human-approved source pack.

## Implementation

- `benchmark_advisor/guide_citations.py` parses the local
  `STATISTICAL_GUIDE.md` markdown tables, audits them against the runtime
  `KNOWN_RULE_IDS` registry and the guide's Source Reference Map, and returns
  v2 `LocalStatisticalCitation` cards.
- Citation lookup is deterministic by exact rule id, supported method family,
  and advisor mode. Returned cards include rule id, section, evidence status,
  source keys, a short guide-derived snippet, and a structured
  `StatisticalGuideReference`.
- `LocalStatisticalCitation.source_keys` carries the guide source-key anchors.
  The source text remains explanatory only; deterministic validator decisions
  still depend on structured design fields and rule-id membership.

## Out Of Scope

- Network retrieval at runtime.
- Vector RAG as a required runtime dependency.
- Letting RAG/LLM output override validator thresholds or guide rule ids.
- Adding unreviewed papers or web text to the MVP.
- Blocking T14/T13 when only the guide citation index is available.

## Allowed Files/Directories

- `docs_benchmark_advisor/planning/STATISTICAL_GUIDE.md`
- new local knowledge files under `docs_benchmark_advisor/planning/`
- advisor guide-index/citation module and tests

## Required Tests

- Guide citation lookup is deterministic and offline.
- Every returned citation maps to a known guide rule id and source key from
  `STATISTICAL_GUIDE.md`.
- Missing source keys fail tests.
- Validator behavior is unchanged when snippet text changes.

## Acceptance Criteria

- The advisor can show source-backed statistical explanations without relying on
  external services.
- The MVP does not require RAG or a stat-agent; `STATISTICAL_GUIDE.md` remains
  the default knowledge source.
- A future source pack, if added, is auditable and reproducible.
