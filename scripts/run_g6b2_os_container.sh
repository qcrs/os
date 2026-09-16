#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$OS_ROOT/docker/compose.g6b2-os.yaml"
PROJECT_NAME="${STATEBUS_B2_COMPOSE_PROJECT:-statebus-g6b2-os}"
CONTAINER_NAME="${STATEBUS_B2_CONTAINER_NAME:-statebus-b2-qwen3-8b}"
B2_HOME_HOST="${STATEBUS_B2_HOME_HOST:-$HOME/statebus/work/g6b2-qwen3-8b-container}"
CONTAINER_ROOT="/workspace/statebus/os"
COMPOSE_ENV_FILE="$B2_HOME_HOST/compose.env"

compose() {
  docker compose --env-file "$COMPOSE_ENV_FILE" -p "$PROJECT_NAME" -f "$COMPOSE_FILE" "$@"
}

prepare_dirs() {
  mkdir -p "$B2_HOME_HOST"/{home,models,caches,logs,runs,work,workspaces,statepool}
  cat > "$COMPOSE_ENV_FILE" <<EOF
STATEBUS_OS_CHECKOUT=${STATEBUS_OS_CHECKOUT:-$OS_ROOT}
STATEBUS_B2_HOME_HOST=$B2_HOME_HOST
STATEBUS_B2_CONTAINER_NAME=$CONTAINER_NAME
STATEBUS_UID=$(id -u)
STATEBUS_GID=$(id -g)
STATEBUS_VLLM_MODELS_ROOT=${STATEBUS_VLLM_MODELS_ROOT:-/data/models}
STATEBUS_VLLM_MODEL_PATH=/data/models/Qwen3-8B
STATEBUS_VLLM_TOKENIZER_PATH=/data/models/Qwen3-8B
STATEBUS_LOCAL_VLLM_BASE_URL=${STATEBUS_LOCAL_VLLM_BASE_URL:-http://127.0.0.1:53334/v1}
STATEBUS_LOCAL_VLLM_HEALTH_URL=${STATEBUS_LOCAL_VLLM_HEALTH_URL:-http://127.0.0.1:53334/health}
STATEBUS_VLLM_METRICS_URL=${STATEBUS_VLLM_METRICS_URL:-http://127.0.0.1:53334/metrics}
EOF
}

container_exec() {
  docker exec -i \
    -e PROJECT_ROOT="$CONTAINER_ROOT" \
    -e PYTHONPATH="$CONTAINER_ROOT" \
    -e STATEBUS_LLM_CONFIG_FILE="$CONTAINER_ROOT/deploy/statebus_llm.g6b2-qwen3-8b.example" \
    -e STATEBUS_LOCAL_VLLM_BASE_URL="${STATEBUS_LOCAL_VLLM_BASE_URL:-http://127.0.0.1:53334/v1}" \
    -e STATEBUS_LOCAL_VLLM_HEALTH_URL="${STATEBUS_LOCAL_VLLM_HEALTH_URL:-http://127.0.0.1:53334/health}" \
    -e STATEBUS_LOCAL_VLLM_MODEL="${STATEBUS_LOCAL_VLLM_MODEL:-qwen3-8b}" \
    -e STATEBUS_G6B2_PROFILE_ID="${STATEBUS_G6B2_PROFILE_ID:-g6b2-live-qwen3-8b-gpu0-u050-v1}" \
    -e STATEBUS_G6B2_EMBEDDING_MODE="${STATEBUS_G6B2_EMBEDDING_MODE:-deterministic}" \
    -e STATEBUS_G6B2_EMBEDDING_MODEL_PATH="${STATEBUS_G6B2_EMBEDDING_MODEL_PATH:-/statebus/models/Qwen3-Embedding-0.6B}" \
    -e STATEBUS_G6B2_EMBEDDING_DEVICE="${STATEBUS_G6B2_EMBEDDING_DEVICE:-cuda:0}" \
    -e STATEBUS_EMBED_MODEL_PATH="${STATEBUS_EMBED_MODEL_PATH:-/statebus/models/Qwen3-Embedding-0.6B}" \
    -e STATEBUS_EMBED_DEVICE="${STATEBUS_EMBED_DEVICE:-cuda:0}" \
    "$CONTAINER_NAME" bash -lc '
      set -euo pipefail
      source "$PROJECT_ROOT/docker/activate_statebus_container.sh"
      cd "$PROJECT_ROOT"
      exec "$@"
    ' -- "$@"
}

verify_mount() {
  local mounted_root
  mounted_root="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/workspace/statebus/os"}}{{.Source}}{{end}}{{end}}' "$CONTAINER_NAME")"
  [[ "$mounted_root" == "${STATEBUS_OS_CHECKOUT:-$OS_ROOT}" ]] || {
    printf 'B2 container mount mismatch: expected %s, got %s\n' "${STATEBUS_OS_CHECKOUT:-$OS_ROOT}" "$mounted_root" >&2
    return 1
  }
  docker exec "$CONTAINER_NAME" test -f "$CONTAINER_ROOT/statebus/benchmark/g6b2_live_validation.py"
  docker exec "$CONTAINER_NAME" test -f "$CONTAINER_ROOT/deploy/statebus_llm.g6b2-qwen3-8b.example"
}

usage() {
  cat <<'EOF'
Usage: scripts/run_g6b2_os_container.sh <config|up|down|inspect|verify|exec|smoke> [command ...]

The container mounts the current os checkout at /workspace/statebus/os and uses
host networking to reach host vLLM at http://127.0.0.1:53334/v1. It exposes
physical GPU 1 to the container for embedding (logical cuda:0) and never
recreates statebus-dev-qcrs.
EOF
}

action="${1:-}"
case "$action" in
  config)
    prepare_dirs
    compose config
    ;;
  up)
    prepare_dirs
    if docker inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
      verify_mount
      compose up -d --no-build --no-recreate
    else
      compose up -d --no-build --no-recreate
      verify_mount
    fi
    verify_mount
    ;;
  down)
    prepare_dirs
    compose down
    ;;
  inspect)
    docker inspect "$CONTAINER_NAME" --format '{{.Name}} {{.Config.Image}} {{.HostConfig.NetworkMode}} {{json .Mounts}}'
    ;;
  verify)
    verify_mount
    printf 'B2 os checkout mount verified: %s\n' "$OS_ROOT"
    ;;
  exec)
    shift
    [[ $# -gt 0 ]] || { usage >&2; exit 2; }
    verify_mount
    container_exec "$@"
    ;;
  smoke)
    verify_mount
    docker inspect "$CONTAINER_NAME" --format '{{.Config.User}} {{.HostConfig.NetworkMode}} {{.Config.Image}} {{json .HostConfig.DeviceRequests}}'
    container_exec /usr/bin/python3 -c '
import json, os, urllib.request
from statebus.integrations.llm import LLMConfig
config = LLMConfig.from_runtime().with_mode("local_vllm")
assert config.provider_config("default").base_url.rstrip("/") == os.environ["STATEBUS_LOCAL_VLLM_BASE_URL"].rstrip("/")
assert {config.role_config(role).model for role in ("planner", "retriever", "executor", "summarizer")} == {"qwen3-8b"}
assert os.environ.get("PROJECT_ROOT") == "/workspace/statebus/os"
assert os.environ.get("STATEBUS_EMBED_DEVICE") == "cuda:0"
assert os.environ.get("STATEBUS_STUDIO_EMBED_DEVICE") == "cuda:0"
with urllib.request.urlopen(os.environ["STATEBUS_LOCAL_VLLM_HEALTH_URL"], timeout=10) as response:
    assert 200 <= response.status < 300
with urllib.request.urlopen(os.environ["STATEBUS_LOCAL_VLLM_BASE_URL"].rstrip("/") + "/models", timeout=10) as response:
    payload = json.load(response)
ids = [item.get("id") for item in payload.get("data", [])]
assert ids == ["qwen3-8b"]
print(json.dumps({"checkout": os.getcwd(), "model": "qwen3-8b", "health": "passed", "models": ids}, sort_keys=True))
'
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
