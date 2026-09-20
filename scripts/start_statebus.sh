#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
OS_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

PROFILE="${STATEBUS_PROFILE:-qwen3-32b-gpu2-u050}"
CONTAINER_NAME="${STATEBUS_CONTAINER_NAME:-statebus-runtime}"
EMBED_PHYSICAL_GPU="${STATEBUS_EMBED_PHYSICAL_GPU:-1}"

usage() {
  cat <<'EOF'
Usage:
  scripts/start_statebus.sh --list-profiles
  scripts/start_statebus.sh [profile] [--container-name NAME] [--embedding-gpu INDEX]
  scripts/start_statebus.sh [profile] --print-config

Profiles:
  qwen3-8b-gpu0-u050   /data/models/Qwen3-8B, served qwen3-8b, physical GPU0,
                       context 4096, GPU memory utilization 0.50.
  qwen3-32b-gpu2-u050  /data/models/Qwen3-32B, served qwen3-32b, physical GPU2,
                       context 8192, GPU memory utilization 0.82.

Common embedding configuration:
  Qwen3-Embedding-0.6B on physical GPU1 by default; inside the container it is
  always logical cuda:0. Override with --embedding-gpu INDEX when necessary.

The selected vLLM model, API address, GPU, context, embedding device, and
container name are printed before startup. A healthy matching vLLM service is
reused; it is never stopped or restarted by this command.
EOF
}

list_profiles() {
  printf '%s\n' \
    'qwen3-8b-gpu0-u050  model=/data/models/Qwen3-8B served=qwen3-8b gpu=0 context=4096 util=0.50' \
    'qwen3-32b-gpu2-u050 model=/data/models/Qwen3-32B served=qwen3-32b gpu=2 context=8192 util=0.82'
}

load_profile() {
  case "$PROFILE" in
    qwen3-8b-gpu0-u050|qwen3-8b|8b)
      PROFILE="qwen3-8b-gpu0-u050"
      ENV_FILE="$OS_ROOT/deploy/vllm.env.gpu0-8b-u050"
      LLM_CONFIG="/workspace/statebus/os/deploy/statebus_llm.g6b2-qwen3-8b.example"
      MODEL="qwen3-8b"
      MODEL_PATH="/data/models/Qwen3-8B"
      SERVICE_GPU="0"
      CONTEXT="4096"
      UTILIZATION="0.50"
      PROFILE_ID_BASE="g6b2-live-qwen3-8b-gpu0-u050"
      ;;
    qwen3-32b-gpu2-u050|qwen3-32b|32b)
      PROFILE="qwen3-32b-gpu2-u050"
      ENV_FILE="$OS_ROOT/deploy/vllm.env.gpu2-32b-u050"
      LLM_CONFIG="/workspace/statebus/os/deploy/statebus_llm.g6b2-qwen3-32b.example"
      MODEL="qwen3-32b"
      MODEL_PATH="/data/models/Qwen3-32B"
      SERVICE_GPU="2"
      CONTEXT="8192"
      UTILIZATION="0.82"
      PROFILE_ID_BASE="g6b2-live-qwen3-32b-gpu2-u050"
      ;;
    *)
      printf '不支持的 profile：%s\n' "$PROFILE" >&2
      list_profiles >&2
      exit 2
      ;;
  esac
  [[ -r "$ENV_FILE" ]] || {
    printf 'profile env file 不存在或不可读：%s\n' "$ENV_FILE" >&2
    exit 2
  }
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  require_profile_value() {
    local name="$1" expected="$2" actual
    actual="${!name:-}"
    [[ "$actual" == "$expected" ]] || {
      printf 'profile=%s 配置不一致：%s=%s，期望=%s\n' "$PROFILE" "$name" "${actual:-<unset>}" "$expected" >&2
      exit 2
    }
  }
  require_profile_value STATEBUS_VLLM_MODEL_PATH "$MODEL_PATH"
  require_profile_value STATEBUS_VLLM_SERVED_MODEL_NAME "$MODEL"
  require_profile_value STATEBUS_VLLM_HOST "127.0.0.1"
  require_profile_value STATEBUS_VLLM_PORT "53334"
  require_profile_value STATEBUS_VLLM_CUDA_VISIBLE_DEVICES "$SERVICE_GPU"
  require_profile_value STATEBUS_VLLM_MAX_MODEL_LEN "$CONTEXT"
  require_profile_value STATEBUS_VLLM_MAX_NUM_SEQS "1"
  require_profile_value STATEBUS_VLLM_MAX_NUM_BATCHED_TOKENS "$CONTEXT"
  require_profile_value STATEBUS_VLLM_GPU_MEMORY_UTILIZATION "$UTILIZATION"
  require_profile_value STATEBUS_VLLM_TENSOR_PARALLEL_SIZE "1"
  BASE_URL="http://127.0.0.1:53334/v1"
  HEALTH_URL="http://127.0.0.1:53334/health"
  EMBED_MODEL_PATH="/statebus/models/Qwen3-Embedding-0.6B"
  HOST_LLM_CONFIG_FILE="$OS_ROOT/deploy/$(basename "$LLM_CONFIG")"
}

