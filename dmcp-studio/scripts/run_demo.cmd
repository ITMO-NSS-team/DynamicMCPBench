@echo off
setlocal
set "HERE=%~dp0"
set "ROOT=%HERE%..\.."
if not "%DMCP_STUDIO_PYTHON%"=="" (
  "%DMCP_STUDIO_PYTHON%" "%HERE%run_demo.py" %*
  exit /b %ERRORLEVEL%
)
if exist "%ROOT%\.venv\Scripts\python.exe" (
  "%ROOT%\.venv\Scripts\python.exe" "%HERE%run_demo.py" %*
  exit /b %ERRORLEVEL%
)
where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  python "%HERE%run_demo.py" %*
  exit /b %ERRORLEVEL%
)
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  py -3 "%HERE%run_demo.py" %*
  exit /b %ERRORLEVEL%
)
echo Python 3 was not found. Install Python 3.11+ or run with uv: uv run python "%HERE%run_demo.py" %*
exit /b 1
