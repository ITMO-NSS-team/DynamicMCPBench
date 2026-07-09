#!/usr/bin/env python3
"""Capture the two DMCP Studio figures for the paper (React + Geist SPA).

Starts the REPLAY backend (which serves the built ``frontend/dist`` bundle),
drives the stages in a headless Chromium, and writes two PNGs:

* ``fig_advisor.png`` — Stage 0, the Benchmark Advisor v2 statistical workbench
  (claim card, MDE/power diagnostics, assumptions, alternatives, citations),
  captured from the default planning request as soon as a plan is returned.
* ``fig_studio.png`` — Stage 4 scoring, the verdict flip: the ``hermes3-8b``
  candidate is marked **FAILED** under effect-scoring (incomplete aggregation)
  even though its prose would pass answer-matching.

Selectors target stable ``data-testid`` hooks + semantic roles, not DOM ids
(the React rewrite dropped the old vanilla-JS ids). Regenerate after UI changes.

Requires:  uv pip install playwright && python -m playwright install chromium
Build:     (cd dmcp-studio/frontend && npm ci && npm run build)   # dist must exist
Run:       uv run python dmcp-studio/experiments/capture_screenshot.py
Out:       paper_demo/figures/fig_advisor.png, paper_demo/figures/fig_studio.png
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
STUDIO = ROOT / "dmcp-studio"
DIST = STUDIO / "frontend" / "dist"
OUT_ADVISOR = ROOT / "paper_demo" / "figures" / "fig_advisor.png"
OUT_STUDIO = ROOT / "paper_demo" / "figures" / "fig_studio.png"

# Capture geometry (env-tunable so the figures can be reframed without code edits).
SCALE = int(os.environ.get("CAP_SCALE", "2"))  # device_scale_factor: 2 = retina/print
ADVISOR_W = int(os.environ.get("CAP_ADVISOR_W", "1500"))
ADVISOR_H = int(os.environ.get("CAP_ADVISOR_H", "1400"))  # top crop of the tall workbench
STUDIO_W = int(os.environ.get("CAP_STUDIO_W", "1500"))
STUDIO_H = int(os.environ.get("CAP_STUDIO_H", "1000"))
STUDIO_FULLPAGE = os.environ.get("CAP_STUDIO_FULLPAGE", "1") == "1"
TIMEOUT = 30_000


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_health(port: int, timeout: float = 30.0) -> None:
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(0.3)
    raise RuntimeError("backend did not become healthy")


def capture(port: int) -> None:
    base = f"http://127.0.0.1:{port}/"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        # NB: do NOT set reduced_motion="reduce" — the trace-line reveal is a CSS
        # opacity 0→1 animation that prefers-reduced-motion disables, which would
        # leave the candidate trajectory invisible. Let animations run and settle.
        ctx = browser.new_context(
            viewport={"width": ADVISOR_W, "height": ADVISOR_H},
            device_scale_factor=SCALE,
        )
        page = ctx.new_page()
        # "commit" (not load/networkidle): the module script + Geist fonts delay the
        # load event in headless-shell; wait on concrete elements instead.
        page.goto(base, wait_until="commit")

        # --- Stage 0 — Design: the advisor auto-plans from the default intent. ---
        page.wait_for_selector('[data-testid="advisor-stage"][data-ready="1"]', timeout=TIMEOUT)
        # the statistical workbench: metric strip (MDE/CI) + power curve must be drawn.
        page.wait_for_selector(".advisor-v2 .metric-strip .metric", timeout=TIMEOUT)
        page.wait_for_selector(".advisor-v2 .curve-row", timeout=TIMEOUT)
        page.wait_for_timeout(700)  # let panels + verdict settle
        page.screenshot(path=str(OUT_ADVISOR), full_page=False)
        print(f"wrote {OUT_ADVISOR}")

        # --- Stage 2 — Explore: servers auto-load and the first is auto-selected, so
        # the Explore nav is already enabled. Generate a goal and run exploration. ---
        page.set_viewport_size({"width": STUDIO_W, "height": STUDIO_H})
        page.locator("button.nav-item", has_text="Explore").click()
        page.get_by_role("button", name="Run exploration").click()  # auto-waits for goal

        # --- Stage 3 — Distill: nav enables once the trace is recorded; entering the
        # stage auto-distills. --- (clicks auto-wait until each nav item is enabled)
        page.locator("button.nav-item", has_text="Distill").click()

        # --- Stage 4 — Score: pick the answer-pass / effect-fail candidate, run it. ---
        page.locator("button.nav-item", has_text="Score").click()
        page.locator("button.pick", has_text="hermes3-8b").click()
        page.get_by_role("button", name="Run candidate").click()
        # effect mode is the default; wait for the verdict to settle on FAILED.
        page.wait_for_function(
            "() => { const c = document.querySelector("
            '\'[data-testid="score-stage"] [data-testid="verdict-chip"]\');'
            " return c && c.textContent.trim() === 'FAILED'; }",
            timeout=TIMEOUT,
        )
        page.wait_for_timeout(1000)  # let the trace-line + ledger animations settle
        page.screenshot(path=str(OUT_STUDIO), full_page=STUDIO_FULLPAGE)
        print(f"wrote {OUT_STUDIO}")

        browser.close()


def main() -> int:
    if not DIST.is_dir():
        print(
            f"error: {DIST} not found — build the SPA first:\n"
            "  (cd dmcp-studio/frontend && npm ci && npm run build)",
            file=sys.stderr,
        )
        return 1
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.app:app", "--port", str(port), "--log-level", "warning"],
        cwd=str(STUDIO),
    )
    try:
        _wait_health(port)
        capture(port)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
