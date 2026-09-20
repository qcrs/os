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

  local script_dir profile vllm_env_file requested_env_file requested_embedding_gpu
  local default_model_path default_served_model default_gpu default_context
  local default_batched_tokens default_utilization
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  profile="${1:-${STATEBUS_LOCAL_VLLM_PROFILE:-qwen3-32b-gpu2-u050}}"
  requested_env_file="${STATEBUS_VLLM_ENV_FILE:-}"
  requested_embedding_gpu="${STATEBUS_G6B2_EMBEDDING_PHYSICAL_GPU:-${STATEBUS_EMBED_PHYSICAL_GPU:-1}}"

  if [[ ! -f "${script_dir}/activate_statebus_host.sh" ]]; then
    echo "[statebus-local-vllm] 缺少宿主机环境脚本：${script_dir}/activate_statebus_host.sh" >&2
    return 1
  fi

  # shellcheck disable=SC1090
  source "${script_dir}/activate_statebus_host.sh"

  # A profile activation is a configuration boundary.  Do not let a prior
  # sourced profile leak model, GPU, context, or service settings into the
  # next one.  A caller-supplied custom env file is preserved below; the two
  # tracked profile files are always selected from the requested profile.
  unset \
    STATEBUS_VLLM_ENV_FILE STATEBUS_VLLM_MODEL_PATH STATEBUS_VLLM_TOKENIZER_PATH \
    STATEBUS_VLLM_SERVED_MODEL_NAME STATEBUS_VLLM_HOST STATEBUS_VLLM_PORT \
    STATEBUS_VLLM_CUDA_VISIBLE_DEVICES STATEBUS_VLLM_MAX_MODEL_LEN \
    STATEBUS_VLLM_MAX_NUM_SEQS STATEBUS_VLLM_MAX_NUM_BATCHED_TOKENS \
    STATEBUS_VLLM_GPU_MEMORY_UTILIZATION STATEBUS_VLLM_TENSOR_PARALLEL_SIZE \
    STATEBUS_VLLM_DTYPE STATEBUS_VLLM_ENABLE_PREFIX_CACHING \
    STATEBUS_VLLM_ENFORCE_EAGER STATEBUS_VLLM_MAX_LOGPROBS \
    STATEBUS_VLLM_RUNTIME_DIR STATEBUS_VLLM_SERVICE_MODE STATEBUS_VLLM_START_WAIT_S \
    STATEBUS_VLLM_ENV_PREFIX STATEBUS_LOCAL_VLLM_MODEL STATEBUS_LOCAL_VLLM_PORT \
    STATEBUS_LOCAL_VLLM_BASE_URL STATEBUS_LOCAL_VLLM_HEALTH_URL \
    STATEBUS_LOCAL_VLLM_PROFILE STATEBUS_G6B2_PROFILE_ID \
    STATEBUS_G6B2_SERVICE_PHYSICAL_GPU STATEBUS_LLM_CONFIG_FILE \
    STATEBUS_CONTAINER_LLM_CONFIG_FILE STATEBUS_HOST_LLM_CONFIG_FILE \
    STATEBUS_G6B2_EMBEDDING_MODE STATEBUS_G6B2_EMBEDDING_MODEL_PATH \
    STATEBUS_G6B2_EMBEDDING_DEVICE STATEBUS_G6B2_EMBEDDING_PHYSICAL_GPU \
    STATEBUS_EMBED_PHYSICAL_GPU STATEBUS_EMBED_MODEL_PATH STATEBUS_EMBED_DEVICE \
    2>/dev/null || true

  case "$profile" in
    qwen3-8b-gpu0-u050|qwen3-8b|8b)
      profile="qwen3-8b-gpu0-u050"
      default_model_path="/data/models/Qwen3-8B"
      default_served_model="qwen3-8b"
      default_gpu="0"
      default_context="4096"
      default_batched_tokens="4096"
      default_utilization="0.50"
      vllm_env_file="${script_dir}/vllm.env.gpu0-8b-u050"
      ;;
    qwen3-32b-gpu2-u050|qwen3-32b|32b)
      profile="qwen3-32b-gpu2-u050"
      default_model_path="/data/models/Qwen3-32B"
      default_served_model="qwen3-32b"
      default_gpu="2"
      default_context="8192"
      default_batched_tokens="8192"
      default_utilization="0.82"
      vllm_env_file="${script_dir}/vllm.env.gpu2-32b-u050"
      ;;
    *)
      echo "[statebus-local-vllm] 不支持的 profile：$profile" >&2
      echo "[statebus-local-vllm] 当前支持：qwen3-8b-gpu0-u050, qwen3-32b-gpu2-u050" >&2
      return 1
      ;;
  esac

  # Do not accidentally reuse a tracked profile file from an earlier source;
  # only a genuinely custom path is honored as an explicit override.
  case "$requested_env_file" in
    ""|"${script_dir}/vllm.env.gpu0-8b-u050"|"${script_dir}/vllm.env.gpu2-32b-u050")
      ;;
    *)
      vllm_env_file="$requested_env_file"
      ;;
  esac
  if [[ ! -r "$vllm_env_file" ]]; then
    echo "[statebus-local-vllm] vLLM env file 不存在或不可读：$vllm_env_file" >&2
    return 1
  fi
  # shellcheck disable=SC1090
  source "$vllm_env_file"

  require_value() {
    local name="$1" expected="$2" actual
    actual="${!name:-}"
    if [[ "$actual" != "$expected" ]]; then
      echo "[statebus-local-vllm] profile=$profile 配置不一致：${name}=${actual:-<unset>}，期望=${expected}" >&2
      return 1
    fi
  }

  require_value STATEBUS_VLLM_MODEL_PATH "$default_model_path"
  require_value STATEBUS_VLLM_SERVED_MODEL_NAME "$default_served_model"
  require_value STATEBUS_VLLM_HOST "127.0.0.1"
  require_value STATEBUS_VLLM_PORT "53334"
  require_value STATEBUS_VLLM_CUDA_VISIBLE_DEVICES "$default_gpu"
  require_value STATEBUS_VLLM_MAX_MODEL_LEN "$default_context"
  require_value STATEBUS_VLLM_MAX_NUM_SEQS "1"
  require_value STATEBUS_VLLM_MAX_NUM_BATCHED_TOKENS "$default_batched_tokens"
  require_value STATEBUS_VLLM_GPU_MEMORY_UTILIZATION "$default_utilization"
  require_value STATEBUS_VLLM_TENSOR_PARALLEL_SIZE "1"

  export STATEBUS_VLLM_ENV_FILE="$vllm_env_file"

  export STATEBUS_LOCAL_VLLM_PROFILE="$profile"
  export STATEBUS_VLLM_MODEL_PATH="$default_model_path"
  export STATEBUS_VLLM_TOKENIZER_PATH="$default_model_path"
  export STATEBUS_VLLM_SERVED_MODEL_NAME="$default_served_model"
  export STATEBUS_LOCAL_VLLM_MODEL="$STATEBUS_VLLM_SERVED_MODEL_NAME"
  export STATEBUS_VLLM_HOST="127.0.0.1"
  export STATEBUS_VLLM_PORT="53334"
  export STATEBUS_LOCAL_VLLM_PORT="$STATEBUS_VLLM_PORT"
  export STATEBUS_LOCAL_VLLM_BASE_URL="http://127.0.0.1:${STATEBUS_VLLM_PORT}/v1"
  export STATEBUS_LOCAL_VLLM_HEALTH_URL="http://127.0.0.1:${STATEBUS_VLLM_PORT}/health"
  export STATEBUS_VLLM_CUDA_VISIBLE_DEVICES="$default_gpu"
  export STATEBUS_VLLM_MAX_MODEL_LEN="$default_context"
  export STATEBUS_VLLM_GPU_MEMORY_UTILIZATION="$default_utilization"
  export STATEBUS_VLLM_MAX_NUM_SEQS="1"
  export STATEBUS_VLLM_MAX_NUM_BATCHED_TOKENS="$default_batched_tokens"
  export STATEBUS_VLLM_TENSOR_PARALLEL_SIZE="1"
  if [[ "$profile" == "qwen3-8b-gpu0-u050" ]]; then
    export STATEBUS_G6B2_PROFILE_ID="g6b2-live-qwen3-8b-gpu0-u050-qwen3-embedding-gpu1-v1"
    export STATEBUS_G6B2_SERVICE_PHYSICAL_GPU="0"
    export STATEBUS_CONTAINER_LLM_CONFIG_FILE="/workspace/statebus/os/deploy/statebus_llm.g6b2-qwen3-8b.example"
    export STATEBUS_LLM_CONFIG_FILE="${script_dir}/statebus_llm.g6b2-qwen3-8b.example"
  else
    export STATEBUS_G6B2_PROFILE_ID="g6b2-live-qwen3-32b-gpu2-u050-qwen3-embedding-gpu1-v1"
    export STATEBUS_G6B2_SERVICE_PHYSICAL_GPU="2"
    export STATEBUS_CONTAINER_LLM_CONFIG_FILE="/workspace/statebus/os/deploy/statebus_llm.g6b2-qwen3-32b.example"
    export STATEBUS_LLM_CONFIG_FILE="${script_dir}/statebus_llm.g6b2-qwen3-32b.example"
  fi
  export STATEBUS_LOCAL_VLLM_MODEL="$STATEBUS_VLLM_SERVED_MODEL_NAME"
  export STATEBUS_CONTAINER_NAME="${STATEBUS_CONTAINER_NAME:-statebus-runtime}"
  export STATEBUS_B2_CONTAINER_NAME="$STATEBUS_CONTAINER_NAME"
  export STATEBUS_B2_HOME_HOST="${STATEBUS_B2_HOME_HOST:-${HOME}/statebus/work/${STATEBUS_CONTAINER_NAME}-container}"
  export STATEBUS_G6B2_EMBEDDING_MODE="local"
  export STATEBUS_G6B2_EMBEDDING_PHYSICAL_GPU="$requested_embedding_gpu"
  [[ "$STATEBUS_G6B2_EMBEDDING_PHYSICAL_GPU" =~ ^[0-9]+$ ]] || {
    echo "[statebus-local-vllm] embedding GPU 必须是物理 GPU 编号：$STATEBUS_G6B2_EMBEDDING_PHYSICAL_GPU" >&2
    return 1
  }
  [[ "$STATEBUS_G6B2_EMBEDDING_PHYSICAL_GPU" != "$default_gpu" ]] || {
    echo "[statebus-local-vllm] embedding GPU 不能与 vLLM 服务 GPU 相同：$default_gpu" >&2
    return 1
  }
  export STATEBUS_G6B2_EMBEDDING_DEVICE="cuda:0"
  export STATEBUS_EMBED_PHYSICAL_GPU="$STATEBUS_G6B2_EMBEDDING_PHYSICAL_GPU"
  export STATEBUS_EMBED_DEVICE="cuda:0"
  export STATEBUS_EMBED_MODEL_PATH="/statebus/models/Qwen3-Embedding-0.6B"

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
