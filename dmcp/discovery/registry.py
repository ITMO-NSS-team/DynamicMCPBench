"""Client for registry.modelcontextprotocol.io (the official MCP Registry).

Paginated, retry-tolerant fetch over the v0 API. Returns DiscoveredServer
records normalized to dmcp's own schemas — so downstream consumers don't
care which catalog the record came from.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Iterator
from typing import Any

import httpx

from dmcp.discovery.schemas import (
    DiscoveredEnvVar,
    DiscoveredPackage,
    DiscoveredRemote,
    DiscoveredServer,
    PackageKind,
    TransportKind,
)

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://registry.modelcontextprotocol.io"
PAGE_LIMIT = 100
SAFETY_PAGE_CAP = 1000
META_KEY = "io.modelcontextprotocol.registry/official"


def _coerce_pkg_kind(raw: str | None) -> PackageKind:
    if raw == "pypi":
        return PackageKind.pypi
    if raw == "npm":
        return PackageKind.npm
    if raw == "oci":
        return PackageKind.oci
    if raw == "nuget":
        return PackageKind.nuget
    return PackageKind.other


def _coerce_transport(raw: dict[str, Any] | None) -> TransportKind:
    t = (raw or {}).get("type")
    if t == "stdio":
        return TransportKind.stdio
    if t == "sse":
        return TransportKind.sse
    if t in ("streamable-http", "streamable_http", "http"):
        return TransportKind.streamable_http
    return TransportKind.stdio


def _coerce_env_vars(raw: Iterable[dict[str, Any]] | None) -> list[DiscoveredEnvVar]:
    out: list[DiscoveredEnvVar] = []
    for e in raw or []:
        out.append(
            DiscoveredEnvVar(
                name=e.get("name", ""),
                description=e.get("description"),
                is_required=bool(e.get("isRequired") or e.get("required")),
                is_secret=bool(e.get("isSecret") or e.get("secret")),
            )
        )
    return out


def _record_to_server(rec: dict[str, Any]) -> DiscoveredServer:
    s = rec.get("server", {}) or {}
    meta = (rec.get("_meta") or {}).get(META_KEY) or {}
    pkgs: list[DiscoveredPackage] = []
    for p in s.get("packages") or []:
        pkgs.append(
            DiscoveredPackage(
                kind=_coerce_pkg_kind(p.get("registryType")),
                identifier=p.get("identifier", ""),
                version=p.get("version"),
                transport=_coerce_transport(p.get("transport")),
                runtime_arguments=list(p.get("runtimeArguments") or []),
                package_arguments=list(p.get("packageArguments") or []),
                environment_variables=_coerce_env_vars(p.get("environmentVariables")),
            )
        )
    remotes: list[DiscoveredRemote] = []
    for r in s.get("remotes") or []:
        remotes.append(
            DiscoveredRemote(
                transport=_coerce_transport(r),
                url=r.get("url", ""),
            )
        )
    return DiscoveredServer(
        source="mcp-registry",
        name=s.get("name", ""),
        title=s.get("title"),
        description=s.get("description"),
        version=s.get("version"),
        repository_url=(s.get("repository") or {}).get("url"),
        is_latest=bool(meta.get("isLatest", True)),
        status=meta.get("status"),
        packages=pkgs,
        remotes=remotes,
        raw=rec,
    )


class MCPRegistryClient:
    """Paginated fetch of every server record from the official registry."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 60.0,
        max_attempts: int = 4,
    ) -> None:
        self.base_url = base_url
        self._client = httpx.Client(
            timeout=timeout,
            transport=httpx.HTTPTransport(retries=3),
            headers={"Accept": "application/json"},
        )
        self._max_attempts = max_attempts

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        last_err: Exception | None = None
        for attempt in range(self._max_attempts):
            try:
                r = self._client.get(url, params=params)
                r.raise_for_status()
                return r.json()
            except Exception as e:
                last_err = e
                wait = 2.0 * (attempt + 1)
                log.warning(
                    "registry GET %s attempt %d failed: %s — retrying in %.1fs",
                    url, attempt + 1, type(e).__name__, wait,
                )
                time.sleep(wait)
        raise RuntimeError(f"registry GET {url} failed after {self._max_attempts} attempts: {last_err}")

    def iter_all(
        self,
        *,
        latest_only: bool = True,
        active_only: bool = True,
        limit_per_page: int = PAGE_LIMIT,
        max_pages: int = SAFETY_PAGE_CAP,
    ) -> Iterator[DiscoveredServer]:
        """Yield every server in the registry, paged transparently."""
        cursor = ""
        for _page in range(max_pages):
            params: dict[str, Any] = {"limit": limit_per_page}
            if cursor:
                params["cursor"] = cursor
            d = self._get("/v0/servers", params)
            for rec in d.get("servers", []):
                srv = _record_to_server(rec)
                if latest_only and not srv.is_latest:
                    continue
                if active_only and srv.status and srv.status != "active":
                    continue
                yield srv
            cursor = (d.get("metadata") or {}).get("nextCursor")
            if not cursor:
                return
        log.warning("hit max_pages=%d cap; results may be incomplete", max_pages)
