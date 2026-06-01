"""Eval-side tool-pool distractor sampler (E2.1).

When `dmcp eval --pool target` runs, the candidate agent sees the spec's
required tools PLUS a controlled set of distractors. The shape of that
distractor set drives the SAE rate and the P_alt degradation curves
(simple_approach §6/§7, PDF §4/§5).

This module is the **eval-side** sampler. It does NOT generate tasks from
a graph — task generation stays forward-trace-driven per
`memory/feedback_agb_orthogonality.md`. Sampling lives here only as a
control over the tool POOL the candidate is offered at evaluation time.

Six strategies (PDF §4.5):

  random        Uniform random pick from the rest of the catalog. The
                neutral baseline against which other strategies are scored.
  hard_neg      Tools whose descriptions are lexically nearest to the
                required tools — confuses the agent on intent. v0 uses
                token Jaccard as a deterministic, zero-dependency stand-in;
                E2.2 swaps in a real embedding index.
  cross_domain  Tools whose server tags do NOT intersect the required
                servers' tags. Probes "wrong-domain look-alikes."
  same_name     Same tool name on a DIFFERENT server (the SAE primitive).
                Optional near-collisions by SequenceMatcher ratio fold in
                edit-distance neighbors.
  sibling       Other tools on the SAME servers as required (intra-server
                confusion — closely related operations).
  stratified    Roughly equal mix of all five — the headline "Target"
                condition for the ablation.

Scope of v0: lexical hard_neg only (E2.2 lands embeddings); no networking;
deterministic per `seed`. Out of scope: graph construction, motif mining,
back-instruction from a sampled pool — those would breach the orthogonality
rule. This module's outputs only ever shape the candidate's tool POOL.
"""

from __future__ import annotations

import random
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from dmcp.embeddings import EmbeddingIndex
from dmcp.manifest import Manifest
from dmcp.spec import ToolReference
from dmcp.trace import Trace

VALID_STRATEGIES = ("random", "hard_neg", "cross_domain", "same_name", "sibling", "stratified")
NEAR_COLLISION_RATIO = 0.85  # SequenceMatcher threshold for same_name's edit-distance fold-in
HARD_NEG_DENOISE = 0.97  # cosine >= this => near-duplicate, dropped from hard_neg (E2.2 denoising)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class ToolEntry:
    """One pool tool. `tags` carries the server's manifest tags (e.g. domain
    labels) — used by cross_domain. Empty tags are fine; cross_domain then
    falls back to "any tool whose server is not one of the required ones."
    """

    server_id: str
    tool_name: str
    description: str = ""
    tags: tuple[str, ...] = ()

    @property
    def key(self) -> tuple[str, str]:
        return (self.server_id, self.tool_name)


@dataclass
class ToolCatalog:
    """The candidate tool universe. Built from observed traces (which carry
    `tool_specs[server_id]` after every session) and, optionally, a manifest
    to attach domain tags. Tools are deduplicated by (server_id, tool_name)."""

    entries: list[ToolEntry] = field(default_factory=list)

    @classmethod
    def from_traces(cls, traces: Iterable[Trace], manifest: Manifest | None = None) -> ToolCatalog:
        tags_for: dict[str, tuple[str, ...]] = {}
        if manifest is not None:
            for e in manifest.servers:
                tags_for[e.server_id] = tuple(e.tags)
        seen: dict[tuple[str, str], ToolEntry] = {}
        for tr in traces:
            for sid, specs in tr.tool_specs.items():
                tags = tags_for.get(sid, ())
                for ts in specs:
                    key = (sid, ts.name)
                    if key in seen:
                        continue
                    seen[key] = ToolEntry(
                        server_id=sid,
                        tool_name=ts.name,
                        description=(ts.description or ""),
                        tags=tags,
                    )
        return cls(entries=sorted(seen.values(), key=lambda e: e.key))

    def __len__(self) -> int:
        return len(self.entries)

    def excluding(self, refs: Iterable[ToolReference]) -> list[ToolEntry]:
        block = {(r.server_id, r.tool_name) for r in refs}
        return [e for e in self.entries if e.key not in block]

    def lookup(self, ref: ToolReference) -> ToolEntry | None:
        for e in self.entries:
            if e.key == (ref.server_id, ref.tool_name):
                return e
        return None


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(text.lower()) if len(t) >= 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _required_entries(required: Sequence[ToolReference], catalog: ToolCatalog) -> list[ToolEntry]:
    """Resolve required ToolReferences against the catalog. Missing entries
    fall back to bare-bones ToolEntry(server_id, tool_name) so downstream
    strategies still have a name/server to work from."""
    out: list[ToolEntry] = []
    for r in required:
        e = catalog.lookup(r)
        out.append(e if e is not None else ToolEntry(server_id=r.server_id, tool_name=r.tool_name))
    return out


