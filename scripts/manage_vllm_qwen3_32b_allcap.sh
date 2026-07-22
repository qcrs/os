#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROFILE="$REPO_ROOT/deploy/activate_statebus_vllm_allcap.sh"

# shellcheck disable=SC1090
source "$PROFILE"

STOP_TIMEOUT_S="${STATEBUS_VLLM_STOP_TIMEOUT_S:-60}"

usage() {
  printf 'usage: %s {check|start|stop|restart|status}\n' "${0##*/}" >&2
}

read_process_args() {
  local pid="$1"
  PROCESS_ARGS=()
  [[ "$pid" =~ ^[0-9]+$ && -r "/proc/$pid/cmdline" && -O "/proc/$pid" ]] || return 1
  mapfile -d '' -t PROCESS_ARGS < "/proc/$pid/cmdline"
  ((${#PROCESS_ARGS[@]} > 0))
}

process_matches_identity() {
  local pid="$1" arg previous=""
  local saw_vllm=0 saw_serve=0 saw_model=0 saw_port=0
  read_process_args "$pid" || return 1
  for arg in "${PROCESS_ARGS[@]}"; do
    if [[ "$arg" == "vllm" || "$arg" == */vllm ]]; then
      saw_vllm=1
    elif [[ "$arg" == "serve" ]]; then
      saw_serve=1
    elif [[ "$arg" == "$STATEBUS_VLLM_MODEL_PATH" ]]; then
      saw_model=1
    elif [[ "$arg" == "--port=$STATEBUS_VLLM_PORT" ]]; then
      saw_port=1
    elif [[ "$previous" == "--port" && "$arg" == "$STATEBUS_VLLM_PORT" ]]; then
      saw_port=1
    fi
    previous="$arg"
  done
  ((saw_vllm && saw_serve && saw_model && saw_port))
}

process_is_allcap() {
  local pid="$1" arg previous="" env_entry
  local prefix=0 embeds=0 direct=0 worker=0 middleware=0 logprobs=0 request_ids=0
  local exporter=0 v0=0 named=0 diagnostics=0 cuda=0
  read_process_args "$pid" || return 1
  for arg in "${PROCESS_ARGS[@]}"; do
    case "$arg" in
      --enable-prefix-caching) prefix=1 ;;
      --enable-prompt-embeds) embeds=1 ;;
      --disable-frontend-multiprocessing) direct=1 ;;
      --enable-request-id-headers) request_ids=1 ;;
    esac
    if [[ "$previous" == "--worker-extension-cls" && "$arg" == "v2.integrations.vllm_latent.worker_extension.LatentWorkerExtension" ]]; then
      worker=1
    elif [[ "$previous" == "--middleware" && "$arg" == "v2.integrations.vllm_latent.middleware.LatentHandoffMiddleware" ]]; then
      middleware=1
    elif [[ "$previous" == "--max-logprobs" && "$arg" == "$STATEBUS_VLLM_MAX_LOGPROBS" ]]; then
      logprobs=1
    fi
    previous="$arg"
  done
  if [[ -r "/proc/$pid/environ" ]]; then
    while IFS= read -r -d '' env_entry; do
      case "$env_entry" in
        STATEBUS_VLLM_EXPORT_PREFIX_COUNTERS=1) exporter=1 ;;
        VLLM_USE_V1=0) v0=1 ;;
        STATEBUS_VLLM_SERVICE_NAME="$STATEBUS_VLLM_SERVICE_NAME") named=1 ;;
        STATEBUS_LATENT_ALIGNMENT_DIAGNOSTICS=true) diagnostics=1 ;;
        CUDA_VISIBLE_DEVICES="$STATEBUS_VLLM_CUDA_VISIBLE_DEVICES") cuda=1 ;;
      esac
    done < "/proc/$pid/environ"
  fi
  ((prefix && embeds && direct && worker && middleware && logprobs && request_ids && exporter && v0 && named && diagnostics && cuda))
}

find_matching_pids() {
  local proc_dir pid
  for proc_dir in /proc/[0-9]*; do
    pid="${proc_dir##*/}"
    if process_matches_identity "$pid"; then
      printf '%s\n' "$pid"
    fi
  done
}

