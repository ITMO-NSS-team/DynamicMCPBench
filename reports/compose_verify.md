# docker-compose MCP stack — smoke-vet report (E3.3)

`manifests/compose.json` wires the 13 MCP servers from `docker-compose-mcp.yaml`
as HTTP/SSE entries. Bring the stack up (`docs/SETUP.md`), then
`dmcp verify -m manifests/compose.json`. The servers that pass the strict
`--require-all` gate are also folded into `manifests/servers.json` (tier:compose).

Verified on itmo-laba 2026-06-02 (each server brought up + verified individually):

| server_id | transport | dynamism | endpoint | verify |
|---|---|---|---|---|
| `compose_duckdb` | sse | stateful_write | `http://localhost:8008/sse` | **fail** — init failed: ExceptionGroup: unhandled errors in a TaskGroup |
| `compose_elasticsearch` | streamable_http | stateful_write | `http://localhost:8010/mcp` | **fail** — init failed: McpError: Session terminated |
| `compose_git` | sse | stateful_write | `http://localhost:8019/sse` | **partial** — 1/12 tools ok (pass_rate 0.08) |
| `compose_grafana` | sse | live_read | `http://localhost:8012/sse` | **partial** — 13/44 tools ok (pass_rate 0.30) |
| `compose_kafka` | streamable_http | stateful_write | `http://localhost:8018/mcp` | **partial** — 7/8 tools ok (pass_rate 0.88) |
| `compose_meilisearch` | streamable_http | stateful_write | `http://localhost:8011/mcp` | **fail** — init failed: McpError: Session terminated |
| `compose_mongo` | streamable_http | stateful_write | `http://localhost:8002/mcp` | **partial** — 19/25 tools ok (pass_rate 0.76) |
| `compose_neo4j` | sse | stateful_write | `http://localhost:8003/sse` | **full** — 3/3 tools ok |
| `compose_postgres` | sse | stateful_write | `http://localhost:8001/sse` | **full** — 9/9 tools ok |
| `compose_prometheus` | sse | live_read | `http://localhost:8013/sse` | **fail** — compose up failed/timed out (registry throttling or build er |
| `compose_qdrant` | sse | stateful_write | `http://localhost:8005/sse` | **full** — 2/2 tools ok |
| `compose_redis` | sse | stateful_write | `http://localhost:8006/sse` | **fail** — server timeout >100s |
| `compose_time` | sse | static | `http://localhost:8020/sse` | **full** — 2/2 tools ok |

**4/13 pass the strict 100% gate** (postgres, neo4j, qdrant, time). Partials need DB state or a different endpoint path; streamable_http servers (elasticsearch/meilisearch) drop the session — likely a path/handshake mismatch to revisit.
