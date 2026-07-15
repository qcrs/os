#!/usr/bin/env bash
set -euo pipefail

STAMP="${STATEBUS_LIVE_SMOKE_STAMP:-$(date +%Y%m%d_%H%M%S)}"
HOST_RUNS_ROOT="${STATEBUS_HOST_RUNS_ROOT:-/home/qcrs/statebus/runs}"
CONTAINER_RUNS_ROOT="${STATEBUS_CONTAINER_RUNS_ROOT:-/statebus/runs}"
OUT_ROOT="${HOST_RUNS_ROOT}/live_smoke_qwen3_${STAMP}"
mkdir -p "$OUT_ROOT"

export STATEBUS_LOCAL_VLLM_BASE_URL="${STATEBUS_LOCAL_VLLM_BASE_URL:-http://127.0.0.1:53334/v1}"
export STATEBUS_LOCAL_VLLM_MODEL="${STATEBUS_LOCAL_VLLM_MODEL:-qwen3-32b}"
export STATEBUS_VLLM_SERVED_MODEL_NAME="${STATEBUS_VLLM_SERVED_MODEL_NAME:-qwen3-32b}"
export STATEBUS_EMBED_DEVICE="${STATEBUS_EMBED_DEVICE:-cuda:1}"
export STATEBUS_EMBED_MODEL_PATH="${STATEBUS_EMBED_MODEL_PATH:-/statebus/models/Qwen3-Embedding-0.6B}"
export STATEBUS_PREFIX_ALIGNMENT_MODE="${STATEBUS_PREFIX_ALIGNMENT_MODE:-shared_evidence_prefix}"
export STATEBUS_EVIDENCE_DYNAMIC_PRUNING_ENABLED="${STATEBUS_EVIDENCE_DYNAMIC_PRUNING_ENABLED:-1}"
export STATEBUS_LOCAL_VLLM_REQUEST_TIMEOUT_S="${STATEBUS_LOCAL_VLLM_REQUEST_TIMEOUT_S:-90}"
export STATEBUS_LOCAL_VLLM_PLANNER_MAX_TOKENS="${STATEBUS_LOCAL_VLLM_PLANNER_MAX_TOKENS:-384}"
export STATEBUS_LOCAL_VLLM_RETRIEVER_MAX_TOKENS="${STATEBUS_LOCAL_VLLM_RETRIEVER_MAX_TOKENS:-384}"
export STATEBUS_LOCAL_VLLM_EXECUTOR_MAX_TOKENS="${STATEBUS_LOCAL_VLLM_EXECUTOR_MAX_TOKENS:-512}"
export STATEBUS_LOCAL_VLLM_SUMMARIZER_MAX_TOKENS="${STATEBUS_LOCAL_VLLM_SUMMARIZER_MAX_TOKENS:-512}"

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "${OUT_ROOT}/run.log"; }

run_live() {
  local stage="$1"
  local run_id="$2"
  local args="$3"
  local container_root="${CONTAINER_RUNS_ROOT}/${run_id}"
  local host_root="${HOST_RUNS_ROOT}/${run_id}"
  mkdir -p "$host_root"
  STATEBUS_LOCAL_VLLM_CHECK_RUN_ID="$run_id" \
    ./scripts/run_v2_local_vllm_container_check.sh /bin/bash -lc "
mkdir -p '${container_root}'
/usr/bin/python3 -m v2.benchmark.live_runner ${args} \\
  --role-path-mode local_vllm \\
  --embedding-mode local \\
  --state-pool-mode auto \\
  --workspace-root '${container_root}/workspaces' \\
  --runtime-root '${container_root}/runtime' \\
  --socket-path '${container_root}/control.sock' \\
  --suite-id '${run_id}' \\
  > '${container_root}/stdout.json'
" > "${OUT_ROOT}/${stage}.log" 2>&1
  test -s "${host_root}/stdout.json"
  jq -e . "${host_root}/stdout.json" > /dev/null
  log "DONE ${stage} runner"
}

log "Live Smoke start: ${STAMP}"
curl -sf "${STATEBUS_LOCAL_VLLM_BASE_URL%/v1}/health" > "${OUT_ROOT}/vllm_health.json"

PREFLIGHT_ID="smoke-preflight-${STAMP}"
run_live preflight "$PREFLIGHT_ID" "--suite preflight --benchmark-tier dev"
jq -e '.ok == true' "${HOST_RUNS_ROOT}/${PREFLIGHT_ID}/stdout.json" > /dev/null
log "PASS preflight gate"

COMPARE_ID="smoke-compare-${STAMP}"
run_live compare "$COMPARE_ID" \
  "--suite compare --benchmark-tier formal --case-id benchmark-sample-7 --max-cases 1"
