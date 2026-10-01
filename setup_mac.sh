#!/usr/bin/env bash
# Set up maintained source without overwriting UI or user data.
set -euo pipefail
task_repo_dir="$(cd "$(dirname "$0")" && pwd)"
task_python="${PYTHON:-python3.11}"
command -v "$task_python" >/dev/null || { echo 'Install Python 3.11, or set PYTHON to a Python 3.12 executable for the core service.'; exit 1; }
"$task_python" -m venv "$task_repo_dir/.venv"
"$task_repo_dir/.venv/bin/python" -m pip install -r "$task_repo_dir/backend/requirements-core.txt"
if [ ! -f "$task_repo_dir/backend/.env" ]; then cp "$task_repo_dir/backend/.env.example" "$task_repo_dir/backend/.env"; fi
echo 'Ready. Run .venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 from this repository.'
