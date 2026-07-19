#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
container_name="${STATEBUS_V2_CONTAINER_NAME:-statebus-dev-qcrs}"
gpu_index="${STATEBUS_CUDA_VISIBLE_DEVICES:-1}"
embedding_device="${STATEBUS_EMBED_DEVICE:-cuda:0}"
run_id="${STATEBUS_ADAPTIVE_EFFECT_RUN_ID:-adaptive_enhancement_effect_$(date +%Y%m%d_%H%M%S)}"
host_result_root="${STATEBUS_HOST_RUNS_ROOT:-$HOME/statebus/runs}/${run_id}"
container_result_root="/statebus/runs/${run_id}"
existing_summary="${STATEBUS_ADAPTIVE_EFFECT_EXISTING_SUMMARY:-}"
timeout_seconds="${STATEBUS_ADAPTIVE_EFFECT_TIMEOUT_S:-1200}"
vllm_base_url="${STATEBUS_LOCAL_VLLM_BASE_URL:-http://127.0.0.1:53334/v1}"
vllm_model="${STATEBUS_LOCAL_VLLM_MODEL:-qwen3-32b}"

if [[ ! "$gpu_index" =~ ^[0-9]+$ ]]; then
  printf 'STATEBUS_CUDA_VISIBLE_DEVICES must be one physical GPU index, got %q\n' "$gpu_index" >&2
  exit 2
fi
if [[ ! "$timeout_seconds" =~ ^[0-9]+$ ]]; then
  printf 'STATEBUS_ADAPTIVE_EFFECT_TIMEOUT_S must be an integer, got %q\n' "$timeout_seconds" >&2
  exit 2
fi
if ! docker inspect --format '{{.State.Running}}' "$container_name" 2>/dev/null | grep -qx true; then
  printf 'container is not running: %s\n' "$container_name" >&2
  exit 2
fi

if [[ "$existing_summary" == /home/qcrs/statebus/runs/* ]]; then
  existing_summary="/statebus/runs/${existing_summary#/home/qcrs/statebus/runs/}"
fi

mkdir -p "$host_result_root"
printf '[adaptive-effect] one focused causal probe; no legacy 5-case/25-case suite\n'
printf '[adaptive-effect] physical GPU: %s; container embedding device: %s\n' "$gpu_index" "$embedding_device"
printf '[adaptive-effect] result root: %s\n' "$host_result_root"

cd "$project_root"
docker exec -i -u 0 \
  -e CUDA_VISIBLE_DEVICES="$gpu_index" \
  -e STATEBUS_EMBED_DEVICE="$embedding_device" \
  -e STATEBUS_EMBEDDING_MODE=local \
  -e STATEBUS_EMBED_MODEL_PATH="${STATEBUS_EMBED_MODEL_PATH:-/statebus/models/Qwen3-Embedding-0.6B}" \
  -e STATEBUS_LOCAL_VLLM_BASE_URL="$vllm_base_url" \
  -e STATEBUS_LOCAL_VLLM_MODEL="$vllm_model" \
  -e STATEBUS_ADAPTIVE_ROLE_WORKER_TIMEOUT_S="${STATEBUS_ADAPTIVE_ROLE_WORKER_TIMEOUT_S:-300}" \
  -e STATEBUS_ADAPTIVE_SUMMARIZER_MAX_TOKENS="${STATEBUS_ADAPTIVE_SUMMARIZER_MAX_TOKENS:-1400}" \
  -e STATEBUS_ADAPTIVE_EFFECT_LIVE_TIMEOUT_S="${STATEBUS_ADAPTIVE_EFFECT_LIVE_TIMEOUT_S:-900}" \
  -e STATEBUS_ADAPTIVE_EFFECT_EXISTING_SUMMARY="$existing_summary" \
  -e STATEBUS_ADAPTIVE_EFFECT_RESULT_ROOT="$container_result_root" \
  -e STATEBUS_ADAPTIVE_EFFECT_TIMEOUT_S="$timeout_seconds" \
  "$container_name" /bin/bash -s <<'CONTAINER_BASH'
set -euo pipefail

source /workspace/statebus/project/docker/activate_statebus_container.sh
cd /workspace/statebus/project
mkdir -p "$STATEBUS_ADAPTIVE_EFFECT_RESULT_ROOT"

health_url="${STATEBUS_LOCAL_VLLM_BASE_URL%/v1}/health"
curl -fsS "$health_url" >/dev/null
printf '[adaptive-effect] vLLM health: OK (%s)\n' "$health_url"

python3 - <<'PY'
import os
import torch

device = os.environ["STATEBUS_EMBED_DEVICE"]
if not torch.cuda.is_available():
    raise SystemExit("PyTorch CUDA is unavailable")
probe = torch.arange(8, device=device).sum().item()
print(f"[adaptive-effect] CUDA: OK device={device} count={torch.cuda.device_count()} probe={probe}")
PY

python3 scripts/v2_diagnostics/check_codeact_bwrap_sandbox.py \
  > "$STATEBUS_ADAPTIVE_EFFECT_RESULT_ROOT/bwrap_readiness.json"
printf '[adaptive-effect] bwrap readiness: OK\n'

python3 -m pytest -q \
  tests/v2/test_adaptive_enhancement_effect.py \
  tests/v2/test_capability_validators.py \
  tests/v2/test_adaptive_codeact_integration.py::test_python_failure_falls_back_only_with_a_fresh_dsl_grant \
  2>&1 | tee "$STATEBUS_ADAPTIVE_EFFECT_RESULT_ROOT/pytest.log"

args=(
  --output-root "$STATEBUS_ADAPTIVE_EFFECT_RESULT_ROOT"
)
if [[ -n "$STATEBUS_ADAPTIVE_EFFECT_EXISTING_SUMMARY" ]]; then
  args+=(--existing-summary "$STATEBUS_ADAPTIVE_EFFECT_EXISTING_SUMMARY")
  printf '[adaptive-effect] using existing live summary: %s\n' "$STATEBUS_ADAPTIVE_EFFECT_EXISTING_SUMMARY"
else
  printf '[adaptive-effect] starting one fresh live adaptive causal probe\n'
fi

timeout "$STATEBUS_ADAPTIVE_EFFECT_TIMEOUT_S" \
  python3 scripts/v2_diagnostics/run_adaptive_enhancement_effect.py "${args[@]}" \
  2>&1 | tee "$STATEBUS_ADAPTIVE_EFFECT_RESULT_ROOT/console.log"
CONTAINER_BASH

latest_summary="$(
  rg --files "$host_result_root" \
    | rg '/adaptive_enhancement_effect_[^/]+/summary\.json$' \
    | sort \
    | tail -n 1
)"
if [[ -z "$latest_summary" ]]; then
  printf '[adaptive-effect] summary.json was not produced under %s\n' "$host_result_root" >&2
  exit 2
fi
printf '[adaptive-effect] PASS\n'
printf '[adaptive-effect] summary: %s\n' "$latest_summary"
printf '[adaptive-effect] analysis: %s\n' "${latest_summary%/summary.json}/analysis.md"
