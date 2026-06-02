# Running experiments — subsets and the full 100+ server set

DynamicMCPBench is **trace-native**: tasks are distilled from *real execution
traces* recorded against live MCP servers, and agents are scored on
**trajectory/effect alignment**, never on final-answer string match. This guide
shows how to go from the server manifest to a scored leaderboard, on either a
**subset** of servers or the **full** set.

```
servers.json ──goal-gen──▶ goals ──generate (explore+distill)──▶ TaskSpecs ──eval──▶ results ──report/curve/ablate
   (+catalog,                                                      (effect checkpoints,
    +direct_alt)                                                    ordering, minefields)
```

## 0. One-time setup

```bash
bash scripts/bootstrap.sh           # installs uv + node, project venv, sandbox dirs
export PATH="$HOME/.local/bin:$PATH"
echo 'OPENROUTER_API_KEY=...' >> .env   # needed for goal-gen / explore / distill / eval / verify
```

Every server launches with **no hardcoded paths** — npm servers via `npx -y
<pkg>@<ver>`, pypi servers via `uvx --from <pkg>==<ver> <entry>`. So a fresh
clone with only `node` + `uv` can bring up any server in the manifest. The first
launch of each server fetches it (cached afterwards).

## 1. The server artifacts

| File | What it is |
|---|---|
| `manifests/servers.json` | **canonical** set (100+): portable, verified, tagged. The default `--manifest` for the pipeline. |
| `manifests/catalog.json` | per-server sidecar: package coords, full tool list, `pass_rate`, and **discovered tool-dependencies**. |
| `manifests/direct_alt.json` | same-name tools across different servers — the **SAE / P_alt** primitive (seed; `reviewed:false` until human-checked). |
| `manifests/local.json` | the 16 hand-curated substrate servers (provenance). |

**Verification bar.** A crawled server is in `servers.json` only if it
initializes and **every exercised (non-destructive) tool returns ok**
(`pass_rate == 1.0`) under `dmcp verify --llm --strict --require-all`. The
verifier is **dependency-aware**: when a tool needs an id/handle produced by
another tool (a prerequisite), it first calls a producer tool, harvests a real
value, and reuses it — so genuinely-working servers aren't failed for needing
state, and the producer→consumer edge is recorded in the catalog.

**Reproduce / extend the set:**
```bash
# crawl + portable-verify the registry to a target count (resumable, detached-friendly)
uv run python scripts/collect_servers.py --target 120 --max-candidates 2000 --concurrency 10
# re-verify the substrate under the same bar, then merge + tag + classify domains + find alternatives
uv run dmcp verify -m manifests/local.json --llm --strict --require-all --json-out reports/local_verify.jsonl
uv run python scripts/enrich_manifest.py        # → servers.json + catalog.json + direct_alt.json
```

## 2. Choosing a subset (or the full set)

`dmcp subset` filters `servers.json` by tag axes into a smaller manifest you pass
to the rest of the pipeline via `--manifest`. Axes (predicates AND together;
repeatable options OR within an axis):

| Axis | Option | Values |
|---|---|---|
| domain | `--domain` | dev, web-scraping, data, science, finance, geo-maps, productivity, communication, media, security, cloud-infra, ai-ml, search, other |
| dynamism | `--dyn` | static, live_read, stateful_write |
| package | `--pkg` | npm, pypi |
| size | `--size` | small (≤3 tools), medium (≤10), large (>10) |
| has tool-deps | `--has-deps` | servers with discovered prerequisite chains |
| has alternative | `--has-alt` | servers with a same-name tool on another server (SAE) |
| arbitrary tag | `--tag` | any tag string |
| verify status | `--tag verify:full` | full (all tools 100%) vs partial (some tools need state) |

```bash
# a focused finance + science live-read subset
uv run dmcp subset --domain finance --domain science --dyn live_read -o manifests/subsets/finread.json
# servers that exercise tool-dependencies (for ordering/prerequisite experiments)
uv run dmcp subset --has-deps -o manifests/subsets/with_deps.json
# the FULL set is just servers.json itself — no subset needed
```

Pre-built subsets live under `manifests/subsets/`.

