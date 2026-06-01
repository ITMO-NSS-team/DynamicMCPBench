"""Smoke tests — seed of the suite (CC.1). Every code step adds tests here or nearby.

These exercise the on-disk schemas that the whole pipeline round-trips through;
if they break, traces/specs can't be serialized and nothing downstream works.
"""

from __future__ import annotations

import uuid

from dmcp.manifest import Dynamism
from dmcp.spec import (
    ComplexityProfile,
    TaskSpec,
    ToolEffectCheckpoint,
    ToolReference,
)
from dmcp.trace import Trace, canonicalize_args


def test_canonicalize_args_is_order_independent():
    assert canonicalize_args({"b": 1, "a": 2}) == canonicalize_args({"a": 2, "b": 1})
    assert canonicalize_args(None) == "{}"


def test_trace_roundtrips_through_jsonl():
    t = Trace(goal="check the time")
    restored = Trace.model_validate_json(t.to_jsonl())
    assert restored.trace_id == t.trace_id
    assert restored.goal == "check the time"


def test_taskspec_roundtrips_through_jsonl():
    spec = TaskSpec(
        source_trace_id=uuid.uuid4(),
        prompt="tell me the current UTC time",
        dynamism=Dynamism.live_read,
        servers_used=["time"],
        complexity=ComplexityProfile(
            trace_depth=1,
            distinct_servers=1,
            cross_server=False,
            runtime_branching=False,
            state_coupling=False,
            recovery_required=False,
        ),
        checkpoints=[
            ToolEffectCheckpoint(
                checkpoint_id="c1",
                description="the time tool was called",
                equivalence_set=[ToolReference(server_id="time", tool_name="get_current_time")],
            )
        ],
    )
    restored = TaskSpec.model_validate_json(spec.to_jsonl())
    assert restored.prompt == spec.prompt
    assert restored.checkpoints[0].equivalence_set[0].tool_name == "get_current_time"