def _stable_sort_key(e: ToolEntry) -> tuple[str, str]:
    return e.key


def _seeded(seed: int) -> random.Random:
    return random.Random(seed)


def _take(pool: list[ToolEntry], n: int) -> list[ToolEntry]:
    return pool[: max(0, n)]


def _sample_random(candidates: list[ToolEntry], n: int, rng: random.Random) -> list[ToolEntry]:
    pool = sorted(candidates, key=_stable_sort_key)
    rng.shuffle(pool)
    return _take(pool, n)


def _sample_hard_neg(
    candidates: list[ToolEntry],
    required_entries: list[ToolEntry],
    n: int,
    rng: random.Random,
    embeddings: EmbeddingIndex | None = None,
) -> list[ToolEntry]:
    """Rank candidates by similarity to the required tools.

    With an `embeddings` index, similarity is cosine over tool-description
    vectors and near-duplicates (cos >= HARD_NEG_DENOISE) are dropped (denoising,
    simple_approach §5.2). Without it, falls back to token Jaccard. Tie-break is
    deterministic (server_id, tool_name); the seed only shuffles the zero tail.
    """
    req_keys = [r.key for r in required_entries]
    req_tokens = [_tokens(r.description + " " + r.tool_name) for r in required_entries]
    scored: list[tuple[float, tuple[str, str], ToolEntry]] = []
    for e in candidates:
        if embeddings is not None:
            sim = embeddings.max_sim(e.key, req_keys)
            if sim >= HARD_NEG_DENOISE:
                continue
        else:
            ct = _tokens(e.description + " " + e.tool_name)
            sim = max((_jaccard(ct, rt) for rt in req_tokens), default=0.0)
        scored.append((sim, e.key, e))
    # Highest similarity first, deterministic on ties.
    scored.sort(key=lambda x: (-x[0], x[1]))
    positive = [e for sim, _, e in scored if sim > 0.0]
    zero = [e for sim, _, e in scored if sim <= 0.0]
    rng.shuffle(zero)
    return _take(positive + zero, n)


def _sample_cross_domain(
    candidates: list[ToolEntry],
    required_entries: list[ToolEntry],
    n: int,
    rng: random.Random,
    embeddings: EmbeddingIndex | None = None,
) -> list[ToolEntry]:
    req_tags: set[str] = set()
    req_servers: set[str] = set()
    for r in required_entries:
        req_tags.update(r.tags)
        req_servers.add(r.server_id)
    out: list[ToolEntry] = []
    for e in candidates:
        if req_tags and e.tags and set(e.tags) & req_tags:
            continue
        if not req_tags and e.server_id in req_servers:
            # No tag information available → fall back to "any tool on a
            # server the required set does not use."
            continue
        out.append(e)
    if embeddings is not None:
        req_keys = [r.key for r in required_entries]
        out.sort(key=lambda c: (-embeddings.max_sim(c.key, req_keys), c.key))
    else:
        out.sort(key=_stable_sort_key)
        rng.shuffle(out)
    return _take(out, n)


def _sample_same_name(
    candidates: list[ToolEntry],
    required_entries: list[ToolEntry],
    n: int,
    rng: random.Random,
    *,
    include_near_collisions: bool = True,
) -> list[ToolEntry]:
    req_names = [r.tool_name for r in required_entries]
    req_keys = {r.key for r in required_entries}
    exact: list[ToolEntry] = []
    near: list[tuple[float, tuple[str, str], ToolEntry]] = []
    for e in candidates:
        if e.key in req_keys:
            continue
        if e.tool_name in req_names:
            exact.append(e)
            continue
        if include_near_collisions:
            best = max(
                (SequenceMatcher(None, e.tool_name, n_).ratio() for n_ in req_names),
                default=0.0,
            )
            if best >= NEAR_COLLISION_RATIO:
                near.append((best, e.key, e))
    exact.sort(key=_stable_sort_key)
    rng.shuffle(exact)
    near.sort(key=lambda x: (-x[0], x[1]))
    near_entries = [e for _, _, e in near]
    return _take(exact + near_entries, n)


