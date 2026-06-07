"""Per-model OpenRouter prices and cost computation (E8.1 / B1).

Surface for `dmcp/llm.py::UsageAccumulator` and `scripts/cost_latency.py`. The
table is the 8-model panel from `docs/EXPERIMENTS_SUITE.md §1.1` plus the
generator/judge defaults; unknown models return a zero-cost fallback so an
unpinned candidate never crashes a run (the unknown-price flag surfaces in the
EvaluationResult summary so the Pareto stays honest).

Scope of v0: USD-per-million-tokens, two-tier (input / output). No tiered
pricing, no cache-discount, no embedding-cost (negligible against chat usage
in the candidate-agent path). When OpenRouter rotates a tag the price moves
in tandem; pin the model id and the snapshot date.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPrice:
    """USD per 1M tokens. Source: pinned snapshot from EXPERIMENTS_SUITE §1.1."""

    input_per_mtok: float
    output_per_mtok: float


_FREE = ModelPrice(0.0, 0.0)


PRICES: dict[str, ModelPrice] = {
    # Candidate panel (EXPERIMENTS_SUITE §1.1)
    "openai/gpt-5.5": ModelPrice(5.0, 30.0),
    "anthropic/claude-opus-4.8": ModelPrice(5.0, 25.0),
    "anthropic/claude-sonnet-4.6": ModelPrice(3.0, 15.0),
    "google/gemini-3.1-pro-preview": ModelPrice(2.0, 12.0),
    "qwen/qwen3.7-max": ModelPrice(1.25, 3.75),
    "moonshotai/kimi-k2.6": ModelPrice(0.68, 3.42),
    "z-ai/glm-4.7": ModelPrice(0.40, 1.75),
    "minimax/minimax-m3": ModelPrice(0.30, 1.20),
    # Generator / judge defaults
    "anthropic/claude-haiku-4.5": ModelPrice(0.80, 4.0),
    # Free endpoint pool (E8.0b; see dmcp/providers.py::FREE_MODELS).
    # Pinned at 0 so the unknown_price flag doesn't trip on legitimately-free
    # models, and so cost extrapolation reads $0 for them without special-casing.
    "deepseek-v4-pro": _FREE,
    "kimi-k2p6": _FREE,
    "kimi-k2p5": _FREE,
    "glm-5p1": _FREE,
    "gpt-oss-120b": _FREE,
    "minimax-m2p7": _FREE,
}


def get_price(model: str) -> ModelPrice | None:
    """Return the pinned price for `model`, or None if unknown."""
    return PRICES.get(model)


def compute_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """USD cost of `input_tokens` + `output_tokens` on `model`. Unknown → 0.0.

    Caller surfaces the unknown-price flag separately (see UsageAccumulator).
    """
    p = get_price(model)
    if p is None:
        return 0.0
    return (input_tokens / 1_000_000.0) * p.input_per_mtok + (output_tokens / 1_000_000.0) * p.output_per_mtok
