#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
if [[ ! -f .venv/requirements-installed ]]; then
  .venv/bin/python -m pip install -r requirements.txt
  touch .venv/requirements-installed
fi
logs="${XDG_STATE_HOME:-$HOME/.local/state}/codex-claude-usage"
mkdir -p "$logs"
nohup .venv/bin/python desktop/run_app.py >>"$logs/tray.log" 2>&1 </dev/null &
echo 'Started Codex + Claude tray in background.'
