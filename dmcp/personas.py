"""Persona / intent library for goal generation (Phase 2A of the rev. 3 plan).

A small curated set of user personas. `goal_gen.py` seeds each generation call
with a few distinct personas so the LLM produces goals from varied points of
view instead of one generic "realistic user" voice — measurably widening the
diversity of the goal corpus (see `diversity_score`).

Scope of v0: a static, hand-curated library + deterministic selection. Learned
or auto-mined personas are future work.
"""

from __future__ import annotations

import random
import re

# Each persona: a stable id, a short label, and an intent that shapes requests
# WITHOUT being named in the goal text. Kept domain-agnostic so it composes with
# arbitrary crawled servers.
PERSONAS: list[dict[str, str]] = [
    {
        "id": "backend-dev",
        "label": "Backend engineer",
        "intent": "triaging and fixing issues in a code repository",
    },
    {
        "id": "data-analyst",
        "label": "Data analyst",
        "intent": "exploring and summarizing structured data to answer a question",
    },
    {
        "id": "sre",
        "label": "Site-reliability engineer",
        "intent": "checking the current state/health of a system or service",
    },
    {
        "id": "researcher",
        "label": "Academic researcher",
        "intent": "gathering and cross-referencing sources on a topic",
    },
    {"id": "pm", "label": "Project manager", "intent": "tracking tasks, status, and ownership across tools"},
    {
        "id": "journalist",
        "label": "Journalist",
        "intent": "fact-checking a claim against live, authoritative sources",
    },
    {
        "id": "finance-ops",
        "label": "Finance operations analyst",
        "intent": "reconciling records and verifying figures",
    },
    {
        "id": "support-agent",
        "label": "Customer-support agent",
        "intent": "looking up and updating a customer's records",
    },
    {"id": "student", "label": "Student", "intent": "learning a topic and collecting references for study"},
    {
        "id": "release-eng",
        "label": "Release engineer",
        "intent": "snapshotting and tagging the current state before a change",
    },
]


def select_personas(n: int, seed: int = 0) -> list[dict[str, str]]:
    """Deterministically pick `n` personas (cycling if n exceeds the library).

    Same (n, seed) always yields the same list, so goal generation is
    reproducible. Different seeds rotate the selection.
    """
    if n <= 0 or not PERSONAS:
        return []
    pool = list(PERSONAS)
    random.Random(seed).shuffle(pool)
    return [pool[i % len(pool)] for i in range(n)]


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def diversity_score(texts: list[str]) -> float:
    """Lexical diversity of a set of texts in [0,1].

    1 - mean pairwise Jaccard similarity of token sets. Identical texts → 0;
    fully disjoint vocabularies → 1. Needs ≥2 non-empty texts (else 0.0). A
    cheap, model-free proxy used to validate that persona seeding broadens the
    generated goal corpus.
    """
    tok = [_tokens(t) for t in texts if t and t.strip()]
    if len(tok) < 2:
        return 0.0
    sims: list[float] = []
    for i in range(len(tok)):
        for j in range(i + 1, len(tok)):
            a, b = tok[i], tok[j]
            union = a | b
            sims.append(1.0 if not union else len(a & b) / len(union))
    return 1.0 - (sum(sims) / len(sims))
