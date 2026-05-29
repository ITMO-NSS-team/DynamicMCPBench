# Bucket A: MCP servers requiring API keys

Curated from the official MCP Registry crawl (`crawled/discovered_full.jsonl`, 10,109 records) and verified-good public packages. Once you create accounts and obtain credentials, drop the env vars into `.env` (gitignored) and we'll add the corresponding manifest entries.

Format per server:

- **server** — npm/pypi identifier (what we'd run)
- **signup** — where to register
- **env vars** — what the server actually needs at runtime
- **why useful** — what kind of agent goals this unlocks

Recommended starter pack (pick 5-7 to keep ops light): GitHub, Brave Search, Linear, Notion, Slack, Tavily, Supabase.

---

## Knowledge / search / web

### GitHub
- **server** (npm): `@modelcontextprotocol/server-github` (the deprecated stdio package; also new `github-mcp-server` Go binary)
- **signup**: https://github.com/settings/tokens (create a fine-grained or classic PAT)
- **env vars**: `GITHUB_PERSONAL_ACCESS_TOKEN`
- **why**: real repo state — issues, PRs, commits, file contents. Best for cross-server goals against `git` (sandboxed) + `github` (live read of real repos).

### Brave Search
- **server** (npm): `@modelcontextprotocol/server-brave-search`
- **signup**: https://api.search.brave.com/app/keys (free tier: 2,000 queries/month)
- **env vars**: `BRAVE_API_KEY`
- **why**: real web search results — pairs naturally with `fetch` (already in manifest) for research workflows.

### Tavily
- **server** (npm): `tavily-mcp` or via `@tavily/mcp`
- **signup**: https://app.tavily.com (free tier: 1,000 searches/month)
- **env vars**: `TAVILY_API_KEY`
- **why**: alternative search API with research-flavored answer endpoint.

### Perplexity
- **server** (npm): `@perplexity-ai/mcp-server`
- **signup**: https://docs.perplexity.ai (you need an API key under your Perplexity Pro account)
- **env vars**: `PERPLEXITY_API_KEY`
- **why**: research-style search with citations baked in.

### Exa
- **server** (npm): `exa-mcp-server`
- **signup**: https://dashboard.exa.ai (free tier: 1,000 requests/month)
- **env vars**: `EXA_API_KEY`
- **why**: semantic web search — finds pages by meaning, not keywords. Good for "find me a paper that does X" style goals.

### Firecrawl
- **server** (npm): `firecrawl-mcp-server`
- **signup**: https://firecrawl.dev (free tier: 500 credits)
- **env vars**: `FIRECRAWL_API_KEY`
- **why**: scrape + crawl complex websites with JS rendering. Useful for "extract data from this docs site" goals.

---

## Productivity / SaaS

### Linear
- **server** (npm): `@linear/mcp-server` (official) or `linear-mcp`
- **signup**: https://linear.app/settings/api (personal API key)
- **env vars**: `LINEAR_API_KEY`
- **why**: real issue tracker — create issues, update status, comment, query.

### Notion
- **server** (npm): `@notionhq/notion-mcp-server` (official)
- **signup**: https://www.notion.so/profile/integrations → "+ New integration", then share a page with the integration
- **env vars**: `NOTION_API_KEY` (sometimes `NOTION_TOKEN`)
- **why**: real workspace pages — read, write, search, comment.

### Slack
- **server** (npm): `slack-workspace-mcp-server` (or the deprecated `@modelcontextprotocol/server-slack`)
- **signup**: https://api.slack.com/apps → "Create New App" → "From scratch" → install to a workspace you control (create a test workspace if needed)
- **env vars**: `SLACK_BOT_TOKEN` (starts with `xoxb-`)
- **why**: real messaging — post, react, list channels, fetch history.

### Discord
- **server** (npm): `mcp-discord` or `@modelcontextprotocol/server-discord`
- **signup**: https://discord.com/developers/applications → "New Application" → Bot → grant intents → invite to a test server
- **env vars**: `DISCORD_TOKEN`
- **why**: parallel to Slack; useful for cross-platform messaging goals.

### Airtable
- **server** (pypi): `mcparmory-airtable` (or community npm equivalents)
- **signup**: https://airtable.com/create/tokens (personal access token; pick the bases you want exposed)
- **env vars**: `AIRTABLE_API_KEY`, `AIRTABLE_BASE_ID`
- **why**: structured database with sheets-like UX; CRUD against real records.

### Jira / Atlassian
- **server** (pypi): `mcparmory-atlassian-jira` (or `@modelcontextprotocol/server-atlassian`)
- **signup**: https://id.atlassian.com/manage-profile/security/api-tokens (free Jira Cloud account if you don't have one)
- **env vars**: `JIRA_HOST`, `JIRA_EMAIL`, `JIRA_API_TOKEN`
- **why**: complement to Linear with a different schema; gives "issue tracker" goals breadth.

---

## Email / communication

### Resend
- **server** (pypi): `mcparmory-resend`
- **signup**: https://resend.com (free tier: 100 emails/day, 3,000/month — you do need to verify a domain to actually send anywhere except onboarding@resend.dev)
- **env vars**: `RESEND_API_KEY`
- **why**: simplest "send an email" tool; great for stateful_write semantics that are easy to verify (received vs not).

### SendGrid
- **server** (pypi/npm): community `sendgrid-mcp` variants
- **signup**: https://app.sendgrid.com (free tier: 100/day forever)
- **env vars**: `SENDGRID_API_KEY`
- **why**: alternative to Resend with a more enterprise-style API surface.

---

## Databases (live)

### Supabase
- **server** (npm): `@supabase/mcp-server-supabase` (official)
- **signup**: https://supabase.com (free tier: 2 projects, 500MB Postgres each)
- **env vars**: `SUPABASE_ACCESS_TOKEN`, plus `SUPABASE_PROJECT_REF` per project
- **why**: real Postgres + auth + storage. Best for stateful_write goals against a real DB.

### Neon
- **server** (pypi): `neon-mcp-server` (also `@neondatabase/mcp` on npm)
- **signup**: https://neon.tech (free tier: serverless Postgres)
- **env vars**: `NEON_API_KEY`
- **why**: serverless Postgres with branch/restore tools — interesting for stateful goals around schema changes.

### MongoDB Atlas
- **server** (npm): `mongodb-mcp-server` (official)
- **signup**: https://www.mongodb.com/cloud/atlas (free tier: M0 shared cluster)
- **env vars**: `MONGODB_URI` (or `MDB_MCP_API_CLIENT_ID` / `MDB_MCP_API_CLIENT_SECRET`)
- **why**: document DB — different shape from our sandboxed SQLite, adds diversity.

---

## Observability / DevOps

### Sentry
- **server** (pypi): `mcparmory-sentry` or `@sentry/mcp`
- **signup**: https://sentry.io (free tier: 5k errors/month)
- **env vars**: `SENTRY_AUTH_TOKEN`, `SENTRY_ORG_SLUG`
- **why**: read real error/issue stream; live_read goals around "what's broken in service X".

### Cloudflare
- **server** (npm): community `cloudflare-mcp` or official ones
- **signup**: https://dash.cloudflare.com/profile/api-tokens (free Cloudflare account)
- **env vars**: `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`
- **why**: DNS, workers, KV — varied tool surface across networking/edge.

### Datadog
- **server** (pypi): `mcparmory-datadog`
- **signup**: https://app.datadoghq.com (free 14-day trial — note this expires, less suitable for long-term benchmark)
- **env vars**: `DD_API_KEY`, `DD_APP_KEY`
- **why**: metrics + logs querying. Skip if you don't already have a paid account.

---

## Payments / commerce

### Stripe
- **server** (npm): `@stripe/mcp` (official) or `stripe-agent-toolkit`
- **signup**: https://dashboard.stripe.com (free; use **test mode** keys only — never live)
- **env vars**: `STRIPE_SECRET_KEY` (sk_test_...)
- **why**: payments domain with rich resource types (customers, charges, subscriptions). Test mode is safe.

---

## AI infrastructure / vector DBs

### Pinecone
- **server** (pypi): `mcparmory-pinecone`
- **signup**: https://www.pinecone.io (free tier: 1 serverless index)
- **env vars**: `PINECONE_API_KEY`
- **why**: vector DB — different mental model than SQL; semantic search goals.

### Cohere
- **server** (npm): `@coherenceos/mcp-server` (note: this is Coherence, not Cohere — careful)
- For actual Cohere AI: community `cohere-mcp` variants
- **signup**: https://dashboard.cohere.com (free trial credits)
- **env vars**: `COHERE_API_KEY`
- **why**: embeddings + rerank — useful when composed with vector stores.

### HuggingFace
- **server** (community): `huggingface-mcp` / `@huggingface/mcp-server`
- **signup**: https://huggingface.co/settings/tokens (free user-access token)
- **env vars**: `HF_TOKEN`
- **why**: model hub queries, dataset metadata, inference API.

### Replicate
- **server** (pypi): `mcparmory-replicate`
- **signup**: https://replicate.com (free credits at signup)
- **env vars**: `REPLICATE_API_TOKEN`
- **why**: run hosted models — adds genuine compute-side workflow goals.

---

## Design / dev tools

### Figma
- **server** (pypi): `mcparmory-figma`
- **signup**: https://www.figma.com/developers/api (free Figma account)
- **env vars**: `FIGMA_API_KEY`
- **why**: design files — read components, comments, styles. Live_read against shared design state.

### GitLab
- **server** (pypi): `mcparmory-gitlab` (or `@modelcontextprotocol/server-gitlab`)
- **signup**: https://gitlab.com/-/user_settings/personal_access_tokens (free GitLab.com account)
- **env vars**: `GITLAB_PERSONAL_ACCESS_TOKEN`
- **why**: alternative to GitHub for breadth — different schema, same domain.

---

## Notes

- **Avoid trial-only services for long-term work**: Datadog free is 14 days; consider it lower priority unless you already have paid access.
- **Stripe MUST stay in test mode**: never put live keys in `.env`. Test-mode keys start with `sk_test_`.
- **OAuth flows** (Slack, Discord, Notion): create a personal test workspace you don't mind agents writing into — don't point them at your real workspace until you've calibrated.
- **Rate limits matter**: free tiers cap us. We're fine for benchmark generation (one trace per goal) but will want to cache aggressively in replay mode (which we already do).
- **What to put in `.env`**: just the env vars — no comments or quotes, one per line, e.g. `GITHUB_PERSONAL_ACCESS_TOKEN=ghp_...`.

When ready, list the services you've registered with and I'll wire the corresponding manifest entries with the right `env` blocks.
