#!/usr/bin/env bash

_statebus_local_vllm_restore_shell_options() {
  if [[ "${_STATEBUS_LOCAL_VLLM_HAD_ERREXIT:-0}" == "1" ]]; then
    set -o errexit
  else
    set +o errexit
  fi
  if [[ "${_STATEBUS_LOCAL_VLLM_HAD_NOUNSET:-0}" == "1" ]]; then
    set -o nounset
  else
    set +o nounset
  fi
  if [[ "${_STATEBUS_LOCAL_VLLM_HAD_PIPEFAIL:-0}" == "1" ]]; then
    set -o pipefail
  else
    set +o pipefail
  fi
}

_statebus_activate_local_vllm_profile_main() {
  set -euo pipefail

  local script_dir profile vllm_env_file
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  profile="${1:-${STATEBUS_LOCAL_VLLM_PROFILE:-qwen3-32b}}"

  if [[ ! -f "${script_dir}/activate_statebus_host.sh" ]]; then
    echo "[statebus-local-vllm] 缺少宿主机环境脚本：${script_dir}/activate_statebus_host.sh" >&2
    return 1
  fi

  # shellcheck disable=SC1090
  source "${script_dir}/activate_statebus_host.sh"

  if [[ "$profile" != "qwen3-32b" && "$profile" != "32b" ]]; then
    echo "[statebus-local-vllm] 不支持的 profile：$profile" >&2
    echo "[statebus-local-vllm] 当前支持：qwen3-32b" >&2
    return 1
  fi

  vllm_env_file="${STATEBUS_VLLM_ENV_FILE:-${script_dir}/vllm.env.local}"
  if [[ -f "$vllm_env_file" ]]; then
    # shellcheck disable=SC1090
    source "$vllm_env_file"
  fi

  export STATEBUS_LOCAL_VLLM_PROFILE="qwen3-32b"
  export STATEBUS_VLLM_MODEL_PATH="${STATEBUS_VLLM_MODEL_PATH:-/data/models/Qwen3-32B}"
  export STATEBUS_VLLM_SERVED_MODEL_NAME="${STATEBUS_VLLM_SERVED_MODEL_NAME:-qwen3-32b}"
  export STATEBUS_LOCAL_VLLM_MODEL="$STATEBUS_VLLM_SERVED_MODEL_NAME"
  export STATEBUS_VLLM_HOST="${STATEBUS_VLLM_HOST:-127.0.0.1}"
  export STATEBUS_VLLM_PORT="${STATEBUS_VLLM_PORT:-53334}"
  export STATEBUS_LOCAL_VLLM_PORT="$STATEBUS_VLLM_PORT"
  export STATEBUS_LOCAL_VLLM_BASE_URL="http://127.0.0.1:${STATEBUS_VLLM_PORT}/v1"
  export STATEBUS_LOCAL_VLLM_HEALTH_URL="http://127.0.0.1:${STATEBUS_VLLM_PORT}/health"
  export STATEBUS_VLLM_CUDA_VISIBLE_DEVICES="${STATEBUS_VLLM_CUDA_VISIBLE_DEVICES:-2}"
  export STATEBUS_VLLM_MAX_MODEL_LEN="${STATEBUS_VLLM_MAX_MODEL_LEN:-4096}"
  export STATEBUS_VLLM_GPU_MEMORY_UTILIZATION="${STATEBUS_VLLM_GPU_MEMORY_UTILIZATION:-0.82}"
  export STATEBUS_VLLM_MAX_NUM_SEQS="${STATEBUS_VLLM_MAX_NUM_SEQS:-1}"
  export STATEBUS_VLLM_MAX_NUM_BATCHED_TOKENS="${STATEBUS_VLLM_MAX_NUM_BATCHED_TOKENS:-4096}"
  export STATEBUS_VLLM_TENSOR_PARALLEL_SIZE="${STATEBUS_VLLM_TENSOR_PARALLEL_SIZE:-1}"

  echo "[statebus-local-vllm] 配置=$STATEBUS_LOCAL_VLLM_PROFILE"
  echo "[statebus-local-vllm] 模型目录=$STATEBUS_VLLM_MODEL_PATH"
  echo "[statebus-local-vllm] 服务模型名=$STATEBUS_VLLM_SERVED_MODEL_NAME"
  echo "[statebus-local-vllm] API地址=$STATEBUS_LOCAL_VLLM_BASE_URL"
  echo "[statebus-local-vllm] 健康地址=$STATEBUS_LOCAL_VLLM_HEALTH_URL"
  echo "[statebus-local-vllm] 物理GPU=$STATEBUS_VLLM_CUDA_VISIBLE_DEVICES"
  echo "[statebus-local-vllm] 张量并行=$STATEBUS_VLLM_TENSOR_PARALLEL_SIZE"
  if [[ -n "${STATEBUS_VLLM_NUM_GPU_BLOCKS_OVERRIDE:-}" ]]; then
    echo "[statebus-local-vllm] GPU块覆盖=$STATEBUS_VLLM_NUM_GPU_BLOCKS_OVERRIDE"
  fi
}

_STATEBUS_LOCAL_VLLM_HAD_ERREXIT=0
_STATEBUS_LOCAL_VLLM_HAD_NOUNSET=0
_STATEBUS_LOCAL_VLLM_HAD_PIPEFAIL=0
if shopt -qo errexit; then
  _STATEBUS_LOCAL_VLLM_HAD_ERREXIT=1
fi
if shopt -qo nounset; then
  _STATEBUS_LOCAL_VLLM_HAD_NOUNSET=1
fi
if shopt -qo pipefail; then
  _STATEBUS_LOCAL_VLLM_HAD_PIPEFAIL=1
fi

if _statebus_activate_local_vllm_profile_main "$@"; then
  _statebus_activate_local_vllm_status=0
else
  _statebus_activate_local_vllm_status=$?
fi

_statebus_local_vllm_restore_shell_options

unset -f _statebus_local_vllm_restore_shell_options
unset -f _statebus_activate_local_vllm_profile_main
unset _STATEBUS_LOCAL_VLLM_HAD_ERREXIT _STATEBUS_LOCAL_VLLM_HAD_NOUNSET _STATEBUS_LOCAL_VLLM_HAD_PIPEFAIL

return "${_statebus_activate_local_vllm_status}" 2>/dev/null || exit "${_statebus_activate_local_vllm_status}"