[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && { usage; exit 0; }
if [[ "${1:-}" == "--list-profiles" ]]; then
  list_profiles
  exit 0
fi
if [[ $# -gt 0 && "${1:0:2}" != "--" ]]; then
  PROFILE="$1"
  shift
fi

PRINT_CONFIG=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --container-name) CONTAINER_NAME="${2:?missing value}"; shift 2 ;;
    --embedding-gpu) EMBED_PHYSICAL_GPU="${2:?missing value}"; shift 2 ;;
    --print-config) PRINT_CONFIG=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf '未知参数：%s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done
[[ "$EMBED_PHYSICAL_GPU" =~ ^[0-9]+$ ]] || {
  printf 'embedding GPU 必须是物理 GPU 编号：%s\n' "$EMBED_PHYSICAL_GPU" >&2
  exit 2
}

load_profile
if [[ "$EMBED_PHYSICAL_GPU" == "$SERVICE_GPU" ]]; then
  printf 'Embedding GPU 不能与 vLLM 服务 GPU 相同：gpu=%s\n' "$SERVICE_GPU" >&2
  exit 2
fi
PROFILE_ID="${PROFILE_ID_BASE}-qwen3-embedding-gpu${EMBED_PHYSICAL_GPU}-v1"

export STATEBUS_VLLM_ENV_FILE="$ENV_FILE"
export STATEBUS_CONTAINER_NAME="$CONTAINER_NAME"
export STATEBUS_B2_CONTAINER_NAME="$CONTAINER_NAME"
export STATEBUS_B2_HOME_HOST="${HOME}/statebus/work/${CONTAINER_NAME}-container"
export STATEBUS_LOCAL_VLLM_MODEL="$MODEL"
export STATEBUS_LOCAL_VLLM_BASE_URL="$BASE_URL"
export STATEBUS_LOCAL_VLLM_HEALTH_URL="$HEALTH_URL"
export STATEBUS_LLM_CONFIG_FILE="$HOST_LLM_CONFIG_FILE"
export STATEBUS_CONTAINER_LLM_CONFIG_FILE="$LLM_CONFIG"
export STATEBUS_HOST_LLM_CONFIG_FILE="$HOST_LLM_CONFIG_FILE"
export STATEBUS_VLLM_MODEL_PATH="$MODEL_PATH"
export STATEBUS_VLLM_TOKENIZER_PATH="$MODEL_PATH"
export STATEBUS_VLLM_SERVED_MODEL_NAME="$MODEL"
export STATEBUS_VLLM_HOST="127.0.0.1"
export STATEBUS_VLLM_PORT="53334"
export STATEBUS_VLLM_CUDA_VISIBLE_DEVICES="$SERVICE_GPU"
export STATEBUS_VLLM_MAX_MODEL_LEN="$CONTEXT"
export STATEBUS_VLLM_MAX_NUM_SEQS="1"
export STATEBUS_VLLM_MAX_NUM_BATCHED_TOKENS="$CONTEXT"
export STATEBUS_VLLM_GPU_MEMORY_UTILIZATION="$UTILIZATION"
export STATEBUS_VLLM_TENSOR_PARALLEL_SIZE="1"
export STATEBUS_VLLM_PROFILE="$PROFILE"
export STATEBUS_G6B2_PROFILE_ID="$PROFILE_ID"
export STATEBUS_G6B2_SERVICE_PHYSICAL_GPU="$SERVICE_GPU"
export STATEBUS_G6B2_EMBEDDING_MODE="local"
export STATEBUS_G6B2_EMBEDDING_MODEL_PATH="$EMBED_MODEL_PATH"
export STATEBUS_G6B2_EMBEDDING_DEVICE="cuda:0"
export STATEBUS_G6B2_EMBEDDING_PHYSICAL_GPU="$EMBED_PHYSICAL_GPU"
export STATEBUS_EMBED_PHYSICAL_GPU="$EMBED_PHYSICAL_GPU"
export STATEBUS_EMBED_MODEL_PATH="$EMBED_MODEL_PATH"
export STATEBUS_EMBED_DEVICE="cuda:0"

