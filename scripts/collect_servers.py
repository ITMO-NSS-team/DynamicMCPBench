#!/usr/bin/env python3
"""Robust unattended no-creds MCP-server collector (E3.1 / E3.2).

Design goals (every one a fix for an earlier failure):
  * PORTABLE, NO HARDCODED PATHS — kept servers launch via `npx -y <pkg>@<ver>`
    (npm) or `uvx --from <pkg>==<ver> <entry>` / `uvx --from <pkg>==<ver> python
    -m <module>` (pypi). Anyone with node+uv can run them; the manifest contains
    no machine-specific paths. The package coordinates are recorded for repro.
  * HANG ISOLATION — each candidate is verified in a subprocess started in its
    own session; on timeout the WHOLE process group is SIGKILLed, so a server
    that hangs on init/shutdown can never stall the run.
  * HONEST 100% GATE — verification runs `dmcp verify --llm --strict
    --require-all` (dependency-aware: a tool needing an id produced by another is
    resolved by reusing a harvested value). A server is KEPT iff EVERY exercised
    non-destructive tool returns ok. Discovered tool-dependencies are captured.
  * NO REPO POLLUTION — each verify runs with cwd set to a throwaway sandbox dir.
  * PARALLEL + RESUMABLE — N candidates concurrently; the manifest + catalog +
    log are flushed after EACH result; re-running skips kept ids; `--exclude`
    skips already-attempted ids for efficient top-ups.

Usage:
  uv run python scripts/collect_servers.py --target 120 --max-candidates 1500 \
      --concurrency 10 --out manifests/crawled-strict.json --log collect.log
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import shutil
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dmcp.discovery import MCPRegistryClient  # noqa: E402
from dmcp.discovery.schemas import PackageKind  # noqa: E402
from dmcp.install import _normalize_module_name  # noqa: E402
from dmcp.vet import _classify_dynamism, _sanitize_server_id  # noqa: E402

TMP = Path("/tmp/dmcp-collect")
TMP.mkdir(parents=True, exist_ok=True)
SANDBOX_ROOT = TMP / "sandbox"
SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)

# Resolve tool binaries to absolute paths so a detached `setsid nohup` run never
# depends on PATH (dmcp is a venv console-script; uv/uvx/npx live in ~/.local/bin).
# NOTE: these absolute paths are used only to INVOKE the collector's own tooling;
# the manifest stores bare `npx`/`uvx` so it stays portable for everyone else.
DMCP_BIN = str(ROOT / ".venv" / "bin" / "dmcp")
if not Path(DMCP_BIN).exists():
    DMCP_BIN = "dmcp"
UV_BIN = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv")
UVX_BIN = shutil.which("uvx") or str(Path.home() / ".local" / "bin" / "uvx")
NPX_BIN = shutil.which("npx") or str(Path.home() / ".local" / "bin" / "npx")


def log(fh, msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    fh.write(line + "\n")
    fh.flush()


async def run_killable(cmd: list[str], timeout: float, cwd: str | None = None) -> tuple[int | None, bool]:
    """Run cmd in its own session; SIGKILL the whole group on timeout."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
        cwd=cwd,
    )
    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout)
        return proc.returncode, False
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(proc.wait(), timeout=5)
        return None, True


