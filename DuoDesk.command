#!/bin/bash
# Double-click this on macOS to open DuoDesk. First run sets everything up.
cd "$(dirname "$0")" || exit 1

if [ ! -d .venv ]; then
  echo "First run — setting up (one time, ~30s)..."
  python3 -m venv .venv || { echo "Could not create venv. Install Python 3 from python.org."; read -r; exit 1; }
  ./.venv/bin/python -m pip install --upgrade pip >/dev/null 2>&1
  ./.venv/bin/pip install -r requirements.txt || { echo "Dependency install failed."; read -r; exit 1; }
fi

./.venv/bin/python -m duodesk gui
