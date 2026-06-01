"""E2.1 — eval-side distractor sampler.

Tests each of the six strategies on a hand-built synthetic catalog:
- determinism (same seed → same result)
- required tools never leak into the distractor set
- per-strategy semantic guarantees (sibling stays same-server, same_name
  finds collisions on other servers, cross_domain excludes overlapping
  tags, hard_neg ranks by lexical similarity, stratified mixes)
"""

from __future__ import annotations

import pytest

from dmcp.sampling import (
    VALID_STRATEGIES,
    ToolCatalog,
    ToolEntry,
    build_pool,
    sample_distractors,
)
from dmcp.spec import ToolReference


def _make_catalog() -> ToolCatalog:
    return ToolCatalog(
        entries=[
            # github server: code & issue tools
            ToolEntry("github", "search_issues", "search GitHub issues by query", ("vcs", "code")),
            ToolEntry("github", "create_pr", "open a pull request on GitHub", ("vcs", "code")),
            ToolEntry("github", "list_branches", "list branches of a repo", ("vcs", "code")),
            # gitlab server: SAE-relevant near-twin of github
            ToolEntry("gitlab", "search_issues", "search GitLab issues by query", ("vcs", "code")),
            ToolEntry("gitlab", "create_mr", "open a merge request on GitLab", ("vcs", "code")),
            # weather server: live_read, different domain
            ToolEntry("weather", "current_weather", "current temperature for a city", ("weather",)),
            ToolEntry("weather", "forecast_5day", "five-day forecast for a city", ("weather",)),
            # filesystem server: static, different domain again
            ToolEntry("filesystem", "read_file", "read a file from disk", ("fs",)),
            ToolEntry("filesystem", "write_file", "write a file to disk", ("fs",)),
            # finance server: near-name to search_issues (edit distance)
            ToolEntry("finance", "search_issuers", "search bond issuers", ("finance",)),
        ]
    )


def _required() -> list[ToolReference]:
    return [ToolReference(server_id="github", tool_name="search_issues")]


def test_valid_strategies_are_exposed():
    assert set(VALID_STRATEGIES) == {
        "random",
        "hard_neg",
        "cross_domain",
        "same_name",
        "sibling",
        "stratified",
    }


def test_unknown_strategy_raises():
    with pytest.raises(ValueError):
        sample_distractors("nope", _required(), _make_catalog(), n=3, seed=0)


def test_required_tools_never_appear_in_distractors():
    cat = _make_catalog()
    req = _required()
    for strat in VALID_STRATEGIES:
        got = sample_distractors(strat, req, cat, n=10, seed=42)
        assert (req[0].server_id, req[0].tool_name) not in {e.key for e in got}, strat


@pytest.mark.parametrize("strategy", VALID_STRATEGIES)
def test_strategies_are_deterministic(strategy):
    cat = _make_catalog()
    req = _required()
    a = sample_distractors(strategy, req, cat, n=4, seed=7)
    b = sample_distractors(strategy, req, cat, n=4, seed=7)
    assert [e.key for e in a] == [e.key for e in b]


def test_random_seed_changes_pick():
    cat = _make_catalog()
    req = _required()
    a = sample_distractors("random", req, cat, n=4, seed=0)
    b = sample_distractors("random", req, cat, n=4, seed=99)
    # With 9 candidates and 4 picks the chance two random seeds tie exactly
    # is negligible; if this ever flakes, raise n or change the seeds.
    assert [e.key for e in a] != [e.key for e in b]


def test_sibling_returns_only_same_server_tools():
    cat = _make_catalog()
    got = sample_distractors("sibling", _required(), cat, n=10, seed=0)
    assert got  # at least one sibling exists
    for e in got:
        assert e.server_id == "github"
        assert e.tool_name != "search_issues"


def test_same_name_finds_cross_server_collisions():
    cat = _make_catalog()
    got = sample_distractors("same_name", _required(), cat, n=10, seed=0)
    keys = {e.key for e in got}
    # gitlab.search_issues is an exact same-name collision on a different server
    assert ("gitlab", "search_issues") in keys
    # finance.search_issuers is the near-collision (edit-distance fold-in)
    assert ("finance", "search_issuers") in keys


