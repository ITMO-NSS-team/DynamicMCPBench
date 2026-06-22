# DMCP Studio — installable demo image (REPLAY mode; booth-safe, no network).
#
# Build (from the repo root, so the context includes pyproject + dmcp/):
#   docker build -f dmcp-studio/Dockerfile -t dmcp-studio .
# Run:
#   docker run --rm -p 8000:8000 dmcp-studio
# Then open http://localhost:8000
#
# The frontend ships as the committed Bun bundle (frontend/app.js), so the image
# needs no Node/Bun toolchain. REPLAY needs no MCP server packages or API keys.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install the dmcp package + studio extra first (better layer caching).
COPY pyproject.toml ./
COPY dmcp ./dmcp
RUN pip install -e ".[studio]"

# Studio backend + committed frontend bundle.
COPY dmcp-studio ./dmcp-studio

# Pre-build the frozen REPLAY fixture so the image ships ready to serve
# (asserts the three showcase verdicts at build time — a build-time smoke test).
RUN python dmcp-studio/experiments/e3_curate.py

EXPOSE 8000
WORKDIR /app/dmcp-studio
# Serve the SPA + API. Fixtures are pre-warmed on startup (FastAPI lifespan).
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
