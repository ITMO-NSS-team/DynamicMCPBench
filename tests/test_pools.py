"""E2.3: Gold/Target/Full pool construction (offline, deterministic)."""

from __future__ import annotations

import uuid

from dmcp.manifest import Dynamism
from dmcp.pools import build_eval_pool, pool_to_tool_surface, required_tool_refs
from dmcp.sampling import ToolCatalog, ToolEntry
from dmcp.spec import (
    ComplexityProfile,
    TaskSpec,
    ToolEffectCheckpoint,
    ToolReference,
)
from dmcp.trace import ToolSpec


def _spec(reqs: list[tuple[str, str]]) -> TaskSpec:
    return TaskSpec(
        source_trace_id=uuid.uuid4(),
        prompt="p",
        dynamism=Dynamism.live_read,
        servers_used=sorted({s for s, _ in reqs}),
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
                checkpoint_id=f"c{i}",
                description="d",
                equivalence_set=[ToolReference(server_id=s, tool_name=t)],
            )
            for i, (s, t) in enumerate(reqs)
        ],
    )


def _catalog() -> ToolCatalog:
    return ToolCatalog(
        entries=[
            ToolEntry("github", "search_issues", "find issues"),  # required
            ToolEntry("gitlab", "search_issues", "find issues on gitlab"),  # same-name ALT
            ToolEntry("slack", "post_message", "send a chat message"),  # other
            ToolEntry("fetch", "fetch", "http get a url"),  # other
            ToolEntry("github", "create_issue", "make an issue"),  # sibling
        ]
    )


def test_required_tool_refs():
    refs = required_tool_refs(_spec([("github", "search_issues")]))
    assert [(r.server_id, r.tool_name) for r in refs] == [("github", "search_issues")]


def test_gold_is_required_only():
    pool = build_eval_pool(_spec([("github", "search_issues")]), _catalog(), mode="gold")
    assert [e.key for e in pool] == [("github", "search_issues")]


def test_full_is_required_plus_all_once():
    pool = build_eval_pool(_spec([("github", "search_issues")]), _catalog(), mode="full")
    keys = [e.key for e in pool]
    assert ("github", "search_issues") in keys
    assert len(keys) == len(set(keys)) == 5  # every catalog tool, no duplicate


def test_target_size_and_required_present():
    pool = build_eval_pool(
        _spec([("github", "search_issues")]), _catalog(), mode="target", p_alt=0.5, pool_size=2, seed=0
    )
    keys = [e.key for e in pool]
    assert keys[0] == ("github", "search_issues")  # required first, present
    assert len(pool) <= 1 + 2  # required + up to pool_size distractors
    assert keys.count(("github", "search_issues")) == 1  # not duplicated as a distractor


def test_target_p_alt_one_picks_same_name_alternative():
    pool = build_eval_pool(
        _spec([("github", "search_issues")]), _catalog(), mode="target", p_alt=1.0, pool_size=1, seed=0
    )
    distractors = [e.key for e in pool if e.key != ("github", "search_issues")]
    assert ("gitlab", "search_issues") in distractors


def test_target_deterministic():
    spec, cat = _spec([("github", "search_issues")]), _catalog()
    a = build_eval_pool(spec, cat, mode="target", p_alt=0.5, pool_size=3, seed=7)
    b = build_eval_pool(spec, cat, mode="target", p_alt=0.5, pool_size=3, seed=7)
    assert [e.key for e in a] == [e.key for e in b]


def test_pool_to_tool_surface_reuses_real_and_synthesizes():
    pool = build_eval_pool(
        _spec([("github", "search_issues")]), _catalog(), mode="target", p_alt=1.0, pool_size=1, seed=0
    )
    ref_specs = {
        "github": [
            ToolSpec(
                name="search_issues",
                description="real",
                input_schema={"type": "object", "properties": {"q": {"type": "string"}}},
            )
        ]
    }
    surface = pool_to_tool_surface(pool, ref_specs)
    gh = next(t for t in surface["github"] if t.name == "search_issues")
    assert gh.input_schema.get("properties")  # real schema reused
    assert "gitlab" in surface  # synthesized distractor server present
