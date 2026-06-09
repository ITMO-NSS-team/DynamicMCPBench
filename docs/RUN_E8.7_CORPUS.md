# Contributor guide — run E8.7 corpus generation on your machine

Help expand the DynamicMCPBench corpus by running the headline E8.7 spec
generation on your own machine. You produce TaskSpecs; we merge them into the
shared dataset for the paper.

> **What this generates**: path-agnostic TaskSpecs over the **full ~130-server,
> ~1150-tool substrate** (`manifests/servers.json`), each authored *cross-family*
> (different model families for goal-gen vs. explorer vs. distiller). Two run
> modes: the **full 100+ server run** (the paper target — needs a one-time
> surface capture) and a **16-server lite** quick run. The full E8.7 design lives
> in `docs/EXPERIMENTS_SUITE.md §2.4`.

---

## 1. Get the repo + bootstrap

```bash
git clone https://github.com/ITMO-NSS-team/DynamicMCPBench.git
cd DynamicMCPBench
git switch main && git pull
bash scripts/bootstrap.sh
export PATH="$HOME/.local/bin:$PATH"
```

`bootstrap.sh` is idempotent and cross-platform (Linux / macOS): installs `uv` +
`node` (user-space, no sudo), creates the venv, installs the MCP servers, and
sets up the sandbox dirs under `/tmp/`. Run it once. Then sanity-check the gate:

```bash
bash scripts/check.sh   # should end with: gate: OK
```

## 2. Model access in `.env` (free and/or OpenRouter)

You can author with the **free endpoint**, with **OpenRouter**, or mix them.

**A — Free endpoint (DEAD as of 2026-06-10).** The private free endpoint that
hosted the bare-name pool (`deepseek-v4-pro`, `glm-5p1`, `kimi-k2p6`,
`minimax-m2p7`, `gpt-oss-120b`) went down. Historical configs that point at
it (E8.7 v1, E8.8) are preserved; new contributions should use OpenRouter
(option B below) against the **same model lineages**.

> The `kimi-k2p5` snapshot was retired with the endpoint — k2p6 supersedes it
> on every axis.

**B — OpenRouter (now the only path).** Set `OPENROUTER_API_KEY` (and
`_2`, `_3`, … for concurrency lanes). The canonical OR equivalents of the
former free pool:

| Old free id (dead) | OR equivalent |
|---|---|
| `deepseek-v4-pro` | `deepseek/deepseek-v4-pro` |
| `glm-5p1` | `z-ai/glm-5.1` |
| `kimi-k2p6` | `moonshotai/kimi-k2.6` |
| `gpt-oss-120b` | `openai/gpt-oss-120b` |
| `minimax-m2p7` | `minimax/minimax-m3` |

OR also lets you mix in SOTA authors: `openai/gpt-5.x`, `anthropic/claude-*`,
`google/gemini-*`, `qwen/qwen3.7-max`, `x-ai/grok-4.3`, etc.

Add the values to `.env` at the repo root (`cp .env.example .env`, then edit).

Quick reachability check (swap the model for one your endpoint serves):

```bash
uv run python -c "
import asyncio
from dmcp.llm import OpenRouterClient
async def go():
    c = OpenRouterClient(model='deepseek-v4-pro')   # or 'anthropic/claude-haiku-4.5' on OpenRouter
    r = await c.chat(messages=[{'role':'user','content':'reply OK'}], max_tokens=10)
    print('OK' if r.content else 'EMPTY', '| tokens:', (r.usage or {}))
asyncio.run(go())
"
```

A `404 on /chat/completions` ⇒ `FREE_MODELS_BASE_URL` is missing the `/v1` suffix.

## 3. Bring up docker (for the compose servers)

The compose tier (postgres / neo4j / qdrant / time / … — the 9–11 servers that
give the hardest **stateful_write** dynamism class) needs docker. Start
colima / Docker Desktop, then `docker compose up -d` (see `docs/SETUP.md`). The
~121 crawled + substrate servers don't need docker — skip this if you only want
those.

## 4. Capture tool surfaces — one-time, robust (THE step that unlocks 100+ servers)

`goal-gen` used to **crash the whole run** on a single flaky server: it live-booted
every server inside one event loop, and an anyio cancel-scope timeout leaked a
`CancelledError` that killed the run (this is why earlier guides fell back to the
16-server `local.json`). The robust path captures each server's tools in its **own
process group with a hard timeout + SIGKILL**, then writes a reusable surfaces
file that generation reads instead of live-booting:

```bash
uv run python scripts/capture_surfaces.py \
  --manifest manifests/servers.json \
  --out manifests/surfaces.json \
  --timeout 45 --concurrency 8
```

