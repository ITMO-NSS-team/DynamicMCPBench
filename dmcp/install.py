"""Auto-installer for discovered MCP servers (pypi + npm).

Scope for v0:
  - pypi: `uv pip install <pkg>[==<version>]` into the project .venv. Shared
    venv keeps it fast; version conflicts will surface at smoke time and the
    conflicting server gets excluded.
  - npm: no pre-install. We use `npx -y <pkg>@<version>` at runtime, which
    caches in ~/.npm/_npx after the first invocation.

What we deliberately do NOT do at v0:
  - Per-server venvs / containerized installs. Necessary for production use,
    out of scope here.
  - oci (docker) packages. Docker buildx isn't on this machine.
  - Server-supplied runtimeArguments/packageArguments. Most catalog records
    leave those empty, so we use conventions instead (`python -m <module>`
    for pypi, `npx -y <pkg>` for npm). Servers whose actual entry point
    differs will fail smoke and get filtered out — that's acceptable.

Per-server timeout is enforced so a malicious or stuck install doesn't
hang the crawl indefinitely.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import time
from dataclasses import dataclass, field
from enum import Enum

from dmcp.discovery.schemas import DiscoveredPackage, DiscoveredServer, PackageKind

log = logging.getLogger(__name__)


class InstallStatus(str, Enum):
    success = "success"
    skip_no_candidate = "skip_no_candidate"
    skip_credentials = "skip_credentials"
    timeout = "timeout"
    install_error = "install_error"


@dataclass
class InstallResult:
    server_name: str
    chosen_package: DiscoveredPackage | None
    status: InstallStatus
    reason: str = ""
    install_seconds: float = 0.0
    stderr_tail: str = ""
    invoke_command: str | None = None
    invoke_args: list[str] = field(default_factory=list)


def _normalize_module_name(identifier: str) -> str:
    """Best-effort PyPI distribution name → importable module name.

    PyPI normalization replaces -/. with _, and lowercases. This works for
    the *distribution* name, but the importable module sometimes differs
    (e.g. `Pillow` → `PIL`). For MCP servers the convention is usually
    that the distribution name *is* the module name, so we follow it.
    """
    return identifier.lower().replace("-", "_").replace(".", "_")


def _pick_package(server: DiscoveredServer) -> DiscoveredPackage | None:
    """Pick at most one package per server, preferring pypi over npm."""
    candidates = server.no_creds_installable_packages
    if not candidates:
        return None
    pypi = [p for p in candidates if p.kind is PackageKind.pypi]
    if pypi:
        return pypi[0]
    return candidates[0]


def _install_pypi(package: DiscoveredPackage, timeout_s: float) -> tuple[InstallStatus, str, str]:
    pkg_spec = f"{package.identifier}=={package.version}" if package.version else package.identifier
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            ["uv", "pip", "install", "--quiet", pkg_spec],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return InstallStatus.timeout, "uv pip install timeout", ""
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-500:]
        return InstallStatus.install_error, f"uv pip install exit={proc.returncode}", tail
    return InstallStatus.success, f"installed in {time.monotonic() - t0:.1f}s", ""


def _resolve_pypi_invocation(
    package: DiscoveredPackage,
) -> tuple[str, list[str]]:
    """How to spawn the installed pypi server's stdio process.

    v0: always `python -m <module>` where module is the normalized
    distribution name. Smoke will catch wrong guesses.
    """
    module = _normalize_module_name(package.identifier)
    return sys.executable, ["-m", module]


def _resolve_npm_invocation(
    package: DiscoveredPackage,
) -> tuple[str, list[str]]:
    """Use `npx -y` so we don't have to globally pollute npm."""
    pkg_spec = f"{package.identifier}@{package.version}" if package.version else package.identifier
    return "npx", ["-y", pkg_spec]


def install_server(
    server: DiscoveredServer,
    *,
    install_timeout_s: float = 120.0,
) -> InstallResult:
    pkg = _pick_package(server)
    if pkg is None:
        return InstallResult(
            server_name=server.name,
            chosen_package=None,
            status=InstallStatus.skip_no_candidate,
            reason="no installable stdio pypi/npm package without required env vars",
        )

    if pkg.kind is PackageKind.pypi:
        status, reason, stderr = _install_pypi(pkg, install_timeout_s)
        cmd, args = _resolve_pypi_invocation(pkg)
        return InstallResult(
            server_name=server.name,
            chosen_package=pkg,
            status=status,
            reason=reason,
            stderr_tail=stderr,
            invoke_command=cmd,
            invoke_args=args,
        )

    if pkg.kind is PackageKind.npm:
        # No install step — npx will fetch on first invocation. We treat this
        # as success at the install phase; the actual fetch failure (if any)
        # will surface in smoke.
        cmd, args = _resolve_npm_invocation(pkg)
        return InstallResult(
            server_name=server.name,
            chosen_package=pkg,
            status=InstallStatus.success,
            reason="npx will fetch lazily",
            invoke_command=cmd,
            invoke_args=args,
        )

    return InstallResult(
        server_name=server.name,
        chosen_package=pkg,
        status=InstallStatus.skip_no_candidate,
        reason=f"unsupported package kind {pkg.kind.value}",
    )
