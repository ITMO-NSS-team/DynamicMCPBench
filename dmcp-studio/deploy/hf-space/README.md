---
title: DMCP Studio
emoji: 🔬
colorFrom: gray
colorTo: green
sdk: docker
app_port: 8000
pinned: false
license: apache-2.0
short_description: Effect-scored evaluation of LLM agents over MCP
---

# DMCP Studio — interactive demo (REPLAY)

An interactive, trace-grounded studio for **effect-scored** evaluation of LLM
agents over live MCP servers — the demonstration companion to DynamicMCPBench.

This Space runs the studio in its **deterministic REPLAY mode**: the default,
graded path. It needs **no API keys and no network** — every verdict on screen
is computed by the same code path the methodology paper reports, served from
frozen fixtures so the demo is reproducible for anyone.

## What to try

- **Stage 0 — Design.** The Benchmark Advisor turns an evaluation question into a
  statistically grounded design (claim scope, MDE / power, assumptions,
  alternatives, citations) and **refuses** the ones a small budget cannot
  support.
- **Collect → Explore → Distill → Score.** Walk a goal into a reference trace,
  distill it into path-agnostic **effect checkpoints**, then score a candidate.
- **Effect ⇄ Answer toggle.** Re-grade the same run two ways and watch the
  verdict flip — the whole point: answer-matching passes a fluent run that
  skipped required work; effect-scoring catches it.

## How this Space is built

A single Dockerfile builds the React + Geist SPA in a Node stage and serves it
same-origin from a FastAPI backend (`uvicorn backend.app:app`) on port 8000. The
image ships only the built bundle plus a pre-built REPLAY fixture, so it boots
offline. See the DynamicMCPBench repository for the full pipeline and paper.

Licensed under Apache-2.0.
