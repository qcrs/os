#!/usr/bin/env bash
set -euo pipefail

HOST_RUNS_ROOT="${STATEBUS_HOST_RUNS_ROOT:-/home/qcrs/statebus/runs}"
CONTAINER_RUNS_ROOT="${STATEBUS_CONTAINER_RUNS_ROOT:-/statebus/runs}"
STAMP="${STATEBUS_LOCAL_VLLM_MINI_FORMAL_STAMP:-$(date +%Y%m%d_%H%M%S)}"
RUN_ID="${STATEBUS_LOCAL_VLLM_MINI_FORMAL_RUN_ID:-v2-local-vllm-mini-formal-${STAMP}}"
RUN_ROOT="${HOST_RUNS_ROOT}/${RUN_ID}"
CONTAINER_RUN_ROOT="${CONTAINER_RUNS_ROOT}/${RUN_ID}"
MAX_CASES="${STATEBUS_LOCAL_VLLM_MINI_FORMAL_MAX_CASES:-5}"
BENCHMARK_TIER="${STATEBUS_LOCAL_VLLM_MINI_FORMAL_BENCHMARK_TIER:-dev}"
SUITE="${STATEBUS_LOCAL_VLLM_MINI_FORMAL_SUITE:-formal}"
ROLE_PATH_MODE="${STATEBUS_LOCAL_VLLM_MINI_FORMAL_ROLE_PATH_MODE:-local_vllm}"
EMBEDDING_MODE="${STATEBUS_LOCAL_VLLM_MINI_FORMAL_EMBEDDING_MODE:-deterministic}"
STATE_POOL_MODE="${STATEBUS_LOCAL_VLLM_MINI_FORMAL_STATE_POOL_MODE:-auto}"
TRANSPORT="${STATEBUS_LOCAL_VLLM_MINI_FORMAL_TRANSPORT:-loopback}"
STDOUT_JSON="${RUN_ROOT}/mini_formal.stdout.json"
SUMMARY_JSON="${RUN_ROOT}/mini_formal.summary.json"

mkdir -p "$RUN_ROOT"

container_command="
/usr/bin/python3 -m v2.benchmark.live_runner \
  --suite '${SUITE}' \
  --benchmark-tier '${BENCHMARK_TIER}' \
  --role-path-mode '${ROLE_PATH_MODE}' \
  --embedding-mode '${EMBEDDING_MODE}' \
  --state-pool-mode '${STATE_POOL_MODE}' \
  --transport '${TRANSPORT}' \
  --max-cases '${MAX_CASES}' \
  --workspace-root '${CONTAINER_RUN_ROOT}/workspaces' \
  --runtime-root '${CONTAINER_RUN_ROOT}/runtime' \
  --socket-path '${CONTAINER_RUN_ROOT}/control.sock' \
  --suite-id '${RUN_ID}' \
  > '${CONTAINER_RUN_ROOT}/mini_formal.stdout.json'
"

STATEBUS_LOCAL_VLLM_CHECK_RUN_ID="$RUN_ID" \
./scripts/run_v2_local_vllm_container_check.sh /bin/bash -lc "$container_command"

jq --arg host_run_root "${RUN_ROOT}" \
   --arg container_run_root "${CONTAINER_RUN_ROOT}" \
   --arg run_id "${RUN_ID}" '{
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
    transport: .metadata.transport
  },
  report_path: (
    if (.report_path | type) == "string" and (.report_path | startswith($container_run_root))
    then $host_run_root + (.report_path | ltrimstr($container_run_root))
    else .report_path
    end
  ),
  container_report_path: .report_path
}' "$STDOUT_JSON" > "$SUMMARY_JSON"

echo "[statebus-local-vllm-mini-formal] run_root=$RUN_ROOT"
echo "[statebus-local-vllm-mini-formal] stdout_json=$STDOUT_JSON"
echo "[statebus-local-vllm-mini-formal] summary_json=$SUMMARY_JSON"
