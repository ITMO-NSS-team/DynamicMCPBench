#!/usr/bin/env python3
"""Capture the DMCP Studio hero screenshot for the paper's main figure.

Starts the REPLAY backend (which serves the SPA), drives the four stages in a
headless Chromium to the scoring stage, and screenshots the verdict flip — the
``hermes3-8b`` candidate, which **passes** answer-matching but is marked
**FAILED** under effect-scoring (incomplete aggregation). Output is committed as
the paper's ``fig:studio`` so the figure regenerates as the UI evolves.

Requires:  uv pip install playwright && uv run playwright install chromium
Run:       uv run python dmcp-studio/experiments/capture_screenshot.py
Out:       paper_demo/figures/fig_studio.png
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
STUDIO = ROOT / "dmcp-studio"
OUT = ROOT / "paper_demo" / "figures" / "fig_studio.png"
OUT_ADVISOR = ROOT / "paper_demo" / "figures" / "fig_advisor.png"


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
        # `slidein` animation (opacity 0→1), which prefers-reduced-motion disables,
        # leaving the candidate trajectory invisible. Instead we let animations run
        # and wait for them to settle before the shot.
        page = browser.new_context(
            viewport={"width": 1460, "height": 1000},
            device_scale_factor=2,  # retina-crisp PNG for print
        ).new_page()
        # "commit" (not load/networkidle): the sync <script> + Google Fonts delay
        # the load events in headless-shell; wait on a concrete element instead.
        page.goto(base, wait_until="commit")

        # Stage 0 — Design: the advisor proposes a design from the default intent;
        # capture the approved verdict + evidence ledger, then carry it into Collect.
        page.wait_for_function(
            "document.getElementById('dProceed') && !document.getElementById('dProceed').disabled",
            timeout=30_000,
        )
        page.wait_for_function(
            "document.getElementById('dVerdictChip').textContent.trim() === 'APPROVED'",
            timeout=30_000,
        )
        page.wait_for_timeout(500)  # let the verdict + ledger settle
        page.screenshot(path=str(OUT_ADVISOR), full_page=True)
        page.click("#dProceed")

        # Stage 1 → 2: servers auto-load (yfinance pre-selected); generate goal + explore.
        page.wait_for_selector(".server-card", timeout=30_000)
        page.click("#toExplore")
        page.wait_for_function("document.getElementById('goalText').textContent.length > 40")
        page.click("#runExplore")
        page.wait_for_selector("#toDistill:not([disabled])", timeout=30_000)

        # Stage 3: distill.
        page.click("#toDistill")
        page.wait_for_selector("#toScore:not([disabled])", timeout=30_000)

        # Stage 4: pick the answer-pass / effect-fail candidate and run it.
        page.click("#toScore")
        page.wait_for_selector(".cand", timeout=30_000)
        page.click("text=hermes3-8b")
        page.click("#runCand")
        # wait for the verdict to settle on FAILED (effect mode is the default)
        page.wait_for_function(
            "document.getElementById('verdictChip').textContent.trim() === 'FAILED'",
            timeout=30_000,
        )
        page.wait_for_timeout(900)  # let the trace-line + ledger animations settle

        page.screenshot(path=str(OUT), full_page=True)
        browser.close()
    print(f"wrote {OUT}")
    print(f"wrote {OUT_ADVISOR}")


def main() -> int:
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