def _sample_sibling(
    candidates: list[ToolEntry],
    required_entries: list[ToolEntry],
    n: int,
    rng: random.Random,
) -> list[ToolEntry]:
    req_servers = {r.server_id for r in required_entries}
    out = [e for e in candidates if e.server_id in req_servers]
    out.sort(key=_stable_sort_key)
    rng.shuffle(out)
    return _take(out, n)


def _strategy_dispatch(
    strategy: str,
    candidates: list[ToolEntry],
    required_entries: list[ToolEntry],
    n: int,
    rng: random.Random,
    embeddings: EmbeddingIndex | None = None,
) -> list[ToolEntry]:
    if strategy == "random":
        return _sample_random(candidates, n, rng)
    if strategy == "hard_neg":
        return _sample_hard_neg(candidates, required_entries, n, rng, embeddings)
    if strategy == "cross_domain":
        return _sample_cross_domain(candidates, required_entries, n, rng, embeddings)
    if strategy == "same_name":
        return _sample_same_name(candidates, required_entries, n, rng)
    if strategy == "sibling":
        return _sample_sibling(candidates, required_entries, n, rng)
    raise ValueError(f"unknown strategy: {strategy!r}")


def _sample_stratified(
    candidates: list[ToolEntry],
    required_entries: list[ToolEntry],
    n: int,
    rng: random.Random,
    embeddings: EmbeddingIndex | None = None,
) -> list[ToolEntry]:
    """Round-robin draw from the five non-stratified strategies.

    Each strategy is asked for `n` candidates so we have headroom; we then
    interleave-pick one-at-a-time, skipping duplicates, until `n` is reached.
    Deterministic given the seed (each sub-strategy receives a seeded RNG
    derived from the same parent).
    """
    sub_order = ["hard_neg", "same_name", "sibling", "cross_domain", "random"]
    queues: dict[str, list[ToolEntry]] = {}
    for i, name in enumerate(sub_order):
        queues[name] = _strategy_dispatch(
            name, candidates, required_entries, n, _seeded(rng.randrange(2**31) + i), embeddings
        )
    picked: list[ToolEntry] = []
    seen: set[tuple[str, str]] = set()
    while len(picked) < n:
        progressed = False
        for name in sub_order:
            if len(picked) >= n:
                break
            q = queues[name]
            while q:
                e = q.pop(0)
                if e.key in seen:
                    continue
                picked.append(e)
                seen.add(e.key)
                progressed = True
                break
        if not progressed:
            break
    return picked


def sample_distractors(
    strategy: str,
    required: Sequence[ToolReference],
    catalog: ToolCatalog,
    *,
    n: int,
    seed: int = 0,
    embeddings: EmbeddingIndex | None = None,
) -> list[ToolEntry]:
    """Build an `n`-tool distractor set around `required` using `strategy`.

    The returned list never contains any required tool. Determinism is
    guaranteed for a fixed (strategy, required, catalog, n, seed). When the
    candidate pool is smaller than `n` the result is the largest possible
    set (no exception).
    """
    if strategy not in VALID_STRATEGIES:
        raise ValueError(f"unknown strategy {strategy!r}; pick one of {VALID_STRATEGIES}")
    if n < 0:
        raise ValueError("n must be non-negative")
    candidates = catalog.excluding(required)
    req_entries = _required_entries(required, catalog)
    rng = _seeded(seed)
    if strategy == "stratified":
        return _sample_stratified(candidates, req_entries, n, rng, embeddings)
    return _strategy_dispatch(strategy, candidates, req_entries, n, rng, embeddings)


def build_pool(
    required: Sequence[ToolReference],
    catalog: ToolCatalog,
    *,
    strategy: str,
    n_distractors: int,
    seed: int = 0,
    embeddings: EmbeddingIndex | None = None,
) -> list[ToolEntry]:
    """Convenience: required tools (resolved against the catalog) + a
    distractor set of the requested size. The output is what `dmcp eval`
    will eventually feed to the candidate agent in `--pool target` mode
    (E2.3 wires it; this module just builds the pool).
    """
    req_entries = _required_entries(required, catalog)
    distractors = sample_distractors(
        strategy, required, catalog, n=n_distractors, seed=seed, embeddings=embeddings
    )
    return req_entries + distractors
