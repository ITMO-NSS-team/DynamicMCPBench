# Lesson: a clean 0% is a broken run until you check `agent_call_count`

**Type:** lesson / analysis discipline. **Audience:** anyone adding a model to a
sweep or reading a leaderboard cell. Found the hard way in E9.6 (report `e9.1`).

## What happened

`openai/gpt-5.4-mini` produced a complete-looking cell: 150/150 records, no failed
shards, the runner printed `150 results in 12.5 min — ok`. Every record said
`passed=false`. Read as a score it was a plausible headline — the weakest model on
the panel scoring 0.0 under an open catalog. It was not a score. The model never
ran: every one of its 143 candidate traces carried

    outcome=llm_error
    NotFoundError: 404 — No endpoints found that can handle the requested parameters.

`dmcp/llm.py` sets `provider.require_parameters=True` for OpenRouter (added in
E8.10c, so a provider cannot silently ignore the tool schema). That model's only
provider rejects `temperature`, so OpenRouter refused to route rather than drop
the parameter. Probed directly: `require_parameters`+`tool_choice` OK,
`require_parameters`+`max_tokens` OK, `require_parameters`+`temperature` **404**,
`temperature` alone (no flag) OK — the flag is what converts a silent drop into a
loud refusal, which is exactly what it is for.

## Why the failure was invisible

The eval loop catches every exception from `llm.chat` and records
`outcome="llm_error"` (`dmcp/explorer.py:169`), then scores the empty trace
normally. A total API failure and a model that tries and fails both come out as
`passed=false`. Nothing upstream — exit codes, record counts, shard logs —
distinguishes them. `--resume` then treats those records as done, so a re-run
will not repair the cell; it will preserve it.

## How to apply

Before reporting any cell, and *always* before reporting a surprisingly low one:

```python
sm = record["summary"]
sm["agent_call_count"]          # 0 on every task => the model never ran
sm["cost"]["cost_usd"]          # 0.00 across a whole cell => same
```

Rules of thumb:
- `agent_call_count == 0` on **every** task in a cell is never a result. A real
  weak model still calls tools and still costs money.
- A cell that finishes much faster than its peers under identical settings is
  suspect: one failed request per task is quick.
- Error taxonomy alone will not save you — a dead cell shows a huge, believable
  E6 (tool blindness), because "called no tool" and "called the wrong tool" land
  in the same bucket.
- When a model cannot run under the project's determinism settings, **exclude it
  and say why**. Do not relax `require_parameters` to obtain a number: the
  provider then silently ignores `temperature`, and the resulting cell is
  non-deterministic and not comparable with the rest of the matrix. Quarantine the
  artifacts with the evidence (see `evals/cr/quarantine/README.md`) rather than
  deleting them — "no result, for this reason" is a finding; a dropped cell is not.
