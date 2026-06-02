#!/usr/bin/env bash
# Bring up each compose MCP server one at a time (gentle on Docker Hub throttling),
# verify it under the strict 100% gate, record the result. Detached + resumable.
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
cd ~/galyukshev/dmcp/DynamicMCPBench
mkdir -p /tmp/compose_results
touch FEDOT.MAS/.env
CF=docker-compose-mcp.yaml
SVCS="postgres mongo neo4j qdrant redis duckdb elasticsearch meilisearch grafana prometheus kafka git time"

for svc in $SVCS; do
  res=/tmp/compose_results/compose_${svc}.jsonl
  [ -s "$res" ] && { echo "[$svc] already has result, skip"; continue; }
  echo "===== $(date +%H:%M:%S) bringing up ${svc}-mcp ====="
  timeout 420 docker compose -f $CF up -d --build "${svc}-mcp" > /tmp/up_${svc}.log 2>&1
  rc=$?
  echo "[$svc] up rc=$rc"
  if [ $rc -ne 0 ]; then
    echo "{\"server_id\":\"compose_${svc}\",\"ok\":false,\"reason\":\"compose up failed/timed out (registry throttling or build error)\",\"pass_rate\":0}" > "$res"
    continue
  fi
  sleep 30   # let the server + backend become ready
  echo "===== verify compose_${svc} ====="
  timeout 150 uv run dmcp verify -m manifests/compose.json --server "compose_${svc}" \
    --llm --strict --require-all --server-timeout 100 \
    --output /tmp/compose_results/compose_${svc}.md --json-out "$res" >> /tmp/up_${svc}.log 2>&1
  if [ ! -s "$res" ]; then
    echo "{\"server_id\":\"compose_${svc}\",\"ok\":false,\"reason\":\"verify produced no result (killed/unreachable)\",\"pass_rate\":0}" > "$res"
  fi
  python3 -c "import json;r=json.load(open('$res'));print('[%s] ok=%s pr=%s %s'%('$svc',r.get('ok'),r.get('pass_rate'),str(r.get('reason',''))[:50]))" 2>/dev/null || echo "[$svc] result parse issue"
done

echo "===== ALL DONE — summary ====="
python3 - <<'PY'
import json, glob
rows = []
for f in sorted(glob.glob("/tmp/compose_results/compose_*.jsonl")):
    try:
        r = json.load(open(f))
    except Exception:
        continue
    rows.append((r["server_id"], r.get("ok"), r.get("pass_rate"), r.get("ok_count"), r.get("tool_count")))
for sid, ok, pr, okc, tc in rows:
    print(f"{sid:22} ok={ok!s:5} pass_rate={pr} ({okc}/{tc})")
print("PASS(full):", sum(1 for _, ok, pr, *_ in rows if ok and pr == 1.0), "/", len(rows))
PY
echo "BRINGUP_VERIFY_DONE"
