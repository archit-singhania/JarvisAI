#!/usr/bin/env bash
set -euo pipefail
task_repo_dir="$(cd "$(dirname "$0")" && pwd)"
exec bash "$task_repo_dir/aurascript_install.sh"
