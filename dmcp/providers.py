"""LLM provider registry — auto-routes model ids to their base URL + API key.

The candidate-agent loop and the distiller/judge use one client class
(`dmcp.llm.OpenRouterClient`) regardless of which API actually serves a given
model. This module is the lookup that resolves `model_id → Provider` so the
client constructor can pick the right endpoint without callers passing
`base_url` and `api_key` per site.

OpenRouter is the default: anything not registered here lands there. A second
provider (`FREE`) serves a private endpoint where bare-name models live free of
charge. Both expose the OpenAI Chat Completions
surface, so the openai client transport works against either with only the
base URL flipped.

Scope of v0: name-prefix routing. The registry is small enough that an
exact-match check + a slash-prefix fallback is clearer than a full pattern
table. Adding a third provider is a one-line entry + an env var.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


@dataclass(frozen=True)
class Provider:
    """One LLM endpoint. `default_base_url` is used when `base_url_env` is unset
    or no env var is named — needed so OpenRouter (the default) can ship without
    requiring an extra env var beyond the API key."""

    name: str
    api_key_env: str
    base_url_env: str | None = None
    default_base_url: str | None = None


OPENROUTER = Provider(
    name="openrouter",
    api_key_env="OPENROUTER_API_KEY",
    base_url_env=None,
    default_base_url=OPENROUTER_BASE_URL,
)

# Private endpoint with a small free-tier model pool. The base URL is set per
# environment so deployment moves can't strand the calibration.
FREE = Provider(
    name="free",
    api_key_env="FREE_MODELS_API_KEY",
    base_url_env="FREE_MODELS_BASE_URL",
    default_base_url=None,
)


# Bare model ids (no slash) served by the free endpoint.
#
# 2026-06-10: the free endpoint died. These IDs still route to FREE here so
# any historical config that references them surfaces an honest 5xx instead
# of silently misrouting to OpenRouter (which doesn't carry the bare names
# either). New experiments use the OR-prefixed equivalents directly
# (see dmcp/paper_pricing.py::FREE_TO_OR_ALIAS).
# kimi-k2p5 retired (k2p6 supersedes it).
#
# 2026-07-07: HydraGPT restored the free/private generation route at
# https://hydragpt.ru/v1. Keep the historical ids and add the current Hydra
# bare ids so `dmcp generate` / `scripts/build_corpus.py` can route them through
# FREE_MODELS_BASE_URL + FREE_MODELS_API_KEY without call-site changes.
FREE_MODELS: tuple[str, ...] = (
    "deepseek-v4-pro",
    "deepseek-v4-flash",
    "kimi-k2p6",
    "kimi-k2p7",
    "glm-5p1",
    "gpt-oss-120b",
    "minimax-m2p7",
    "minimax-m3",
    "nemotron-3-ultra",
)


def resolve(model: str) -> Provider:
    """Pick the provider for `model`. Exact match on the free pool first;
    everything else (including all `vendor/model` namespaced ids) → OpenRouter.

    Exact-match (not prefix) on the free pool because every free id is bare
    and could otherwise collide with `kimi-*` family slugs in OpenRouter.
    """
    if model in FREE_MODELS:
        return FREE
    return OPENROUTER


def pool_keys(provider: Provider) -> list[str]:
    """Return every API key configured for `provider`, in priority order.

    The primary `<env>` is checked first; numbered siblings `<env>_2`, `<env>_3`,
    ... add concurrency lanes (E8.0b). Empty entries are skipped so a partially
    rotated env doesn't deadhead a parallel dispatcher. Keys are deduplicated
    while preserving order — two env vars pointing at the same actual key
    shouldn't count as two concurrency slots.

    A provider with no keys raises `endpoint_for` later; we don't raise here so
    callers can ask "how many lanes do I have?" without paying the error.
    """
    seen: set[str] = set()
    out: list[str] = []
    suffixes = ("", "_2", "_3", "_4", "_5", "_6", "_7", "_8")
    for suffix in suffixes:
        key = os.environ.get(provider.api_key_env + suffix)
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def endpoint_for(provider: Provider) -> tuple[str, str]:
    """Return `(base_url, api_key)` for `provider`, reading env vars in turn.

    Raises with the specific env var the caller forgot — silent fallback to
    a half-configured client wastes hours when a key is missing.
    """
    api_key = os.environ.get(provider.api_key_env)
    if not api_key:
        raise RuntimeError(
            f"{provider.api_key_env} not set — needed for provider {provider.name!r} (checked env + .env)"
        )
    base_url: str | None = None
    if provider.base_url_env:
        base_url = os.environ.get(provider.base_url_env)
    if not base_url:
        base_url = provider.default_base_url
    if not base_url:
        raise RuntimeError(
            f"base URL for provider {provider.name!r} not configured "
            f"(env {provider.base_url_env or '-'} and no default)"
        )
    return base_url, api_key
