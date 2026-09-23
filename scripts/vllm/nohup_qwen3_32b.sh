#!/usr/bin/env bash
set -Eeuo pipefail

# Host-side nohup wrapper for the managed Qwen3-32B service on port 53334.
# It deliberately matches the full vLLM command line before stopping a stale
# process, so unrelated Python jobs on the same GPU are left untouched.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
VLLM_ENV_FILE="${STATEBUS_VLLM_ENV_FILE:-${PROJECT_ROOT}/deploy/vllm.env.gpu2-32b-u050}"

if [[ ! -r "$VLLM_ENV_FILE" ]]; then
  printf 'vLLM env file 不存在或不可读：%s\n' "$VLLM_ENV_FILE" >&2
  exit 2
fi
export STATEBUS_VLLM_ENV_FILE="$VLLM_ENV_FILE"
# shellcheck disable=SC1090
source "$VLLM_ENV_FILE"

MODEL_PATH="${STATEBUS_VLLM_MODEL_PATH:-/data/models/Qwen3-32B}"
PORT="${STATEBUS_VLLM_PORT:-53334}"
RUNTIME_DIR="${STATEBUS_VLLM_RUNTIME_DIR:-${HOME}/statebus/work/vllm-qwen3-32b-gpu2-u050}"
PID_FILE="${RUNTIME_DIR}/service.pid"
MODE_FILE="${RUNTIME_DIR}/service.mode"
LOG_FILE="${RUNTIME_DIR}/service.log"
START_SCRIPT="${SCRIPT_DIR}/start_qwen3_32b.sh"
START_WAIT_S="${STATEBUS_VLLM_START_WAIT_S:-900}"

usage() {
  cat <<'EOF'
用法：scripts/vllm/nohup_qwen3_32b.sh [start|restart|stop|status|logs]

默认动作：restart
日志：$HOME/statebus/work/vllm-qwen3-32b-gpu2-u050/service.log
端点：http://127.0.0.1:53334/health
EOF
}

health() {
  curl --noproxy '*' --fail --silent --show-error --max-time 5 \
    "http://127.0.0.1:${PORT}/health" >/dev/null
}

service_pids() {
  local current_user
  current_user="$(id -un)"
  ps -eo pid=,user=,comm=,args= | awk -v owner="$current_user" \
    -v model="$MODEL_PATH" -v port="${PORT}" '
      $2 == owner && ($3 == "vllm" || $3 == "python" || $3 == "python3") &&
      index($0, "vllm serve") && index($0, model) &&
      index($0, "--port " port) { print $1 }
    '
}

pid_is_alive() {
  [[ "$1" =~ ^[1-9][0-9]*$ ]] && kill -0 "$1" 2>/dev/null
}

stop_matching_processes() {
  local pids pid child_pids elapsed
  mapfile -t pids < <(service_pids)
  if (( ${#pids[@]} == 0 )); then
    rm -f "$PID_FILE" "$MODE_FILE"
    printf '没有发现匹配的 Qwen3-32B vLLM 进程\n'
    return 0
  fi

  printf '停止匹配的 vLLM 进程：%s\n' "${pids[*]}"
  for pid in "${pids[@]}"; do
    kill -TERM "$pid" 2>/dev/null || true
  done

  elapsed=0
  while (( elapsed < 30 )); do
    child_pids="$(service_pids || true)"
    [[ -z "$child_pids" ]] && break
    sleep 1
    elapsed=$((elapsed + 1))
  done

  mapfile -t pids < <(service_pids)
  if (( ${#pids[@]} > 0 )); then
    printf '匹配进程未在 30 秒内退出，强制结束：%s\n' "${pids[*]}" >&2
    for pid in "${pids[@]}"; do
      kill -KILL "$pid" 2>/dev/null || true
    done
  fi
  rm -f "$PID_FILE" "$MODE_FILE"
}

start_background() {
  local pid elapsed
  mkdir -p "$RUNTIME_DIR"
  : > "$LOG_FILE"
  nohup "$START_SCRIPT" >>"$LOG_FILE" 2>&1 < /dev/null &
  pid=$!
  printf '%s\n' "$pid" > "$PID_FILE"
  printf 'started pid=%s\n' "$pid"
  printf 'log_file=%s\n' "$LOG_FILE"
  printf 'pid_file=%s\n' "$PID_FILE"

  elapsed=0
  while (( elapsed < START_WAIT_S )); do
    if ! pid_is_alive "$pid"; then
      printf 'vLLM 启动进程已退出，请检查日志：%s\n' "$LOG_FILE" >&2
      return 1
    fi
    if health 2>/dev/null; then
      printf 'health=passed url=http://127.0.0.1:%s/health\n' "$PORT"
      return 0
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
  printf '等待 %s 秒后 vLLM 仍未健康，请检查日志：%s\n' "$START_WAIT_S" "$LOG_FILE" >&2
  return 1
}

status() {
  local pids
  mapfile -t pids < <(service_pids)
  if (( ${#pids[@]} > 0 )); then
    printf 'process=running pids=%s\n' "${pids[*]}"
  else
    printf 'process=stopped\n'
  fi
  if health 2>/dev/null; then
    printf 'endpoint=healthy url=http://127.0.0.1:%s/health\n' "$PORT"
  else
    printf 'endpoint=unavailable url=http://127.0.0.1:%s/health\n' "$PORT"
  fi
}

action="${1:-restart}"
case "$action" in
  start)
    if health 2>/dev/null; then
      mapfile -t pids < <(service_pids)
      if (( ${#pids[@]} == 0 )); then
        printf '53334 已健康，但未找到匹配的当前用户 vLLM 进程；拒绝重复启动。\n' >&2
        exit 1
      fi
      mkdir -p "$RUNTIME_DIR"
      printf '%s\n' "${pids[0]}" > "$PID_FILE"
      printf '53334 已健康，保持现有 vLLM，不重复启动。pids=%s\n' "${pids[*]}"
    else
      start_background
    fi
    ;;
  restart)
    stop_matching_processes
    start_background
    ;;
  stop)
    stop_matching_processes
    ;;
  status)
    status
    ;;
  logs)
    exec tail -n 100 -f "$LOG_FILE"
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
