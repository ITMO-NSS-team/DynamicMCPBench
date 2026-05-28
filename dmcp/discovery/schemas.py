"""Discovery schemas — what a catalog says about a server.

These are the *catalog claim* records. They are validated to install or
even speak MCP only by the install + vet phases.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PackageKind(str, Enum):
    pypi = "pypi"
    npm = "npm"
    oci = "oci"
    nuget = "nuget"
    other = "other"


class TransportKind(str, Enum):
    stdio = "stdio"
    sse = "sse"
    streamable_http = "streamable_http"


class DiscoveredEnvVar(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    description: str | None = None
    is_required: bool = False
    is_secret: bool = False


class DiscoveredPackage(BaseModel):
    """One installable artifact for a server."""

    model_config = ConfigDict(extra="allow")
    kind: PackageKind
    identifier: str
    version: str | None = None
    transport: TransportKind = TransportKind.stdio
    runtime_arguments: list[Any] = Field(default_factory=list)
    package_arguments: list[Any] = Field(default_factory=list)
    environment_variables: list[DiscoveredEnvVar] = Field(default_factory=list)

    @property
    def required_env_vars(self) -> list[str]:
        return [e.name for e in self.environment_variables if e.is_required]

    @property
    def has_required_env(self) -> bool:
        return bool(self.required_env_vars)


class DiscoveredRemote(BaseModel):
    model_config = ConfigDict(extra="allow")
    transport: TransportKind
    url: str
    headers_required: list[str] = Field(default_factory=list)


class DiscoveredServer(BaseModel):
    """One server's catalog record across all its packages and remotes."""

    model_config = ConfigDict(extra="allow")
    source: str  # "mcp-registry" | "smithery" | ...
    name: str
    title: str | None = None
    description: str | None = None
    version: str | None = None
    repository_url: str | None = None
    is_latest: bool = True
    status: str | None = None  # "active" | "deprecated" | ...
    packages: list[DiscoveredPackage] = Field(default_factory=list)
    remotes: list[DiscoveredRemote] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)

    def to_jsonl(self) -> str:
        return self.model_dump_json(exclude_none=False)

    @property
    def installable_packages(self) -> list[DiscoveredPackage]:
        """Packages we can plausibly install via pip or npm."""
        return [
            p
            for p in self.packages
            if p.kind in (PackageKind.pypi, PackageKind.npm)
            and p.transport is TransportKind.stdio
        ]

    @property
    def no_creds_installable_packages(self) -> list[DiscoveredPackage]:
        return [p for p in self.installable_packages if not p.has_required_env]
