@echo off
rem One-click release: pack -> deploy to Tencent Cloud -> refresh CDN -> git commit and push
rem Usage: deploy.bat "commit message"
cd /d %~dp0

if not exist .venv\Scripts\python.exe (
  echo [ERROR] .venv not found. Run start.bat first.
  pause
  exit /b 1
)

echo ============================================
echo  Releasing ElderCare to Tencent Cloud ...
echo ============================================
.venv\Scripts\python.exe release.py %*
echo.
pause
