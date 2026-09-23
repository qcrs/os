#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
OS_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
HOST_RUNS_ROOT="${STATEBUS_HOST_RUNS_ROOT:-/home/qcrs/statebus/runs}"
CONTAINER_RUNS_ROOT="${STATEBUS_CONTAINER_RUNS_ROOT:-/statebus/runs}"
CONTAINER_NAME="${STATEBUS_CONTAINER_NAME:-statebus-runtime}"
DEFAULT_B2_HOME_HOST="${STATEBUS_B2_HOME_HOST:-$HOME/statebus/work/${CONTAINER_NAME}-container}"
STAMP="${STATEBUS_LOCAL_VLLM_FORMAL_STAMP:-$(date +%Y%m%d_%H%M%S)}"
MODEL_SLUG_RAW="${STATEBUS_LOCAL_VLLM_MODEL:-${STATEBUS_VLLM_SERVED_MODEL_NAME:-qwen3-32b}}"
MODEL_SLUG="$(printf '%s' "$MODEL_SLUG_RAW" | sed 's/[^A-Za-z0-9._-]/-/g')"
SUITE="${STATEBUS_LOCAL_VLLM_FORMAL_SUITE:-formal}"
BENCHMARK_TIER="${STATEBUS_LOCAL_VLLM_FORMAL_BENCHMARK_TIER:-dev}"
RUN_ID="${STATEBUS_LOCAL_VLLM_FORMAL_RUN_ID:-statebus-local-vllm-${MODEL_SLUG}-${BENCHMARK_TIER}-${STAMP}}"
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

