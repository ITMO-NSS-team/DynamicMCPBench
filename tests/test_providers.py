"""E8.0b: provider registry + auto-routing.

Pins the rules that keep paid OpenRouter ids and free-pool ids from
cross-contaminating: a typo'd `kimi-k2.6` (vendorless OpenRouter id) must NOT
silently route to the free endpoint, and a bare free id must NOT silently
fall through to OpenRouter's paid pool.
"""

from __future__ import annotations

import os

import pytest

from dmcp.providers import FREE, FREE_MODELS, OPENROUTER, endpoint_for, pool_keys, resolve

# ---------------------------------------------------------------------------
# resolve()
# ---------------------------------------------------------------------------


def test_resolve_free_pool_exact_match():
    for m in FREE_MODELS:
        assert resolve(m) is FREE


def test_resolve_openrouter_default_for_namespaced_ids():
    assert resolve("openai/gpt-5.5") is OPENROUTER
    assert resolve("anthropic/claude-sonnet-4.6") is OPENROUTER
    assert resolve("moonshotai/kimi-k2.6") is OPENROUTER


def test_resolve_unknown_bare_id_falls_back_to_openrouter():
    """A typo'd free-pool id (`kimi-k2p99`) must NOT silently route to the
    free endpoint — that would charge the OpenRouter key against the wrong
    base URL and produce a confusing 401."""
    assert resolve("kimi-k2p99") is OPENROUTER
    assert resolve("deepseek-v4-pro-typo") is OPENROUTER


def test_resolve_does_not_match_substring_of_free_id():
    """`deepseek-v4-pro/extra` must not be treated as the free id — guards
    against accidental namespacing that would still hit the wrong endpoint."""
    assert resolve("deepseek-v4-pro/extra") is OPENROUTER


# ---------------------------------------------------------------------------
# endpoint_for() — env var resolution + helpful errors
# ---------------------------------------------------------------------------


