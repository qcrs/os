#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$OS_ROOT/docker/compose.g6b2-os.yaml"
PROJECT_NAME="${STATEBUS_B2_COMPOSE_PROJECT:-statebus-g6b2-os}"
CONTAINER_NAME="${STATEBUS_CONTAINER_NAME:-${STATEBUS_B2_CONTAINER_NAME:-statebus-runtime}}"
B2_HOME_HOST="${STATEBUS_B2_HOME_HOST:-$HOME/statebus/work/${CONTAINER_NAME}-container}"
WORKSPACE_ROOT_HOST="${STATEBUS_WORKSPACE_ROOT_HOST:-$HOME/statebus}"
WORKSPACE_CONTAINER_ROOT="/workspace/statebus"
CONTAINER_ROOT="/workspace/statebus/os"
COMPOSE_ENV_FILE="$B2_HOME_HOST/compose.env"

container_llm_config_file() {
  printf '%s\n' "${STATEBUS_CONTAINER_LLM_CONFIG_FILE:-$CONTAINER_ROOT/deploy/statebus_llm.g6b2-qwen3-32b.example}"
}

compose() {
  docker compose --env-file "$COMPOSE_ENV_FILE" -p "$PROJECT_NAME" -f "$COMPOSE_FILE" "$@"
}

prepare_dirs() {
  mkdir -p "$B2_HOME_HOST"/{home,models,caches,logs,runs,work,workspaces,statepool}
  cat > "$COMPOSE_ENV_FILE" <<EOF
STATEBUS_OS_CHECKOUT=${STATEBUS_OS_CHECKOUT:-$OS_ROOT}
STATEBUS_WORKSPACE_ROOT_HOST=$WORKSPACE_ROOT_HOST
STATEBUS_B2_HOME_HOST=$B2_HOME_HOST
STATEBUS_B2_CONTAINER_NAME=$CONTAINER_NAME
STATEBUS_CONTAINER_NAME=$CONTAINER_NAME
STATEBUS_UID=$(id -u)
STATEBUS_GID=$(id -g)
STATEBUS_HOST_ENV=${STATEBUS_HOST_ENV:-$HOME/statebus/conda-envs/statebus_host}
STATEBUS_VLLM_MODELS_ROOT=${STATEBUS_VLLM_MODELS_ROOT:-/data/models}
STATEBUS_VLLM_MODEL_PATH=${STATEBUS_VLLM_MODEL_PATH:-/data/models/Qwen3-32B}
STATEBUS_VLLM_TOKENIZER_PATH=${STATEBUS_VLLM_TOKENIZER_PATH:-/data/models/Qwen3-32B}
STATEBUS_LOCAL_VLLM_MODEL=${STATEBUS_LOCAL_VLLM_MODEL:-qwen3-32b}
STATEBUS_VLLM_SERVED_MODEL_NAME=${STATEBUS_VLLM_SERVED_MODEL_NAME:-qwen3-32b}
STATEBUS_VLLM_MAX_MODEL_LEN=${STATEBUS_VLLM_MAX_MODEL_LEN:-8192}
STATEBUS_VLLM_MAX_NUM_SEQS=${STATEBUS_VLLM_MAX_NUM_SEQS:-1}
STATEBUS_VLLM_MAX_NUM_BATCHED_TOKENS=${STATEBUS_VLLM_MAX_NUM_BATCHED_TOKENS:-8192}
STATEBUS_VLLM_GPU_MEMORY_UTILIZATION=${STATEBUS_VLLM_GPU_MEMORY_UTILIZATION:-0.82}
STATEBUS_LLM_CONFIG_FILE=$(container_llm_config_file)
STATEBUS_LOCAL_VLLM_BASE_URL=${STATEBUS_LOCAL_VLLM_BASE_URL:-http://127.0.0.1:53334/v1}
STATEBUS_LOCAL_VLLM_HEALTH_URL=${STATEBUS_LOCAL_VLLM_HEALTH_URL:-http://127.0.0.1:53334/health}
STATEBUS_VLLM_METRICS_URL=${STATEBUS_VLLM_METRICS_URL:-http://127.0.0.1:53334/metrics}
STATEBUS_EMBED_PHYSICAL_GPU=${STATEBUS_EMBED_PHYSICAL_GPU:-1}
STATEBUS_G6B2_PROFILE_ID=${STATEBUS_G6B2_PROFILE_ID:-g6b2-live-qwen3-32b-gpu2-u050-qwen3-embedding-gpu1-v1}
STATEBUS_G6B2_SERVICE_PHYSICAL_GPU=${STATEBUS_G6B2_SERVICE_PHYSICAL_GPU:-2}
STATEBUS_G6B2_EMBEDDING_MODE=${STATEBUS_G6B2_EMBEDDING_MODE:-local}
STATEBUS_G6B2_EMBEDDING_MODEL_PATH=${STATEBUS_G6B2_EMBEDDING_MODEL_PATH:-/statebus/models/Qwen3-Embedding-0.6B}
STATEBUS_G6B2_EMBEDDING_DEVICE=${STATEBUS_G6B2_EMBEDDING_DEVICE:-cuda:0}
STATEBUS_G6B2_EMBEDDING_PHYSICAL_GPU=${STATEBUS_G6B2_EMBEDDING_PHYSICAL_GPU:-${STATEBUS_EMBED_PHYSICAL_GPU:-1}}
STATEBUS_EMBED_MODEL_ROOT=${STATEBUS_EMBED_MODEL_ROOT:-$HOME/statebus/models}
EOF
}

workspace_mount_mode() {
  local workspace_source os_source
  workspace_source="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/workspace/statebus"}}{{.Source}}{{end}}{{end}}' "$CONTAINER_NAME" 2>/dev/null || true)"
  os_source="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/workspace/statebus/os"}}{{.Source}}{{end}}{{end}}' "$CONTAINER_NAME" 2>/dev/null || true)"
  if [[ "$workspace_source" == "$WORKSPACE_ROOT_HOST" ]]; then
    printf 'workspace-root\n'
  elif [[ "$os_source" == "${STATEBUS_OS_CHECKOUT:-$OS_ROOT}" ]]; then
    printf 'legacy-os-only\n'
  else
    printf 'unknown\n'
  fi
}

