#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
embedding_device="${STATEBUS_EMBED_DEVICE:-cuda:1}"
if [[ "$embedding_device" == "auto" ]]; then
  embedding_device="cuda:1"
fi
embedding_model_path="${STATEBUS_EMBED_MODEL_PATH:-/statebus/models/Qwen3-Embedding-0.6B}"
vllm_base_url="${STATEBUS_LOCAL_VLLM_BASE_URL:-http://127.0.0.1:53334/v1}"
vllm_model="${STATEBUS_LOCAL_VLLM_MODEL:-qwen3-32b}"
require_model_success="${STATEBUS_ADAPTIVE_SMOKE_REQUIRE_MODEL_SUCCESS:-1}"
role_http_timeout_s="${STATEBUS_ADAPTIVE_ROLE_HTTP_TIMEOUT_S:-90}"
role_worker_timeout_s="${STATEBUS_ADAPTIVE_ROLE_WORKER_TIMEOUT_S:-105}"

cd "$project_root"

docker exec \
  -u 0 \
  -e STATEBUS_SMOKE_EMBED_DEVICE="$embedding_device" \
  -e STATEBUS_SMOKE_EMBED_MODEL_PATH="$embedding_model_path" \
  -e STATEBUS_SMOKE_LOCAL_VLLM_BASE_URL="$vllm_base_url" \
  -e STATEBUS_SMOKE_LOCAL_VLLM_MODEL="$vllm_model" \
  -e STATEBUS_SMOKE_REQUIRE_MODEL_SUCCESS="$require_model_success" \
  -e STATEBUS_ADAPTIVE_ROLE_HTTP_TIMEOUT_S="$role_http_timeout_s" \
  -e STATEBUS_ADAPTIVE_ROLE_WORKER_TIMEOUT_S="$role_worker_timeout_s" \
  statebus-dev-qcrs \
  bash -lc '
    set -euo pipefail
    source /workspace/statebus/project/docker/activate_statebus_container.sh
    cd /workspace/statebus/project
    export STATEBUS_EMBEDDING_MODE=local
    export STATEBUS_EMBED_DEVICE="$STATEBUS_SMOKE_EMBED_DEVICE"
    export STATEBUS_EMBED_MODEL_PATH="$STATEBUS_SMOKE_EMBED_MODEL_PATH"
    export STATEBUS_LOCAL_VLLM_BASE_URL="$STATEBUS_SMOKE_LOCAL_VLLM_BASE_URL"
    export STATEBUS_LOCAL_VLLM_MODEL="$STATEBUS_SMOKE_LOCAL_VLLM_MODEL"
    printf "[adaptive-smoke] container=%s\n" "${HOSTNAME:-statebus-dev-qcrs}"
    printf "[adaptive-smoke] requested embedding device: %s\n" "$STATEBUS_EMBED_DEVICE"
    printf "[adaptive-smoke] vllm base URL: %s\n" "$STATEBUS_LOCAL_VLLM_BASE_URL"
    printf "[adaptive-smoke] require zero fallback: %s\n" "$STATEBUS_SMOKE_REQUIRE_MODEL_SUCCESS"
    printf "[adaptive-smoke] role timeouts: http=%ss worker=%ss\n" \
      "$STATEBUS_ADAPTIVE_ROLE_HTTP_TIMEOUT_S" "$STATEBUS_ADAPTIVE_ROLE_WORKER_TIMEOUT_S"

    test -f /.dockerenv
    curl -fsS "${STATEBUS_LOCAL_VLLM_BASE_URL%/v1}/health" >/dev/null
    curl -fsS "$STATEBUS_LOCAL_VLLM_BASE_URL/models" >/dev/null

    python3 - <<"PY"
import os
import torch

device = os.environ["STATEBUS_EMBED_DEVICE"]
if not torch.cuda.is_available():
    raise SystemExit("CUDA is not available in statebus-dev-qcrs")
if not device.startswith("cuda:"):
    raise SystemExit(f"expected an explicit CUDA device, got {device!r}")
index = int(device.split(":", 1)[1])
if index >= torch.cuda.device_count():
    raise SystemExit(f"requested {device}, but only {torch.cuda.device_count()} CUDA devices are visible")
probe = torch.arange(8, device=device).sum().item()
print(f"[adaptive-smoke] torch={torch.__version__} cuda_count={torch.cuda.device_count()} device={device} probe={probe}")
PY

    bwrap_result="$(python3 scripts/v2_diagnostics/check_codeact_bwrap_sandbox.py)"
    printf "%s\n" "$bwrap_result"
    BWRAP_RESULT="$bwrap_result" python3 - <<"PY"
import json
import os

payload = json.loads(os.environ["BWRAP_RESULT"])
if not payload.get("ok"):
    raise SystemExit(f"bwrap readiness failed: {payload}")
print("[adaptive-smoke] bwrap readiness: OK")
PY

    require_args=()
    if [[ "$STATEBUS_SMOKE_REQUIRE_MODEL_SUCCESS" == "1" || "$STATEBUS_SMOKE_REQUIRE_MODEL_SUCCESS" == "true" ]]; then
      require_args+=(--require-model-success)
    fi

    set +e
    python3 scripts/v2_diagnostics/run_adaptive_agent_smoke.py \
      --embedding-model-path "$STATEBUS_EMBED_MODEL_PATH" \
      --embedding-device "$STATEBUS_EMBED_DEVICE" \
      "${require_args[@]}" \
      "$@"
    status=$?
    set -e
    if [[ $status -eq 2 ]]; then
      printf "[adaptive-smoke] FAIL: strict model-path acceptance failed (fallback, controlled replan, or incomplete runtime); inspect newest summary.json and roles/*.json\n" >&2
    elif [[ $status -ne 0 ]]; then
      printf "[adaptive-smoke] FAIL: smoke exited with status %s\n" "$status" >&2
    elif [[ "$STATEBUS_SMOKE_REQUIRE_MODEL_SUCCESS" != "1" && "$STATEBUS_SMOKE_REQUIRE_MODEL_SUCCESS" != "true" ]]; then
      printf "[adaptive-smoke] COMPLETED: strict zero-fallback acceptance was disabled; inspect summary.json\n"
    else
      printf "[adaptive-smoke] PASS: all four model roles completed without fallback\n"
    fi
    exit "$status"
  ' statebus-adaptive-smoke "$@"
