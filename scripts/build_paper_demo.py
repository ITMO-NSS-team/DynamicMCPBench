from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAPER_DIR = ROOT / "paper_demo"
TOOLS_DIR = ROOT / ".latex-tools"
TECTONIC_DIR = TOOLS_DIR / "tectonic"
TECTONIC_EXE = TECTONIC_DIR / "tectonic.exe"
TECTONIC_CACHE = TOOLS_DIR / "tectonic-cache"
LATEST_RELEASE_API = "https://api.github.com/repos/tectonic-typesetting/tectonic/releases/latest"


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "DynamicMCPBench-build"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def download(url: str, target: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "DynamicMCPBench-build"})
    with urllib.request.urlopen(request, timeout=300) as response, target.open("wb") as handle:
        shutil.copyfileobj(response, handle)


def ensure_tectonic() -> Path:
    if TECTONIC_EXE.exists():
        return TECTONIC_EXE

    TOOLS_DIR.mkdir(exist_ok=True)
    release = fetch_json(LATEST_RELEASE_API)
    assets = release.get("assets", [])
    selected = None
    for asset in assets:
        name = asset.get("name", "").lower()
        if name.endswith(".zip") and "pc-windows-msvc" in name and "x86_64" in name:
            selected = asset
            break
    if selected is None:
        for asset in assets:
            name = asset.get("name", "").lower()
            if name.endswith(".zip") and "windows" in name and ("x86_64" in name or "amd64" in name):
                selected = asset
                break

    if selected is None:
        names = ", ".join(asset.get("name", "<unnamed>") for asset in assets)
        raise RuntimeError(f"Could not find a Windows x86_64 Tectonic asset. Assets: {names}")

    archive = TOOLS_DIR / selected["name"]
    print(f"Downloading {selected['name']}...")
    download(selected["browser_download_url"], archive)

    extract_dir = TOOLS_DIR / "_tectonic_extract"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir()
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(extract_dir)

    candidates = list(extract_dir.rglob("tectonic.exe"))
    if not candidates:
        raise RuntimeError(f"Downloaded archive did not contain tectonic.exe: {archive}")

    TECTONIC_DIR.mkdir(exist_ok=True)
    shutil.copy2(candidates[0], TECTONIC_EXE)
    shutil.rmtree(extract_dir)
    archive.unlink(missing_ok=True)
    return TECTONIC_EXE


def build_main() -> None:
    tectonic = ensure_tectonic()
    env = os.environ.copy()
    env["TECTONIC_CACHE_DIR"] = str(TECTONIC_CACHE)
    TECTONIC_CACHE.mkdir(parents=True, exist_ok=True)

    command = [
        str(tectonic),
        "--keep-intermediates",
        "--keep-logs",
        "main.tex",
    ]
    print("Running:", " ".join(command))
    subprocess.run(command, cwd=PAPER_DIR, env=env, check=True)


if __name__ == "__main__":
    try:
        build_main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
