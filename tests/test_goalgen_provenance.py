"""goalgen_model is carried from goal tags into spec provenance (E8 metadata)."""

from dmcp.distiller import _build_provenance
from dmcp.trace import Trace


def _trace_with_tags(tags):
    return Trace(goal="g", servers=[], seed_metadata={"llm_model": "x-ai/grok-4.3", "goal_tags": list(tags)})


def test_goalgen_model_stamped_from_tags():
    tr = _trace_with_tags(["strategy:same_name", "goalgen_model:openai/gpt-5.5"])
    prov = _build_provenance(tr, "anthropic/claude-opus-4.8", None)
    assert prov["goalgen_model"] == "openai/gpt-5.5"
    assert prov["goalgen_family"] == "openai"
    # explorer + distiller still recorded
    assert prov["explorer_model"] == "x-ai/grok-4.3"
    assert prov["distiller_model"] == "anthropic/claude-opus-4.8"


def test_no_goalgen_tag_is_fine():
    tr = _trace_with_tags(["strategy:sibling"])
    prov = _build_provenance(tr, "openai/gpt-5.5", None)
    assert "goalgen_model" not in prov
    assert prov["distiller_model"] == "openai/gpt-5.5"
