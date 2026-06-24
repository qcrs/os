#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
RUN_DIR="${STATEBUS_SUITE_OUT:-$REPO_ROOT/runs/v3_next_stage_repeat3_suite_$STAMP}"
LOG_DIR="$RUN_DIR/logs"
LAUNCHER_LOG="$LOG_DIR/launcher.log"

mkdir -p "$LOG_DIR"

COMMAND=(
  python
  scripts/run_v3_next_stage_repeat3_suite.py
  --out "$RUN_DIR"
  --repeat "${STATEBUS_SUITE_REPEAT:-3}"
  --llm-mode "${STATEBUS_SUITE_LLM_MODE:-api}"
)

if [[ -n "${STATEBUS_SUITE_LLM_CONFIG:-}" ]]; then
  COMMAND+=(--llm-config "$STATEBUS_SUITE_LLM_CONFIG")
fi

if [[ "${STATEBUS_SUITE_SKIP_GATES:-0}" == "1" ]]; then
  COMMAND+=(--skip-regression-gates)
fi

if [[ "${STATEBUS_SUITE_SKIP_STATEBUS:-0}" == "1" ]]; then
  COMMAND+=(--skip-statebus-packs)
fi

if [[ "${STATEBUS_SUITE_SKIP_OPEN:-0}" == "1" ]]; then
  COMMAND+=(--skip-open-system)
fi

if [[ "${STATEBUS_SUITE_SKIP_LANGGRAPH_SMOKE:-0}" == "1" ]]; then
  COMMAND+=(--skip-langgraph-smoke)
fi

if [[ "$#" -gt 0 ]]; then
  COMMAND+=("$@")
fi

{
  echo "# Launcher"
  echo
  printf '```bash\n'
  printf '%q ' "${COMMAND[@]}"
  printf '\n```\n'
  echo
  echo "- Run dir: \`$RUN_DIR\`"
  echo "- Log: \`logs/launcher.log\`"
} > "$RUN_DIR/COMMANDS.md"

(
  cd "$REPO_ROOT"
  if command -v setsid >/dev/null 2>&1; then
    nohup setsid "${COMMAND[@]}" > "$LAUNCHER_LOG" 2>&1 &
  else
    nohup "${COMMAND[@]}" > "$LAUNCHER_LOG" 2>&1 &
  fi
  echo $! > "$RUN_DIR/PID"
)

echo "run_dir=$RUN_DIR"
echo "pid=$(cat "$RUN_DIR/PID")"
echo "log=$LAUNCHER_LOG"
