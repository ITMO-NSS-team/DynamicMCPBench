"""Discovery: pull server records from public MCP catalogs.

A `DiscoveredServer` is the *catalog claim* about a server — name, repo,
how to install it, whether it declares required env vars. It is NOT yet
verified to install or run; that's `dmcp.install` + `dmcp.vet`.
"""

from dmcp.discovery.registry import MCPRegistryClient
from dmcp.discovery.schemas import (
    DiscoveredPackage,
    DiscoveredRemote,
    DiscoveredServer,
    PackageKind,
    TransportKind,
)

__all__ = [
    "DiscoveredPackage",
    "DiscoveredRemote",
    "DiscoveredServer",
    "MCPRegistryClient",
    "PackageKind",
    "TransportKind",
]
