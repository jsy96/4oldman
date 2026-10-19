@echo off
rem ElderCare (YiYangTong) web app launcher - Flask + SQLite backend
rem Requires: uv (chocolatey), used to create .venv on first run

cd /d %~dp0

where uv >nul 2>nul
if errorlevel 1 (
  echo [ERROR] uv not found in PATH. Install uv first.
  pause
  exit /b 1
)

if not exist .venv\Scripts\python.exe (
  echo First run: creating virtual environment with uv ...
  uv venv .venv
  uv pip install --python .venv\Scripts\python.exe -r requirements.txt
)

echo Starting ElderCare server at http://127.0.0.1:8000 ...
echo Press Ctrl+C to stop.
.venv\Scripts\python.exe server.py
pause
