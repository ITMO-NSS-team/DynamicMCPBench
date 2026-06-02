"""E6.1: strategy-driven goal seeding (offline — surface capture + LLM mocked)."""

from __future__ import annotations

import asyncio

import pytest

import dmcp.goal_gen as gg
from dmcp.manifest import Manifest, ServerEntry
from dmcp.trace import ToolSpec


def _entry(sid: str, tags: list[str]) -> ServerEntry:
    return ServerEntry.model_validate(
        {
            "server_id": sid,
            "transport": "stdio",
            "dynamism": "live_read",
            "command": "npx",
            "args": ["-y", "x"],
            "tags": tags,
        }
    )


def _spec(name: str) -> ToolSpec:
    return ToolSpec(name=name, description=f"{name} tool", input_schema={})


def _setup(monkeypatch) -> Manifest:
    m = Manifest(
        manifest_version="0.1.0",
        servers=[_entry("github", ["domain:dev"]), _entry("gitlab", ["domain:dev"])],
    )
    surfaces = {
        "github": [_spec("search_issues"), _spec("create_issue")],
        "gitlab": [_spec("search_issues"), _spec("list_projects")],
    }
    entries = {"github": m.by_id("github"), "gitlab": m.by_id("gitlab")}

    async def fake_capture(manifest, server_ids):
        return surfaces, entries

    async def fake_ask(llm, views, n, label, personas=None):
        servers = [v["server_id"] for v in views]
        return [{"goal_id": "g", "goal": "do a thing", "servers": servers, "tags": []}]

    monkeypatch.setattr(gg, "_capture_surfaces", fake_capture)
    monkeypatch.setattr(gg, "_ask_for_goals", fake_ask)
    return m


def test_same_name_tags_and_crosses_servers(monkeypatch):
    m = _setup(monkeypatch)
    goals = asyncio.run(
        gg.generate_strategy_goals(
            manifest=m,
            server_ids=["github", "gitlab"],
            llm=None,
            strategy="same_name",
            n_goals=5,
            seed_set_size=2,
            seed=1,
        )
    )
    assert goals.entries
    assert all("strategy:same_name" in g.tags for g in goals.entries)
    # github↔gitlab both have search_issues → same_name seed must produce ≥1 cross-server goal
    assert any("cross-server" in g.tags for g in goals.entries)


def test_sibling_is_intra_server(monkeypatch):
    m = _setup(monkeypatch)
    goals = asyncio.run(
        gg.generate_strategy_goals(
            manifest=m,
            server_ids=["github", "gitlab"],
            llm=None,
            strategy="sibling",
            n_goals=4,
            seed_set_size=2,
            seed=2,
        )
    )
    assert goals.entries
    assert all("intra-server" in g.tags for g in goals.entries)  # sibling stays on the anchor's server


def test_unknown_strategy_raises(monkeypatch):
    m = _setup(monkeypatch)
    with pytest.raises(ValueError):
        asyncio.run(
            gg.generate_strategy_goals(
                manifest=m, server_ids=["github"], llm=None, strategy="nope", n_goals=1
            )
        )
