# T03a - Human Statistical Guide Curation

## Objective

Perform a human-led statistical literature and methodology review, then harden
`STATISTICAL_GUIDE.md` into the curated knowledge pack that grounds planner
choices, validator checks, UI rationale, and future judge-based rationale
validation.

## Dependencies

- T00

## Parallelization Group

M1-A.

This is primarily a human research/curation task. Do not treat it as an
autonomous coding-agent implementation task. Agents may assist with formatting,
link checks, and consistency checks after a human curator selects the sources and
statistical rules.

## Scope

- Own `docs_benchmark_advisor/planning/STATISTICAL_GUIDE.md`.
- Define stable `guide_version` and rule ids.
- Review current and relevant literature/methodology before freezing the guide,
  including benchmark design, LLM/agent evaluation, paired comparisons,
  bootstrap/rank-stability methods, confidence intervals for proportions,
  power/MDE heuristics, multiple-comparison control, diagnostic slice analysis,
  and claim-boundary practices.
- Record a compact source ledger inside the guide or an adjacent planning note:
  what was read, why it is relevant, and which rule families it supports.
- Map user intent patterns to modes, estimands, metrics, criteria, task
  distribution implications, budget/power rules, and claim boundaries.
- Provide good/bad rationale examples for planner prompts and UI hover text.
- Define which guide rules are mandatory for each mode and criterion family.
- Distinguish evidence-backed rules from expert defaults and demo-oriented
  heuristics.

## Out Of Scope

- Runtime planner implementation.
- Validator implementation.
- UI implementation.
- RAG/retrieval infrastructure.
- Building a literature-search product or citation database.
- Stage-2 validation report implementation.

## Allowed Files/Directories

- `docs_benchmark_advisor/planning/STATISTICAL_GUIDE.md`
- optional adjacent planning note for guide sources, e.g.
  `docs_benchmark_advisor/planning/STATISTICAL_GUIDE_SOURCES.md`
- `docs_benchmark_advisor/planning/TASKS/T03a-statistical-guide.md`
- narrow updates to `docs_benchmark_advisor/planning/INTERFACES.md` if rule
  references need clarification

## Forbidden Files

- `dmcp/**`
- `dmcp-studio/**`
- runtime tests
- fixture JSON files except when coordinating with T08 after guide ids freeze

## Interfaces Consumed

- `AdvisorRequest`
- `AdvisorDesign`
- `Criterion`
- `EvidenceLedgerEntry`
- enum registries from `INTERFACES.md`
- current statistical methodology papers, benchmark/evaluation papers, and
  authoritative statistical references selected by the human curator

## Interfaces Produced

- `STATISTICAL_GUIDE.md` with `guide_version: statistical_guide.v1`.
- Stable rule ids such as `G1.pairwise.selection`,
  `G5.criterion.paired_bootstrap`, and `G7.rationale.hover`.
- Guide-reference requirements for planner, validator, fixtures, and UI.
- Source ledger mapping reviewed references to guide rule families.
- Clear labels for literature-backed rules, expert defaults, and v1 demo
  heuristics.

## Required Tests

- Human review checklist: the guide cites enough current/relevant sources to
  justify each major rule family (`G1` through `G7`) or explicitly labels that
  family as an expert default.
- Human review checklist: no source is cited as stronger evidence than it is;
  papers about public/static benchmarks are not used as proof of private/live
  deployment validity.
- Documentation consistency check: every rule id referenced in fixtures or task
  docs exists in `STATISTICAL_GUIDE.md`.
- Manual checklist: every mode has at least one intent rule, metric rule,
  criterion rule, claim-boundary rule, and rationale rule.
- Manual checklist: guide contains examples of good and bad rationale text.

## Acceptance Criteria

- Guide explains where the advisor's statistical recommendations come from.
- Guide is improved by a human-curated review of current and relevant papers,
  not by relying on unaudited LLM statistical intuition.
- Every major rule family has a cited source rationale or is explicitly marked
  as an expert/default heuristic.
- Planner agents can use guide rules without inventing external knowledge.
- Validator agents can check presence/consistency of guide references.
- UI agents can render hover rationale from evidence ledger entries.
- Rule ids are stable enough to freeze before T03 and T08 start.

## Integration Notes

T03 must consume this guide in planner prompts/rules. T02 must warn/refuse when
required guide references are missing. T06 must render hover text derived from
evidence ledger rationale. T10 must harden against unsupported guide references
and rationale overclaiming.

Because this task is human-led, downstream implementation agents should not
reinterpret the literature. They consume the frozen guide and source ledger as
the statistical authority for v1.

## Risks

- Guide becomes too vague and leaves statistical choices to the LLM.
- Guide cites papers decoratively without tying them to concrete rule families.
- Guide overfits to one paper or one benchmark tradition and ignores
  DynamicMCPBench's trace/effect-scored setting.
- Guide becomes too broad and blocks PR-sized implementation.
- Rule ids change after fixtures and tests depend on them.

## Suggested Prompt For Implementation Agent

This is not a normal autonomous implementation-agent task. Treat it as a human
curation brief:

Read current and relevant statistical methodology, benchmark-evaluation, and
LLM/agent-evaluation papers. Improve
`docs_benchmark_advisor/planning/STATISTICAL_GUIDE.md` so each major rule family
has a clear source rationale or an explicit expert-default label. Preserve
stable `statistical_guide.v1` rule ids where possible, add a compact source
ledger, and keep downstream planner/validator/UI requirements concrete. Do not
implement runtime code.
