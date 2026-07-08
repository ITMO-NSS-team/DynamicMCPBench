"""Cross-platform launcher for DMCP Studio.

The launcher intentionally keeps the long-lived server under the current Python
interpreter instead of `uv run` or a shell wrapper. That makes Ctrl-C, stderr,
Unicode paths, and executable lookup behave consistently on Windows and Linux.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDIO = HERE.parent
ROOT = STUDIO.parent
DEFAULT_PORT = 8000

for path in (STUDIO, ROOT, HERE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from check_studio_server import classify  # noqa: E402


def _path_env(*paths: Path) -> str:
    values = [str(path) for path in paths]
    existing = os.environ.get("PYTHONPATH")
    if existing:
        values.append(existing)
    return os.pathsep.join(values)


def studio_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("UV_CACHE_DIR", str(ROOT / ".uv-cache"))
    env.setdefault("UV_PYTHON_INSTALL_DIR", str(ROOT / ".uv-python"))
    env["PYTHONPATH"] = _path_env(ROOT, STUDIO)
    return env


def run_checked(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    printable = " ".join(command)
    print(f"> {printable}", flush=True)
    completed = subprocess.run(command, cwd=cwd, env=env, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def build_frontend(env: dict[str, str], *, skip: bool) -> None:
    dist = STUDIO / "frontend" / "dist"
    if skip:
        if not dist.is_dir():
            raise SystemExit("frontend/dist is missing; run without --skip-frontend-build first")
        print("> skipping frontend build; serving existing frontend/dist", flush=True)
        return

    npm = shutil.which("npm")
    if npm:
        print("> building frontend (Vite)", flush=True)
        run_checked([npm, "install", "--silent"], cwd=STUDIO / "frontend", env=env)
        run_checked([npm, "run", "build"], cwd=STUDIO / "frontend", env=env)
        return

    if dist.is_dir():
        print("> npm not found; serving existing frontend/dist", flush=True)
        return

    raise SystemExit("npm was not found and frontend/dist is missing; install Node 20+ and retry")


def ensure_fixtures(env: dict[str, str], *, skip: bool) -> None:
    if skip:
        return
    showcase = STUDIO / "backend" / "fixtures" / "showcase_aapl.json"
    if showcase.is_file():
        return
    print("> building REPLAY fixtures", flush=True)
    run_checked([sys.executable, str(STUDIO / "experiments" / "e3_curate.py")], cwd=ROOT, env=env)


def ensure_uvicorn_available() -> None:
    if importlib.util.find_spec("uvicorn") is not None:
        return
    raise SystemExit(
        "uvicorn is not installed for this Python. Install Studio dependencies with "
        '`uv pip install -e ".[studio]"`, then rerun this launcher.'
    )


def serve(port: int, env: dict[str, str]) -> int:
    ensure_uvicorn_available()
    import uvicorn

    os.environ.update(env)
    os.chdir(STUDIO)
    print(f"> DMCP Studio -> http://127.0.0.1:{port}  (REPLAY; Ctrl-C to stop)", flush=True)
    try:
        uvicorn.run("backend.app:app", host="127.0.0.1", port=port)
        return 0
    except KeyboardInterrupt:
        return 130


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch DMCP Studio from source.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", DEFAULT_PORT)))
    parser.add_argument(
        "--skip-frontend-build",
        action="store_true",
        help="serve the existing frontend/dist instead of running npm install/build",
    )
    parser.add_argument(
        "--skip-fixtures",
        action="store_true",
        help="do not generate missing REPLAY fixtures",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    env = studio_env()

    status = classify(args.port)
    if status == "current":
        print(f"> DMCP Studio is already running at http://127.0.0.1:{args.port}", flush=True)
        return 0
    if status == "stale":
        print(
            f"Stale DMCP Studio backend already runs on http://127.0.0.1:{args.port}. "
            "Stop it before rebuilding the frontend, or choose another port.",
            file=sys.stderr,
        )
        return 1
    if status == "occupied":
        print(
            f"Port {args.port} is already used by a non-current service. "
            "Stop it or choose another port.",
            file=sys.stderr,
        )
        return 1

    build_frontend(env, skip=args.skip_frontend_build)
    ensure_fixtures(env, skip=args.skip_fixtures)
    return serve(args.port, env)


if __name__ == "__main__":
    raise SystemExit(main())
