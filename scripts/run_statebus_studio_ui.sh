#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
UI_ROOT="${PROJECT_ROOT}/src/studio-ui"

export VITE_STATEBUS_STUDIO_PORT="${VITE_STATEBUS_STUDIO_PORT:-${STATEBUS_STUDIO_PORT:-50080}}"
export VITE_STATEBUS_STUDIO_UI_PORT="${VITE_STATEBUS_STUDIO_UI_PORT:-50173}"

if ! command -v npm >/dev/null 2>&1; then
  echo "npm was not found on PATH" >&2
  exit 2
fi

stop_owned_ui() {
  local port="$1"
  local listener_pids pid command_line
  listener_pids="$(ss -ltnp "sport = :${port}" 2>/dev/null | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | sort -u)"
  while read -r pid; do
    [[ -n "$pid" ]] || continue
    [[ -r "/proc/${pid}/cmdline" ]] || continue
    command_line="$(tr '\0' ' ' < "/proc/${pid}/cmdline")"
    if [[ "$command_line" == *"${UI_ROOT}/node_modules/.bin/vite"* ]]; then
      echo "[statebus-studio-ui] stopping existing Vite pid=${pid} port=${port}"
      kill "$pid" 2>/dev/null || true
      for _ in {1..20}; do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.1
      done
      if kill -0 "$pid" 2>/dev/null; then
        echo "[statebus-studio-ui] existing process did not stop cleanly: pid=${pid}" >&2
        exit 1
      fi
    else
      echo "[statebus-studio-ui] port ${port} is occupied by an unrelated process; refusing to stop it" >&2
      exit 1
    fi
  done <<< "$listener_pids"
}

stop_owned_ui "$VITE_STATEBUS_STUDIO_UI_PORT"

cd "$UI_ROOT"
exec npm run dev -- --host 127.0.0.1 --port "$VITE_STATEBUS_STUDIO_UI_PORT"
