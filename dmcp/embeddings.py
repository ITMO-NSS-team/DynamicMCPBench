"""Embedding index + cosine similarity for the eval-side sampler (E2.2).

Tool descriptions are embedded once (via `OpenRouterClient.embed`, model pinned)
and cached by `(server_id, tool_name)`. The sampler's `hard_neg` / `cross_domain`
strategies rank candidates by cosine similarity over these vectors when an index
is supplied, and fall back to lexical Jaccard when it is not (no key / offline).

Determinism: embeddings are deterministic for a pinned model snapshot, so a fixed
(catalog, model) yields the same index and therefore the same ranking on every
machine. No graph construction here — this only shapes the candidate tool POOL
(`memory/feedback_agb_orthogonality.md`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Protocol


class Embedder(Protocol):
    """Anything exposing the OpenRouterClient embedding surface."""

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity in [-1, 1]; 0.0 for an empty/zero vector."""
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


@dataclass
class EmbeddingIndex:
    """Cached tool-description vectors keyed by (server_id, tool_name)."""

    vectors: dict[tuple[str, str], list[float]] = field(default_factory=dict)

    def get(self, key: tuple[str, str]) -> list[float] | None:
        return self.vectors.get(key)

    def max_sim(self, key: tuple[str, str], ref_keys: list[tuple[str, str]]) -> float:
        """Max cosine similarity between `key` and any of `ref_keys`.

        Returns 0.0 when `key` or all `ref_keys` are missing from the index.
        """
        v = self.vectors.get(key)
        if v is None:
            return 0.0
        sims = [cosine(v, self.vectors[r]) for r in ref_keys if r in self.vectors]
        return max(sims, default=0.0)

    @classmethod
    async def build(cls, entries, embedder: Embedder, *, batch_size: int = 256) -> EmbeddingIndex:
        """Embed `f"{tool_name}: {description}"` for each entry (with .server_id,
        .tool_name, .description) via `embedder`, batched. Returns a populated index."""
        items = list(entries)
        if not items:
            return cls()
        texts = [f"{e.tool_name}: {e.description}".strip() for e in items]
        vecs: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            vecs.extend(await embedder.embed(texts[i : i + batch_size]))
        return cls(vectors={(e.server_id, e.tool_name): v for e, v in zip(items, vecs, strict=False)})