def test_endpoint_for_openrouter_uses_default_base_url(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.delenv("FREE_MODELS_API_KEY", raising=False)
    base_url, key = endpoint_for(OPENROUTER)
    assert base_url == "https://openrouter.ai/api/v1"
    assert key == "sk-test"


def test_endpoint_for_free_reads_base_url_from_env(monkeypatch):
    monkeypatch.setenv("FREE_MODELS_API_KEY", "free-test")
    monkeypatch.setenv("FREE_MODELS_BASE_URL", "https://free.example.com/v1")
    base_url, key = endpoint_for(FREE)
    assert base_url == "https://free.example.com/v1"
    assert key == "free-test"


def test_endpoint_for_raises_with_specific_env_var_when_key_missing(monkeypatch):
    """Honest blame — silent fallback to a half-configured client wastes hours."""
    monkeypatch.delenv("FREE_MODELS_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="FREE_MODELS_API_KEY"):
        endpoint_for(FREE)


def test_endpoint_for_raises_when_base_url_required_but_missing(monkeypatch):
    monkeypatch.setenv("FREE_MODELS_API_KEY", "free-test")
    monkeypatch.delenv("FREE_MODELS_BASE_URL", raising=False)
    # FREE has no `default_base_url`, so missing env should raise.
    with pytest.raises(RuntimeError, match="base URL"):
        endpoint_for(FREE)


# ---------------------------------------------------------------------------
# pool_keys() — concurrency lanes via numbered env siblings
# ---------------------------------------------------------------------------


def test_pool_keys_collects_primary_and_numbered_siblings(monkeypatch):
    monkeypatch.setenv("FREE_MODELS_API_KEY", "k1")
    monkeypatch.setenv("FREE_MODELS_API_KEY_2", "k2")
    monkeypatch.setenv("FREE_MODELS_API_KEY_3", "k3")
    assert pool_keys(FREE) == ["k1", "k2", "k3"]


def test_pool_keys_returns_empty_when_no_env_set(monkeypatch):
    """Asking 'how many lanes' shouldn't raise when nothing's configured —
    raises happen later via endpoint_for so callers can probe lanes first."""
    monkeypatch.delenv("FREE_MODELS_API_KEY", raising=False)
    for i in range(2, 9):
        monkeypatch.delenv(f"FREE_MODELS_API_KEY_{i}", raising=False)
    assert pool_keys(FREE) == []


def test_pool_keys_skips_gaps(monkeypatch):
    """An env with _2 set but no _1 still finds _2 — partially-rotated envs
    don't deadhead the dispatcher."""
    monkeypatch.delenv("FREE_MODELS_API_KEY", raising=False)
    monkeypatch.setenv("FREE_MODELS_API_KEY_2", "k2")
    monkeypatch.setenv("FREE_MODELS_API_KEY_3", "k3")
    assert pool_keys(FREE) == ["k2", "k3"]


def test_pool_keys_dedups_identical_keys(monkeypatch):
    """Two env vars pointing at the same actual key shouldn't count as two
    concurrency slots — the underlying account rate-limit binds both."""
    monkeypatch.setenv("FREE_MODELS_API_KEY", "samekey")
    monkeypatch.setenv("FREE_MODELS_API_KEY_2", "samekey")
    monkeypatch.setenv("FREE_MODELS_API_KEY_3", "different")
    assert pool_keys(FREE) == ["samekey", "different"]


def test_pool_keys_works_for_openrouter_provider(monkeypatch):
    """The same numbered-sibling convention extends to OpenRouter so
    paid runs can also lane-out when the user has multiple OR keys."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "or1")
    monkeypatch.setenv("OPENROUTER_API_KEY_2", "or2")
    assert pool_keys(OPENROUTER) == ["or1", "or2"]


# ---------------------------------------------------------------------------
# Family resolution still works for the new bare-name ids
# ---------------------------------------------------------------------------


def test_free_models_resolve_to_distinct_family_slugs():
    """For E8.6's cross-family constraint to keep biting on the free pool,
    the six free models must NOT all collapse to one family slug."""
    from dmcp.families import family_of

    slugs = {m: family_of(m) for m in FREE_MODELS}
    # No model lands as 'unknown' — that would break the cross-family picker.
    assert "unknown" not in set(slugs.values()), f"unmapped family in {slugs}"
    # We expect at least 5 distinct families (gpt-oss is its own slug, deepseek
    # and minimax are singletons, kimi-k2p5/k2p6 share moonshot, glm is z-ai).
    assert len(set(slugs.values())) >= 5


def test_gpt_oss_does_not_collide_with_openai_proprietary():
    """gpt-oss is an open-weight lineage, not OpenAI's proprietary GPT line —
    bucketing them together would let cross_family_pick treat them as 'same
    family' and refuse cross-family pairings against OpenAI proprietary models."""
    from dmcp.families import family_of

    assert family_of("gpt-oss-120b") != family_of("openai/gpt-5.5")
    assert family_of("gpt-oss-120b") == "openai-oss"


def test_kimi_bare_and_moonshotai_resolve_to_same_family():
    """The free `kimi-k2p6` and the paid `moonshotai/kimi-k2.6` are the same
    underlying lineage — must share a family slug so the cross-family picker
    treats a panel that mixes them as same-family, not cross-family."""
    from dmcp.families import family_of

    assert family_of("kimi-k2p6") == family_of("moonshotai/kimi-k2.6") == "moonshot"


# ---------------------------------------------------------------------------
# Free models are priced at $0 (no unknown_price warning)
# ---------------------------------------------------------------------------


def test_free_models_have_zero_pinned_price():
    from dmcp.pricing import compute_cost_usd, get_price

    for m in FREE_MODELS:
        p = get_price(m)
        assert p is not None, f"{m} missing from PRICES table"
        assert p.input_per_mtok == 0.0 and p.output_per_mtok == 0.0
        assert compute_cost_usd(m, 1_000_000, 1_000_000) == 0.0


# ---------------------------------------------------------------------------
# OpenRouterClient auto-resolves provider via the registry
# ---------------------------------------------------------------------------


def test_openrouter_client_constructs_against_free_endpoint(monkeypatch):
    """Passing a free-pool model id with no explicit base_url/api_key must
    drive the underlying client to the FREE endpoint, not OpenRouter — that's
    the whole point of the auto-resolution path."""
    monkeypatch.setenv("FREE_MODELS_API_KEY", "free-test")
    monkeypatch.setenv("FREE_MODELS_BASE_URL", "https://free.example.com/v1")
    # Make sure OR key is absent so a bug that misroutes will raise loudly
    # rather than silently picking up OR creds.
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    from dmcp.llm import OpenRouterClient

    client = OpenRouterClient(model="kimi-k2p6")
    # AsyncOpenAI stores the base URL on `._base_url` (a URL-ish object).
    assert "free.example.com" in str(client._client.base_url)
    assert client.model == "kimi-k2p6"


def test_openrouter_client_falls_through_to_openrouter_for_paid_ids(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    monkeypatch.setenv("FREE_MODELS_API_KEY", "should-not-be-used")
    monkeypatch.setenv("FREE_MODELS_BASE_URL", "https://wrong.example.com/v1")
    from dmcp.llm import OpenRouterClient

    client = OpenRouterClient(model="anthropic/claude-sonnet-4.6")
    assert "openrouter.ai" in str(client._client.base_url)
    assert "wrong.example.com" not in str(client._client.base_url)


def test_openrouter_client_explicit_overrides_win(monkeypatch):
    """If a caller hand-passes base_url + api_key, the auto-resolver must not
    second-guess — preserves the existing API for ad-hoc client construction
    (tests, custom endpoints, etc.)."""
    # Both env vars set so neither code path would error if accidentally used.
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("FREE_MODELS_API_KEY", "free-key")
    monkeypatch.setenv("FREE_MODELS_BASE_URL", "https://wrong.example.com/v1")
    from dmcp.llm import OpenRouterClient

    client = OpenRouterClient(
        model="kimi-k2p6",
        api_key="explicit-key",
        base_url="https://explicit.example.com/v1",
    )
    assert "explicit.example.com" in str(client._client.base_url)
    # api_key isn't directly readable from AsyncOpenAI; the round-trip via env
    # is the test we have access to — the assertion above already proves the
    # explicit base_url won, which is the meaningful behavior here.
    _ = os.environ  # silence the "unused import" lint when env access happens via monkeypatch
