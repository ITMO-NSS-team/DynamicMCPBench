"""Deterministic answer-match scorer (RQ1 baseline — NOT the headline).

DynamicMCPBench's headline scoring is trace/effect alignment. RQ1 exists to
*compare* that against final-answer string matching — the prior-art shape
this project deliberately rejects — and surface its ranking instability and
false-fail rate. This module is the answer-match scorer for that
comparison: a deterministic, offline, dependency-free string-similarity
check between a candidate's final assistant message and a reference final
message.

It is hard-labeled a baseline and never imported by the headline scoring
path. The orthogonality contract per `memory/feedback_agb_orthogonality.md`
is: building this scorer is allowed only as a clearly-labeled experimental
arm; using it inside `evaluator.py` is forbidden.

Scoring is intentionally minimal: lowercase + punctuation-strip + token
split, then a token Jaccard with a substring fallback for short canonical
answers. Determinism is exact — no LLM in the loop.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Default token Jaccard threshold above which the answer-match scorer reports
# pass. 0.5 is the rough midpoint where prior-art final-answer scorers
# typically settle. Sweepable from the CLI.
DEFAULT_THRESHOLD = 0.5
_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class AnswerMatchResult:
    """One scorer decision over a (candidate, reference) string pair."""

    passed: bool
    jaccard: float
    substring_hit: bool
    n_reference_tokens: int
    n_candidate_tokens: int
    threshold: float


def _tokens(text: str | None) -> list[str]:
    if not text:
        return []
    return _TOKEN_RE.findall(text.lower())


def _token_set(text: str | None, *, min_len: int = 1) -> set[str]:
    return {t for t in _tokens(text) if len(t) >= min_len}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def score_answer(
    candidate: str | None,
    reference: str | None,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    substring_min_token_len: int = 5,
) -> AnswerMatchResult:
    """Return an answer-match decision over a (candidate, reference) pair.

    Pass iff EITHER:
      - token Jaccard(candidate, reference) >= `threshold`, OR
      - any reference token of length >= `substring_min_token_len` appears
        in the candidate (the canonical-short-answer fallback: matches a
        scorer like "did the candidate say 'Boston'").

    Both strings are normalized identically (lowercase + non-alphanumeric
    split). Empty inputs always fail.
    """
    cand_tokens = _token_set(candidate)
    ref_tokens = _token_set(reference)
    j = _jaccard(cand_tokens, ref_tokens)
    long_ref = {t for t in ref_tokens if len(t) >= substring_min_token_len}
    substring_hit = bool(long_ref) and bool(cand_tokens) and bool(long_ref & cand_tokens)
    passed = (j >= threshold) or substring_hit
    return AnswerMatchResult(
        passed=passed,
        jaccard=j,
        substring_hit=substring_hit,
        n_reference_tokens=len(ref_tokens),
        n_candidate_tokens=len(cand_tokens),
        threshold=threshold,
    )