async def run_capture(cmd: list[str], timeout: float) -> tuple[int | None, str, bool]:
    """Run cmd in its own session capturing stdout; SIGKILL the group on timeout."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode, out.decode("utf-8", "replace"), False
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(proc.wait(), timeout=5)
        return None, "", True


_PROBE = (
    "import importlib.metadata as m,sys;"
    "d=m.distribution(sys.argv[1]);"
    "print(chr(10).join(e.name for e in d.entry_points if e.group=='console_scripts'))"
)


def _pick_script(scripts: list[str], identifier: str, module: str) -> str:
    base = identifier.split("/")[-1].lower()
    cands = {base, base.replace("_", "-"), base.replace("-", "_"), module, module.replace("_", "-")}
    for s in scripts:
        if s in cands or base in s.lower():
            return s
    return scripts[0]


def _pkg(kind: str, identifier: str | None, version: str | None, entrypoint: str | None) -> dict:
    d = {"kind": kind, "identifier": identifier, "version": version, "entrypoint": entrypoint}
    return {k: v for k, v in d.items() if v is not None}


async def portable_command(pkg, install_timeout: float) -> dict | None:
    """Build a PORTABLE launch command (no machine paths). For pypi, probe the
    package's console scripts via uvx (which also warms uv's cache, so the later
    verify is fast); fall back to `python -m <module>`. Returns an entry dict with
    `command`, `args`, and `package` coords, or None if it can't be resolved."""
    if pkg.kind is PackageKind.npm:
        ver = f"{pkg.identifier}@{pkg.version}" if pkg.version else pkg.identifier
        return {
            "command": "npx",
            "args": ["-y", ver],
            "package": _pkg("npm", pkg.identifier, pkg.version, None),
        }
    if pkg.kind is PackageKind.pypi:
        base = f"{pkg.identifier}=={pkg.version}" if pkg.version else pkg.identifier
        rc, out, to = await run_capture(
            [UVX_BIN, "--from", base, "python", "-c", _PROBE, pkg.identifier], install_timeout
        )
        if to:
            return None  # could not resolve/install at all
        module = _normalize_module_name(pkg.identifier)
        scripts = [s.strip() for s in out.splitlines() if s.strip()] if rc == 0 else []
        if scripts:
            entry = _pick_script(scripts, pkg.identifier, module)
            args, entrypoint = ["--from", base, entry], entry
        else:
            args, entrypoint = ["--from", base, "python", "-m", module], f"python -m {module}"
        return {
            "command": "uvx",
            "args": args,
            "package": _pkg("pypi", pkg.identifier, pkg.version, entrypoint),
        }
    return None


async def verify_candidate(sid: str, command: str, args: list[str], timeout: float) -> dict | None:
    """Verify one server in an isolated killable subprocess with a sandbox cwd
    (so stateful servers can't litter the repo). Returns the report dict."""
    entry = {
        "server_id": sid,
        "transport": "stdio",
        "dynamism": "live_read",
        "sandbox": False,
        "command": command,
        "args": args,
        "tags": ["crawled"],
    }
    manifest = {"manifest_version": "0.1.0", "servers": [entry]}
    mpath = TMP / f"{sid}.manifest.json"
    rpath = TMP / f"{sid}.result.jsonl"
    mpath.write_text(json.dumps(manifest), encoding="utf-8")
    if rpath.exists():
        rpath.unlink()
    sbox = SANDBOX_ROOT / sid
    sbox.mkdir(parents=True, exist_ok=True)
    await run_killable(
        [
            DMCP_BIN,
            "verify",
            "-m",
            str(mpath),
            "--llm",
            "--strict",
            "--require-all",
            "--server-timeout",
            str(int(timeout * 0.7)),
            "--output",
            str(TMP / f"{sid}.md"),
            "--json-out",
            str(rpath),
        ],
        timeout,
        cwd=str(sbox),
    )
    shutil.rmtree(sbox, ignore_errors=True)
    if not rpath.exists():
        return None
    try:
        return json.loads(rpath.read_text(encoding="utf-8").splitlines()[0])
    except (IndexError, json.JSONDecodeError):
        return None


