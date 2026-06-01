"""Eval-side tool-pool modes (E2.3): Gold / Target / Full.

`dmcp eval --pool {gold,target,full}` controls WHICH tools the candidate agent is
offered, on top of the deterministic replay world:

  gold    — only the tools the spec's checkpoints require (upper bound).
  target  — required tools + a controlled distractor set built by the sampler.
            `p_alt` is the fraction of distractors that are direct alternatives
            (same tool name on a different server — the SAE primitive); the rest
            are semantic near-misses. The main experimental condition that the
            P_alt degradation curves (E2.7) sweep over.
  full    — required tools + every other tool in the catalog (lower bound).

Pool construction is deterministic given (spec, catalog, mode, p_alt, pool_size,
seed) and works offline (embeddings optional). The pool is rendered into a
tool-surface the explorer offers; calls to distractor tools simply miss the
replay cache — the intended wrong-tool signal. No task generation happens here,
only pool shaping (memory/feedback_agb_orthogonality.md).
"""

from __future__ import annotations

from dmcp.sampling import ToolCatalog, ToolEntry, _required_entries, sample_distractors
from dmcp.spec import TaskSpec, ToolEffectCheckpoint, ToolReference
from dmcp.trace import ToolSpec

POOL_MODES = ("gold", "target", "full")


def required_tool_refs(spec: TaskSpec) -> list[ToolReference]:
    """Tools the spec requires = union of every tool_effect checkpoint's
    equivalence_set (deduped, order-stable). value_produced checkpoints add none.
    """
    seen: set[tuple[str, str]] = set()
    out: list[ToolReference] = []
    for cp in spec.checkpoints:
        if isinstance(cp, ToolEffectCheckpoint):
            for r in cp.equivalence_set:
                k = (r.server_id, r.tool_name)
                if k not in seen:
                    seen.add(k)
                    out.append(r)
    return out


def build_eval_pool(
    spec: TaskSpec,
    catalog: ToolCatalog,
    *,
    mode: str,
    p_alt: float = 0.5,
    pool_size: int = 8,
    seed: int = 0,
    embeddings=None,
) -> list[ToolEntry]:
    """Build the candidate's offered tool pool for `spec` under `mode`."""
    if mode not in POOL_MODES:
        raise ValueError(f"unknown pool mode {mode!r}; pick one of {POOL_MODES}")
    required = required_tool_refs(spec)
    req_entries = _required_entries(required, catalog)
    if mode == "gold":
        return req_entries
    if mode == "full":
        return req_entries + catalog.excluding(required)

    # target: required + p_alt*pool_size direct alternatives + rest near-misses.
    n_alt = round(p_alt * pool_size)
    alts = sample_distractors("same_name", required, catalog, n=n_alt, seed=seed, embeddings=embeddings)
    chosen = {e.key for e in alts}
    need = pool_size - len(alts)
    others: list[ToolEntry] = []
    if need > 0:
        cand = sample_distractors(
            "hard_neg", required, catalog, n=pool_size + len(alts), seed=seed, embeddings=embeddings
        )
        for e in cand:
            if e.key in chosen:
                continue
            others.append(e)
            chosen.add(e.key)
            if len(others) >= need:
                break
    return req_entries + alts + others


def build_strategy_pool(
    spec: TaskSpec,
    catalog: ToolCatalog,
    *,
    strategy: str,
    pool_size: int = 8,
    seed: int = 0,
    embeddings=None,
) -> list[ToolEntry]:
    """Required tools + a single-strategy distractor set (for the ablation harness)."""
    required = required_tool_refs(spec)
    req = _required_entries(required, catalog)
    distractors = sample_distractors(
        strategy, required, catalog, n=pool_size, seed=seed, embeddings=embeddings
    )
    return req + distractors


def pool_to_tool_surface(
    pool: list[ToolEntry],
    reference_specs: dict[str, list[ToolSpec]],
) -> dict[str, list[ToolSpec]]:
    """Render a pool into a {server_id: [ToolSpec]} surface for the explorer.

    Required tools reuse their real ToolSpec (with input schema) from the
    reference trace so the candidate can call them correctly; distractor tools
    not present in the reference get a minimal permissive schema — calling one
    just misses the replay cache.
    """
    real: dict[tuple[str, str], ToolSpec] = {}
    for sid, specs in reference_specs.items():
        for ts in specs:
            real[(sid, ts.name)] = ts
    surface: dict[str, list[ToolSpec]] = {}
    seen: set[tuple[str, str]] = set()
    for e in pool:
        if e.key in seen:
            continue
        seen.add(e.key)
        ts = real.get(e.key) or ToolSpec(
            name=e.tool_name, description=e.description, input_schema={"type": "object"}
        )
        surface.setdefault(e.server_id, []).append(ts)
    return surface