# Stage 2 is a separate bounded pilot contract.  Keep it out of live_runner's
# formal/dev tier parser so the ordinary formal suite cannot be mistaken for
# the four-lane live-vLLM pilot.
if [[ "$SUITE" == "stage2-pilot" ]]; then
  STAGE2_HOST_RUNS_ROOT="${STATEBUS_STAGE2_HOST_RUNS_ROOT:-${HOST_RUNS_ROOT}}"
  STAGE2_HOST_RUN_ROOT="${STAGE2_HOST_RUNS_ROOT}/${RUN_ID}"
  STAGE2_STDOUT_LOG="${STAGE2_HOST_RUN_ROOT}/stage2_pilot.stdout.log"
  STAGE2_STDERR_JSON="${STAGE2_HOST_RUN_ROOT}/stage2_pilot.stderr.log"
  VERIFY_LOG="${STAGE2_HOST_RUN_ROOT}/container_verify.log"
  DRY_RUN="${STATEBUS_LOCAL_VLLM_FORMAL_DRY_RUN:-0}"
  TIMEOUT_S="${STATEBUS_LOCAL_VLLM_FORMAL_TIMEOUT_S:-}"
  REPEATS="${STATEBUS_LOCAL_VLLM_FORMAL_REPEATS:-2}"
  STAGE2_CASE_IDS="${STATEBUS_STAGE2_CASE_IDS:-}"
  STAGE2_FAMILY_IDS="${STATEBUS_STAGE2_FAMILY_IDS:-}"
  STAGE2_LANE_IDS="${STATEBUS_STAGE2_LANE_IDS:-}"
  STAGE2_MAX_CASES_PER_FAMILY="${STATEBUS_STAGE2_MAX_CASES_PER_FAMILY:-0}"
  embedding_device="${STATEBUS_G6B2_EMBEDDING_DEVICE:-${STATEBUS_EMBED_DEVICE:-cuda:0}}"
  [[ "$DRY_RUN" == "0" || "$DRY_RUN" == "1" ]] || {
    printf '[statebus-local-vllm-formal] invalid STATEBUS_LOCAL_VLLM_FORMAL_DRY_RUN=%s (expected 0 or 1)\n' "$DRY_RUN" >&2
    exit 2
  }
  [[ "$RUN_ID" =~ ^[A-Za-z0-9._-]+$ ]] || {
    printf '[statebus-local-vllm-formal] invalid run id: %s\n' "$RUN_ID" >&2
    exit 2
  }
  if [[ -n "$TIMEOUT_S" ]]; then
    if ! [[ "$TIMEOUT_S" =~ ^[0-9]+([.][0-9]+)?$ ]] || [[ "$TIMEOUT_S" =~ ^0+([.]0+)?$ ]]; then
      printf '[statebus-local-vllm-formal] invalid STATEBUS_LOCAL_VLLM_FORMAL_TIMEOUT_S=%s\n' "$TIMEOUT_S" >&2
      exit 2
    fi
  fi
  if ! [[ "$REPEATS" =~ ^[1-9][0-9]*$ ]]; then
    printf '[statebus-local-vllm-formal] invalid STATEBUS_LOCAL_VLLM_FORMAL_REPEATS=%s\n' "$REPEATS" >&2
    exit 2
  fi
  if ! [[ "$STAGE2_MAX_CASES_PER_FAMILY" =~ ^[0-9]+$ ]]; then
    printf '[statebus-local-vllm-formal] invalid STATEBUS_STAGE2_MAX_CASES_PER_FAMILY=%s\n' "$STAGE2_MAX_CASES_PER_FAMILY" >&2
    exit 2
  fi
  if [[ -n "$STAGE2_CASE_IDS" && -n "$STAGE2_FAMILY_IDS" ]]; then
    printf '[statebus-local-vllm-formal] STATEBUS_STAGE2_CASE_IDS and STATEBUS_STAGE2_FAMILY_IDS are mutually exclusive\n' >&2
    exit 2
  fi
  mkdir -p "$STAGE2_HOST_RUNS_ROOT"
  if ! mkdir "$STAGE2_HOST_RUN_ROOT" 2>/dev/null; then
    printf '[statebus-local-vllm-formal] stage2 run root must be new: %s\n' "$STAGE2_HOST_RUN_ROOT" >&2
    exit 2
  fi

  set +e
  "$SCRIPT_DIR/run_g6b2_os_container.sh" verify >"$VERIFY_LOG" 2>&1
  verify_status=$?
  set -e
  if (( verify_status != 0 )); then
    printf '[statebus-local-vllm-formal] container verify failed; runner was not started\n' >&2
    printf '[statebus-local-vllm-formal] verify_log=%s\n' "$VERIFY_LOG" >&2
    exit "$verify_status"
  fi

  STAGE2_CONTAINER_RUN_ROOT="$("$SCRIPT_DIR/run_g6b2_os_container.sh" map-path "$STAGE2_HOST_RUN_ROOT")" || {
    printf '[statebus-local-vllm-formal] stage2 run root is not visible in statebus-runtime: %s\n' "$STAGE2_HOST_RUN_ROOT" >&2
    exit 2
  }
  STAGE2_CONTAINER_ROOT="${STAGE2_CONTAINER_RUN_ROOT}/stage2-pilot"
  stage2_args=(
    python3 -m statebus.benchmark.stage2_pilot
    --output-root "$STAGE2_CONTAINER_ROOT"
    --embedding-device "$embedding_device"
    --run-id "$RUN_ID"
    --repeats "$REPEATS"
    --max-cases-per-family "$STAGE2_MAX_CASES_PER_FAMILY"
  )
  if [[ -n "$STAGE2_CASE_IDS" ]]; then
    IFS=',' read -r -a stage2_case_ids <<<"$STAGE2_CASE_IDS"
    for case_id in "${stage2_case_ids[@]}"; do
      [[ -n "$case_id" ]] && stage2_args+=(--case-id "$case_id")
    done
  fi
  if [[ -n "$STAGE2_FAMILY_IDS" ]]; then
    IFS=',' read -r -a stage2_family_ids <<<"$STAGE2_FAMILY_IDS"
    for family_id in "${stage2_family_ids[@]}"; do
      [[ -n "$family_id" ]] && stage2_args+=(--family-id "$family_id")
    done
  fi
  if [[ -n "$STAGE2_LANE_IDS" ]]; then
    IFS=',' read -r -a stage2_lane_ids <<<"$STAGE2_LANE_IDS"
    for lane_id in "${stage2_lane_ids[@]}"; do
      [[ -n "$lane_id" ]] && stage2_args+=(--lane "$lane_id")
    done
  fi
  [[ "$DRY_RUN" == "1" ]] && stage2_args+=(--dry-run)
  [[ -n "$TIMEOUT_S" ]] && stage2_args+=(--timeout-s "$TIMEOUT_S")

  set +e
  "$SCRIPT_DIR/run_g6b2_os_container.sh" exec "${stage2_args[@]}" >"$STAGE2_STDOUT_LOG" 2>"$STAGE2_STDERR_JSON"
  stage2_status=$?
  set -e
  echo "[statebus-local-vllm-formal] run_root=$STAGE2_HOST_RUN_ROOT"
  echo "[statebus-local-vllm-formal] stage2_output_root=${STAGE2_HOST_RUN_ROOT}/stage2-pilot"
  echo "[statebus-local-vllm-formal] stage2_stdout_log=$STAGE2_STDOUT_LOG"
  echo "[statebus-local-vllm-formal] stage2_stderr_log=$STAGE2_STDERR_JSON"
  echo "[statebus-local-vllm-formal] verify_log=$VERIFY_LOG"
  exit "$stage2_status"
fi

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
/usr/bin/python3 -m statebus.benchmark.live_runner \
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
./scripts/run_local_vllm_container_check.sh /bin/bash -lc "$container_command"

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
