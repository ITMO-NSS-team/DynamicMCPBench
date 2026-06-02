# DynamicMCPBench Report

Generated from 5 TaskSpec(s) and 5 EvaluationResult(s) across 1 model(s).

## Overall pass rate

| Model | Pass rate |
|---|---|
| `anthropic/claude-haiku-4.5 [live]` | 1/5 (20%) |

## Reliability (pass^k)

Single run per task (`--repeat 1`); pass^k == pass@1. Re-run `dmcp eval --repeat K` for reliability spread.

| Model | repeats | pass^k | pass^k (no-SAE) | pass@1 |
|---|---|---|---|---|
| `anthropic/claude-haiku-4.5 [live]` | 1 | 20% | 20% | 20% |

## Error taxonomy (weighted)

Counts of each error type across tasks; E2 (wrong branch) is not auto-classified yet.

| Model | E1 | E2 | E3 | E4 | E5 | E6 | E7 | weighted |
|---|---|---|---|---|---|---|---|---|
| `anthropic/claude-haiku-4.5 [live]` | 0 | 0 | 4 | 0 | 0 | 0 | 6 | 6.6 |

## Per-task results

| task | dynamism | depth | cs | sc | claude-haiku-4.5 [live] |
|---|---|---|---|---|---|
| Search Wikipedia for articles about sola… | live_read | 6 | n | n | ✗ |
| Compare the financial health and recent … | live_read | 11 | n | n | ✗ |
| I'm currently at coordinates 40.7128, -7… | live_read | 1 | n | n | ✓ |
| Find the most recent GDP per capita data… | live_read | 11 | n | n | ✗ |
| Research technology companies in emergin… | live_read | 41 | y | n | ✗ |

## Pass rate by dynamism

| Dynamism | `claude-haiku-4.5 [live]` |
|---|---|
| static | — |
| live_read | 1/5 (20%) |
| stateful_write | — |

## Pass rate by trace depth

| Depth | `claude-haiku-4.5 [live]` |
|---|---|
| 1-2 | 1/1 (100%) |
| 3-4 | — |
| 5+ | 0/4 (0%) |

## Pass rate by complexity flag

| Subset | `claude-haiku-4.5 [live]` |
|---|---|
| cross_server=True | 0/1 (0%) |
| cross_server=False | 1/4 (25%) |
| state_coupling=True | — |
| state_coupling=False | 1/5 (20%) |
