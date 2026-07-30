#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
VLLM_ENV_FILE="${STATEBUS_VLLM_ENV_FILE:-${PROJECT_ROOT}/deploy/vllm.env.local}"

if [[ -f "$VLLM_ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$VLLM_ENV_FILE"
fi

SERVICE_MODE="${STATEBUS_VLLM_SERVICE_MODE:-standard}"
HOST="${STATEBUS_VLLM_HOST:-127.0.0.1}"
PORT="${STATEBUS_VLLM_PORT:-53334}"
MODEL_PATH="${STATEBUS_VLLM_MODEL_PATH:-/data/models/Qwen3-32B}"
RUNTIME_DIR="${STATEBUS_VLLM_RUNTIME_DIR:-${HOME}/statebus/work/vllm-qwen3-32b}"
PID_FILE="${RUNTIME_DIR}/service.pid"
MODE_FILE="${RUNTIME_DIR}/service.mode"
LOG_FILE="${RUNTIME_DIR}/service.log"
START_WAIT_S="${STATEBUS_VLLM_START_WAIT_S:-180}"

case "$SERVICE_MODE" in
  standard)
    START_SCRIPT="${SCRIPT_DIR}/start_qwen3_32b.sh"
    HEALTH_URL="http://${HOST}:${PORT}/health"
    ;;
  kv)
    START_SCRIPT="${PROJECT_ROOT}/scripts/experiments/engine_local_kv/start_engine_local_kv_probe_service.sh"
    HEALTH_URL="http://${HOST}:${PORT}/statebus/kv/health"
    ;;
  *)
    printf '不支持的 STATEBUS_VLLM_SERVICE_MODE：%s，应为 standard 或 kv\n' "$SERVICE_MODE" >&2
    exit 2
    ;;
esac

usage() {
  cat <<'EOF'
用法：scripts/vllm/manage_qwen3_32b.sh 命令

命令：
  start         后台启动服务并等待健康检查通过
  stop          只停止 StateBus PID 文件记录的进程
  restart       停止后重新启动服务
  status        显示托管进程和服务端点状态
  health        检查当前模式对应的健康端点
  logs          持续查看服务日志
  print-config  显示解析后的非敏感配置
  help          显示本帮助

在 deploy/vllm.env.local 中设置 STATEBUS_VLLM_SERVICE_MODE=standard 或 kv。
EOF
}

read_pid() {
  [[ -s "$PID_FILE" ]] || return 1
  local pid
  read -r pid < "$PID_FILE"
  [[ "$pid" =~ ^[1-9][0-9]*$ ]] || return 1
  printf '%s\n' "$pid"
}

is_running() {
  local pid="$1"
  kill -0 "$pid" 2>/dev/null
}

is_expected_process() {
  local pid="$1" cmdline
  [[ -r "/proc/${pid}/cmdline" ]] || return 1
  cmdline="$(tr '\0' ' ' < "/proc/${pid}/cmdline")"
  [[ "$cmdline" == *"vllm"* && "$cmdline" == *"$MODEL_PATH"* ]]
}

probe_health() {
  curl --fail --silent --show-error --max-time 3 "$HEALTH_URL" >/dev/null
}

print_config() {
  printf '模式=%s\n' "$SERVICE_MODE"
  printf '模型=%s\n' "$MODEL_PATH"
  printf 'API地址=http://%s:%s/v1\n' "$HOST" "$PORT"
  printf '健康地址=%s\n' "$HEALTH_URL"
  printf '物理GPU=%s\n' "${STATEBUS_VLLM_CUDA_VISIBLE_DEVICES:-1}"
  printf '运行目录=%s\n' "$RUNTIME_DIR"
  printf '日志文件=%s\n' "$LOG_FILE"
}

start_service() {
  local pid elapsed
  if pid="$(read_pid)" && is_running "$pid"; then
    printf '托管的 vLLM 已在运行：pid=%s\n' "$pid" >&2
    exit 1
  fi
  if probe_health 2>/dev/null; then
    printf '%s 已有服务响应，但该服务不属于当前 PID 文件，拒绝接管。\n' "$HEALTH_URL" >&2
    exit 1
  fi
  if [[ "$SERVICE_MODE" == "kv" ]]; then
    : "${STATEBUS_KV_API_TOKEN_FILE:?kv 模式必须设置 STATEBUS_KV_API_TOKEN_FILE}"
    export STATEBUS_KV_ENGINE_GENERATION="${STATEBUS_KV_ENGINE_GENERATION:-qwen3-32b-kv-$(date +%Y%m%d_%H%M%S)}"
  fi

  mkdir -p "$RUNTIME_DIR"
  : > "$LOG_FILE"
  nohup "$START_SCRIPT" >> "$LOG_FILE" 2>&1 &
  pid=$!
  printf '%s\n' "$pid" > "$PID_FILE"
  printf '%s\n' "$SERVICE_MODE" > "$MODE_FILE"
  printf '正在启动 vLLM：pid=%s mode=%s log=%s\n' "$pid" "$SERVICE_MODE" "$LOG_FILE"

  elapsed=0
  while (( elapsed < START_WAIT_S )); do
    if ! is_running "$pid"; then
      printf 'vLLM 在启动期间退出，请检查：%s\n' "$LOG_FILE" >&2
      exit 1
    fi
    if probe_health 2>/dev/null; then
      printf 'vLLM 健康检查通过：%s\n' "$HEALTH_URL"
      return
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
  printf '等待 %s 秒后 vLLM 仍未就绪，请检查：%s\n' "$START_WAIT_S" "$LOG_FILE" >&2
  exit 1
}

stop_service() {
  local pid elapsed
  if ! pid="$(read_pid)"; then
    printf '没有托管的 vLLM PID 文件：%s\n' "$PID_FILE"
    return
  fi
  if ! is_running "$pid"; then
    printf '进程 pid=%s 已不存在，清理过期 PID 文件\n' "$pid"
    rm -f "$PID_FILE" "$MODE_FILE"
    return
  fi
  if ! is_expected_process "$pid"; then
    printf 'pid=%s 不是预期的 vLLM 模型进程，拒绝停止。\n' "$pid" >&2
    exit 1
  fi

  kill "$pid"
  elapsed=0
  while is_running "$pid" && (( elapsed < 30 )); do
    sleep 1
    elapsed=$((elapsed + 1))
  done
  if is_running "$pid"; then
    printf 'vLLM 在 30 秒内未停止，进程仍存在：pid=%s\n' "$pid" >&2
    exit 1
  fi
  rm -f "$PID_FILE" "$MODE_FILE"
  printf '已停止托管的 vLLM：pid=%s\n' "$pid"
}

status_service() {
  local pid managed_mode
  managed_mode="$(sed -n '1p' "$MODE_FILE" 2>/dev/null || true)"
  if pid="$(read_pid)" && is_running "$pid"; then
    printf '进程=运行中 pid=%s mode=%s\n' "$pid" "${managed_mode:-未知}"
  else
    printf '进程=已停止\n'
  fi
  if probe_health 2>/dev/null; then
    printf '端点=健康 url=%s\n' "$HEALTH_URL"
  else
    printf '端点=不可用 url=%s\n' "$HEALTH_URL"
  fi
}

command="${1:-help}"
case "$command" in
  start) start_service ;;
  stop) stop_service ;;
  restart) stop_service; start_service ;;
  status) status_service ;;
  health) probe_health && printf '健康：%s\n' "$HEALTH_URL" ;;
  logs) exec tail -n 100 -f "$LOG_FILE" ;;
  print-config) print_config ;;
  help|-h|--help) usage ;;
  *) usage >&2; exit 2 ;;
esac