Expect **~130 / 147 servers captured, ~1150 tools**. A hanging server is SIGKILLed
and skipped — it can never crash the capture. `surfaces.json` is
`{server_id: [ToolSpec, …]}`; run it **once** and reuse it for every corpus run.
(Re-run it if you bring up more docker servers or want to refresh.)

## 5. Run the corpus generator

### 5a. Full 100+ server run (the paper target — use this)

```bash
# pick a UNIQUE --out dir so files don't collide on merge (e.g. data/corpus_e8.7_alice)
OUT=data/corpus_e8.7_<your-handle>; mkdir -p "$OUT"

uv run python scripts/build_corpus.py \
  --manifest manifests/servers.json \
  --surfaces manifests/surfaces.json \
  --explorer-models deepseek/deepseek-v4-pro,z-ai/glm-5.1,moonshotai/kimi-k2.6 \
  --distiller-candidates z-ai/glm-5.1,deepseek/deepseek-v4-pro,minimax/minimax-m3,moonshotai/kimi-k2.6 \
  --validator-model minimax/minimax-m3 \
  --goalgen-model deepseek/deepseek-v4-pro \
  --complexities simple,medium,hard \
  --per-strategy 8 \
  --budget 12 \
  --concurrency 3 \
  --out "$OUT" \
  --resume \
  > "$OUT/run.log" 2>&1 &
```

`--surfaces` makes Phase-1 goal-gen read the captured surfaces (no live boot → no
crash) across all ~130 servers; the explorer (Phase-2) still runs live but in
isolated, resumable shards. The `&` backgrounds it; `tail -f "$OUT/run.log"` to
watch.

### 5b. Lite 16-server run (quick, no capture)

For a fast contribution on the always-stable substrate (no capture step needed):

```bash
# same command, but:
  --manifest manifests/local.json     # and DROP the --surfaces line
```

### What the knobs mean

| Knob | Why this value |
|---|---|
| `--manifest manifests/servers.json` + `--surfaces …` | The full 130-server substrate via the pre-captured surfaces (robust). Use `local.json` (no `--surfaces`) for the 16-server lite run. |
| `--explorer-models deepseek/deepseek-v4-pro,z-ai/glm-5.1,moonshotai/kimi-k2.6` | 3 cross-family explorers from the OR-prefixed pool (see §6 to add more). |
| `--distiller-candidates z-ai/glm-5.1,deepseek/deepseek-v4-pro,minimax/minimax-m3,moonshotai/kimi-k2.6` | Order matters — the cross-family picker walks this list per shard and takes the first **non-explorer-family** entry; `moonshotai/kimi-k2.6` is last because it sometimes truncates the distill output. Keep ≥2 families here. |
| `--validator-model minimax/minimax-m3` | 4th-family validator stamps each spec `valid`/`invalid` (advisory; we keep the invalid ones). |
| `--goalgen-model deepseek/deepseek-v4-pro` | Model that **authors the goals** — recorded in `provenance.goalgen_model`. Must support forced/named tool-calling. Omit to use the default `anthropic/claude-haiku-4.5`. |
| `--per-strategy 8` | ≈ 360 goals (15 strategies × 3 complexities × 8). Bump to 16/24 for more. |
| `--budget 12` | Max 12 LLM turns per goal during exploration. |
| `--concurrency 3` | Set to `min(3, number_of_keys)`. With 1 key use `1` (slower but fine). |
| `--resume` | **Always on.** Kill anytime; relaunch with the same command — it skips goals already turned into specs (`provenance.goal_id`). Survives shard crashes. |

### Expected runtime / yield

- 3-key concurrent: **6–10 h**; 1-key: **~24 h**. (+ ~15 min one-time for the capture.)
- Roughly **150–200 specs** per full run after ~50–60% distill yield + ~30%
  tolerated transient exploration errors (the free endpoint is rate-limited).

## 6. Models — run them all (more families ⇒ better ablation)

The **core** panel above (deepseek + glm + kimi) is the homogeneous default. But
please **also run the extended models** — they add generator-family and
generator-*quality* spread that the paper's contamination (G0) and
generator-quality ablations need. Flag which set you used in your contribution so
we can stratify.

Extended explorer panel (OpenRouter, post-2026-06-10):

```bash
  --explorer-models deepseek/deepseek-v4-pro,z-ai/glm-5.1,moonshotai/kimi-k2.6,openai/gpt-oss-120b \
  --distiller-candidates z-ai/glm-5.1,deepseek/deepseek-v4-pro,minimax/minimax-m3,moonshotai/kimi-k2.6
```

