@echo off
set PYTHONUTF8=1
set UV_CACHE_DIR=D:\itmo_tools\DynamicMCPBench\.uv-cache
set UV_PYTHON_INSTALL_DIR=D:\itmo_tools\DynamicMCPBench\.uv-python
cd /d D:\itmo_tools\DynamicMCPBench\dmcp-studio
uv.exe run uvicorn backend.app:app --host 127.0.0.1 --port 8000 > D:\itmo_tools\DynamicMCPBench\tmp\studio-uvicorn.cmd.log 2>&1
