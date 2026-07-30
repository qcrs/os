#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
VLLM_ENV_FILE="${STATEBUS_VLLM_ENV_FILE:-${PROJECT_ROOT}/deploy/vllm.env.local}"

if [[ -f "$VLLM_ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$VLLM_ENV_FILE"
fi

MODEL_PATH="${STATEBUS_VLLM_MODEL_PATH:-/data/models/Qwen3-32B}"
SERVED_MODEL="${STATEBUS_VLLM_SERVED_MODEL_NAME:-qwen3-32b}"
HOST="${STATEBUS_VLLM_HOST:-127.0.0.1}"
PORT="${STATEBUS_VLLM_PORT:-53334}"
VLLM_ENV_PREFIX="${STATEBUS_VLLM_ENV_PREFIX:-${HOME}/statebus/conda-envs/vllm-qwen-cu121}"
VLLM_BIN="${STATEBUS_VLLM_BIN:-${VLLM_ENV_PREFIX}/bin/vllm}"
GPU_INDEX="${STATEBUS_VLLM_CUDA_VISIBLE_DEVICES:-1}"
MAX_MODEL_LEN="${STATEBUS_VLLM_MAX_MODEL_LEN:-8192}"
MAX_NUM_SEQS="${STATEBUS_VLLM_MAX_NUM_SEQS:-1}"
MAX_NUM_BATCHED_TOKENS="${STATEBUS_VLLM_MAX_NUM_BATCHED_TOKENS:-$MAX_MODEL_LEN}"
GPU_MEMORY_UTILIZATION="${STATEBUS_VLLM_GPU_MEMORY_UTILIZATION:-0.82}"
MAX_LOGPROBS="${STATEBUS_VLLM_MAX_LOGPROBS:-20}"
TENSOR_PARALLEL_SIZE="${STATEBUS_VLLM_TENSOR_PARALLEL_SIZE:-1}"
DTYPE="${STATEBUS_VLLM_DTYPE:-bfloat16}"
ENABLE_PREFIX_CACHING="${STATEBUS_VLLM_ENABLE_PREFIX_CACHING:-1}"
ENFORCE_EAGER="${STATEBUS_VLLM_ENFORCE_EAGER:-1}"
KV_CACHE_DTYPE="${STATEBUS_VLLM_KV_CACHE_DTYPE:-}"
CPU_OFFLOAD_GB="${STATEBUS_VLLM_CPU_OFFLOAD_GB:-}"

if [[ ! -x "$VLLM_BIN" ]]; then
  printf '找不到 vLLM 可执行文件：%s\n' "$VLLM_BIN" >&2
  exit 2
fi
if [[ ! -r "$MODEL_PATH/config.json" ]]; then
  printf 'Qwen3-32B 模型目录不可读：%s\n' "$MODEL_PATH" >&2
  exit 2
fi
if [[ "$GPU_INDEX" == *","* ]]; then
  printf '该启动脚本只支持一张物理 GPU，当前配置为：%s\n' "$GPU_INDEX" >&2
  exit 2
fi

export CUDA_VISIBLE_DEVICES="$GPU_INDEX"
export VLLM_USE_V1="${VLLM_USE_V1:-1}"
export VLLM_NO_USAGE_STATS="${VLLM_NO_USAGE_STATS:-1}"
export PYTHONPATH="${PROJECT_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

args=(
  "$VLLM_BIN" serve "$MODEL_PATH"
  --host "$HOST"
  --port "$PORT"
  --served-model-name "$SERVED_MODEL"
  --dtype "$DTYPE"
  --tensor-parallel-size "$TENSOR_PARALLEL_SIZE"
  --max-model-len "$MAX_MODEL_LEN"
  --max-num-seqs "$MAX_NUM_SEQS"
  --max-num-batched-tokens "$MAX_NUM_BATCHED_TOKENS"
  --max-logprobs "$MAX_LOGPROBS"
  --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION"
  --generation-config vllm
  --enable-request-id-headers
  --disable-log-requests
)

if [[ "$ENABLE_PREFIX_CACHING" =~ ^(1|true|yes|on)$ ]]; then
  args+=(--enable-prefix-caching)
else
  args+=(--no-enable-prefix-caching)
fi
if [[ "$ENFORCE_EAGER" =~ ^(1|true|yes|on)$ ]]; then
  args+=(--enforce-eager)
fi
if [[ -n "$KV_CACHE_DTYPE" ]]; then
  args+=(--kv-cache-dtype "$KV_CACHE_DTYPE")
fi
if [[ -n "$CPU_OFFLOAD_GB" ]]; then
  args+=(--cpu-offload-gb "$CPU_OFFLOAD_GB")
fi

printf '[statebus-vllm] 模式=standard\n'
printf '[statebus-vllm] 物理GPU=%s\n' "$CUDA_VISIBLE_DEVICES"
printf '[statebus-vllm] 模型=%s\n' "$MODEL_PATH"
printf '[statebus-vllm] API地址=http://%s:%s/v1\n' "$HOST" "$PORT"
printf '[statebus-vllm] AutomaticPrefixCaching=%s\n' "$ENABLE_PREFIX_CACHING"

exec "${args[@]}"