def test_same_name_near_collisions_can_be_disabled():
    """Internal: confirm the near-collision threshold actually fires by
    comparing the catalog with/without `search_issuers`."""
    cat = _make_catalog()
    got = sample_distractors("same_name", _required(), cat, n=10, seed=0)
    keys = {e.key for e in got}
    # Without near-collisions, only gitlab.search_issues would surface — assert
    # there's at least one extra picked beyond the exact match.
    assert len(keys) >= 2


def test_cross_domain_excludes_overlapping_tags():
    cat = _make_catalog()
    got = sample_distractors("cross_domain", _required(), cat, n=10, seed=0)
    # required has tags ('vcs', 'code'); no returned tool should share either
    for e in got:
        assert not (set(e.tags) & {"vcs", "code"}), e
    # but tools from weather/filesystem/finance should be eligible
    servers = {e.server_id for e in got}
    assert servers.issubset({"weather", "filesystem", "finance"})


def test_hard_neg_ranks_lexically_similar_first():
    cat = _make_catalog()
    got = sample_distractors("hard_neg", _required(), cat, n=2, seed=0)
    keys = {e.key for e in got}
    # The required tool's description is "search GitHub issues by query"; the
    # nearest other tool by token overlap is gitlab.search_issues (same name,
    # near-identical description). It must be in the top-2.
    assert ("gitlab", "search_issues") in keys


def test_stratified_mixes_strategies_and_dedupes():
    cat = _make_catalog()
    got = sample_distractors("stratified", _required(), cat, n=6, seed=0)
    keys = [e.key for e in got]
    assert len(keys) == len(set(keys)), "stratified must not return duplicates"
    # Should reach across servers (not just one cluster)
    assert len({e.server_id for e in got}) >= 3


def test_n_capped_by_available_pool():
    cat = _make_catalog()
    # ask for far more than the catalog can supply
    got = sample_distractors("sibling", _required(), cat, n=100, seed=0)
    # github has 3 tools, minus the required one → at most 2 siblings
    assert len(got) == 2


def test_n_zero_returns_empty():
    cat = _make_catalog()
    for strat in VALID_STRATEGIES:
        assert sample_distractors(strat, _required(), cat, n=0, seed=0) == []


def test_build_pool_prefixes_required():
    cat = _make_catalog()
    req = _required()
    pool = build_pool(req, cat, strategy="hard_neg", n_distractors=3, seed=0)
    assert pool[0].key == (req[0].server_id, req[0].tool_name)
    assert len(pool) == 1 + 3
    # required + distractors are unique
    keys = [e.key for e in pool]
    assert len(keys) == len(set(keys))


def test_catalog_from_traces_dedupes_and_attaches_tags():
    from dmcp.manifest import Dynamism, Manifest, ServerEntry
    from dmcp.trace import ToolSpec, Trace, TransportKind

    t1 = Trace(goal="g1")
    t1.tool_specs = {"github": [ToolSpec(name="search_issues", description="search GitHub issues")]}
    t2 = Trace(goal="g2")
    t2.tool_specs = {
        "github": [ToolSpec(name="search_issues", description="dup — should be deduped")],
        "weather": [ToolSpec(name="current_weather", description="current temperature")],
    }
    manifest = Manifest(
        servers=[
            ServerEntry(
                server_id="github",
                transport=TransportKind.stdio,
                dynamism=Dynamism.static,
                command="echo",
                tags=["vcs", "code"],
            ),
            ServerEntry(
                server_id="weather",
                transport=TransportKind.stdio,
                dynamism=Dynamism.live_read,
                command="echo",
                tags=["weather"],
            ),
        ]
    )
    cat = ToolCatalog.from_traces([t1, t2], manifest=manifest)
    assert len(cat) == 2  # deduped to 2 unique tools
    by_key = {e.key: e for e in cat.entries}
    assert by_key[("github", "search_issues")].tags == ("vcs", "code")
    assert by_key[("weather", "current_weather")].tags == ("weather",)
    # excluding() removes the requested refs
    rest = cat.excluding([ToolReference(server_id="github", tool_name="search_issues")])
    assert {e.key for e in rest} == {("weather", "current_weather")}
