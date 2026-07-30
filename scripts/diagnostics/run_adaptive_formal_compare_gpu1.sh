#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
container_name="${STATEBUS_CONTAINER_NAME:-statebus-dev-qcrs}"
gpu_index="${STATEBUS_CUDA_VISIBLE_DEVICES:-1}"
embedding_device="${STATEBUS_EMBED_DEVICE:-cuda:0}"
vllm_base_url="${STATEBUS_LOCAL_VLLM_BASE_URL:-http://127.0.0.1:53334/v1}"
vllm_model="${STATEBUS_LOCAL_VLLM_MODEL:-qwen3-32b}"
max_cases="${STATEBUS_ADAPTIVE_FORMAL_MAX_CASES:-25}"
case_ids="${STATEBUS_ADAPTIVE_FORMAL_CASE_IDS:-}"
lane="${STATEBUS_ADAPTIVE_FORMAL_LANE:-both}"
quality_threshold="${STATEBUS_ADAPTIVE_FORMAL_QUALITY_THRESHOLD:-0.80}"
exit_gate="${STATEBUS_ADAPTIVE_FORMAL_EXIT_GATE:-high-accuracy}"
timeout_seconds="${STATEBUS_ADAPTIVE_FORMAL_TIMEOUT_S:-43200}"
run_id="${STATEBUS_ADAPTIVE_FORMAL_RUN_ID:-adaptive_formal_compare_$(date +%Y%m%d_%H%M%S)}"
host_result_root="${STATEBUS_HOST_RUNS_ROOT:-$HOME/statebus/runs}/${run_id}"
container_result_root="/statebus/runs/${run_id}"

if [[ ! "$gpu_index" =~ ^[0-9]+$ ]]; then
  printf 'STATEBUS_CUDA_VISIBLE_DEVICES must be one physical GPU index, got %q\n' "$gpu_index" >&2
  exit 2
fi
if [[ ! "$max_cases" =~ ^[0-9]+$ ]] || (( max_cases < 1 || max_cases > 25 )); then
  printf 'STATEBUS_ADAPTIVE_FORMAL_MAX_CASES must be an integer from 1 through 25, got %q\n' "$max_cases" >&2
  exit 2
fi
if [[ ! "$timeout_seconds" =~ ^[0-9]+$ ]]; then
  printf 'STATEBUS_ADAPTIVE_FORMAL_TIMEOUT_S must be an integer, got %q\n' "$timeout_seconds" >&2
  exit 2
fi
case "$lane" in
  both|strict|adaptive) ;;
  *)
    printf 'STATEBUS_ADAPTIVE_FORMAL_LANE must be both, strict, or adaptive; got %q\n' "$lane" >&2
    exit 2
    ;;
esac
case "$exit_gate" in
  high-accuracy|all-correct) ;;
  *)
    printf 'STATEBUS_ADAPTIVE_FORMAL_EXIT_GATE must be high-accuracy or all-correct; got %q\n' "$exit_gate" >&2
    exit 2
    ;;
esac
if ! docker inspect --format '{{.State.Running}}' "$container_name" 2>/dev/null | grep -qx true; then
  printf 'container is not running: %s\n' "$container_name" >&2
  exit 2
fi

mkdir -p "$host_result_root"
printf '[adaptive-formal] formal registry comparison; strict L3 vs bounded adaptive LLM CodeAct\n'
printf '[adaptive-formal] cases: %s/25; lane: %s\n' "$max_cases" "$lane"
printf '[adaptive-formal] exit gate: %s; quality threshold: %s\n' "$exit_gate" "$quality_threshold"
if [[ -n "$case_ids" ]]; then
  printf '[adaptive-formal] case filter: %s\n' "$case_ids"
fi
printf '[adaptive-formal] physical GPU: %s; container embedding device: %s\n' "$gpu_index" "$embedding_device"
printf '[adaptive-formal] result root: %s\n' "$host_result_root"

cd "$project_root"
docker exec -i -u 0 \
  -e CUDA_VISIBLE_DEVICES="$gpu_index" \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e STATEBUS_EMBED_DEVICE="$embedding_device" \
  -e STATEBUS_EMBEDDING_MODE=local \
  -e STATEBUS_EMBED_MODEL_PATH="${STATEBUS_EMBED_MODEL_PATH:-/statebus/models/Qwen3-Embedding-0.6B}" \
  -e STATEBUS_LOCAL_VLLM_BASE_URL="$vllm_base_url" \
  -e STATEBUS_LOCAL_VLLM_MODEL="$vllm_model" \
  -e STATEBUS_ADAPTIVE_ROLE_HTTP_TIMEOUT_S="${STATEBUS_ADAPTIVE_ROLE_HTTP_TIMEOUT_S:-240}" \
  -e STATEBUS_ADAPTIVE_ROLE_WORKER_TIMEOUT_S="${STATEBUS_ADAPTIVE_ROLE_WORKER_TIMEOUT_S:-300}" \
  -e STATEBUS_ADAPTIVE_SUMMARIZER_MAX_TOKENS="${STATEBUS_ADAPTIVE_SUMMARIZER_MAX_TOKENS:-1400}" \
  -e STATEBUS_ADAPTIVE_FORMAL_CODE_MAX_TOKENS="${STATEBUS_ADAPTIVE_FORMAL_CODE_MAX_TOKENS:-1400}" \
  -e STATEBUS_ADAPTIVE_FORMAL_RESULT_ROOT="$container_result_root" \
  -e STATEBUS_ADAPTIVE_FORMAL_MAX_CASES="$max_cases" \
  -e STATEBUS_ADAPTIVE_FORMAL_CASE_IDS="$case_ids" \
  -e STATEBUS_ADAPTIVE_FORMAL_LANE="$lane" \
  -e STATEBUS_ADAPTIVE_FORMAL_QUALITY_THRESHOLD="$quality_threshold" \
  -e STATEBUS_ADAPTIVE_FORMAL_EXIT_GATE="$exit_gate" \
  -e STATEBUS_ADAPTIVE_FORMAL_TIMEOUT_S="$timeout_seconds" \
  "$container_name" /bin/bash -s <<'CONTAINER_BASH'
