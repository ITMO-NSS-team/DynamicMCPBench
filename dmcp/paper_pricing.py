"""Paper-pricing aliases — map free-pool ids to their OpenRouter equivalents.

User 2026-06-07: the headline experiments run on the free endpoint at $0
(E8.0b), but the paper has to report what those experiments WOULD have cost
on the canonical paid pool. Token counts are already captured per spec
(E8.1 `summary.cost.{prompt_tokens, completion_tokens}`); this module is the
lookup that recomputes "paper cost" against the OR price for the
analogous model.

The aliases below are best-guess and meant to be edited as snapshots
rotate. A missing alias yields `None` so the caller can surface "no paper
equivalent" rather than silently report $0.
"""

from __future__ import annotations

from dataclasses import dataclass

from dmcp.openrouter_prices import LivePrice, get_effective_price

# free model id → canonical OpenRouter id used for paper-pricing.
# Tweak as snapshots rotate; tests pin the structure (every free model has
# an alias entry) but not the targets, so renames are a one-line change.
FREE_TO_OR_ALIAS: dict[str, str] = {
    "deepseek-v4-pro": "deepseek/deepseek-v3.1",
    "kimi-k2p6": "moonshotai/kimi-k2.6",
    "kimi-k2p5": "moonshotai/kimi-k2.5",
    "glm-5p1": "z-ai/glm-5.1",
    "gpt-oss-120b": "openai/gpt-oss-120b",
    "minimax-m2p7": "minimax/minimax-m2.7",
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
