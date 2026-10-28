#!/usr/bin/env bash
# Keep LF line endings on Windows: see .gitattributes.
# Managed Windows/WSL backend. Parent tray holds stdin open, on Exit it sends
# "stop" and closes stdin. If the parent crashes, stdin EOF stops the backend.
set -uo pipefail
service="${1:-}"
case "$service" in
  codex) folder=work-codex-usage-api ;;
  claude) folder=claude-usage-api ;;
  *) echo "Unknown backend: $service" >&2; exit 2 ;;
esac
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root/$folder" || exit 2
mkdir -p "${XDG_STATE_HOME:-$HOME/.local/state}/codex-claude-usage"
log="${XDG_STATE_HOME:-$HOME/.local/state}/codex-claude-usage/$service.log"
python3 -u server.py >>"$log" 2>&1 &
child=$!
cleanup() {
  trap - EXIT HUP INT TERM
  kill "$child" 2>/dev/null || true
  wait "$child" 2>/dev/null || true
}
trap cleanup EXIT HUP INT TERM
while kill -0 "$child" 2>/dev/null; do
  line=""
  IFS= read -r -t 1 line
  result=$?
  if [[ "$result" -eq 0 && "$line" == "stop" ]]; then break; fi
  if [[ "$result" -eq 1 ]]; then break; fi  # parent pipe EOF
  # bash returns >128 for timeout, so continue checking child liveness
 done
