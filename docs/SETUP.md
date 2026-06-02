# Setup — running the MCP servers

One command brings up everything needed to run every server in
`manifests/local.json` (the pypi-packaged ones and the npm/`npx` ones):

```bash
bash scripts/bootstrap.sh
```

`bootstrap.sh` is idempotent and cross-platform (Linux / macOS, x64 / arm64). It:

1. installs **uv** (if missing) into `~/.local/bin`;
2. installs **node LTS** (if missing) user-space into `~/.local` (no sudo) — needed
   for the `npx`-based servers (`fs`, `memory`, and the cyanheads public-API set);
3. creates the project **venv** and installs `dmcp` + the pypi substrate servers
   (`.[servers,dev]`);
4. creates the sandboxed working dirs under `/tmp/` for the `stateful_write`
   servers (`fs`, `memory`, `sqlite`, `git`, `arxiv`);
5. warns about soft prerequisites: `gh` auth (for PR/auto-merge), `OPENROUTER_API_KEY`
   in `.env` (for explore/distill/eval/verify), and `docker` (for the compose stack).

After bootstrap, ensure `~/.local/bin` is on your `PATH`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

## Server tiers

- **pypi / stdio** (`time`, `fetch`, `git`, `sqlite`, `wikipedia`, `arxiv`, `yfinance`)
  — installed by `uv pip install -e ".[servers]"`, launched as `python -m <module>`.
- **npx / node** (`fs`, `memory`, `osm`, `wikidata`, `worldbank`, `eurostat`,
  `crossref`, `openlibrary`, `pubmed`) — fetched on first use via `npx -y`.
- **docker** (`docker-compose-mcp.yaml`) — a heavier DB-backed stack
  (postgres / mongo / neo4j / qdrant / redis / ...). Bring it up with
  `docker compose -f docker-compose-mcp.yaml up -d`. Optional; wired as a manifest
  in step E3.3.

## Verifying servers

`dmcp verify --manifest manifests/local.json` boots each server, lists its tools,
and exercises every tool (synthesizing arguments from the input schema), writing a
per-server / per-tool pass/fail report. Use it after adding servers.

Paths are kept portable (`/tmp/...`, which resolves correctly on both Linux and
macOS) so the manifest works on any contributor's machine.

## Canonical experiment manifest (`manifests/servers.json`)

`servers.json` is the **canonical** set used for experiments — **136 servers**
(120 crawled no-creds + the 16-server substrate), all launched with **no hardcoded
paths**:

- crawled servers run via `npx -y <pkg>@<ver>` (npm) or `uvx --from <pkg>==<ver>
  <entry>` (pypi) — fetched on first use; only `node` + `uv` are required;
- the substrate servers run from the project venv (after `bash scripts/bootstrap.sh`).

Each crawled server passed `dmcp verify --llm --strict --require-all`: it
initializes and **every exercised non-destructive tool returns ok**, using
dependency-aware prerequisite resolution (a tool needing an id produced by another
is satisfied by first calling that producer). Sidecars:

- `manifests/catalog.json` — package coords, tool list, discovered tool-dependencies, `pass_rate`;
- `manifests/direct_alt.json` — same-name cross-server tool groups (the SAE / P_alt primitive);
- `manifests/subsets/` — prebuilt subsets (by dynamism / package / deps / alt).

Reproduce or extend the set:

```bash
uv run python scripts/collect_servers.py --target 120 --max-candidates 2000 --concurrency 10
uv run dmcp verify -m manifests/local.json --llm --strict --require-all --json-out reports/local_verify.jsonl
uv run python scripts/enrich_manifest.py --include-local-below-1
```

Pick a subset (or use the full set) and run the pipeline — see **`docs/EXPERIMENTS.md`**:

```bash
uv run dmcp subset --domain finance --dyn live_read -o manifests/subsets/fin.json
uv run dmcp goal-gen -m manifests/subsets/fin.json --per-server 2 -o data/goals.json
```