prepare_directories() {
  mkdir -p "${STATEBUS_VLLM_PID_FILE%/*}" "${STATEBUS_VLLM_LOG_FILE%/*}"
}

check_configuration() {
  local file installed_version
  prepare_directories
  [[ "$STOP_TIMEOUT_S" =~ ^[1-9][0-9]*$ ]] || {
    printf 'invalid STATEBUS_VLLM_STOP_TIMEOUT_S: %s\n' "$STOP_TIMEOUT_S" >&2
    return 2
  }
  [[ -x "$STATEBUS_VLLM_START_SCRIPT" ]] || {
    printf 'launcher is missing or not executable: %s\n' "$STATEBUS_VLLM_START_SCRIPT" >&2
    return 2
  }
  [[ -x "$STATEBUS_VLLM_ENV_PREFIX/bin/python" && -x "$STATEBUS_VLLM_ENV_PREFIX/bin/vllm" ]] || {
    printf 'vLLM environment is incomplete: %s\n' "$STATEBUS_VLLM_ENV_PREFIX" >&2
    return 2
  }
  installed_version="$("$STATEBUS_VLLM_ENV_PREFIX/bin/python" -c 'from importlib.metadata import version; print(version("vllm"))')"
  [[ "$installed_version" == "$STATEBUS_VLLM_EXPECTED_VERSION" ]] || {
    printf 'vLLM version mismatch: expected %s, found %s\n' "$STATEBUS_VLLM_EXPECTED_VERSION" "$installed_version" >&2
    return 2
  }
  [[ -r "$REPO_ROOT/scripts/vllm_exporter/sitecustomize.py" && -r "$REPO_ROOT/scripts/vllm_v0_prefix_counter_exporter.py" ]] || {
    printf 'StateBus prefix counter exporter files are missing\n' >&2
    return 2
  }
  PYTHONPATH="$REPO_ROOT/scripts:$REPO_ROOT" \
    "$STATEBUS_VLLM_ENV_PREFIX/bin/python" -c \
    'from importlib.metadata import version; from vllm_v0_prefix_counter_exporter import require_supported_vllm_version; require_supported_vllm_version(version("vllm"))'
  for file in config.json model.safetensors.index.json tokenizer_config.json tokenizer.json; do
    [[ -r "$STATEBUS_VLLM_MODEL_PATH/$file" ]] || {
      printf 'model identity file is missing: %s\n' "$STATEBUS_VLLM_MODEL_PATH/$file" >&2
      return 2
    }
  done
  [[ -s "$STATEBUS_LATENT_API_TOKEN_FILE" ]] || {
    printf 'latent token file is missing or empty: %s\n' "$STATEBUS_LATENT_API_TOKEN_FILE" >&2
    return 2
  }
  [[ "$(stat -c '%a' "$STATEBUS_LATENT_API_TOKEN_FILE")" == "600" ]] || {
    printf 'latent token file must have mode 600: %s\n' "$STATEBUS_LATENT_API_TOKEN_FILE" >&2
    return 2
  }
  bash -n "$STATEBUS_VLLM_START_SCRIPT"
  printf 'configuration: READY\n'
  printf 'service: %s\n' "$STATEBUS_VLLM_SERVICE_NAME"
  printf 'profile: %s (vLLM %s, V0)\n' "$STATEBUS_VLLM_CAPABILITY_PROFILE" "$installed_version"
  printf 'endpoint: %s\n' "$STATEBUS_LOCAL_VLLM_BASE_URL"
  printf 'metrics: %s\n' "$STATEBUS_VLLM_METRICS_URL"
  printf 'cuda_visible_devices: %s\n' "$STATEBUS_VLLM_CUDA_VISIBLE_DEVICES"
  printf 'pid_file: %s\n' "$STATEBUS_VLLM_PID_FILE"
  printf 'log_file: %s\n' "$STATEBUS_VLLM_LOG_FILE"
}

