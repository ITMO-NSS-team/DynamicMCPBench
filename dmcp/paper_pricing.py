"""Paper-pricing aliases — map historical free-pool ids to their OpenRouter equivalents.

User 2026-06-07: original headline experiments ran on the free endpoint at $0
(E8.0b / E8.7 v1 / E8.8), but the paper has to report what those experiments
WOULD have cost on the canonical paid pool. Token counts are captured per spec
(E8.1 `summary.cost.{prompt_tokens, completion_tokens}`); this module is the
lookup that recomputes "paper cost" against the OR price for the analogous
model.

User 2026-06-10: the free endpoint died. New experiments run against OR
directly with the IDs below as the actual model strings — but this alias map
stays so historical (E8.7 v1 / E8.8) corpus and eval rows that recorded the
bare-name free IDs (`deepseek-v4-pro`, `kimi-k2p6`, ...) still paper-cost
cleanly.

A missing alias yields `None` so the caller can surface "no paper equivalent"
rather than silently report $0.
"""

from __future__ import annotations

from dataclasses import dataclass

from dmcp.openrouter_prices import LivePrice, get_effective_price

# Historical free model id → canonical OpenRouter id used for paper-pricing.
# Tests pin the structure (every still-live free model has an alias entry);
# kimi-k2p5 was retired 2026-06-10 (k2p6 supersedes it) and is intentionally
# absent — historical evals that mention it will paper-cost as None.
FREE_TO_OR_ALIAS: dict[str, str] = {
    "deepseek-v4-pro": "deepseek/deepseek-v4-pro",
    "kimi-k2p6": "moonshotai/kimi-k2.6",
    "glm-5p1": "z-ai/glm-5.1",
    "gpt-oss-120b": "openai/gpt-oss-120b",
    "minimax-m2p7": "minimax/minimax-m3",
}


@dataclass(frozen=True)
class PaperCost:
    """Cost the paper will report for the analogous OR model.

    `usd` is None when no alias is registered or no live/static price exists
    for the alias — caller surfaces "no paper equivalent" so the
    reproducibility note in the paper stays honest.
    """

    alias: str | None
    usd: float | None


def paper_cost_for(
    model: str,
    input_tokens: int,
    output_tokens: int,
    live: dict[str, LivePrice],
) -> PaperCost:
    """OR-equivalent cost for free-pool `model`'s token usage.

    Resolution order: registered alias → live OR price → static pinned price
    in `dmcp/pricing.py`. Models already on OR (anything with a vendor slash)
    paper-cost themselves at their own price.
    """
    alias = FREE_TO_OR_ALIAS.get(model)
    if alias is None and "/" in model:
        # Already an OR-style id — paper-cost is its own price.
        alias = model
    if alias is None:
        return PaperCost(alias=None, usd=None)
    price = get_effective_price(alias, live)
    if price is None:
        return PaperCost(alias=alias, usd=None)
    usd = (input_tokens / 1_000_000.0) * price.input_per_mtok + (
        output_tokens / 1_000_000.0
    ) * price.output_per_mtok
    return PaperCost(alias=alias, usd=usd)
