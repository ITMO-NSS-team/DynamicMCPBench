#!/usr/bin/env bash
# Idempotent environment bootstrap — sets up EVERYTHING needed to run the MCP
# servers in manifests/local.json (uv + venv + pypi servers + node for npx
# servers). Cross-platform (Linux / macOS, x64 / arm64). Safe to re-run.
# See docs/SETUP.md.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"

# 1. uv (package/venv manager)
if ! command -v uv >/dev/null 2>&1; then
  echo "installing uv ..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

# 2. node + npx (for npm-based MCP servers) — user-space official tarball, no sudo
if ! command -v node >/dev/null 2>&1; then
  echo "installing node LTS (user-space) ..."
  nos=$(uname -s); narch=$(uname -m)
  case "$nos" in Linux) plat=linux ;; Darwin) plat=darwin ;; *) plat="" ;; esac
  case "$narch" in x86_64) a=x64 ;; arm64 | aarch64) a=arm64 ;; *) a="" ;; esac
  if [ -n "$plat" ] && [ -n "$a" ]; then
    ver=$(curl -fsSL https://nodejs.org/dist/index.json \
      | python3 -c 'import json,sys;print(next(x["version"] for x in json.load(sys.stdin) if x["lts"]))')
    curl -fsSL -o /tmp/dmcp-node.tar.gz "https://nodejs.org/dist/${ver}/node-${ver}-${plat}-${a}.tar.gz"
    mkdir -p "$HOME/.local/node"
    tar -xzf /tmp/dmcp-node.tar.gz -C "$HOME/.local/node" --strip-components=1
    rm -f /tmp/dmcp-node.tar.gz
    for b in node npm npx; do ln -sf "$HOME/.local/node/bin/$b" "$HOME/.local/bin/$b"; done
  else
    echo "WARN: unsupported platform ($nos/$narch) for auto node install — install node manually"
  fi
fi
command -v node >/dev/null 2>&1 && echo "node $(node --version), npx $(npx --version)" \
  || echo "WARN: node/npx missing — npm-based MCP servers will not run"

# 3. project venv + package (dev tools + the pypi-packaged substrate servers)
[ -d .venv ] || uv venv
uv pip install -e ".[servers,dev]" || {
  echo "WARN: '.[servers,dev]' install failed; falling back to '.[dev]'"
  uv pip install -e ".[dev]"
}

# 4. sandboxed working dirs for stateful_write servers (portable /tmp paths),
#    seeded with sample content so their read tools have something to act on.
mkdir -p /tmp/dmcp-fs-sandbox /tmp/dmcp-memory /tmp/dmcp-sandbox /tmp/dmcp-arxiv
[ -f /tmp/dmcp-fs-sandbox/sample.txt ] || printf 'hello from the dmcp sandbox\n' > /tmp/dmcp-fs-sandbox/sample.txt
if [ ! -d /tmp/dmcp-sandbox-repo/.git ]; then
  git init -q /tmp/dmcp-sandbox-repo 2>/dev/null || true
fi
if [ -d /tmp/dmcp-sandbox-repo/.git ] && [ -z "$(git -C /tmp/dmcp-sandbox-repo log -1 --oneline 2>/dev/null)" ]; then
  printf '# dmcp sandbox repo\n' > /tmp/dmcp-sandbox-repo/README.md
  git -C /tmp/dmcp-sandbox-repo add -A 2>/dev/null || true
  git -C /tmp/dmcp-sandbox-repo -c user.email=dmcp@example.com -c user.name=dmcp commit -q -m "seed sandbox repo" 2>/dev/null || true
fi

# 5. soft prerequisites (warn, don't fail)
if command -v gh >/dev/null 2>&1; then
  gh auth status >/dev/null 2>&1 || echo "WARN: gh not authenticated — run 'gh auth login' for PR/auto-merge"
else
  echo "WARN: gh CLI missing — PR/auto-merge unavailable"
fi
{ [ -f .env ] && grep -q '^OPENROUTER_API_KEY=.' .env; } \
  || echo "WARN: OPENROUTER_API_KEY not set in .env — explore/distill/eval/generate/verify will fail"
if command -v docker >/dev/null 2>&1; then
  echo "docker present ($(docker --version 2>/dev/null | head -1))"
  # docker compose v2 plugin (user-space, no sudo) — needed for the E3.3 compose MCP stack
  if ! docker compose version >/dev/null 2>&1; then
    echo "installing docker compose v2 plugin (user-space) ..."
    mkdir -p "$HOME/.docker/cli-plugins"
    case "$(uname -m)" in x86_64) ca=x86_64 ;; aarch64 | arm64) ca=aarch64 ;; *) ca="" ;; esac
    case "$(uname -s)" in Linux) co=linux ;; Darwin) co=darwin ;; *) co="" ;; esac
    if [ -n "$ca" ] && [ -n "$co" ]; then
      curl -fsSL -o "$HOME/.docker/cli-plugins/docker-compose" \
        "https://github.com/docker/compose/releases/download/v2.32.4/docker-compose-${co}-${ca}" \
        && chmod +x "$HOME/.docker/cli-plugins/docker-compose" || echo "WARN: docker compose plugin install failed"
    fi
  fi
  docker compose version >/dev/null 2>&1 \
    && echo "  docker compose ready — MCP stack: docker compose -f docker-compose-mcp.yaml --profile minimal up -d --build"
else
  echo "NOTE: docker absent — the docker-compose MCP stack (E3.3) is unavailable"
fi

echo "bootstrap: OK"
