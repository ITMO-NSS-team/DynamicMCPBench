"""Live OpenRouter price fetcher + cache (E8.0a).

Why bother when `dmcp/pricing.py` already has a static table: the user-redacted
calibration pool includes models the table doesn't pin (qwen3.6, glm-5.1,
deepseek-v3.1, ...), and OpenRouter rotates pricing per snapshot. The static
table stays as the *pinned* fallback for reproducibility; this module supplies
the *current* price for whatever id the caller asks about.

Live fetch hits `https://openrouter.ai/api/v1/models` once and caches to
`data/openrouter_prices.json` (gitignored, since `data/` is). Offline / no-key
callers can run `--prices-cache` against an already-fetched cache and never
touch the network.

OpenRouter's pricing fields are USD-per-token strings ("0.0000005"); we
multiply by 1e6 to get the per-Mtoken figure compute_cost_usd expects.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_CACHE_PATH = Path("data/openrouter_prices.json")
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


@dataclass(frozen=True)
class LivePrice:
    """USD per 1M tokens, exactly as `dmcp/pricing.py::ModelPrice`."""

    input_per_mtok: float
    output_per_mtok: float


def parse_prices(payload: dict[str, Any]) -> dict[str, LivePrice]:
    """Project the OpenRouter `/models` payload to {model_id: LivePrice}.

    Skips entries without a numeric `pricing.prompt` / `pricing.completion`
    so the parser is robust to partial or rotating listings.
    """
    out: dict[str, LivePrice] = {}
    for item in payload.get("data") or []:
        model_id = item.get("id")
        pricing = item.get("pricing") or {}
        prompt = pricing.get("prompt")
        completion = pricing.get("completion")
        if not isinstance(model_id, str):
            continue
        try:
            inp = float(prompt) * 1_000_000.0
            out_ = float(completion) * 1_000_000.0
        except (TypeError, ValueError):
            continue
        out[model_id] = LivePrice(input_per_mtok=inp, output_per_mtok=out_)
    return out


def load_cache(path: Path = DEFAULT_CACHE_PATH) -> dict[str, LivePrice]:
    """Read a previously-fetched cache. Missing file → empty dict (caller picks up)."""
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, LivePrice] = {}
    for mid, p in raw.items():
        try:
            out[mid] = LivePrice(
                input_per_mtok=float(p["input_per_mtok"]),
                output_per_mtok=float(p["output_per_mtok"]),
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


def save_cache(prices: dict[str, LivePrice], path: Path = DEFAULT_CACHE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        mid: {"input_per_mtok": p.input_per_mtok, "output_per_mtok": p.output_per_mtok}
        for mid, p in prices.items()
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fetch_live(
    *,
    cache_path: Path = DEFAULT_CACHE_PATH,
    api_key: str | None = None,
    timeout_s: float = 20.0,
) -> dict[str, LivePrice]:
    """Hit `/api/v1/models`, parse, cache, return.

    Network failures bubble up — callers should decide whether to fall back
    to the static `pricing.PRICES` table; silently swallowing the error here
    would yield "zero cost" surprise.
    """
    import urllib.request

    headers: dict[str, str] = {"Accept": "application/json"}
    key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(OPENROUTER_MODELS_URL, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310 (trusted URL)
        payload = json.loads(resp.read().decode("utf-8"))
    prices = parse_prices(payload)
    save_cache(prices, cache_path)
    return prices


def get_effective_price(model: str, live: dict[str, LivePrice]) -> LivePrice | None:
    """Live table first (covers new releases), then the static pinned table.

    The fallback exists so that a calibration run that can't reach OR's
    endpoint still produces honest numbers for the eight pinned models.
    """
    p = live.get(model)
    if p is not None:
        return p
    from dmcp.pricing import get_price

    static = get_price(model)
    if static is None:
        return None
    return LivePrice(static.input_per_mtok, static.output_per_mtok)


def compute_cost_usd(model: str, input_tokens: int, output_tokens: int, live: dict[str, LivePrice]) -> float:
    """Cost computed against the live table with static fallback. Unknown → 0.0."""
    price = get_effective_price(model, live)
    if price is None:
        return 0.0
    return (input_tokens / 1_000_000.0) * price.input_per_mtok + (
        output_tokens / 1_000_000.0
    ) * price.output_per_mtok