COMPARE_JSON="${HOST_RUNS_ROOT}/${COMPARE_ID}/stdout.json"
jq -e '
  .execution_scope == "diagnostic_partial" and
  .selected_case_count == 1 and
  .strict_equal_quality_comparison_valid == true and
  ((.comparison_summary.local_vllm_statebus_quality_floor_pass_count //
     .comparison_summary.local_vllm_debug_statebus_quality_floor_pass_count // 0) == 1) and
  ((.comparison_summary.local_vllm_external_quality_floor_pass_count //
     .comparison_summary.local_vllm_debug_external_quality_floor_pass_count // 0) == 1)
' "$COMPARE_JSON" > /dev/null
LOGIT_METRICS=$(find "${HOST_RUNS_ROOT}/${COMPARE_ID}" -path '*benchmark-sample-7/logs/task_metrics.json' -print -quit)
test -n "$LOGIT_METRICS"
jq -e '
  (.logit_state_transfer_count // 0) > 0 and
  (.logit_sequence_length // 0) > 0 and
  (.logit_peak_position // -1) >= 0 and
  (.logit_peak_position < .logit_sequence_length)
' "$LOGIT_METRICS" > /dev/null
log "PASS compare + Track C + logit gates"

REPLAY_ID="smoke-replay-${STAMP}"
run_live replay "$REPLAY_ID" \
  "--suite statebus --benchmark-tier formal --statebus-mode replay-ready --case-id benchmark-sample-7 --max-cases 1 --layer L3"
jq -e '
  .execution_scope == "diagnostic_partial" and
  .effective_statebus_mode == "replay_ready" and
  .effective_replay_history_source == "history_bootstrap" and
  .aggregated_metrics.case_count == 1 and
  .aggregated_metrics.quality_floor_pass_count == 1 and
  (((.telemetry_summary.validated_replay_count // 0) +
    (.telemetry_summary.exact_replay_count // 0)) > 0) and
  (.telemetry_summary.skipped_step_count // 0) > 0
' "${HOST_RUNS_ROOT}/${REPLAY_ID}/stdout.json" > /dev/null
log "PASS replay gate"

CSV_ID="smoke-continuous-csv-${STAMP}"
run_live continuous_csv "$CSV_ID" \
  "--suite continuous --family csv_table_profile --max-cases 2 --layer L3"
jq -e '
  .selected_round_count == 2 and
  .available_round_count == 10 and
  .aggregated_metrics.case_count == 2 and
  .aggregated_metrics.quality_floor_pass_count == 2 and
  (.telemetry_summary.history_runtime_root_count // 0) > 0
' "${HOST_RUNS_ROOT}/${CSV_ID}/stdout.json" > /dev/null
log "PASS continuous csv gate"

CROSS_ID="smoke-continuous-cross-${STAMP}"
run_live continuous_cross "$CROSS_ID" \
  "--suite continuous --family cross_period_financial --max-cases 2 --layer L3"
jq -e '
  .selected_round_count == 2 and
  .aggregated_metrics.case_count == 2 and
  .aggregated_metrics.quality_floor_pass_count == 2 and
  (.telemetry_summary.validated_replay_count // 0) >= 1 and
  (.telemetry_summary.skipped_step_count // 0) >= 1
' "${HOST_RUNS_ROOT}/${CROSS_ID}/stdout.json" > /dev/null
log "PASS continuous cross-period gate"

FORMAL_ID="smoke-formal-${STAMP}"
run_live formal "$FORMAL_ID" \
  "--suite formal --benchmark-tier formal --case-id formal-trend-003 --max-cases 1"
jq -e '
  .execution_scope == "diagnostic_partial" and
  .selected_case_count == 1 and
  (.layers | length) == 4 and
  ([.layers[] | select(
    .aggregated_metrics.case_count == 1 and
    .aggregated_metrics.quality_floor_pass_count == 1
  )] | length) == 4
' "${HOST_RUNS_ROOT}/${FORMAL_ID}/stdout.json" > /dev/null
log "PASS formal report gate"

jq -n \
  --arg stamp "$STAMP" \
  --arg out_root "$OUT_ROOT" \
  --arg compare "$COMPARE_JSON" \
  --arg replay "${HOST_RUNS_ROOT}/${REPLAY_ID}/stdout.json" \
  --arg csv "${HOST_RUNS_ROOT}/${CSV_ID}/stdout.json" \
  --arg cross "${HOST_RUNS_ROOT}/${CROSS_ID}/stdout.json" \
  --arg formal "${HOST_RUNS_ROOT}/${FORMAL_ID}/stdout.json" \
  '{overall_ok: true, execution_scope: "diagnostic", stamp: $stamp, out_root: $out_root,
    reports: {compare: $compare, replay: $replay, continuous_csv: $csv,
              continuous_cross: $cross, formal: $formal}}' \
  > "${OUT_ROOT}/summary.json"

log "Live Smoke PASS: ${OUT_ROOT}/summary.json"
