@echo off
REM Double-click on Windows (shows a console; use DuoDesk.vbs for no console).
REM Updates from git, sets up the environment, then opens DuoDesk.
cd /d "%~dp0"

where git >nul 2>&1 && git pull

if not exist .venv\Scripts\python.exe (
  echo First run - setting up ^(one time^)...
  python -m venv .venv || (echo Install Python 3 from python.org and tick "Add to PATH". & pause & exit /b 1)
)

.venv\Scripts\python -m pip install -q -r requirements.txt
.venv\Scripts\python -m duodesk gui
