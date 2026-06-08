# Contributor guide — run E8.7 corpus generation on your machine

Help expand the DynamicMCPBench corpus by running the headline E8.7 spec
generation on your own machine. You produce TaskSpecs; we merge them into
the shared dataset. **No cost** — everything runs against the free
endpoint.

> **What this is generating**: ~150–200 path-agnostic TaskSpecs per run,
> each authored cross-family (different model families for explorer vs.
> distiller) over the 16-server local substrate. The full E8.7 design
> lives in `docs/EXPERIMENTS_SUITE.md §2.4`.

## 1. Get the repo + bootstrap

```bash
git clone https://github.com/ITMO-NSS-team/DynamicMCPBench.git
cd DynamicMCPBench
git switch main && git pull
bash scripts/bootstrap.sh
export PATH="$HOME/.local/bin:$PATH"
```

`bootstrap.sh` is idempotent and cross-platform (Linux / macOS). It
installs `uv` + `node` (user-space, no sudo), creates the venv, installs
the MCP servers, and sets up the sandbox dirs under `/tmp/`. Run it once.

Verify the gate is green before going further:

```bash
bash scripts/check.sh
```

## 2. Add the free-models access to `.env`

The free endpoint hosts 6 models at $0. **Ask the team lead** (privately
— don't paste keys into chat or PRs) for:

- `FREE_MODELS_BASE_URL`
- `FREE_MODELS_API_KEY` (your primary key)
- Optionally `FREE_MODELS_API_KEY_2`, `_3`, … if more keys are available
  for concurrency

Add them to `.env` at the repo root:

```bash
cp .env.example .env
# then edit .env to add the values you received
```

Quick sanity check that the endpoint is reachable:

```bash
uv run python -c "
import asyncio
from dmcp.llm import OpenRouterClient
async def go():
    c = OpenRouterClient(model='deepseek-v4-pro')
    r = await c.chat(messages=[{'role':'user','content':'reply OK'}], max_tokens=10)
    print('OK,' if r.content else 'EMPTY,', 'tokens:', (r.usage or {}).get('prompt_tokens'), '+', (r.usage or {}).get('completion_tokens'))
asyncio.run(go())
"
```

Expected output: a line ending with token counts (>0). If you see a 404
on `/chat/completions`, your `FREE_MODELS_BASE_URL` is missing the `/v1`
suffix.

## 3. (Optional) Bring up docker

The 16-server `manifests/local.json` substrate doesn't need docker, so
the doc below uses it. If you also want the 11 docker-compose servers
(more SAE coverage), start `colima` / Docker Desktop first.

## 4. Run the corpus generator

This is the exact configuration we're running centrally. **Please use it
unchanged** so all contributions are homogeneous and easy to merge.

```bash
# pick a UNIQUE --out dir for your machine so files don't collide on merge.
# Replace `<your-handle>` below (e.g. data/corpus_e8.7_alice).
OUT=data/corpus_e8.7_<your-handle>
mkdir -p "$OUT"

uv run python scripts/build_corpus.py \
  --manifest manifests/local.json \
  --explorer-models deepseek-v4-pro,glm-5p1,kimi-k2p6 \
  --distiller-candidates glm-5p1,deepseek-v4-pro,minimax-m2p7,kimi-k2p6 \
  --validator-model minimax-m2p7 \
  --complexities simple,medium,hard \
  --per-strategy 8 \
  --budget 12 \
  --concurrency 3 \
  --out "$OUT" \
  --resume \
  > "$OUT/run.log" 2>&1 &
```

The `&` puts it in the background so you can close the terminal. Tail
the log to peek:

```bash
tail -f "$OUT/run.log"
```

### What the knobs mean

| Knob | Why this value |
|---|---|
| `--manifest manifests/local.json` | The 16 stable servers (time, fetch, git, sqlite, fs, memory, wikipedia, arxiv, …) |
| `--explorer-models deepseek-v4-pro,glm-5p1,kimi-k2p6` | 3 cross-family explorers from the free pool |
| `--distiller-candidates glm-5p1,deepseek-v4-pro,…` | Order matters — `kimi-k2p6` is last because it sometimes truncates the distill output. The cross-family picker walks this list per shard and picks the first non-explorer-family entry. |
| `--validator-model minimax-m2p7` | 4th-family validator stamps each spec as `valid`/`invalid` (advisory; we don't drop the invalid ones) |
| `--per-strategy 8` | ≈ 290 goals total before resume / yield filtering |
| `--budget 12` | Max 12 LLM turns per goal during exploration |
| `--concurrency 3` | Set this to `min(3, number_of_keys_you_have)`. With 1 key, use `1` (it'll still complete, just slower). |
| `--resume` | Make sure this is **always on**. Lets you kill the run anytime; relaunch picks up exactly where it stopped. |

### Expected runtime

- 3-key concurrent: **6–10 hours** to finish all 290 goals
- 1-key sequential: **~24 hours**

Roughly **150–200 specs** per full run after yield filtering. You can
kill any time and restart later — `--resume` will pick up where you
left off.

## 5. What gets produced

In your `--out` directory:

```
data/corpus_e8.7_<your-handle>/
├── goals_full.json          # all goals from Phase 1 (290 entries)
├── goals_shard_{0,1,2}.json # per-shard goal slices
├── traces_shard_{0,1,2}.jsonl  # explorer traces
├── specs_shard_{0,1,2}.jsonl   # distilled specs (provenance-stamped)
├── traces.jsonl             # concat of per-shard traces (final)
├── specs.jsonl              # concat of per-shard specs (final)
├── coverage.md              # human-readable coverage report
└── run.log                  # full session log
```

The headline file is `specs.jsonl`. Each row is a `TaskSpec`. The
`provenance` field on every spec records which models authored it
(`explorer_model`, `explorer_family`, `distiller_model`, `distiller_family`,
`shard_id`, `goal_id`) plus the validator's verdict — exactly what we
need to stratify the corpus at analysis time.

## 6. Sharing your contribution back

When the run finishes (or you've decided you've contributed enough):

1. **Sanity check** the corpus has real content:

   ```bash
   wc -l "$OUT/specs.jsonl" "$OUT/traces.jsonl"
   ```

2. **Optionally** strip the `run.log` (it's verbose and not needed):

   ```bash
   rm "$OUT/run.log"
   ```

3. **Send the directory** to the maintainer via:
   - A pull request that adds the dir under `contributions/` (preferred —
     gets attributed in git history), OR
   - A tarball (`tar czf corpus_<handle>.tar.gz "$OUT"`) shared on the
     team channel.

**Note on PR size:** the `traces.jsonl` file can be 5-30 MB. If the PR
is too large for GitHub web review, send only `specs.jsonl` +
`coverage.md` via PR and the traces via tarball.

### Merge semantics

Each contributor's specs land in its own subdir. At merge time we:

1. Concatenate every contributor's `specs.jsonl`
2. Deduplicate by `task_id` (random UUID; collisions ≈ 0)
3. Re-validate any specs whose `provenance.validator.verdict == invalid`
   are kept (advisory; downstream filters can drop them)

Your `provenance.goal_id` will be unique to your run (the goal-gen LLM
mints kebab-case slugs per invocation; cross-contributor collisions are
astronomically unlikely). So no manual disambiguation is required.

## 7. Troubleshooting

### `no API keys found for provider 'free'`
Your `.env` is missing `FREE_MODELS_API_KEY`, or the script can't find
`.env` (run from the repo root).

### `Path not found: /chat/completions`
`FREE_MODELS_BASE_URL` is missing the `/v1` suffix. Should look like
`https://<host>/v1`, not `https://<host>/`.

### All shards exit 1 after a few goals
You're on a pre-PR-66 commit. Run `git pull && git switch main` and
relaunch with the same command + `--resume` — your progress is preserved.

### Yield rate looks low / many `llm_error` outcomes
The free endpoint is rate-limited or congested. The `--resume` design
means you can just let the run finish; we tolerate ~30% transient
exploration errors per the calibration. The distill rate of ~50–60% is
expected.

### Distill error: "LLM did not call emit_task_spec"
Pre-PR-63 truncation bug. Pull main and relaunch with `--resume`.

### Something else weird
Grab the last 50 lines of `run.log` and ping the team channel. Don't
delete the output dir — `--resume` is robust to almost any crash.

## 8. FAQ

**Q: Can I change `--per-strategy` to produce more specs?**
A: Yes, increase to 16 or 24. The cross-family contract and resume both
still work. Just expect a longer run.

**Q: Can I use a different manifest?**
A: Strongly prefer `manifests/local.json` for now. The full 147-server
substrate works but isn't fully stable on every machine yet.

**Q: Can I add more explorers (kimi-k2p5, gpt-oss-120b)?**
A: Yes, but please flag it in the contribution so we can stratify by
explorer family at analysis time. Don't change `--distiller-candidates`
order — the working distillers up front matters.

**Q: Do I need to commit my output to my fork?**
A: Optional. The traces are gitignored by default; you'll need to
force-add or move them outside `traces/`. The PR-based contribution path
above handles this cleanly via `contributions/`.

---

*If you find a bug in the runner, please open an issue or PR rather than
patching locally — keeping the runner in sync ensures merge-clean
corpus rows.*
