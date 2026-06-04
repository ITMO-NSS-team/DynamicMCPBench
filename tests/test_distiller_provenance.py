"""E8.6: distiller auto-stamps explorer + distiller family on every TaskSpec.

The cross-family panel relies on G0 stratification by author family —
covered here by the unit on `_build_provenance` (the helper the distiller
uses to construct the per-spec stamp).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from dmcp.distiller import _build_provenance
from dmcp.trace import Trace


def _trace(*, llm_model: str | None = "openai/gpt-5.5") -> Trace:
    seed = {} if llm_model is None else {"llm_model": llm_model}
    return Trace(trace_id=uuid.uuid4(), goal="g", seed_metadata=seed, started_at=datetime.now(UTC))


# ---------------------------------------------------------------------------
# _build_provenance — surface shape + auto-derivation
# ---------------------------------------------------------------------------


def test_build_provenance_auto_derives_families_from_model_strings():
    prov = _build_provenance(_trace(llm_model="openai/gpt-5.5"), "anthropic/claude-opus-4.8", None)
    assert prov["explorer_model"] == "openai/gpt-5.5"
    assert prov["explorer_family"] == "openai"
    assert prov["distiller_model"] == "anthropic/claude-opus-4.8"
    assert prov["distiller_family"] == "anthropic"


def test_build_provenance_omits_explorer_when_trace_lacks_llm_model():
    """A hand-built trace without seed_metadata.llm_model gets no explorer
    fields — honest absence beats fake "unknown" entries (matches the IAE
    rate-is-None pattern)."""
    prov = _build_provenance(_trace(llm_model=None), "anthropic/claude-opus-4.8", None)
    assert "explorer_model" not in prov
    assert "explorer_family" not in prov
    assert prov["distiller_family"] == "anthropic"


def test_build_provenance_lets_runner_overrides_supersede_auto_fields():
    """The build_corpus runner re-stamps `explorer_model` per shard — the
    runner is the authoritative source when it disagrees with the trace
    (e.g. the explorer rotated mid-batch)."""
    overrides = {
        "explorer_model": "google/gemini-3.1-pro-preview",
        "explorer_family": "google",
        "shard_id": 2,
    }
    prov = _build_provenance(_trace(llm_model="openai/gpt-5.5"), "anthropic/claude-opus-4.8", overrides)
    assert prov["explorer_family"] == "google"
    assert prov["shard_id"] == 2
    assert prov["distiller_family"] == "anthropic"  # not overridden → keeps auto value


def test_build_provenance_handles_unknown_model_families():
    prov = _build_provenance(_trace(llm_model="acme/mystery-x"), "acme/distiller-y", None)
    assert prov["explorer_family"] == "unknown"
    assert prov["distiller_family"] == "unknown"