print_config() {
  printf '[statebus] profile=%s\n' "$PROFILE"
  printf '[statebus] model_path=%s\n' "$MODEL_PATH"
  printf '[statebus] served_model=%s\n' "$MODEL"
  printf '[statebus] vllm_url=%s\n' "$BASE_URL"
  printf '[statebus] service_physical_gpu=%s\n' "$SERVICE_GPU"
  printf '[statebus] max_model_len=%s\n' "$CONTEXT"
  printf '[statebus] max_num_seqs=1\n'
  printf '[statebus] max_num_batched_tokens=%s\n' "$CONTEXT"
  printf '[statebus] gpu_memory_utilization=%s\n' "$UTILIZATION"
  printf '[statebus] embedding_model=%s\n' "$EMBED_MODEL_PATH"
  printf '[statebus] embedding_physical_gpu=%s\n' "$EMBED_PHYSICAL_GPU"
  printf '[statebus] embedding_container_device=cuda:0\n'
  printf '[statebus] container_name=%s\n' "$CONTAINER_NAME"
  printf '[statebus] host_config_path=%s\n' "$HOST_LLM_CONFIG_FILE"
  printf '[statebus] container_config_path=%s\n' "$LLM_CONFIG"
  printf '[statebus] container_env=%s\n' "$HOME/statebus/conda-envs/statebus_host"
}

print_config
(( PRINT_CONFIG == 1 )) && exit 0

[[ -r "$MODEL_PATH/config.json" ]] || {
  printf 'model config 不可读：%s/config.json\n' "$MODEL_PATH" >&2
  exit 2
}

if curl --noproxy '*' --fail --silent --show-error --max-time 5 "$HEALTH_URL" >/dev/null; then
  if ! command -v jq >/dev/null 2>&1; then
    printf '[statebus] 缺少 jq，无法结构化校验 /v1/models。\n' >&2
    exit 2
  fi
  model_payload="$(curl --noproxy '*' --fail --silent --show-error --max-time 5 "$BASE_URL/models")"
  if jq -e --arg expected "$MODEL" '.data | type == "array" and length == 1 and .[0].id == $expected' <<<"$model_payload" >/dev/null; then
    printf '[statebus] vLLM 已健康运行，复用 %s\n' "$MODEL"
  else
    printf '[statebus] 端口 53334 已有其他模型服务或模型列表格式不符，目标模型=%s；不会自动停止现有服务。\n' "$MODEL" >&2
    exit 3
  fi
else
  printf '[statebus] 启动 vLLM profile=%s\n' "$PROFILE"
  STATEBUS_VLLM_ENV_FILE="$ENV_FILE" STATEBUS_VLLM_PROFILE="$PROFILE" \
    "$OS_ROOT/scripts/vllm/manage_qwen3_32b.sh" start
fi

"$OS_ROOT/scripts/run_g6b2_os_container.sh" up
"$OS_ROOT/scripts/run_g6b2_os_container.sh" verify
"$OS_ROOT/scripts/run_g6b2_os_container.sh" smoke
