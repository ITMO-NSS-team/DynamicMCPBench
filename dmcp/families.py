"""Model-family registry + cross-family pickers for the generation panel (E8.6).

Why a registry at all: single-model authoring is a known confound (the corpus
mirrors the explorer's idiosyncrasies; the distiller and the judge can collude
with that model's defaults). The remedy from `docs/EXPERIMENTS_SUITE.md §2.2`
is **role-split + cross-family** generation — every spec's explorer family
must differ from its distiller family, and a 4th family validates. This
module is the lookup table + the picker that enforces the constraint.

The registry is keyed by the OpenRouter id prefix because the same family
ships many model snapshots; tying to the prefix keeps the table small and
forward-compatible with new releases inside the same family.

Scope of v0: a single-tier family slug per model (no nesting like
"openai/gpt-x" → "openai" → "gpt-family"); enough for the panel comparison.
Unknown models map to family "unknown" — the picker still works but the
caller should surface that as a warning (analogous to UsageAccumulator's
unknown_price flag).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

UNKNOWN_FAMILY = "unknown"

# Prefix → family slug. First matching prefix wins (no overlap by design).
_FAMILY_PREFIXES: tuple[tuple[str, str], ...] = (
    ("openai/", "openai"),
    ("anthropic/", "anthropic"),
    ("google/", "google"),
    ("qwen/", "qwen"),
    ("moonshotai/", "moonshot"),
    ("z-ai/", "z-ai"),
    ("minimax/", "minimax"),
    ("deepseek/", "deepseek"),
    ("x-ai/", "x-ai"),
    ("meta-llama/", "meta"),
)


def family_of(model: str) -> str:
    """Return the family slug for an OpenRouter model id. Unknown → 'unknown'.

    Matching is purely on the id prefix; pinned snapshots in the same family
    map to the same slug so the cross-family constraint stays meaningful when
    OpenRouter rotates a tag.
    """
    for prefix, fam in _FAMILY_PREFIXES:
        if model.startswith(prefix):
            return fam
    return UNKNOWN_FAMILY


@dataclass(frozen=True)
class CrossFamilyAssignment:
    """One shard's (explorer, distiller) pair where the families differ.

    The picker emits these so the runner can dispatch one `dmcp generate` per
    shard without re-running the constraint check at the call site.
    """

    explorer_model: str
    explorer_family: str
    distiller_model: str
    distiller_family: str


def cross_family_pick(explorer_model: str, distiller_candidates: Iterable[str]) -> str:
    """Pick the first candidate whose family differs from `explorer_model`.

    Used per-shard when the runner has a small panel of admissible distillers
    and wants the cheapest cross-family fallback. Order matters: callers list
    candidates in preference order. Raises if no candidate qualifies — surfacing
    the constraint violation is better than silently mixing within the family.
    """
    explorer_family = family_of(explorer_model)
    for cand in distiller_candidates:
        if family_of(cand) != explorer_family:
            return cand
    raise ValueError(
        f"no cross-family distiller available: explorer={explorer_model!r} "
        f"family={explorer_family!r} all candidates were in the same family"
    )


def assign_shards(
    explorer_models: list[str],
    distiller_candidates: list[str],
) -> list[CrossFamilyAssignment]:
    """One CrossFamilyAssignment per explorer model.

    The distiller is picked per explorer via `cross_family_pick` over the
    candidates *in the order given*. Same explorer model twice → two
    assignments (caller decides what sharding means); a candidate list that
    can't satisfy any shard raises rather than silently same-familying.
    """
    if not explorer_models:
        raise ValueError("explorer_models must be non-empty")
    if not distiller_candidates:
        raise ValueError("distiller_candidates must be non-empty")
    out: list[CrossFamilyAssignment] = []
    for em in explorer_models:
        dm = cross_family_pick(em, distiller_candidates)
        out.append(
            CrossFamilyAssignment(
                explorer_model=em,
                explorer_family=family_of(em),
                distiller_model=dm,
                distiller_family=family_of(dm),
            )
        )
    return out


def ensure_cross_family(explorer_model: str, distiller_model: str) -> None:
    """Raise unless the two models are in different families. Guard rail for
    direct invocations of `dmcp generate` (no shard runner)."""
    ef = family_of(explorer_model)
    df = family_of(distiller_model)
    if ef == df:
        raise ValueError(
            f"explorer and distiller must be in different families: "
            f"explorer={explorer_model!r} ({ef}) distiller={distiller_model!r} ({df})"
        )
