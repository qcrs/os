#!/usr/bin/env bash

_statebus_activate_vllm_allcap_main() {
  local script_dir repo_root statebus_root
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  repo_root="$(cd "$script_dir/.." && pwd)"
  statebus_root="${STATEBUS_HOME:-$HOME/statebus}"

  export STATEBUS_VLLM_CAPABILITY_PROFILE="qwen3-32b-allcap-v0"
  export STATEBUS_VLLM_SERVICE_NAME="statebus-vllm-qwen3-32b-allcap"
  export STATEBUS_VLLM_EXPECTED_VERSION="0.9.2"
  export STATEBUS_VLLM_ENV_PREFIX="${STATEBUS_ALLCAP_VLLM_ENV_PREFIX:-$statebus_root/conda-envs/vllm-qwen-cu121}"
  export STATEBUS_VLLM_MODEL_PATH="${STATEBUS_ALLCAP_VLLM_MODEL_PATH:-/data/models/Qwen3-32B}"
  export STATEBUS_VLLM_SERVED_MODEL_NAME="qwen3-32b"
  export STATEBUS_VLLM_HOST="127.0.0.1"
  export STATEBUS_VLLM_PORT="53334"
  export STATEBUS_VLLM_CUDA_VISIBLE_DEVICES="${STATEBUS_ALLCAP_VLLM_CUDA_VISIBLE_DEVICES:-1}"
  export STATEBUS_VLLM_DTYPE="bfloat16"
  export STATEBUS_VLLM_TENSOR_PARALLEL_SIZE="1"
  export STATEBUS_VLLM_MAX_MODEL_LEN="8192"
  export STATEBUS_VLLM_MAX_NUM_SEQS="1"
  export STATEBUS_VLLM_MAX_NUM_BATCHED_TOKENS="8192"
  export STATEBUS_VLLM_GPU_MEMORY_UTILIZATION="0.82"
  export STATEBUS_VLLM_MAX_LOGPROBS="20"
  export STATEBUS_VLLM_ENABLE_REQUEST_ID_HEADERS="1"
  export STATEBUS_VLLM_EXPORT_PREFIX_COUNTERS="1"
  export VLLM_USE_V1="0"
  export VLLM_NO_USAGE_STATS="1"
  export CUDA_VISIBLE_DEVICES="$STATEBUS_VLLM_CUDA_VISIBLE_DEVICES"

  export STATEBUS_LATENT_API_TOKEN_FILE="${STATEBUS_ALLCAP_LATENT_API_TOKEN_FILE:-$statebus_root/work/latent_api.token}"
  export STATEBUS_LATENT_ALIGNMENT="soft_token_topk_v1"
  export STATEBUS_LATENT_ALIGNMENT_TOP_K="32"
  export STATEBUS_LATENT_ALIGNMENT_TEMPERATURE="1.0"
  export STATEBUS_LATENT_ALIGNMENT_DIAGNOSTICS="true"
  export STATEBUS_LATENT_ONE_SHOT="true"

  export STATEBUS_VLLM_START_SCRIPT="$repo_root/scripts/start_vllm_qwen3_32b_latent.sh"
  export STATEBUS_VLLM_MANAGER_SCRIPT="$repo_root/scripts/manage_vllm_qwen3_32b_allcap.sh"
  export STATEBUS_VLLM_PID_FILE="$statebus_root/work/$STATEBUS_VLLM_SERVICE_NAME.pid"
  export STATEBUS_VLLM_LOG_FILE="$statebus_root/logs/$STATEBUS_VLLM_SERVICE_NAME.log"
  export STATEBUS_LOCAL_VLLM_BASE_URL="http://$STATEBUS_VLLM_HOST:$STATEBUS_VLLM_PORT/v1"
  export STATEBUS_LOCAL_VLLM_HEALTH_URL="http://$STATEBUS_VLLM_HOST:$STATEBUS_VLLM_PORT/health"
  export STATEBUS_VLLM_METRICS_URL="http://$STATEBUS_VLLM_HOST:$STATEBUS_VLLM_PORT/metrics"
}

if _statebus_activate_vllm_allcap_main; then
  _statebus_vllm_allcap_status=0
else
  _statebus_vllm_allcap_status=$?
fi
unset -f _statebus_activate_vllm_allcap_main

return "${_statebus_vllm_allcap_status}" 2>/dev/null || exit "${_statebus_vllm_allcap_status}"