set -euo pipefail

source /workspace/statebus/project/docker/activate_statebus_container.sh
cd /workspace/statebus/project
mkdir -p "$STATEBUS_ADAPTIVE_FORMAL_RESULT_ROOT"

health_url="${STATEBUS_LOCAL_VLLM_BASE_URL%/v1}/health"
curl -fsS "$health_url" >/dev/null
printf '[adaptive-formal] vLLM health: OK (%s)\n' "$health_url"

python3 - <<'PY'
import os
import torch

device = os.environ["STATEBUS_EMBED_DEVICE"]
if not torch.cuda.is_available():
    raise SystemExit("PyTorch CUDA is unavailable")
probe = torch.arange(8, device=device).sum().item()
print(f"[adaptive-formal] CUDA: OK device={device} count={torch.cuda.device_count()} probe={probe}")
PY

python3 scripts/diagnostics/check_codeact_bwrap_sandbox.py \
  > "$STATEBUS_ADAPTIVE_FORMAL_RESULT_ROOT/bwrap_readiness.json"
python3 - "$STATEBUS_ADAPTIVE_FORMAL_RESULT_ROOT/bwrap_readiness.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], "r", encoding="utf-8"))
readiness = payload.get("llm_bwrap_readiness", {})
if not payload.get("ok") or not readiness.get("ready") or readiness.get("actual_backend") != "bwrap":
    raise SystemExit("LLM bwrap readiness did not pass")
if int(readiness.get("sandbox_uid", 0)) == 0 or int(readiness.get("sandbox_gid", 0)) == 0:
    raise SystemExit("LLM bwrap sandbox identity must be non-root")
PY
printf '[adaptive-formal] bwrap readiness: OK\n'

python3 -m pytest -q \
  tests/test_llm_codeact_policy.py \
  tests/test_adaptive_formal_compare.py \
  tests/test_adaptive_codeact_integration.py \
  > "$STATEBUS_ADAPTIVE_FORMAL_RESULT_ROOT/pytest.log" 2>&1
printf '[adaptive-formal] focused pytest: OK\n'

args=(
  --output-root "$STATEBUS_ADAPTIVE_FORMAL_RESULT_ROOT"
  --embedding-model-path "$STATEBUS_EMBED_MODEL_PATH"
  --embedding-device "$STATEBUS_EMBED_DEVICE"
  --max-cases "$STATEBUS_ADAPTIVE_FORMAL_MAX_CASES"
  --lane "$STATEBUS_ADAPTIVE_FORMAL_LANE"
  --quality-threshold "$STATEBUS_ADAPTIVE_FORMAL_QUALITY_THRESHOLD"
  --exit-gate "$STATEBUS_ADAPTIVE_FORMAL_EXIT_GATE"
)
if [[ -n "${STATEBUS_ADAPTIVE_FORMAL_CASE_IDS:-}" ]]; then
  IFS=',' read -r -a selected_case_ids <<< "$STATEBUS_ADAPTIVE_FORMAL_CASE_IDS"
  for case_id in "${selected_case_ids[@]}"; do
    [[ -n "$case_id" ]] && args+=(--case-id "$case_id")
  done
fi
if [[ "${STATEBUS_ADAPTIVE_FORMAL_FAIL_FAST:-0}" == "1" ]]; then
  args+=(--fail-fast)
fi

printf '[adaptive-formal] starting serialized formal comparison\n'
timeout "$STATEBUS_ADAPTIVE_FORMAL_TIMEOUT_S" \
  python3 scripts/diagnostics/run_adaptive_formal_compare.py "${args[@]}" \
  > "$STATEBUS_ADAPTIVE_FORMAL_RESULT_ROOT/console.log" 2>&1
CONTAINER_BASH

latest_summary="$(
  rg --files "$host_result_root" \
    | rg '/adaptive_formal_compare_[^/]+/summary\.json$' \
    | sort \
    | tail -n 1
)"
if [[ -z "$latest_summary" ]]; then
  printf '[adaptive-formal] summary.json was not produced under %s\n' "$host_result_root" >&2
  exit 2
fi
printf '[adaptive-formal] PASS\n'
printf '[adaptive-formal] summary: %s\n' "$latest_summary"
printf '[adaptive-formal] report: %s\n' "${latest_summary%/summary.json}/summary.md"