- `openai/gpt-oss-120b` — a deliberately **weaker** generator: lower yield,
  but a valuable low-end data point for "does generator quality bias the
  corpus?". Expect fewer specs from its shard — that's the signal, not a bug.
- `minimax/minimax-m3` — newer than the retired `minimax-m2p7`; cheap and
  reliable.
- (Retired: `kimi-k2p5` was the older Kimi snapshot; k2p6 supersedes it.)

Every spec is provenance-stamped with which model authored it (§7), so mixing
models in one run is fine — we separate them at analysis time.

## 7. What gets produced (full provenance — built for the paper merge)

In your `--out` directory:

```
data/corpus_e8.7_<handle>/
├── goals_full.json             # all goals (Phase 1)
├── goals_shard_{0..N}.json     # per-shard goal slices
├── traces_shard_{0..N}.jsonl   # explorer traces
├── specs_shard_{0..N}.jsonl    # distilled specs (provenance-stamped)
├── traces.jsonl / specs.jsonl  # concatenated finals
├── coverage.md                 # human-readable coverage report
└── run.log
```

The headline file is `specs.jsonl`. Every spec's `provenance` records the **full
authoring chain** — `goalgen_model`, `explorer_model`, `distiller_model` (+ each
`…_family`), `shard_id`, `goal_id`, and the validator verdict. That is exactly
what we stratify on for the generator-contamination (G0) study and per-model
ablations, so **don't drop or rename provenance fields**.

## 8. Sharing your contribution back (merge for the paper)

1. Sanity check it has content: `wc -l "$OUT/specs.jsonl" "$OUT/traces.jsonl"` and
   skim `coverage.md` (all 15 strategies + a depth spread should be present).
2. Optionally drop the verbose log: `rm "$OUT/run.log"`.
3. Send the directory via either:
   - a PR adding it under `contributions/<handle>/` (preferred — git attribution), or
   - a tarball (`tar czf corpus_<handle>.tar.gz "$OUT"`) on the team channel.

**PR size:** `traces.jsonl` can be 5–30 MB. If the PR is too big for web review,
PR `specs.jsonl` + `coverage.md` and send `traces.jsonl` as a tarball.

**Merge semantics:** we concatenate every contributor's `specs.jsonl`, dedupe by
`task_id` (random UUID; collisions ≈ 0), and stratify by `provenance` (generator
family/model, strategy, depth, server). Your `goal_id` slugs are unique to your
run, so no manual disambiguation is needed.

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| `no API keys found for provider 'free'` | `.env` missing `FREE_MODELS_API_KEY`, or you're not in the repo root. |
| `404 … /chat/completions` | `FREE_MODELS_BASE_URL` needs the `/v1` suffix (`https://host/v1`). |
| **goal-gen crashes / `CancelledError: deadline exceeded` / `exit a cancel scope`** | You skipped the capture step. **Always pass `--surfaces manifests/surfaces.json`** (§4) on the full run — it bypasses the live boot that crashes on flaky servers. |
| `404 No endpoints found that support the provided 'tool_choice'` | A distiller/goal-gen model on OpenRouter whose provider doesn't support *forced named* tool-calling (e.g. `qwen3-coder-plus`, `minimax-m3` on some routes). Use big-lab models (OpenAI/Anthropic/Google) or the free pool for goal-gen + distill. |
| A shard `exited 1` mid-run | Expected for a transient crash. Just relaunch with the same command — `--resume` continues from where it stopped. |
| Low yield / many `llm_error` outcomes | Free endpoint is rate-limited; `--resume` lets it finish. ~50–60% distill yield is normal. |
| `LLM did not call emit_task_spec` | Old truncation bug — `git pull && git switch main`, relaunch with `--resume`. |
| Something else weird | Grab the last 50 lines of `run.log`, ping the team channel, and **don't delete the `--out` dir** (`--resume` recovers almost anything). |

## 10. FAQ

**Q: 16 or 130 servers?** A: 130 (the full `servers.json` + `--surfaces`) is the
paper target — use it. `local.json` (16) is only the quick/lite fallback.

**Q: Can I bump `--per-strategy`?** A: Yes (16 / 24) — the cross-family contract +
`--resume` still hold; expect a longer run.

**Q: Do I need both free and OpenRouter keys?** A: No. Free-only works end-to-end
(set `--goalgen-model` to a free model). OpenRouter is only needed for the SOTA /
`minimax-m3` models.

**Q: Do I commit the output to my fork?** A: Optional — traces are gitignored;
use the `contributions/` PR path in §8.

---

*Found a bug in the runner? Open an issue/PR rather than patching locally — keeping
the runner in sync keeps every contributor's corpus rows merge-clean.*
