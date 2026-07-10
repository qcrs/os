#!/usr/bin/env bash
set -euo pipefail

MODEL_PATH="${STATEBUS_VLLM_MODEL_PATH:-/data/models/Qwen3-32B}"
SERVED_MODEL_NAME="${STATEBUS_VLLM_SERVED_MODEL_NAME:-qwen3-32b}"
HOST="${STATEBUS_VLLM_HOST:-127.0.0.1}"
PORT="${STATEBUS_VLLM_PORT:-53334}"
MAX_MODEL_LEN="${STATEBUS_VLLM_MAX_MODEL_LEN:-8192}"
GPU_MEMORY_UTILIZATION="${STATEBUS_VLLM_GPU_MEMORY_UTILIZATION:-0.95}"
MAX_NUM_SEQS="${STATEBUS_VLLM_MAX_NUM_SEQS:-1}"
MAX_NUM_BATCHED_TOKENS="${STATEBUS_VLLM_MAX_NUM_BATCHED_TOKENS:-$MAX_MODEL_LEN}"
DTYPE="${STATEBUS_VLLM_DTYPE:-bfloat16}"
ENFORCE_EAGER="${STATEBUS_VLLM_ENFORCE_EAGER:-1}"
KV_CACHE_DTYPE="${STATEBUS_VLLM_KV_CACHE_DTYPE:-}"
TENSOR_PARALLEL_SIZE="${STATEBUS_VLLM_TENSOR_PARALLEL_SIZE:-1}"
VLLM_ENV_PREFIX="${STATEBUS_VLLM_ENV_PREFIX:-/home/qcrs/statebus/conda-envs/vllm-qwen-cu121}"
DEFAULT_CUDA_VISIBLE_DEVICES="${STATEBUS_VLLM_CUDA_VISIBLE_DEVICES:-2}"
export VLLM_USE_V1="${VLLM_USE_V1:-0}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-$DEFAULT_CUDA_VISIBLE_DEVICES}"

if [[ "${CONDA_PREFIX:-}" != "$VLLM_ENV_PREFIX" && -d "$VLLM_ENV_PREFIX" ]]; then
  if [[ -n "${CONDA_EXE:-}" ]]; then
    CONDA_BASE="$("$CONDA_EXE" info --base)"
  elif command -v conda >/dev/null 2>&1; then
    CONDA_BASE="$(conda info --base)"
  elif [[ -x "/opt/miniconda/bin/conda" ]]; then
    CONDA_BASE="$(/opt/miniconda/bin/conda info --base)"
  else
    CONDA_BASE=""
  fi
  if [[ -n "$CONDA_BASE" ]]; then
    # shellcheck disable=SC1090
    source "$CONDA_BASE/etc/profile.d/conda.sh"
    conda activate "$VLLM_ENV_PREFIX"
  fi
fi

args=(
  vllm serve "$MODEL_PATH"
  --served-model-name "$SERVED_MODEL_NAME" \
  --host "$HOST" \
  --port "$PORT" \
  --dtype "$DTYPE" \
  --max-model-len "$MAX_MODEL_LEN" \
  --max-num-seqs "$MAX_NUM_SEQS" \
  --max-num-batched-tokens "$MAX_NUM_BATCHED_TOKENS" \
  --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION" \
  --tensor-parallel-size "$TENSOR_PARALLEL_SIZE" \
  --enable-prefix-caching
)

if [[ "$ENFORCE_EAGER" == "1" || "$ENFORCE_EAGER" == "true" ]]; then
  args+=(--enforce-eager)
fi

if [[ -n "$KV_CACHE_DTYPE" ]]; then
  args+=(--kv-cache-dtype "$KV_CACHE_DTYPE")
fi

echo "[statebus-vllm] model_path=$MODEL_PATH"
echo "[statebus-vllm] served_model_name=$SERVED_MODEL_NAME"
echo "[statebus-vllm] endpoint=http://$HOST:$PORT/v1"
echo "[statebus-vllm] cuda_visible_devices=$CUDA_VISIBLE_DEVICES"
echo "[statebus-vllm] tensor_parallel_size=$TENSOR_PARALLEL_SIZE"
echo "[statebus-vllm] max_model_len=$MAX_MODEL_LEN"
echo "[statebus-vllm] gpu_memory_utilization=$GPU_MEMORY_UTILIZATION"

exec "${args[@]}"