status_service() {
  local pid state
  local -a pids=()
  mapfile -t pids < <(find_matching_pids)
  if ((${#pids[@]} == 0)); then
    printf 'STOPPED name=%s endpoint=%s\n' "$STATEBUS_VLLM_SERVICE_NAME" "$STATEBUS_LOCAL_VLLM_BASE_URL"
    return 1
  fi
  for pid in "${pids[@]}"; do
    if process_is_allcap "$pid"; then
      state="ALLCAP"
    else
      state="CONFIG_MISMATCH"
    fi
    printf 'RUNNING name=%s pid=%s state=%s endpoint=%s\n' "$STATEBUS_VLLM_SERVICE_NAME" "$pid" "$state" "$STATEBUS_LOCAL_VLLM_BASE_URL"
  done
  printf 'log=%s\n' "$STATEBUS_VLLM_LOG_FILE"
}

start_service() {
  local pid
  local -a pids=()
  check_configuration
  mapfile -t pids < <(find_matching_pids)
  if ((${#pids[@]} > 0)); then
    for pid in "${pids[@]}"; do
      if ! process_is_allcap "$pid"; then
        printf 'matching service has a different capability profile (pid=%s); use restart\n' "$pid" >&2
        return 3
      fi
    done
    printf '%s\n' "${pids[0]}" > "$STATEBUS_VLLM_PID_FILE"
    printf 'already running: %s pid=%s\n' "$STATEBUS_VLLM_SERVICE_NAME" "${pids[0]}"
    return 0
  fi

  {
    printf '\n[%s] starting %s\n' "$(date '+%F %T %Z')" "$STATEBUS_VLLM_SERVICE_NAME"
  } >> "$STATEBUS_VLLM_LOG_FILE"
  nohup bash "$STATEBUS_VLLM_START_SCRIPT" >> "$STATEBUS_VLLM_LOG_FILE" 2>&1 < /dev/null &
  pid=$!
  printf '%s\n' "$pid" > "$STATEBUS_VLLM_PID_FILE"
  disown "$pid" 2>/dev/null || true
  sleep 2
  if ! kill -0 "$pid" 2>/dev/null; then
    printf 'vLLM exited during startup; inspect %s\n' "$STATEBUS_VLLM_LOG_FILE" >&2
    return 4
  fi
  printf 'STARTING name=%s pid=%s log=%s\n' "$STATEBUS_VLLM_SERVICE_NAME" "$pid" "$STATEBUS_VLLM_LOG_FILE"
  printf 'startup is asynchronous; status does not call /health or /metrics\n'
}

stop_service() {
  local pid deadline alive
  local -a pids=()
  mapfile -t pids < <(find_matching_pids)
  if ((${#pids[@]} == 0)); then
    rm -f -- "$STATEBUS_VLLM_PID_FILE"
    printf 'already stopped: %s\n' "$STATEBUS_VLLM_SERVICE_NAME"
    return 0
  fi
  printf 'stopping %s pid(s)=%s\n' "$STATEBUS_VLLM_SERVICE_NAME" "${pids[*]}"
  for pid in "${pids[@]}"; do
    kill -TERM "$pid" 2>/dev/null || true
  done
  deadline=$((SECONDS + STOP_TIMEOUT_S))
  while ((SECONDS < deadline)); do
    alive=0
    for pid in "${pids[@]}"; do
      if kill -0 "$pid" 2>/dev/null; then
        alive=$((alive + 1))
      fi
    done
    ((alive == 0)) && break
    sleep 1
  done
  if ((alive > 0)); then
    printf 'graceful timeout reached; sending KILL to remaining matching pid(s)\n' >&2
    for pid in "${pids[@]}"; do
      kill -KILL "$pid" 2>/dev/null || true
    done
  fi
  rm -f -- "$STATEBUS_VLLM_PID_FILE"
  printf 'stopped: %s\n' "$STATEBUS_VLLM_SERVICE_NAME"
}

main() {
  local command="${1:-}"
  case "$command" in
    check)
      check_configuration
      ;;
    start)
      start_service
      ;;
    stop)
      stop_service
      ;;
    restart)
      check_configuration
      stop_service
      start_service
      ;;
    status)
      status_service
      ;;
    *)
      usage
      return 2
      ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
