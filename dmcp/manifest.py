"""Server manifest — declarative inventory of MCP servers available to dmcp.

A manifest is the single input shared by `dmcp crawl`, `dmcp explore`, and
`dmcp eval`. It carries:
  - how to reach each server (transport + endpoint or command)
  - the **dynamism class** (static / live_read / stateful_write) that Claim 3
    of the rev. 3 plan turns into a measured difficulty axis
  - a sandbox flag — required for stateful_write servers so exploration cannot
    cause real-world side effects.

JSON format (one file per environment). YAML can be added later by swapping
the loader; the schema lives here, not in a serialization library.
"""

from __future__ import annotations

import json
import os
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dmcp.recorder import (
    ServerConfig,
    SseServer,
    StdioServer,
    StreamableHttpServer,
)
from dmcp.trace import TransportKind

MANIFEST_VERSION = "0.1.0"


class Dynamism(str, Enum):
    """How the server's externally observable state evolves.

    static          — pure functions / immutable data (e.g. time, math).
    live_read       — read-only against a changing world (e.g. weather, news,
                      grafana, search). Same call at different times → different
                      answers, but no side effects.
    stateful_write  — mutates state observers can read (e.g. postgres INSERT,
                      git commit, kafka produce). Sandboxing mandatory.
    """

    static = "static"
    live_read = "live_read"
    stateful_write = "stateful_write"


class ServerEntry(BaseModel):
    """One server's declaration in a manifest. Validates that the transport
    fields are coherent and that stateful_write entries are sandboxed."""

    model_config = ConfigDict(extra="forbid")

    server_id: str
    transport: TransportKind
    dynamism: Dynamism
    sandbox: bool = False
    description: str | None = None
    tags: list[str] = Field(default_factory=list)

    # stdio fields
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] | None = None

    # http/sse fields
    endpoint: str | None = None
    headers: dict[str, str] | None = None

    # provenance / metadata (optional; written by the collector + enrich step)
    package: dict | None = None
    tool_count: int | None = None

    # env var NAMES this server needs at runtime (E3.4 credentialed tier). The
    # VALUES come from .env / os.environ — never the manifest.
    requires_env: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> ServerEntry:
        if self.transport is TransportKind.stdio:
            if not self.command:
                raise ValueError(f"{self.server_id}: stdio transport requires `command`")
            if self.endpoint or self.headers:
                raise ValueError(f"{self.server_id}: stdio transport does not take `endpoint`/`headers`")
        else:
            if not self.endpoint:
                raise ValueError(f"{self.server_id}: {self.transport.value} transport requires `endpoint`")
            if self.command or self.args or self.env:
                raise ValueError(
                    f"{self.server_id}: {self.transport.value} transport does not take `command`/`args`/`env`"
                )
        if self.dynamism is Dynamism.stateful_write and not self.sandbox:
            raise ValueError(
                f"{self.server_id}: stateful_write servers must set sandbox=true so "
                "exploration cannot cause real side effects"
            )
        return self

    def _plumbed_env(self) -> dict[str, str] | None:
        """Merge declared env with secret VALUES for `requires_env`, read from
        os.environ (.env-loaded). Secrets never live in the manifest."""
        env = dict(self.env or {})
        for var in self.requires_env:
            val = os.environ.get(var)
            if val:
                env[var] = val
        return env or None

    def to_config(self) -> ServerConfig:
        if self.transport is TransportKind.stdio:
            return StdioServer(
                server_id=self.server_id,
                command=self.command or "",
                args=list(self.args),
                env=self._plumbed_env(),
            )
        if self.transport is TransportKind.sse:
            return SseServer(
                server_id=self.server_id,
                url=self.endpoint or "",
                headers=self.headers,
            )
        return StreamableHttpServer(
            server_id=self.server_id,
            url=self.endpoint or "",
            headers=self.headers,
        )


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_version: str = MANIFEST_VERSION
    servers: list[ServerEntry]

    @model_validator(mode="after")
    def _unique_ids(self) -> Manifest:
        seen: set[str] = set()
        for s in self.servers:
            if s.server_id in seen:
                raise ValueError(f"duplicate server_id: {s.server_id}")
            seen.add(s.server_id)
        return self

    @classmethod
    def load(cls, path: Path) -> Manifest:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    def by_id(self, server_id: str) -> ServerEntry:
        for s in self.servers:
            if s.server_id == server_id:
                return s
        raise KeyError(server_id)

    def configs(self, server_ids: list[str] | None = None) -> list[ServerConfig]:
        entries = self.servers if server_ids is None else [self.by_id(i) for i in server_ids]
        return [e.to_config() for e in entries]

    def dump(self, path: Path) -> None:
        data = self.model_dump(mode="json", exclude_none=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def gate_credentials(
        self, server_ids: list[str] | None = None, *, load_env: bool = True
    ) -> tuple[list[ServerEntry], list[tuple[str, list[str]]]]:
        """Split servers into (runnable, skipped) by whether their `requires_env`
        keys are present in the environment. Loads .env first so present keys count.
        skipped = [(server_id, [missing_var, ...])]. This is the credentialed-tier
        gate: missing keys skip gracefully (E3.4)."""
        if load_env:
            try:
                from dotenv import load_dotenv

                load_dotenv(override=False)
            except Exception:
                pass
        entries = self.servers if server_ids is None else [self.by_id(i) for i in server_ids]
        runnable: list[ServerEntry] = []
        skipped: list[tuple[str, list[str]]] = []
        for e in entries:
            missing = [v for v in e.requires_env if not os.environ.get(v)]
            (skipped.append((e.server_id, missing)) if missing else runnable.append(e))
        return runnable, skipped