def _size_bucket(n: int) -> str:
    return "small" if n <= 3 else ("medium" if n <= 10 else "large")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=120)
    ap.add_argument("--max-candidates", type=int, default=1500)
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--verify-timeout", type=float, default=180.0)
    ap.add_argument("--install-timeout", type=float, default=240.0)
    ap.add_argument("--out", default="manifests/crawled-strict.json")
    ap.add_argument("--catalog", default=None, help="Catalog sidecar (default: <out>.catalog.json)")
    ap.add_argument("--log", default="collect.log")
    ap.add_argument(
        "--exclude",
        default=None,
        help="File of already-attempted server_ids (one per line) to skip on a top-up run",
    )
    a = ap.parse_args()

    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    catalog_path = ROOT / (a.catalog or str(out).replace(".json", ".catalog.json"))
    fh = open(ROOT / a.log, "a", encoding="utf-8")  # noqa: SIM115 (lives for the whole run)

    kept: list[dict] = []
    kept_ids: set[str] = set()
    catalog: dict[str, dict] = {}
    if out.exists():
        try:
            kept = list(json.loads(out.read_text(encoding="utf-8")).get("servers", []))
            kept_ids = {e["server_id"] for e in kept}
            log(fh, f"resuming: {len(kept)} servers already kept")
        except (json.JSONDecodeError, KeyError):
            pass
    if catalog_path.exists():
        with contextlib.suppress(json.JSONDecodeError):
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))

    exclude_ids: set[str] = set()
    if a.exclude and (ROOT / a.exclude).exists():
        exclude_ids = {
            ln.strip() for ln in (ROOT / a.exclude).read_text(encoding="utf-8").splitlines() if ln.strip()
        }
        log(fh, f"excluding {len(exclude_ids)} already-attempted server_ids")

    def write_out() -> None:
        out.write_text(json.dumps({"manifest_version": "0.1.0", "servers": kept}, indent=2), encoding="utf-8")
        catalog_path.write_text(json.dumps(catalog, indent=2), encoding="utf-8")

    log(
        fh,
        f"discovering no-creds candidates (target={a.target}, max={a.max_candidates}, conc={a.concurrency})",
    )
    client = MCPRegistryClient()
    candidates = []
    seen_pkg: set[tuple] = set()
    for srv in client.iter_all():
        picks = srv.no_creds_installable_packages
        if not picks:
            continue
        p = picks[0]
        key = (p.kind.value, p.identifier)
        if key in seen_pkg:
            continue
        seen_pkg.add(key)
        sid = _sanitize_server_id(srv.name)
        if sid in kept_ids or sid in exclude_ids:
            continue
        candidates.append((srv, p, sid))
        if len(candidates) >= a.max_candidates:
            break
    log(fh, f"selected {len(candidates)} unique candidates")

    sem = asyncio.Semaphore(a.concurrency)
    lock = asyncio.Lock()
    stop = asyncio.Event()
    stats = {"done": 0, "install_fail": 0, "verify_fail": 0, "kept": 0}

    async def worker(disc, pkg, sid):
        if stop.is_set():
            return
        async with sem:
            if stop.is_set():
                return
            try:
                cmd_info = await portable_command(pkg, a.install_timeout)
                if cmd_info is None:
                    stats["install_fail"] += 1
                    log(fh, f"  install-fail   {sid}")
                    return
                command, args = cmd_info["command"], cmd_info["args"]
                rep = await verify_candidate(sid, command, args, a.verify_timeout)
                if rep and rep.get("ok"):
                    tools = rep.get("tools") or []
                    dyn = _classify_dynamism([t["tool"] for t in tools]).value
                    tool_count = rep.get("tool_count") or len(tools)
                    deps = rep.get("dependencies") or []
                    entry = {
                        "server_id": sid,
                        "transport": "stdio",
                        # crawled servers are exercised WITHOUT a sandbox, so we
                        # only attest read behavior — cap dynamism at live_read.
                        "dynamism": dyn if dyn != "stateful_write" else "live_read",
                        "sandbox": False,
                        "command": command,
                        "args": args,
                        "description": (disc.description or "")[:200] or None,
                        "tags": [
                            "crawled",
                            "no-creds",
                            f"pkg:{cmd_info['package']['kind']}",
                            f"size:{_size_bucket(tool_count)}",
                            f"deps:{'yes' if deps else 'no'}",
                        ],
                        "package": cmd_info["package"],
                    }
                    async with lock:
                        if sid not in kept_ids and not stop.is_set():
                            kept.append(entry)
                            kept_ids.add(sid)
                            catalog[sid] = {
                                "package": cmd_info["package"],
                                "tool_count": tool_count,
                                "pass_rate": rep.get("pass_rate"),
                                "tools": [{"name": t["tool"], "status": t["status"]} for t in tools],
                                "dependencies": deps,
                            }
                            write_out()
                            stats["kept"] = len(kept)
                            if len(kept) >= a.target:
                                stop.set()
                    log(
                        fh,
                        f"  KEEP [{len(kept):>3}/{a.target}] {sid}  "
                        f"({rep.get('ok_count')}/{tool_count} tools, {len(deps)} deps)",
                    )
                else:
                    stats["verify_fail"] += 1
                    reason = (rep or {}).get("reason", "no result / killed")
                    log(fh, f"  verify-fail    {sid}  ({str(reason)[:60]})")
            except Exception as e:
                log(fh, f"  ERROR          {sid}  {type(e).__name__}: {str(e)[:80]}")
            finally:
                stats["done"] += 1
                if stats["done"] % 25 == 0:
                    log(
                        fh,
                        f"--- progress: {stats['done']}/{len(candidates)} done, kept={len(kept)}, "
                        f"install_fail={stats['install_fail']}, verify_fail={stats['verify_fail']} ---",
                    )

    tasks = [asyncio.create_task(worker(d, p, s)) for d, p, s in candidates]
    await asyncio.gather(*tasks, return_exceptions=True)
    write_out()
    log(fh, f"DONE: kept {len(kept)} servers -> {out}  (target {a.target})")
    log(fh, f"final stats: {stats}")
    fh.close()


if __name__ == "__main__":
    asyncio.run(main())
