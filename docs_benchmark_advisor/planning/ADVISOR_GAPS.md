# Benchmark Advisor gap memo

Status: working memo for the next advisor wave. This file records the concrete
gaps found after reviewing the current v1 module and Studio integration, so
future implementation agents do not have to rediscover them from chat history.

## Current useful baseline

- v1 has strict schemas, deterministic planner/validator composition, guide rule
  references, golden fixtures, Studio Stage 0, and dry-run export preview.
- v1 is a good pre-run sanity gate, but it is not yet a full statistical
  advisor, generation handoff, or post-run inference layer.
- v1 routes must remain compatible while v2 is added alongside them.

## Gaps to close

- Planning statistics are labeled heuristics and do not yet provide a real
  statistical workbench: no full power curves, sensitivity analysis,
  paired-vs-unpaired assumption surfacing, multiplicity policy, or post-run
  report.
- `ValidationReportStub` declares the outcome tensor but no report generator
  consumes actual task/model/attempt outcomes.
- Intent parsing is brittle. The fixture phrase "short step finance workflows"
  works, while realistic variants such as "short finance workflows" can miss
  `short_chain` tuning.
- The dry-run export is displayed but not carried into Studio Collect or
  `/api/goal`; the visible "Carry" action is only navigation.
- `/api/advisor/validate` exists in the backend but the frontend does not expose
  structured edit/revalidate controls.
- Frontend schemas treat advisor `design` and `export_config` as `unknown`,
  weakening the client contract.
- Export `server_scope` is empty unless supplied externally; Studio does not map
  selected servers back into advisor export state.
- The validator resolves status with refused > clarification > warning >
  approved, but only exposes the first refusal as the main refusal object; users
  cannot see the full blocking issue set.
- There is no local statistical RAG/knowledge layer. The frozen guide registry
  can confirm rule ids, but it cannot retrieve human-readable statistical
  background, source snippets, or method-selection context.
- There is no guarded background job layer for corpus generation. Launching
  `scripts/build_corpus.py` from advisor export needs an explicit confirmation
  gate, command preview, job status, artifacts, and logs.

## Required next architecture

- Use a dual-engine advisor: a local RAG/stat-agent may propose and explain, but
  deterministic rules must validate every design, export, launch, and report.
- Keep v1 routes intact. Add v2 routes for richer design, validation, report,
  and guarded launch behavior.
- Build statistics first, then guarded handoff, then UI/schema/intent hardening.
