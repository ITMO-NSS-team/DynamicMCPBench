"""Description normalization Level A / Level B (E2.6).

Tool-description quality is a controlled variable in the benchmark (PDF §4.2,
simple_approach §6.2): ~97% of real descriptions carry a "smell", and without
controlling for this the benchmark measures spec quality, not agent capability.
Two normalization levels rewrite the descriptions the candidate is offered:

  Level A (surface)  — style/structure only, NO new content. Deterministic:
                       reshapes the existing description + parameter names into a
                       consistent `Purpose: … Parameters: …` form. Offline.
  Level B (semantic) — augmentation. An LLM fills the 5-part rubric
                       [Purpose][Inputs][Outputs][Constraints][When to use vs
                       alternatives], adding genuinely-inferable detail (needs a
                       key). temperature=0 for reproducibility.

`apply_normalization` rewrites a tool surface (the {server_id: [ToolSpec]} dict
the explorer offers) at the chosen level, deduplicating identical tools.
"""

from __future__ import annotations

import re

from dmcp.llm import OpenRouterClient
from dmcp.trace import ToolSpec

LEVEL_B_SYSTEM = (
    "You rewrite an MCP tool description into a complete, standardized spec. "
    "Produce exactly these labeled parts: [Purpose] [Inputs] [Outputs] "
    "[Constraints] [When to use vs alternatives]. Add genuinely helpful detail "
    "inferable from the tool name and parameters, but do NOT invent capabilities "
    "the tool clearly lacks. Return ONLY the rewritten description."
)


def _param_names(input_schema: dict | None) -> list[str]:
    return list((input_schema or {}).get("properties", {}).keys())


def normalize_level_a(name: str, description: str, input_schema: dict | None) -> str:
    """Surface normalization: consistent structure from existing content only.

    No new semantics — just whitespace-collapses the description and appends the
    declared parameter names in a fixed `Purpose: … Parameters: …` shell.
    """
    desc = re.sub(r"\s+", " ", description or "").strip()
    params = _param_names(input_schema)
    purpose = desc or f"the {name} operation"
    return f"Purpose: {purpose} Parameters: {', '.join(params) if params else 'none'}."


async def normalize_level_b(
    name: str, description: str, input_schema: dict | None, llm: OpenRouterClient
) -> str:
    """Semantic augmentation via the 5-part rubric (LLM, temperature 0)."""
    params = _param_names(input_schema)
    user = (
        f"Tool name: {name}\n"
        f"Current description: {description or '(none)'}\n"
        f"Parameters: {params or 'none'}\n\n"
        "Rewrite per the 5-part template."
    )
    resp = await llm.chat(
        messages=[
            {"role": "system", "content": LEVEL_B_SYSTEM},
            {"role": "user", "content": user},
        ],
        temperature=0.0,
        max_tokens=400,
    )
    return (resp.content or "").strip() or (description or "")


async def apply_normalization(
    surface: dict[str, list[ToolSpec]],
    level: str,
    llm: OpenRouterClient,
) -> dict[str, list[ToolSpec]]:
    """Return a copy of `surface` with each ToolSpec.description normalized to
    `level` ("a" or "b"). Identical (server, tool) pairs are normalized once."""
    if level not in ("a", "b"):
        raise ValueError(f"unknown desc level {level!r}; pick 'a' or 'b'")
    cache: dict[tuple[str, str], str] = {}
    out: dict[str, list[ToolSpec]] = {}
    for sid, specs in surface.items():
        new_specs: list[ToolSpec] = []
        for ts in specs:
            key = (sid, ts.name)
            if key not in cache:
                if level == "a":
                    cache[key] = normalize_level_a(ts.name, ts.description or "", ts.input_schema)
                else:
                    cache[key] = await normalize_level_b(ts.name, ts.description or "", ts.input_schema, llm)
            new_specs.append(ts.model_copy(update={"description": cache[key]}))
        out[sid] = new_specs
    return out
