"""E8.2 / B2: candidate tool-exposure architectures (flat / RAG-MCP / hierarchical).

Pure-Python tests on a synthetic 3-server × 4-tool surface; injected fake
embed_fn / route_fn keep the suite offline and deterministic. The cli wiring
(--architecture flag) is exercised via apply_architecture from dmcp.cli code-path.
"""

from __future__ import annotations

import asyncio

import pytest

from dmcp.architecture import (
    ARCHITECTURES,
    apply_architecture,
    flat_surface,
    hier_surface,
    rag_surface,
)
from dmcp.trace import ToolSpec


def _surface() -> dict[str, list[ToolSpec]]:
    """3 servers, 4 tools each. Tool descriptions skew toward each server's domain."""
    return {
        "fs": [
            ToolSpec(name="read_file", description="read a file from local disk"),
            ToolSpec(name="write_file", description="write a file to local disk"),
            ToolSpec(name="list_dir", description="list files in a directory"),
            ToolSpec(name="stat_file", description="return file size and mtime"),
        ],
        "git": [
            ToolSpec(name="git_status", description="show the working tree status"),
            ToolSpec(name="git_log", description="show commit history"),
            ToolSpec(name="git_diff", description="show unstaged changes"),
            ToolSpec(name="git_commit", description="record changes to the repository"),
        ],
        "time": [
            ToolSpec(name="get_current_time", description="return the current UTC time"),
            ToolSpec(name="convert_tz", description="convert between time zones"),
            ToolSpec(name="format_date", description="format a timestamp"),
            ToolSpec(name="parse_date", description="parse a date string"),
        ],
    }


# ---------------------------------------------------------------------------
# flat — identity passthrough
# ---------------------------------------------------------------------------


def test_flat_is_identity():
    s = _surface()
    out = flat_surface(s)
    assert set(out) == set(s)
    for sid in s:
        assert [t.name for t in out[sid]] == [t.name for t in s[sid]]
    # Copy, not reference — caller can mutate without affecting input.
    out["fs"].pop()
    assert len(s["fs"]) == 4


def test_apply_architecture_dispatches_to_flat_without_fns():
    out = asyncio.run(apply_architecture("flat", _surface(), "anything"))
    assert sum(len(v) for v in out.values()) == 12


# ---------------------------------------------------------------------------
# rag — top-k by cosine; injected embed_fn lets us script which tools win
# ---------------------------------------------------------------------------


def _make_lex_embed_fn(query_terms: list[str]):
    """Tiny lexical embedder: each text → a binary vector over `query_terms`.

    Cosine between query and tool reduces to overlap on the term set, which is
    enough to assert that the architecture lifts the *correct* tools without
    pulling in a real embedding model.
    """

    def vec(text: str) -> list[float]:
        # Split on common separators so `git_diff` → {git, diff} matches both
        # terms — the real embedder cares about subwords; this approximation
        # keeps tool names from being opaque tokens.
        tokens = text.lower().replace(":", " ").replace("_", " ").split()
        return [1.0 if t in tokens else 0.0 for t in query_terms]

    async def embed(texts: list[str]) -> list[list[float]]:
        return [vec(t) for t in texts]

    return embed


def test_rag_keeps_top_k_and_drops_unrelated_tools():
    s = _surface()
    embed = _make_lex_embed_fn(["git", "commit", "diff", "log", "status"])
    out = asyncio.run(
        rag_surface(s, "show me the latest git commit and any unstaged diff", embed_fn=embed, k=3)
    )
    flat = {(sid, t.name) for sid, ts in out.items() for t in ts}
    # All winners must be git-domain — fs and time tools have zero overlap.
    assert all(sid == "git" for sid, _ in flat)
    assert len(flat) == 3


def test_rag_returns_surface_unchanged_when_k_exceeds_total():
    s = _surface()
    embed = _make_lex_embed_fn(["anything"])  # vectors won't matter
    out = asyncio.run(rag_surface(s, "q", embed_fn=embed, k=100))
    assert sum(len(v) for v in out.values()) == 12


def test_rag_preserves_server_grouping():
    """Tools that survive top-k stay attached to their original server_id."""
    s = _surface()
    # Embed terms span both fs and time so the top-k is mixed.
    embed = _make_lex_embed_fn(["file", "time", "directory", "zone"])
    out = asyncio.run(rag_surface(s, "file and time", embed_fn=embed, k=4))
    by_server = {sid: {t.name for t in ts} for sid, ts in out.items()}
    # Each surviving tool must come from a server that actually contains it.
    src = _surface()
    for sid, names in by_server.items():
        for n in names:
            assert n in {t.name for t in src[sid]}


def test_rag_on_empty_surface_is_empty():
    embed = _make_lex_embed_fn(["x"])
    out = asyncio.run(rag_surface({}, "q", embed_fn=embed, k=5))
    assert out == {}


# ---------------------------------------------------------------------------
# hier — router picks a single server
# ---------------------------------------------------------------------------


def test_hier_exposes_only_chosen_server():
    s = _surface()

    async def route(_prompt, _summaries):
        return "git"

    out = asyncio.run(hier_surface(s, "rewrite history", route_fn=route))
    assert set(out.keys()) == {"git"}
    assert [t.name for t in out["git"]] == [t.name for t in s["git"]]


def test_hier_router_summaries_include_all_servers():
    """The router sees every available server — without the listing it can't choose."""
    s = _surface()
    seen: list[str] = []

    async def route(_prompt, summaries):
        seen.extend(sid for sid, _ in summaries)
        return summaries[-1][0]

    asyncio.run(hier_surface(s, "x", route_fn=route))
    assert set(seen) == set(s)


def test_hier_falls_back_when_router_returns_unknown_id():
    """A hallucinated server_id must not yield an empty toolbox."""
    s = _surface()

    async def route(_prompt, _summaries):
        return "nonexistent_server"

    out = asyncio.run(hier_surface(s, "x", route_fn=route))
    assert len(out) == 1
    assert next(iter(out)) in s


def test_hier_on_empty_surface_is_empty():
    async def route(_p, _s):
        return "x"

    out = asyncio.run(hier_surface({}, "q", route_fn=route))
    assert out == {}


# ---------------------------------------------------------------------------
# Dispatcher behavior
# ---------------------------------------------------------------------------


def test_apply_architecture_unknown_name_raises():
    with pytest.raises(ValueError, match="unknown architecture"):
        asyncio.run(apply_architecture("hyper-quantum", _surface(), "q"))


def test_apply_architecture_rag_requires_embed_fn():
    with pytest.raises(ValueError, match="rag"):
        asyncio.run(apply_architecture("rag", _surface(), "q"))


def test_apply_architecture_hier_requires_route_fn():
    with pytest.raises(ValueError, match="hier"):
        asyncio.run(apply_architecture("hier", _surface(), "q"))


def test_architectures_constant_is_a_known_set():
    assert ARCHITECTURES == ("flat", "rag", "hier")
