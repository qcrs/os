#!/usr/bin/env bash
set -euo pipefail

HOST_RUNS_ROOT="${STATEBUS_HOST_RUNS_ROOT:-/home/qcrs/statebus/runs}"
CONTAINER_RUNS_ROOT="${STATEBUS_CONTAINER_RUNS_ROOT:-/statebus/runs}"
STAMP="${STATEBUS_LOCAL_VLLM_FORMAL_STAMP:-$(date +%Y%m%d_%H%M%S)}"
MODEL_SLUG_RAW="${STATEBUS_LOCAL_VLLM_MODEL:-${STATEBUS_VLLM_SERVED_MODEL_NAME:-qwen3-8b}}"
MODEL_SLUG="$(printf '%s' "$MODEL_SLUG_RAW" | sed 's/[^A-Za-z0-9._-]/-/g')"
SUITE="${STATEBUS_LOCAL_VLLM_FORMAL_SUITE:-formal}"
BENCHMARK_TIER="${STATEBUS_LOCAL_VLLM_FORMAL_BENCHMARK_TIER:-dev}"
RUN_ID="${STATEBUS_LOCAL_VLLM_FORMAL_RUN_ID:-v2-local-vllm-${MODEL_SLUG}-${BENCHMARK_TIER}-${STAMP}}"
RUN_ROOT="${HOST_RUNS_ROOT}/${RUN_ID}"
CONTAINER_RUN_ROOT="${CONTAINER_RUNS_ROOT}/${RUN_ID}"
MAX_CASES="${STATEBUS_LOCAL_VLLM_FORMAL_MAX_CASES:-}"
ROLE_PATH_MODE="${STATEBUS_LOCAL_VLLM_FORMAL_ROLE_PATH_MODE:-local_vllm}"
EMBEDDING_MODE="${STATEBUS_LOCAL_VLLM_FORMAL_EMBEDDING_MODE:-deterministic}"
STATE_POOL_MODE="${STATEBUS_LOCAL_VLLM_FORMAL_STATE_POOL_MODE:-auto}"
TRANSPORT="${STATEBUS_LOCAL_VLLM_FORMAL_TRANSPORT:-loopback}"
STDOUT_JSON="${RUN_ROOT}/formal_suite.stdout.json"
SUMMARY_JSON="${RUN_ROOT}/formal_suite.summary.json"
CONTAINER_STDOUT_JSON="${CONTAINER_RUN_ROOT}/formal_suite.stdout.json"
CONTAINER_SOCKET_PATH="${CONTAINER_RUN_ROOT}/control.sock"
AF_UNIX_SOCKET_PATH_MAX_BYTES="${STATEBUS_AF_UNIX_SOCKET_PATH_MAX_BYTES:-107}"

mkdir -p "$RUN_ROOT"

socket_path_bytes="$(printf '%s' "$CONTAINER_SOCKET_PATH" | wc -c | tr -d ' ')"
if (( socket_path_bytes > AF_UNIX_SOCKET_PATH_MAX_BYTES )); then
  echo "[statebus-local-vllm-formal] AF_UNIX path too long: bytes=${socket_path_bytes} max=${AF_UNIX_SOCKET_PATH_MAX_BYTES} path=${CONTAINER_SOCKET_PATH}" >&2
  echo "[statebus-local-vllm-formal] shorten STATEBUS_LOCAL_VLLM_FORMAL_RUN_ID or STATEBUS_CONTAINER_RUNS_ROOT" >&2
  exit 2
fi

max_cases_arg=""
if [[ -n "$MAX_CASES" ]]; then
  max_cases_arg="--max-cases '${MAX_CASES}'"
fi

container_command="
/usr/bin/python3 -m v2.benchmark.live_runner \
  --suite '${SUITE}' \
  --benchmark-tier '${BENCHMARK_TIER}' \
  --role-path-mode '${ROLE_PATH_MODE}' \
  --embedding-mode '${EMBEDDING_MODE}' \
  --state-pool-mode '${STATE_POOL_MODE}' \
  --transport '${TRANSPORT}' \
  ${max_cases_arg} \
  --workspace-root '${CONTAINER_RUN_ROOT}/workspaces' \
  --runtime-root '${CONTAINER_RUN_ROOT}/runtime' \
  --socket-path '${CONTAINER_SOCKET_PATH}' \
  --suite-id '${RUN_ID}' \
  > '${CONTAINER_STDOUT_JSON}'
"

STATEBUS_LOCAL_VLLM_CHECK_RUN_ID="$RUN_ID" \
./scripts/run_v2_local_vllm_container_check.sh /bin/bash -lc "$container_command"

jq --arg host_run_root "${RUN_ROOT}" \
   --arg container_run_root "${CONTAINER_RUN_ROOT}" \
   --arg run_id "${RUN_ID}" \
   --arg local_vllm_model "${STATEBUS_LOCAL_VLLM_MODEL:-${STATEBUS_VLLM_SERVED_MODEL_NAME:-}}" \
   --arg local_vllm_base_url "${STATEBUS_LOCAL_VLLM_BASE_URL:-}" '{
  run_id: $run_id,
  selected_case_count,
  available_case_count,
  layers: [.layers[] | {
    layer,
    case_count: .aggregated_metrics.case_count,
    quality_floor_pass_count: .aggregated_metrics.quality_floor_pass_count
  }],
  comparison_summary: {
    protocol_L3_total_tokens: .comparison_summary.protocol_L3_total_tokens,
    text_L0_total_tokens: .comparison_summary.text_L0_total_tokens,
    protocol_vs_text_token_delta: .comparison_summary.protocol_vs_text_token_delta,
    protocol_L3_prompt_tokens: .comparison_summary.protocol_L3_prompt_tokens,
    text_L0_prompt_tokens: .comparison_summary.text_L0_prompt_tokens,
    protocol_vs_text_prompt_token_delta: .comparison_summary.protocol_vs_text_prompt_token_delta,
    protocol_L3_control_bytes: .comparison_summary.protocol_L3_control_bytes,
    text_L0_control_bytes: .comparison_summary.text_L0_control_bytes,
    protocol_vs_text_control_bytes_delta: .comparison_summary.protocol_vs_text_control_bytes_delta
  },
  metadata: {
    benchmark_tier: .metadata.benchmark_tier,
    role_path_mode: .metadata.role_path_mode,
    embedding_mode: .metadata.embedding_mode,
    state_pool_mode_used: .metadata.state_pool_mode_used,
    transport: .metadata.transport,
    local_vllm_model: $local_vllm_model,
    local_vllm_base_url: $local_vllm_base_url
  },
  report_path: (
    if (.report_path | type) == "string" and (.report_path | startswith($container_run_root))
    then $host_run_root + (.report_path | ltrimstr($container_run_root))
    else .report_path
    end
  ),
  container_report_path: .report_path
}' "$STDOUT_JSON" > "$SUMMARY_JSON"

echo "[statebus-local-vllm-formal] run_root=$RUN_ROOT"
echo "[statebus-local-vllm-formal] stdout_json=$STDOUT_JSON"
echo "[statebus-local-vllm-formal] summary_json=$SUMMARY_JSON"
