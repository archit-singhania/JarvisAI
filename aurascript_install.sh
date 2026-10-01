#!/usr/bin/env bash
# The generated Documents/AuraScript scaffold has been retired.
set -euo pipefail
task_repo_dir="$(cd "$(dirname "$0")" && pwd)"
cd "$task_repo_dir/aurascript"
npm ci
npm run prepare:editor
echo 'Maintained AuraScript installed. Start the Wednesday backend, then run npm start here.'
