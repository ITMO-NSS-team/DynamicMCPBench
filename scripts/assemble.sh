#!/usr/bin/env bash
# Final assembly: re-verify substrate -> merge+enrich -> prebuild subsets.
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
cd ~/galyukshev/dmcp/DynamicMCPBench
mkdir -p reports manifests/subsets

echo "=== [1/3] re-verify the 16 substrate servers under --require-all ==="
uv run dmcp verify -m manifests/local.json --llm --strict --require-all \
  --server-timeout 180 \
  --output reports/local_verify.md --json-out reports/local_verify.jsonl
echo "substrate verify rc=$?"

echo "=== [2/3] enrich: merge crawled + substrate, classify domains, find alternatives ==="
uv run python scripts/enrich_manifest.py --include-local-below-1
echo "enrich rc=$?"

echo "=== [3/3] prebuild canonical subsets ==="
uv run dmcp subset -m manifests/servers.json --dyn live_read       -o manifests/subsets/live_read.json
uv run dmcp subset -m manifests/servers.json --dyn static          -o manifests/subsets/static.json
uv run dmcp subset -m manifests/servers.json --dyn stateful_write  -o manifests/subsets/stateful_write.json
uv run dmcp subset -m manifests/servers.json --pkg npm             -o manifests/subsets/npm.json
uv run dmcp subset -m manifests/servers.json --pkg pypi            -o manifests/subsets/pypi.json
uv run dmcp subset -m manifests/servers.json --has-deps            -o manifests/subsets/with_deps.json
uv run dmcp subset -m manifests/servers.json --has-alt             -o manifests/subsets/with_alt.json

echo "=== summary ==="
python3 - <<'PY'
import json, collections
d = json.load(open("manifests/servers.json"))["servers"]
print("servers.json total:", len(d))
def tagval(e, pfx):
    for t in e["tags"]:
        if t.startswith(pfx+":"):
            return t.split(":",1)[1]
    return "?"
print("dynamism:", dict(collections.Counter(e["dynamism"] for e in d)))
print("pkg:", dict(collections.Counter(tagval(e,"pkg") for e in d)))
print("domain:", dict(collections.Counter(tagval(e,"domain") for e in d)))
print("has-deps:", sum(1 for e in d if "deps:yes" in e["tags"]))
print("has-alt:", sum(1 for e in d if "alt:yes" in e["tags"]))
print("substrate:", sum(1 for e in d if "substrate" in e["tags"]))
da = json.load(open("manifests/direct_alt.json"))
print("direct_alt groups:", len(da))
PY
echo "ASSEMBLY DONE"
