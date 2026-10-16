@echo off
REM Double-click this on Windows to open NestKVM. First run sets everything up.
cd /d "%~dp0"

if not exist .venv (
  echo First run - setting up ^(one time^)...
  python -m venv .venv || (echo Could not create venv. Install Python 3 from python.org and tick "Add to PATH". & pause & exit /b 1)
  .venv\Scripts\python -m pip install --upgrade pip >nul 2>&1
  .venv\Scripts\pip install -r requirements.txt || (echo Dependency install failed. & pause & exit /b 1)
)

.venv\Scripts\python -m nestkvm gui