## 3. Generate tasks (goals → traces → TaskSpecs)

```bash
# 1) seed realistic goals from each server's tool surface (persona-seeded)
uv run dmcp goal-gen -m manifests/subsets/finread.json --per-server 2 --cross-pairs 1 \
    -o data/goals.json
# 2) forward-explore each goal against live servers and distill keepers into TaskSpecs
uv run dmcp generate data/goals.json -m manifests/subsets/finread.json \
    --traces-out data/traces.jsonl --specs-out data/specs.jsonl
```

A **TaskSpec** holds: a natural-language prompt, **effect checkpoints** (each with
an `equivalence_set` so any tool that produces the effect is accepted — path
agnostic), **value_produced** checkpoints, **causal-ordering constraints**
(`before_id`, capturing prerequisites observed in the trace), **minefields**
(effects that must not occur), and dynamism/complexity descriptors.

## 4. Evaluate a model

```bash
uv run dmcp eval data/specs.jsonl -m manifests/subsets/finread.json \
    --model openai/gpt-4o --repeat 3 --pool target --p-alt 0.5 --pool-size 8 \
    -o reports/eval_gpt4o.jsonl
uv run dmcp report reports/eval_gpt4o.jsonl -o reports/leaderboard.md
```

Key eval knobs (all measured on the trace, answer-agnostic):

- **Pool modes** (`--pool`): `gold` (only required tools — clean baseline),
  `target` (required + controlled distractors), `full` (the whole manifest's tool
  surface — realism).
- **Semantic density** (`--p-alt`, `--pool-size`): in `target` mode, `--p-alt`
  sets the fraction of distractors that are *direct alternatives* of the required
  tools; sweeping `p-alt ∈ {0,.25,.5,.75,1}` yields the **P_alt degradation
  curve** (`dmcp curve`).
- **Distractor sampling** (`dmcp/sampling.py`): random, hard_neg, cross_domain,
  same_name, sibling, stratified — the basis of the **SAE** (Server Attribution
  Error) ablations (`dmcp ablate`).
- **Reliability** (`--repeat k`): `pass^k` (all k attempts pass), plus
  `pass^k_no_SAE`.
- **Error taxonomy** (E1–E7, weighted): E1 missing-prerequisite, E4 SAE/server
  confusion, E5 order violation, … (`dmcp/evaluator.py`).

## 5. Tool dependencies (prerequisites) — how they flow

"One tool needs another first" is first-class:

- **Captured** at verification time (the producer→consumer edges in
  `catalog.json`, harvested from real traces — forward / trace-native).
- **Encoded** in each TaskSpec as causal-ordering constraints (`before_id`).
- **Scored** by the evaluator: missing a prerequisite is **E1** (weight 1.0); a
  correct-tools-wrong-order trajectory is **E5**.
- **Sliceable**: `dmcp subset --has-deps` isolates dependency-bearing servers.

The pre-computed dependency *graph* generator (`dmcp/baselines/graph_sampling.py`)
is a **comparison baseline** for RQ2 — the headline path stays forward/trace-native.

## 6. Full-data generation (the large corpus)

Generating the full goals + TaskSpecs corpus over all 100+ servers is an
LLM-heavy run; do it detached and resumable:

```bash
uv run dmcp goal-gen -m manifests/servers.json --per-server 2 --cross-pairs 30 -o data/goals_full.json
setsid nohup uv run dmcp generate data/goals_full.json -m manifests/servers.json \
    --traces-out data/traces_full.jsonl --specs-out data/specs_full.jsonl \
    > data/generate_full.log 2>&1 < /dev/null &
```

See `docs/PLAN.md` (E3 / E4) for the remaining experiment steps (full corpus,
RQ1–RQ4, leaderboard, human-validation subset).

> **Substrate note:** 4 substrate servers (`git`, `fs`, `arxiv`, `openlibrary`) are tagged `verify:partial` — a few of their tools need preconditions our single-shot verifier cannot synthesize (e.g. an existing branch for `git_checkout`). They are kept because they provide the only `stateful_write` and `static` coverage; in real exploration traces those tools are used in dependency order and work. Use `--tag verify:full` for the strict 132-server set.
