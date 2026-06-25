# Benchmark Advisor golden fixtures (BA1.3 / T08)

Shared request→outcome oracles for the advisor. Every downstream task (validator
T02, planner T03, planning stats T04, Studio API T05, UI T06, integration T09)
should consume these instead of inventing local wire shapes.

These are **plain JSON, hand-maintained** — edit the files directly. Each file
follows the frozen fixture format from `../planning/INTERFACES.md`
("File And Fixture Formats"):

| field | meaning |
|---|---|
| `id` | stable, lowercase, hyphen-separated; equals the filename stem |
| `description` | one-line human summary |
| `request` | an `AdvisorRequest` (parses against the BA1.1 schema) |
| `expected_status` | `approved` / `warning` / `refused` / `needs_clarification` |
| `expected_warning_codes` | list of `warning_code` the validator should emit |
| `expected_refusal_code` | a `refusal_code`, or `null` |
| `expected_clarification_missing_fields` | list of field/concept names |
| `expected_export_subset` | partial `ExportConfig` to match; **omitted** when export is expected to be null (refused / needs_clarification) |

Guide rule ids cited anywhere in a fixture must exist in
`../planning/STATISTICAL_GUIDE.md` (`statistical_guide.v1`). The loader test
enforces this.

## Inventory

| id | mode | expected | covers |
|---|---|---|---|
| `pairwise-finance-valid` | pairwise | approved | happy path; guide-backed criterion in export |
| `leaderboard-small-budget-warning` | leaderboard | warning `underpowered_design` | budget in the leaderboard warning band |
| `regression-non-inferiority` | regression | approved | non-inferiority margin framing |
| `diagnostic-same-name` | diagnostic | approved | same-name / wrong-server diagnostic slice |
| `underpowered-refusal` | pairwise | refused `insufficient_budget` | budget below the confirmatory floor |
| `too-few-repeats-warning` | pairwise | warning `too_few_repeats` | reliability claim with 2 attempts |
| `low-cross-server-coverage-warning` | pairwise | warning `insufficient_cross_server_coverage` | cross-server intent, low coverage |
| `long-workflow-low-long-chain-warning` | pairwise | warning `insufficient_long_chain_coverage` | long-workflow intent, low long-chain |
| `recovery-low-coverage-warning` | pairwise | warning `insufficient_recovery_coverage` | recovery intent, low coverage |
| `smoke-test-only` | pairwise | warning `smoke_test_only` | tiny budget; claim scope downgraded |
| `ambiguous-intent-clarification` | pairwise | needs_clarification | pairwise with no candidate models |
| `edited-budget-drops-to-warning` | pairwise | warning `underpowered_design` | `/validate` revalidation oracle |
| `final-answer-grading-refusal` | pairwise | refused `unsupported_final_answer_claim` | final-answer grading is forbidden |
| `stateful-write-requires-sandbox-refusal` | pairwise | refused `invalid_distribution` | stateful-write without the sandbox knob |

14 fixtures spanning every response state and every validator threshold family.
