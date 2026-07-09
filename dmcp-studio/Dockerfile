# DMCP Studio — installable demo image (REPLAY mode; booth-safe, no network).
#
# Build (from the repo root, so the context includes pyproject + dmcp/):
#   docker build -f dmcp-studio/Dockerfile -t dmcp-studio .
# Run:
#   docker run --rm -p 8000:8000 dmcp-studio
# Then open http://localhost:8000
#
# The frontend is a React + Geist (Vercel) SPA built with Vite in a Node stage;
# the Python image ships only the built bundle (frontend/dist), so the runtime
# needs no Node toolchain. REPLAY needs no MCP server packages or API keys.

# ---- Stage 1: build the SPA ----
FROM node:20-slim AS web
WORKDIR /web
COPY dmcp-studio/frontend/package.json dmcp-studio/frontend/package-lock.json ./
RUN npm ci
COPY dmcp-studio/frontend ./
RUN npm run build

# ---- Stage 2: Python runtime ----
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install the dmcp package + studio extra first (better layer caching).
# Both `dmcp` and `benchmark_advisor` are wheel packages (see pyproject
# [tool.hatch.build.targets.wheel]) and backend/app.py imports benchmark_advisor
# at load time, so both source trees must be present before the editable install.
COPY pyproject.toml ./
COPY dmcp ./dmcp
COPY benchmark_advisor ./benchmark_advisor
RUN pip install -e ".[studio]"

# Studio backend.
COPY dmcp-studio ./dmcp-studio
# The one runtime file the advisor reads from outside the wheel packages: the
# versioned statistical guide (benchmark_advisor/guide_citations.py loads it at
# design time). Without it the /api/advisor/v2/design route 500s.
COPY docs_benchmark_advisor/planning/STATISTICAL_GUIDE.md ./docs_benchmark_advisor/planning/STATISTICAL_GUIDE.md
# Built SPA bundle from the Node stage (backend serves frontend/dist when present).
COPY --from=web /web/dist ./dmcp-studio/frontend/dist

# Pre-build the frozen REPLAY fixture so the image ships ready to serve
# (asserts the three showcase verdicts at build time — a build-time smoke test).
RUN python dmcp-studio/experiments/e3_curate.py

EXPOSE 8000
WORKDIR /app/dmcp-studio
# Serve the SPA + API. Fixtures are pre-warmed on startup (FastAPI lifespan).
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
