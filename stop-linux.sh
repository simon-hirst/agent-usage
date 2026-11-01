#!/usr/bin/env bash
# Stop only this project's tray process (source or packaged) and its owned backends.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
pids=()

# ps is available on both Linux and macOS, unlike /proc or pgrep variants.
while IFS= read -r line; do
  read -r pid command <<< "$line"
  [[ "$pid" =~ ^[0-9]+$ ]] || continue
  [[ "$pid" != "$$" && "$pid" != "$PPID" ]] || continue
  case "$command" in
    *--backend-server*|*--backend-supervisor*|*--direct-usage*|*--verify-bundle*) continue ;;
  esac
  case "$command" in
    *"/ProviderUsageTray/ProviderUsageTray"*|*"/ProviderUsageTray.app/Contents/MacOS/ProviderUsageTray"*)
      pids+=("$pid") ;;
    *"$root/desktop/run_app.py"*)
      pids+=("$pid") ;;
    *"desktop/run_app.py"*)
      # Relative script path: check the process's actual working directory.
      cwd=""
      if [[ -L "/proc/$pid/cwd" ]]; then
        cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null || true)"
      elif command -v lsof >/dev/null 2>&1; then
        while IFS= read -r item; do
          if [[ "$item" == n* ]]; then cwd="${item:1}"; break; fi
        done < <(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null || true)
      fi
      [[ "$cwd" == "$root" ]] && pids+=("$pid") ;;
  esac
done < <(ps -Aww -o pid= -o command=)

if (( ${#pids[@]} == 0 )); then
  echo 'Provider Usage Tray is not running.'
  exit 0
fi

for pid in "${pids[@]}"; do
  echo "Stopping Provider Usage Tray (PID $pid)..."
  kill -TERM "$pid" 2>/dev/null || true
done

# Give the backend supervisors time to observe the parent pipe closing.
for _ in 1 2 3 4 5; do
  any=0
  for pid in "${pids[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then any=1; fi
  done
  (( any == 0 )) && break
  sleep 1
done
for pid in "${pids[@]}"; do
  if kill -0 "$pid" 2>/dev/null; then
    echo "Force-stopping unresponsive tray PID $pid..."
    kill -KILL "$pid" 2>/dev/null || true
  fi
done
echo 'Tray stopped. Independently started API servers are left alone.'
