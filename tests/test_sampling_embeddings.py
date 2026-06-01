"""E2.2: embedding index + cosine-ranked hard_neg / cross_domain (offline)."""

from __future__ import annotations

from dmcp.embeddings import EmbeddingIndex, cosine
from dmcp.sampling import ToolCatalog, ToolEntry, sample_distractors
from dmcp.spec import ToolReference


def test_cosine_bounds():
    assert abs(cosine([1.0, 0.0], [1.0, 0.0]) - 1.0) < 1e-9
    assert cosine([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert cosine([], [1.0]) == 0.0
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_max_sim():
    idx = EmbeddingIndex(vectors={("s", "r"): [1.0, 0.0], ("s2", "a"): [0.8, 0.6]})
    assert abs(idx.max_sim(("s2", "a"), [("s", "r")]) - 0.8) < 1e-9
    assert idx.max_sim(("missing", "x"), [("s", "r")]) == 0.0


def _catalog():
    return ToolCatalog(
        entries=[
            ToolEntry("s", "req", "the required tool"),
            ToolEntry("s2", "near", "near"),
            ToolEntry("s2", "far", "far"),
            ToolEntry("s2", "dup", "dup"),
        ]
    )


def test_hard_neg_ranks_by_cosine_and_denoises():
    idx = EmbeddingIndex(
        vectors={
            ("s", "req"): [1.0, 0.0],
            ("s2", "near"): [0.8, 0.6],  # cos 0.80
            ("s2", "far"): [0.2, 0.98],  # cos ~0.20
            ("s2", "dup"): [0.999, 0.0447],  # cos ~0.999 → near-duplicate, denoised
        }
    )
    out = sample_distractors(
        "hard_neg",
        [ToolReference(server_id="s", tool_name="req")],
        _catalog(),
        n=3,
        embeddings=idx,
    )
    keys = [e.key for e in out]
    assert ("s2", "dup") not in keys  # denoised near-duplicate
    assert keys.index(("s2", "near")) < keys.index(("s2", "far"))  # cosine order


def test_hard_neg_lexical_fallback_without_index():
    # No embeddings → lexical path still works and respects n.
    out = sample_distractors(
        "hard_neg",
        [ToolReference(server_id="s", tool_name="req")],
        _catalog(),
        n=2,
    )
    assert len(out) <= 2
    assert all(e.key != ("s", "req") for e in out)


class _StubEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(t)), 1.0] for t in texts]


async def test_index_build_from_entries():
    cat = ToolCatalog(entries=[ToolEntry("s", "a", "x"), ToolEntry("s", "b", "yy")])
    idx = await EmbeddingIndex.build(cat.entries, _StubEmbedder())
    assert ("s", "a") in idx.vectors
    assert len(idx.vectors[("s", "a")]) == 2
