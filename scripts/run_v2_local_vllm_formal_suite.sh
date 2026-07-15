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
CASE_ID="${STATEBUS_LOCAL_VLLM_FORMAL_CASE_ID:-}"
LAYER="${STATEBUS_LOCAL_VLLM_FORMAL_LAYER:-}"
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

case_id_arg=""
if [[ -n "$CASE_ID" ]]; then
  case_id_arg="--case-id '${CASE_ID}'"
fi

layer_arg=""
if [[ -n "$LAYER" ]]; then
  layer_arg="--layer '${LAYER}'"
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
  ${case_id_arg} \
  ${layer_arg} \
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
  suite_type: (if .layers != null then "statebus_or_formal" else "compare" end),

  # --- statebus / formal suite fields (null for compare suite) ---
  selected_case_count,
  available_case_count,
  layers: (
    if .layers != null then
      [.layers[] | {
        layer,
        case_count: .aggregated_metrics.case_count,
        quality_floor_pass_count: .aggregated_metrics.quality_floor_pass_count
      }]
    else null end
  ),

  # --- compare suite fields (null for statebus/formal suite) ---
  formal_compare_case_count,
  formal_compare_family_count,
  formal_external_claim_kind,
  formal_quality_superiority_claim_allowed,
  formal_superiority_claim_allowed,
  strict_equal_quality_comparison_valid,
  mode_reports: (
    if .mode_reports != null then
      [.mode_reports[] | {
        role_path_mode,
        comparison_valid,
        invalid_reason
      }]
    else null end
  ),

  # --- comparison_summary: statebus/formal keys and compare keys coexist (null-safe) ---
  comparison_summary: {
    protocol_L3_total_tokens:              .comparison_summary.protocol_L3_total_tokens,
    text_L0_total_tokens:                  .comparison_summary.text_L0_total_tokens,
    protocol_vs_text_token_delta:          .comparison_summary.protocol_vs_text_token_delta,
    protocol_L3_prompt_tokens:             .comparison_summary.protocol_L3_prompt_tokens,
    text_L0_prompt_tokens:                 .comparison_summary.text_L0_prompt_tokens,
    protocol_vs_text_prompt_token_delta:   .comparison_summary.protocol_vs_text_prompt_token_delta,
    protocol_L3_control_bytes:             .comparison_summary.protocol_L3_control_bytes,
    text_L0_control_bytes:                 .comparison_summary.text_L0_control_bytes,
    protocol_vs_text_control_bytes_delta:  .comparison_summary.protocol_vs_text_control_bytes_delta,
    local_vllm_llm_total_tokens_delta:     .comparison_summary.local_vllm_llm_total_tokens_delta,
    local_vllm_prompt_tokens_delta:        .comparison_summary.local_vllm_prompt_tokens_delta,
    local_vllm_completion_tokens_delta:    .comparison_summary.local_vllm_completion_tokens_delta,
    local_vllm_statebus_llm_total_tokens:  .comparison_summary.local_vllm_statebus_llm_total_tokens,
    local_vllm_external_llm_total_tokens:  .comparison_summary.local_vllm_external_llm_total_tokens,
    local_vllm_statebus_quality_floor_pass_count: (
      .comparison_summary.local_vllm_statebus_quality_floor_pass_count
      // .comparison_summary.local_vllm_debug_statebus_quality_floor_pass_count
    ),
    local_vllm_external_quality_floor_pass_count: (
      .comparison_summary.local_vllm_external_quality_floor_pass_count
      // .comparison_summary.local_vllm_debug_external_quality_floor_pass_count
    ),
    local_vllm_debug_quality_floor_pass_delta: .comparison_summary.local_vllm_debug_quality_floor_pass_delta
  },

  metadata: {
    benchmark_tier:     (.metadata.benchmark_tier     // .benchmark_tier),
    role_path_mode:     (.metadata.role_path_mode     // null),
    embedding_mode:     (.metadata.embedding_mode     // null),
    state_pool_mode_used: (.metadata.state_pool_mode_used // null),
    transport:          (.metadata.transport          // null),
    local_vllm_model:   $local_vllm_model,
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