container_path_for_host() {
  local host_path="$1" mode relative
  mode="$(workspace_mount_mode)"

  if [[ "$host_path" == "$B2_HOME_HOST" ]]; then
    printf '/statebus\n'
    return 0
  elif [[ "$host_path" == "$B2_HOME_HOST"/* ]]; then
    printf '/statebus/%s\n' "${host_path#"$B2_HOME_HOST"/}"
    return 0
  fi

  case "$mode" in
    workspace-root)
      if [[ "$host_path" == "$WORKSPACE_ROOT_HOST" ]]; then
        printf '%s\n' "$WORKSPACE_CONTAINER_ROOT"
      elif [[ "$host_path" == "$WORKSPACE_ROOT_HOST"/* ]]; then
        relative="${host_path#"$WORKSPACE_ROOT_HOST"/}"
        printf '%s/%s\n' "$WORKSPACE_CONTAINER_ROOT" "$relative"
      else
        return 1
      fi
      ;;
    legacy-os-only)
      if [[ "$host_path" == "$OS_ROOT" ]]; then
        printf '%s\n' "$CONTAINER_ROOT"
      elif [[ "$host_path" == "$OS_ROOT"/* ]]; then
        relative="${host_path#"$OS_ROOT"/}"
        printf '%s/%s\n' "$CONTAINER_ROOT" "$relative"
      else
        return 1
      fi
      ;;
    *)
      return 1
      ;;
  esac
}

container_exec() {
  docker exec -i \
    -e NO_PROXY="${NO_PROXY:-127.0.0.1,localhost}" \
    -e no_proxy="${no_proxy:-127.0.0.1,localhost}" \
    -e PROJECT_ROOT="$CONTAINER_ROOT" \
    -e PYTHONPATH="$CONTAINER_ROOT/src" \
    -e STATEBUS_CONTAINER_NAME="$CONTAINER_NAME" \
    -e STATEBUS_B2_CONTAINER_NAME="$CONTAINER_NAME" \
    -e STATEBUS_LLM_CONFIG_FILE="$(container_llm_config_file)" \
    -e STATEBUS_LOCAL_VLLM_BASE_URL="${STATEBUS_LOCAL_VLLM_BASE_URL:-http://127.0.0.1:53334/v1}" \
    -e STATEBUS_LOCAL_VLLM_HEALTH_URL="${STATEBUS_LOCAL_VLLM_HEALTH_URL:-http://127.0.0.1:53334/health}" \
    -e STATEBUS_LOCAL_VLLM_MODEL="${STATEBUS_LOCAL_VLLM_MODEL:-qwen3-32b}" \
    -e STATEBUS_G6B2_PROFILE_ID="${STATEBUS_G6B2_PROFILE_ID:-g6b2-live-qwen3-32b-gpu2-u050-qwen3-embedding-gpu1-v1}" \
    -e STATEBUS_G6B2_SERVICE_PHYSICAL_GPU="${STATEBUS_G6B2_SERVICE_PHYSICAL_GPU:-2}" \
    -e STATEBUS_G6B2_EMBEDDING_MODE="${STATEBUS_G6B2_EMBEDDING_MODE:-local}" \
    -e STATEBUS_G6B2_EMBEDDING_MODEL_PATH="${STATEBUS_G6B2_EMBEDDING_MODEL_PATH:-/statebus/models/Qwen3-Embedding-0.6B}" \
    -e STATEBUS_G6B2_EMBEDDING_DEVICE="${STATEBUS_G6B2_EMBEDDING_DEVICE:-cuda:0}" \
    -e STATEBUS_G6B2_EMBEDDING_PHYSICAL_GPU="${STATEBUS_G6B2_EMBEDDING_PHYSICAL_GPU:-${STATEBUS_EMBED_PHYSICAL_GPU:-1}}" \
    -e STATEBUS_VLLM_MODEL_PATH="${STATEBUS_VLLM_MODEL_PATH:-/data/models/Qwen3-32B}" \
    -e STATEBUS_VLLM_TOKENIZER_PATH="${STATEBUS_VLLM_TOKENIZER_PATH:-/data/models/Qwen3-32B}" \
    -e STATEBUS_VLLM_SERVED_MODEL_NAME="${STATEBUS_VLLM_SERVED_MODEL_NAME:-${STATEBUS_LOCAL_VLLM_MODEL:-qwen3-32b}}" \
    -e STATEBUS_VLLM_MAX_MODEL_LEN="${STATEBUS_VLLM_MAX_MODEL_LEN:-8192}" \
    -e STATEBUS_VLLM_MAX_NUM_SEQS="${STATEBUS_VLLM_MAX_NUM_SEQS:-1}" \
    -e STATEBUS_VLLM_MAX_NUM_BATCHED_TOKENS="${STATEBUS_VLLM_MAX_NUM_BATCHED_TOKENS:-8192}" \
    -e STATEBUS_VLLM_GPU_MEMORY_UTILIZATION="${STATEBUS_VLLM_GPU_MEMORY_UTILIZATION:-0.82}" \
    -e STATEBUS_EMBED_MODEL_PATH="${STATEBUS_EMBED_MODEL_PATH:-/statebus/models/Qwen3-Embedding-0.6B}" \
    -e STATEBUS_EMBED_DEVICE=cuda:0 \
    -e STATEBUS_STUDIO_EMBED_DEVICE=cuda:0 \
    -e STATEBUS_WORKSPACE_MOUNT_MODE="$(workspace_mount_mode)" \
    "$CONTAINER_NAME" bash -lc '
      set -euo pipefail
      source "$PROJECT_ROOT/docker/activate_statebus_container.sh"
      cd "$PROJECT_ROOT"
      exec "$@"
    ' -- "$@"
}

verify_mount() {
  local inspect_json
  local llm_config expected_image expected_os_checkout expected_home_host
  local workspace_mode
  local expected_models_root expected_host_env expected_embed_root
  local expected_embed_gpu expected_profile expected_service_gpu
  local expected_embed_mode expected_embed_model expected_embed_device
  local expected_model expected_served expected_context expected_seqs expected_batch expected_util
  llm_config="$(container_llm_config_file)"
  expected_image="${STATEBUS_B2_IMAGE:-statebus-dev-openeuler:24.03-lts-sp3-embed}"
  expected_os_checkout="${STATEBUS_OS_CHECKOUT:-$OS_ROOT}"
  expected_home_host="$B2_HOME_HOST"
  expected_models_root="${STATEBUS_VLLM_MODELS_ROOT:-/data/models}"
  expected_host_env="${STATEBUS_HOST_ENV:-$HOME/statebus/conda-envs/statebus_host}"
  expected_embed_root="${STATEBUS_EMBED_MODEL_ROOT:-$HOME/statebus/models}"
  expected_embed_gpu="${STATEBUS_G6B2_EMBEDDING_PHYSICAL_GPU:-${STATEBUS_EMBED_PHYSICAL_GPU:-1}}"
  expected_profile="${STATEBUS_G6B2_PROFILE_ID:-g6b2-live-qwen3-32b-gpu2-u050-qwen3-embedding-gpu1-v1}"
  expected_service_gpu="${STATEBUS_G6B2_SERVICE_PHYSICAL_GPU:-2}"
  expected_embed_mode="${STATEBUS_G6B2_EMBEDDING_MODE:-local}"
  expected_embed_model="${STATEBUS_G6B2_EMBEDDING_MODEL_PATH:-/statebus/models/Qwen3-Embedding-0.6B}"
  expected_embed_device="${STATEBUS_G6B2_EMBEDDING_DEVICE:-cuda:0}"
  expected_model="${STATEBUS_LOCAL_VLLM_MODEL:-qwen3-32b}"
  expected_served="${STATEBUS_VLLM_SERVED_MODEL_NAME:-$expected_model}"
  expected_context="${STATEBUS_VLLM_MAX_MODEL_LEN:-8192}"
  expected_seqs="${STATEBUS_VLLM_MAX_NUM_SEQS:-1}"
  expected_batch="${STATEBUS_VLLM_MAX_NUM_BATCHED_TOKENS:-8192}"
  expected_util="${STATEBUS_VLLM_GPU_MEMORY_UTILIZATION:-0.82}"

  inspect_json="$(docker inspect "$CONTAINER_NAME" 2>/dev/null)" || {
    printf 'StateBus runtime container is not inspectable: %s\n' "$CONTAINER_NAME" >&2
    return 1
  }
  command -v jq >/dev/null 2>&1 || {
    printf 'jq is required for structured container verification\n' >&2
    return 1
  }
  jq -e --arg name "/$CONTAINER_NAME" \
    '.[0].Name == $name and .[0].State.Running == true' <<<"$inspect_json" >/dev/null || {
    printf 'StateBus runtime container is not running or has an unexpected name: %s\n' "$CONTAINER_NAME" >&2
    return 1
  }
  jq -e --arg image "$expected_image" \
    '.[0].Config.Image == $image' <<<"$inspect_json" >/dev/null || {
    printf 'StateBus runtime container image mismatch: expected %s\n' "$expected_image" >&2
    return 1
  }
  jq -e '.[0].HostConfig.NetworkMode == "host"' <<<"$inspect_json" >/dev/null || {
    printf 'StateBus runtime container network mismatch: expected host\n' >&2
    return 1
  }
  require_mount() {
    local destination="$1" expected="$2" actual
    actual="$(jq -r --arg destination "$destination" '.[0].Mounts[]? | select(.Destination == $destination) | .Source' <<<"$inspect_json")"
    [[ "$actual" == "$expected" ]] || {
      printf 'StateBus runtime mount mismatch: destination=%s expected=%s got=%s\n' "$destination" "$expected" "$actual" >&2
      return 1
    }
  }
  workspace_mode="$(workspace_mount_mode)"
  case "$workspace_mode" in
    workspace-root)
      require_mount "$WORKSPACE_CONTAINER_ROOT" "$WORKSPACE_ROOT_HOST"
      ;;
    legacy-os-only)
      require_mount "$CONTAINER_ROOT" "$expected_os_checkout"
      printf 'warning: statebus-runtime is using legacy os-only mount; recreate it to expose %s and %s\n' \
        "$WORKSPACE_ROOT_HOST/project" "$WORKSPACE_ROOT_HOST/runs" >&2
      ;;
    *)
      printf 'StateBus runtime workspace mount mismatch: expected %s -> %s or legacy %s -> %s\n' \
        "$WORKSPACE_ROOT_HOST" "$WORKSPACE_CONTAINER_ROOT" "$expected_os_checkout" "$CONTAINER_ROOT" >&2
      return 1
      ;;
  esac
  require_mount /statebus "$expected_home_host"
  require_mount /data/models "$expected_models_root"
  require_mount /home/qcrs/statebus/conda-envs/statebus_host "$expected_host_env"
  require_mount /statebus/models "$expected_embed_root"
  jq -e --arg gpu "$expected_embed_gpu" '
    (.[0].HostConfig.DeviceRequests // [])
    | any(.[]; .Driver == "nvidia"
      and ((.DeviceIDs // []) | index($gpu) != null)
      and any((.Capabilities // [])[]?; index("gpu") != null))
  ' <<<"$inspect_json" >/dev/null || {
    printf 'StateBus runtime NVIDIA device request mismatch: expected physical GPU %s\n' "$expected_embed_gpu" >&2
    return 1
  }
  warn_stale_env() {
    local key="$1" expected="$2" actual
    actual="$(jq -r --arg key "$key" '[.[0].Config.Env[]? | select(startswith($key + "=")) | ltrimstr($key + "=")][0] // ""' <<<"$inspect_json")"
    [[ "$actual" == "$expected" ]] || {
      printf 'warning: stale container creation environment: %s expected=%s created_with=%s; command-scoped value will be verified via docker exec\n' \
        "$key" "$expected" "${actual:-<unset>}" >&2
    }
  }
  warn_stale_env STATEBUS_LLM_CONFIG_FILE "$llm_config"
  warn_stale_env STATEBUS_G6B2_PROFILE_ID "$expected_profile"
  warn_stale_env STATEBUS_G6B2_SERVICE_PHYSICAL_GPU "$expected_service_gpu"
  warn_stale_env STATEBUS_G6B2_EMBEDDING_MODE "$expected_embed_mode"
  warn_stale_env STATEBUS_G6B2_EMBEDDING_MODEL_PATH "$expected_embed_model"
  warn_stale_env STATEBUS_G6B2_EMBEDDING_DEVICE "$expected_embed_device"
  warn_stale_env STATEBUS_G6B2_EMBEDDING_PHYSICAL_GPU "$expected_embed_gpu"
  warn_stale_env STATEBUS_LOCAL_VLLM_MODEL "$expected_model"
  warn_stale_env STATEBUS_VLLM_SERVED_MODEL_NAME "$expected_served"
  warn_stale_env STATEBUS_VLLM_MODEL_PATH "${STATEBUS_VLLM_MODEL_PATH:-/data/models/Qwen3-32B}"
  warn_stale_env STATEBUS_VLLM_TOKENIZER_PATH "${STATEBUS_VLLM_TOKENIZER_PATH:-/data/models/Qwen3-32B}"
  warn_stale_env STATEBUS_VLLM_MAX_MODEL_LEN "$expected_context"
  warn_stale_env STATEBUS_VLLM_MAX_NUM_SEQS "$expected_seqs"
  warn_stale_env STATEBUS_VLLM_MAX_NUM_BATCHED_TOKENS "$expected_batch"
  warn_stale_env STATEBUS_VLLM_GPU_MEMORY_UTILIZATION "$expected_util"

  docker exec "$CONTAINER_NAME" test -f "$CONTAINER_ROOT/src/statebus/benchmark/g6b2_live_validation.py"
  docker exec "$CONTAINER_NAME" test -f "$llm_config" || {
    printf 'StateBus container LLM config missing: %s\n' "$llm_config" >&2
    return 1
  }
  docker exec "$CONTAINER_NAME" test -f "$expected_embed_model/config.json" || {
    printf 'StateBus embedding model config missing: %s/config.json\n' "$expected_embed_model" >&2
    return 1
  }
  docker exec "$CONTAINER_NAME" command -v python3 >/dev/null
  container_exec /usr/bin/python3 -c '
import os
import sys

pairs = list(zip(sys.argv[1::2], sys.argv[2::2]))
mismatches = [
    f"{key}:expected={expected}:got={os.environ.get(key)!r}"
    for key, expected in pairs
    if os.environ.get(key) != expected
]
if mismatches:
    raise SystemExit("effective container environment mismatch: " + ";".join(mismatches))
import statebus
assert os.path.isdir("/workspace/statebus/os")
if os.environ.get("STATEBUS_WORKSPACE_MOUNT_MODE") == "workspace-root":
    assert os.path.isdir("/workspace/statebus/project")
    assert os.path.isdir("/workspace/statebus/runs")
' \
    STATEBUS_LLM_CONFIG_FILE "$llm_config" \
    STATEBUS_G6B2_PROFILE_ID "$expected_profile" \
    STATEBUS_G6B2_SERVICE_PHYSICAL_GPU "$expected_service_gpu" \
    STATEBUS_G6B2_EMBEDDING_MODE "$expected_embed_mode" \
    STATEBUS_G6B2_EMBEDDING_MODEL_PATH "$expected_embed_model" \
    STATEBUS_G6B2_EMBEDDING_DEVICE "$expected_embed_device" \
    STATEBUS_G6B2_EMBEDDING_PHYSICAL_GPU "$expected_embed_gpu" \
    STATEBUS_LOCAL_VLLM_MODEL "$expected_model" \
    STATEBUS_VLLM_SERVED_MODEL_NAME "$expected_served" \
    STATEBUS_VLLM_MODEL_PATH "${STATEBUS_VLLM_MODEL_PATH:-/data/models/Qwen3-32B}" \
    STATEBUS_VLLM_TOKENIZER_PATH "${STATEBUS_VLLM_TOKENIZER_PATH:-/data/models/Qwen3-32B}" \
    STATEBUS_VLLM_MAX_MODEL_LEN "$expected_context" \
    STATEBUS_VLLM_MAX_NUM_SEQS "$expected_seqs" \
    STATEBUS_VLLM_MAX_NUM_BATCHED_TOKENS "$expected_batch" \
    STATEBUS_VLLM_GPU_MEMORY_UTILIZATION "$expected_util" \
    STATEBUS_EMBED_DEVICE cuda:0 \
    STATEBUS_STUDIO_EMBED_DEVICE cuda:0
}

usage() {
  cat <<'EOF'
Usage: scripts/run_g6b2_os_container.sh <config|up|down|inspect|verify|exec|smoke> [command ...]

The container mounts the whole statebus workspace at /workspace/statebus and
uses host networking to reach host vLLM at http://127.0.0.1:53334/v1. The
legacy os-only mount is accepted for inspection, but up recreates the named
statebus-runtime container when the workspace-root mount is not active. The
physical embedding GPU is selected with STATEBUS_EMBED_PHYSICAL_GPU (default
1) and is always logical cuda:0 inside the container. The same container is
reused across tasks.
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
      if [[ "$(workspace_mount_mode)" == "workspace-root" ]]; then
        compose up -d --no-build --no-recreate
      else
        printf '[statebus] recreating %s to activate workspace-root mount %s -> %s\n' \
          "$CONTAINER_NAME" "$WORKSPACE_ROOT_HOST" "$WORKSPACE_CONTAINER_ROOT" >&2
        compose up -d --no-build --force-recreate
      fi
    else
      compose up -d --no-build --no-recreate
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
    printf 'StateBus runtime mount verified: mode=%s workspace=%s -> %s\n' \
      "$(workspace_mount_mode)" "$WORKSPACE_ROOT_HOST" "$WORKSPACE_CONTAINER_ROOT"
    ;;
  mount-mode)
    workspace_mount_mode
    ;;
  map-path)
    shift
    [[ $# -eq 1 ]] || { usage >&2; exit 2; }
    # Keep command substitution machine-readable.  verify_mount performs an
    # effective in-container environment check whose activation diagnostics
    # belong on the terminal, not in the mapped path value.
    verify_mount >/dev/null
    container_path_for_host "$1" || {
      printf 'host path is not visible in the current container mount: %s\n' "$1" >&2
      exit 2
    }
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
import json, os, urllib.error, urllib.request
from statebus.integrations.llm import LLMConfig

def fetch(url, *, method="GET", payload=None):
    request = urllib.request.Request(url, method=method)
    if payload is not None:
        request.add_header("Content-Type", "application/json")
        request.data = json.dumps(payload).encode("utf-8")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=20) as response:
        body = response.read()
        return response.status, json.loads(body) if body else None

config = LLMConfig.from_runtime().with_mode("local_vllm")
assert config.provider_config("default").base_url.rstrip("/") == os.environ["STATEBUS_LOCAL_VLLM_BASE_URL"].rstrip("/")
expected_model = os.environ["STATEBUS_LOCAL_VLLM_MODEL"]
assert {config.role_config(role).model for role in ("planner", "retriever", "executor", "summarizer")} == {expected_model}
assert os.environ.get("PROJECT_ROOT") == "/workspace/statebus/os"
assert os.environ.get("STATEBUS_EMBED_DEVICE") == "cuda:0"
assert os.environ.get("STATEBUS_STUDIO_EMBED_DEVICE") == "cuda:0"
health_status, _ = fetch(os.environ["STATEBUS_LOCAL_VLLM_HEALTH_URL"])
assert 200 <= health_status < 300
models_status, payload = fetch(os.environ["STATEBUS_LOCAL_VLLM_BASE_URL"].rstrip("/") + "/models")
assert 200 <= models_status < 300
assert isinstance(payload, dict)
ids = [item.get("id") for item in payload.get("data", [])]
assert ids == [expected_model]
request_status, completion = fetch(
    os.environ["STATEBUS_LOCAL_VLLM_BASE_URL"].rstrip("/") + "/chat/completions",
    method="POST",
    payload={
        "model": expected_model,
        "messages": [{"role": "user", "content": "Reply with exactly: statebus-smoke"}],
        "temperature": 0,
        "max_tokens": 16,
    },
)
assert 200 <= request_status < 300
assert isinstance(completion, dict)
choices = completion.get("choices") or []
assert choices and isinstance(choices[0].get("message", {}).get("content"), str)
print(json.dumps({"checkout": os.getcwd(), "model": expected_model, "health": "passed", "models": ids, "provider_request": "passed"}, sort_keys=True))
'
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
