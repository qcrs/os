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

  local script_dir profile
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  profile="${1:-${STATEBUS_LOCAL_VLLM_PROFILE:-qwen3-8b}}"

  if [[ ! -f "${script_dir}/activate_statebus_host.sh" ]]; then
    echo "[statebus-local-vllm] missing host activation script: ${script_dir}/activate_statebus_host.sh" >&2
    return 1
  fi

  # shellcheck disable=SC1090
  source "${script_dir}/activate_statebus_host.sh"

  case "$profile" in
    qwen3-8b|8b|dev-8b)
      export STATEBUS_LOCAL_VLLM_PROFILE="qwen3-8b"
      export STATEBUS_VLLM_MODEL_PATH="/data/models/Qwen3-8B"
      export STATEBUS_VLLM_SERVED_MODEL_NAME="qwen3-8b"
      export STATEBUS_LOCAL_VLLM_MODEL="qwen3-8b"
      export STATEBUS_VLLM_HOST="0.0.0.0"
      export STATEBUS_VLLM_PORT="53333"
      export STATEBUS_LOCAL_VLLM_PORT="53333"
      export STATEBUS_LOCAL_VLLM_BASE_URL="http://127.0.0.1:53333/v1"
      export STATEBUS_LOCAL_VLLM_HEALTH_URL="http://127.0.0.1:53333/health"
      export STATEBUS_VLLM_CUDA_VISIBLE_DEVICES="1"
      export STATEBUS_VLLM_MAX_MODEL_LEN="8192"
      export STATEBUS_VLLM_GPU_MEMORY_UTILIZATION="0.35"
      export STATEBUS_VLLM_MAX_NUM_SEQS="4"
      export STATEBUS_VLLM_MAX_NUM_BATCHED_TOKENS="8192"
      export STATEBUS_VLLM_TENSOR_PARALLEL_SIZE="1"
      ;;
    qwen3-32b|32b|formal-32b)
      export STATEBUS_LOCAL_VLLM_PROFILE="qwen3-32b"
      export STATEBUS_VLLM_MODEL_PATH="/data/models/Qwen3-32B"
      export STATEBUS_VLLM_SERVED_MODEL_NAME="qwen3-32b"
      export STATEBUS_LOCAL_VLLM_MODEL="qwen3-32b"
      export STATEBUS_VLLM_HOST="127.0.0.1"
      export STATEBUS_VLLM_PORT="53334"
      export STATEBUS_LOCAL_VLLM_PORT="53334"
      export STATEBUS_LOCAL_VLLM_BASE_URL="http://127.0.0.1:53334/v1"
      export STATEBUS_LOCAL_VLLM_HEALTH_URL="http://127.0.0.1:53334/health"
      export STATEBUS_VLLM_CUDA_VISIBLE_DEVICES="2"
      export STATEBUS_VLLM_MAX_MODEL_LEN="4096"
      export STATEBUS_VLLM_GPU_MEMORY_UTILIZATION="0.92"
      export STATEBUS_VLLM_MAX_NUM_SEQS="1"
      export STATEBUS_VLLM_MAX_NUM_BATCHED_TOKENS="4096"
      export STATEBUS_VLLM_TENSOR_PARALLEL_SIZE="1"
      ;;
    qwen3-32b-2gpu|32b-2gpu|formal-32b-2gpu)
      export STATEBUS_LOCAL_VLLM_PROFILE="qwen3-32b-2gpu"
      export STATEBUS_VLLM_MODEL_PATH="/data/models/Qwen3-32B"
      export STATEBUS_VLLM_SERVED_MODEL_NAME="qwen3-32b"
      export STATEBUS_LOCAL_VLLM_MODEL="qwen3-32b"
      export STATEBUS_VLLM_HOST="127.0.0.1"
      export STATEBUS_VLLM_PORT="53334"
      export STATEBUS_LOCAL_VLLM_PORT="53334"
      export STATEBUS_LOCAL_VLLM_BASE_URL="http://127.0.0.1:53334/v1"
      export STATEBUS_LOCAL_VLLM_HEALTH_URL="http://127.0.0.1:53334/health"
      export STATEBUS_VLLM_CUDA_VISIBLE_DEVICES="0,1"
      export STATEBUS_VLLM_MAX_MODEL_LEN="8192"
      export STATEBUS_VLLM_GPU_MEMORY_UTILIZATION="0.90"
      export STATEBUS_VLLM_MAX_NUM_SEQS="1"
      export STATEBUS_VLLM_MAX_NUM_BATCHED_TOKENS="8192"
      export STATEBUS_VLLM_TENSOR_PARALLEL_SIZE="2"
      ;;
    qwen2.5-14b|14b|fallback-14b)
      export STATEBUS_LOCAL_VLLM_PROFILE="qwen2.5-14b"
      export STATEBUS_VLLM_MODEL_PATH="/data/models/Qwen2.5-14B-Instruct"
      export STATEBUS_VLLM_SERVED_MODEL_NAME="qwen2.5-14b-instruct"
      export STATEBUS_LOCAL_VLLM_MODEL="qwen2.5-14b-instruct"
      export STATEBUS_VLLM_HOST="0.0.0.0"
      export STATEBUS_VLLM_PORT="53335"
      export STATEBUS_LOCAL_VLLM_PORT="53335"
      export STATEBUS_LOCAL_VLLM_BASE_URL="http://127.0.0.1:53335/v1"
      export STATEBUS_LOCAL_VLLM_HEALTH_URL="http://127.0.0.1:53335/health"
      export STATEBUS_VLLM_CUDA_VISIBLE_DEVICES="1"
      export STATEBUS_VLLM_MAX_MODEL_LEN="8192"
      export STATEBUS_VLLM_GPU_MEMORY_UTILIZATION="0.50"
      export STATEBUS_VLLM_MAX_NUM_SEQS="2"
      export STATEBUS_VLLM_MAX_NUM_BATCHED_TOKENS="4096"
      export STATEBUS_VLLM_TENSOR_PARALLEL_SIZE="1"
      ;;
    *)
      echo "[statebus-local-vllm] unsupported profile: $profile" >&2
      echo "[statebus-local-vllm] supported profiles: qwen3-8b, qwen3-32b, qwen3-32b-2gpu, qwen2.5-14b" >&2
      return 1
      ;;
  esac

  echo "[statebus-local-vllm] profile=$STATEBUS_LOCAL_VLLM_PROFILE"
  echo "[statebus-local-vllm] model_path=$STATEBUS_VLLM_MODEL_PATH"
  echo "[statebus-local-vllm] served_model_name=$STATEBUS_VLLM_SERVED_MODEL_NAME"
  echo "[statebus-local-vllm] base_url=$STATEBUS_LOCAL_VLLM_BASE_URL"
  echo "[statebus-local-vllm] health_url=$STATEBUS_LOCAL_VLLM_HEALTH_URL"
  echo "[statebus-local-vllm] cuda_visible_devices=$STATEBUS_VLLM_CUDA_VISIBLE_DEVICES"
  echo "[statebus-local-vllm] tensor_parallel_size=$STATEBUS_VLLM_TENSOR_PARALLEL_SIZE"
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
