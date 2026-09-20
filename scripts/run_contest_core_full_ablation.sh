#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKSPACE_ROOT="$(cd "$OS_ROOT/.." && pwd)"
CONTAINER_RUNNER="$OS_ROOT/scripts/run_g6b2_os_container.sh"
LIVE_RUNNER="$OS_ROOT/scripts/run_g6b2_live.sh"
SUMMARY_TOOL="$OS_ROOT/tools/measurement/summarize_contest_core_ablation.py"
ANALYSIS_TOOL="$OS_ROOT/tools/measurement/analyze_contest_core_full_ablation.py"

P2_PAYLOAD_COUNT_PER_SIZE=10
P2_REPEATS=3
P2_TIMEOUT_S=20
P4_ROUNDS_PER_FAMILY=10
P4_EPOCHS=3
P4_LIVE_PAIRS=60
P4_LIVE_MAX_DURATION_S=7200
P4_MINIMAL_MAX_DURATION_S=600
SERVICE_RUNTIME_DIR="/home/qcrs/statebus/work/vllm-qwen3-32b-gpu2-u050"
OUTPUT_ROOT=""
SKIP_LIVE=0
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage:
  scripts/run_contest_core_full_ablation.sh [options]

Runs the current contest-core ablations serially:
  P2  3 sizes x 10 payloads x 3 repeats = 90 matched payload groups
  P3  all 8 semantic holdout cases x off/on/consumer_off
  P4  deterministic: 2 families x 10 rounds x 3 epochs = 60 pairs
  P4  live: one qwen3-32b minimal pair, then a 60-pair campaign

The script records every stage exit code and continues after quality/correctness
gate failures. It does not disable validators, delete failed rows, zero-fill
missing metrics, or start/stop/restart/kill vLLM.

Options:
  --output-root DIR              New run root under /home/qcrs/statebus
  --skip-live                    Skip P4 live minimal + 60-pair campaign
                                 (P3 remains live because it requires the model)
  --p4-live-pairs N              P4 live campaign pairs, 1..120 (default: 60)
  --p4-live-max-duration-s N     P4 campaign wall budget (default: 7200)
  --service-runtime-dir DIR      Existing qwen3-32b manager runtime directory
  --dry-run                      Print commands without creating files or running
  -h, --help                     Show this help

Outputs:
  stage_status.tsv
  logs/*.log
  benefit_summary.json
  benefit_summary.md

The orchestrator exits 0 after producing the summary even when individual
stages return nonzero. Inspect stage_status.tsv and the source artifacts.
EOF
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 2
}

positive_integer() {
  [[ "$1" =~ ^[1-9][0-9]*$ ]]
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-root)
      OUTPUT_ROOT="${2:?missing value for --output-root}"
      shift 2
      ;;
    --skip-live)
      SKIP_LIVE=1
      shift
      ;;
    --p4-live-pairs)
      P4_LIVE_PAIRS="${2:?missing value for --p4-live-pairs}"
      shift 2
      ;;
    --p4-live-max-duration-s)
      P4_LIVE_MAX_DURATION_S="${2:?missing value for --p4-live-max-duration-s}"
      shift 2
      ;;
    --service-runtime-dir)
      SERVICE_RUNTIME_DIR="${2:?missing value for --service-runtime-dir}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown option: $1"
      ;;
  esac
done

positive_integer "$P4_LIVE_PAIRS" || die "--p4-live-pairs must be a positive integer"
(( P4_LIVE_PAIRS <= 120 )) || die "--p4-live-pairs must be <= 120"
positive_integer "$P4_LIVE_MAX_DURATION_S" || die "--p4-live-max-duration-s must be a positive integer"

if [[ -z "$OUTPUT_ROOT" ]]; then
  OUTPUT_ROOT="$WORKSPACE_ROOT/work/contest-core-full-ablation-$(date +%Y%m%d_%H%M%S)"
elif [[ "$OUTPUT_ROOT" != /* ]]; then
  OUTPUT_ROOT="$PWD/$OUTPUT_ROOT"
fi
OUTPUT_ROOT="$(realpath -m "$OUTPUT_ROOT")"
case "$OUTPUT_ROOT" in
  "$WORKSPACE_ROOT"/*) ;;
  *) die "--output-root must be under $WORKSPACE_ROOT so P3 can access it in the container" ;;
esac

P2_ROOT="$OUTPUT_ROOT/p2"
P3_ROOT="$OUTPUT_ROOT/p3"
P4_DETERMINISTIC_ROOT="$OUTPUT_ROOT/p4-deterministic"
P4_LIVE_ROOT="$OUTPUT_ROOT/p4-live"
P4_LIVE_MINIMAL_BASE="$P4_LIVE_ROOT/minimal"
P4_LIVE_CAMPAIGN_BASE="$P4_LIVE_ROOT/campaign"
LOG_ROOT="$OUTPUT_ROOT/logs"
STAGE_STATUS="$OUTPUT_ROOT/stage_status.tsv"

print_command() {
  printf '  '
  printf '%q ' "$@"
  printf '\n'
}

if (( DRY_RUN == 1 )); then
  P3_CONTAINER_ROOT="/workspace/statebus/${P3_ROOT#"$WORKSPACE_ROOT"/}"
  printf 'run_root=%s\n' "$OUTPUT_ROOT"
  printf 'commands:\n'
  print_command source "$OS_ROOT/deploy/activate_statebus_host.sh"
  print_command python3 -m statebus.benchmark.low_overhead_ablation \
    --output-root "$P2_ROOT" \
    --payload-count-per-size "$P2_PAYLOAD_COUNT_PER_SIZE" \
    --repeats "$P2_REPEATS" \
    --timeout-s "$P2_TIMEOUT_S"
  print_command "$CONTAINER_RUNNER" exec python3 -m statebus.benchmark.live_runner \
    --suite semantic-state-ablation \
    --role-path-mode local_vllm \
    --embedding-mode local \
    --state-pool-mode shared_memory \
    --transport subprocess \
    --runtime-root "$P3_CONTAINER_ROOT/runtime" \
    --workspace-root "$P3_CONTAINER_ROOT/workspaces"
  for epoch in $(seq 1 "$P4_EPOCHS"); do
    printf -v epoch_name 'epoch-%02d' "$epoch"
    print_command python3 -m statebus.benchmark.memory_ablation \
      --output-root "$P4_DETERMINISTIC_ROOT/$epoch_name" \
      --rounds-per-family "$P4_ROUNDS_PER_FAMILY"
  done
  if (( SKIP_LIVE == 0 )); then
    print_command env STATEBUS_LOCAL_VLLM_MODEL=qwen3-32b \
      STATEBUS_LLM_CONFIG_FILE=/workspace/statebus/os/deploy/statebus_llm.g6b2-qwen3-32b.example \
      STATEBUS_CONTAINER_LLM_CONFIG_FILE=/workspace/statebus/os/deploy/statebus_llm.g6b2-qwen3-32b.example \
      STATEBUS_G6B2_EMBEDDING_MODE=local \
      STATEBUS_G6B2_EMBEDDING_MODEL_PATH=/statebus/models/Qwen3-Embedding-0.6B \
      STATEBUS_G6B2_EMBEDDING_DEVICE=cuda:0 \
      STATEBUS_G6B2_EMBEDDING_PHYSICAL_GPU=1 \
      STATEBUS_EMBED_PHYSICAL_GPU=1 \
      STATEBUS_EMBED_MODEL_PATH=/statebus/models/Qwen3-Embedding-0.6B \
      STATEBUS_EMBED_DEVICE=cuda:0 \
      "$LIVE_RUNNER" minimal \
      --service-runtime-dir "$SERVICE_RUNTIME_DIR" \
      --output-base "$P4_LIVE_MINIMAL_BASE" \
      --max-duration-s "$P4_MINIMAL_MAX_DURATION_S"
    print_command env STATEBUS_LOCAL_VLLM_MODEL=qwen3-32b \
      STATEBUS_LLM_CONFIG_FILE=/workspace/statebus/os/deploy/statebus_llm.g6b2-qwen3-32b.example \
      STATEBUS_CONTAINER_LLM_CONFIG_FILE=/workspace/statebus/os/deploy/statebus_llm.g6b2-qwen3-32b.example \
      STATEBUS_G6B2_EMBEDDING_MODE=local \
      STATEBUS_G6B2_EMBEDDING_MODEL_PATH=/statebus/models/Qwen3-Embedding-0.6B \
      STATEBUS_G6B2_EMBEDDING_DEVICE=cuda:0 \
      STATEBUS_G6B2_EMBEDDING_PHYSICAL_GPU=1 \
      STATEBUS_EMBED_PHYSICAL_GPU=1 \
      STATEBUS_EMBED_MODEL_PATH=/statebus/models/Qwen3-Embedding-0.6B \
      STATEBUS_EMBED_DEVICE=cuda:0 \
      "$LIVE_RUNNER" campaign \
      --minimal-evidence-root '<artifact_root emitted by p4_live_minimal>' \
      --service-runtime-dir "$SERVICE_RUNTIME_DIR" \
      --pairs "$P4_LIVE_PAIRS" \
      --max-duration-s "$P4_LIVE_MAX_DURATION_S" \
      --output-base "$P4_LIVE_CAMPAIGN_BASE"
  fi
  print_command python3 "$SUMMARY_TOOL" --run-root "$OUTPUT_ROOT"
  print_command python3 "$ANALYSIS_TOOL" --run-root "$OUTPUT_ROOT"
  exit 0
fi

[[ ! -e "$OUTPUT_ROOT" ]] || die "output root already exists: $OUTPUT_ROOT"
mkdir -p "$LOG_ROOT"
printf 'stage\tstarted_at\tended_at\tduration_s\texit_code\toutcome\tartifact_root\tlog_path\n' > "$STAGE_STATUS"

cd "$OS_ROOT"
# shellcheck disable=SC1091
source "$OS_ROOT/deploy/activate_statebus_host.sh"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$OS_ROOT"

record_stage() {
  local stage="$1" started="$2" ended="$3" duration="$4" rc="$5"
  local outcome="$6" artifact_root="$7" log_path="$8"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$stage" "$started" "$ended" "$duration" "$rc" "$outcome" \
    "$artifact_root" "$log_path" >> "$STAGE_STATUS"
}

run_stage() {
  local stage="$1" artifact_root="$2"
  shift 2
  local log_path="$LOG_ROOT/$stage.log"
  local started ended start_epoch end_epoch duration rc outcome
  started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  start_epoch="$(date +%s)"
  printf '\n[%s] start\n' "$stage" | tee "$log_path"
  printf '[%s] command:' "$stage" | tee -a "$log_path"
  printf ' %q' "$@" | tee -a "$log_path"
  printf '\n' | tee -a "$log_path"
  set +e
  "$@" 2>&1 | tee -a "$log_path"
  rc="${PIPESTATUS[0]}"
  set -e
  ended="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  end_epoch="$(date +%s)"
  duration="$((end_epoch - start_epoch))"
  outcome="completed"
  (( rc == 0 )) || outcome="nonzero"
  record_stage "$stage" "$started" "$ended" "$duration" "$rc" "$outcome" \
    "$artifact_root" "$log_path"
  printf '[%s] end rc=%s duration_s=%s\n' "$stage" "$rc" "$duration" | tee -a "$log_path"
  if (( rc == 130 || rc == 143 )); then
    return "$rc"
  fi
  return 0
}

record_skipped() {
  local stage="$1" reason="$2" artifact_root="$3"
  local now log_path="$LOG_ROOT/$stage.log"
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '[%s] skipped: %s\n' "$stage" "$reason" | tee "$log_path"
  record_stage "$stage" "$now" "$now" 0 0 "skipped:$reason" "$artifact_root" "$log_path"
}

run_p3() {
  local container_root
  container_root="$("$CONTAINER_RUNNER" map-path "$P3_ROOT")" || return $?
  "$CONTAINER_RUNNER" exec python3 -m statebus.benchmark.live_runner \
    --suite semantic-state-ablation \
    --role-path-mode local_vllm \
    --embedding-mode local \
    --state-pool-mode shared_memory \
    --transport subprocess \
    --runtime-root "$container_root/runtime" \
    --workspace-root "$container_root/workspaces"
}

mkdir -p "$P3_ROOT"
run_stage p2 "$P2_ROOT" \
  python3 -m statebus.benchmark.low_overhead_ablation \
  --output-root "$P2_ROOT" \
  --payload-count-per-size "$P2_PAYLOAD_COUNT_PER_SIZE" \
  --repeats "$P2_REPEATS" \
  --timeout-s "$P2_TIMEOUT_S"

run_stage p3 "$P3_ROOT/runtime/semantic-state-ablation" run_p3

for epoch in $(seq 1 "$P4_EPOCHS"); do
  printf -v epoch_name 'epoch-%02d' "$epoch"
  run_stage "p4_deterministic_$epoch_name" "$P4_DETERMINISTIC_ROOT/$epoch_name" \
    python3 -m statebus.benchmark.memory_ablation \
    --output-root "$P4_DETERMINISTIC_ROOT/$epoch_name" \
    --rounds-per-family "$P4_ROUNDS_PER_FAMILY"
done

LIVE_ENV=(
  STATEBUS_LOCAL_VLLM_MODEL=qwen3-32b
  STATEBUS_LLM_CONFIG_FILE=/workspace/statebus/os/deploy/statebus_llm.g6b2-qwen3-32b.example
  STATEBUS_CONTAINER_LLM_CONFIG_FILE=/workspace/statebus/os/deploy/statebus_llm.g6b2-qwen3-32b.example
  STATEBUS_G6B2_EMBEDDING_MODE=local
  STATEBUS_G6B2_EMBEDDING_MODEL_PATH=/statebus/models/Qwen3-Embedding-0.6B
  STATEBUS_G6B2_EMBEDDING_DEVICE=cuda:0
  STATEBUS_G6B2_EMBEDDING_PHYSICAL_GPU=1
  STATEBUS_EMBED_PHYSICAL_GPU=1
  STATEBUS_EMBED_MODEL_PATH=/statebus/models/Qwen3-Embedding-0.6B
  STATEBUS_EMBED_DEVICE=cuda:0
)

if (( SKIP_LIVE == 1 )); then
  record_skipped p4_live_minimal user_requested_skip "$P4_LIVE_MINIMAL_BASE"
  record_skipped p4_live_campaign user_requested_skip "$P4_LIVE_CAMPAIGN_BASE"
else
  run_stage p4_live_minimal "$P4_LIVE_MINIMAL_BASE" \
    env "${LIVE_ENV[@]}" \
    "$LIVE_RUNNER" minimal \
    --service-runtime-dir "$SERVICE_RUNTIME_DIR" \
    --output-base "$P4_LIVE_MINIMAL_BASE" \
    --max-duration-s "$P4_MINIMAL_MAX_DURATION_S"

  minimal_artifact="$(sed -n 's/^artifact_root=//p' "$LOG_ROOT/p4_live_minimal.log" | tail -n 1)"
  if [[ -n "$minimal_artifact" && -d "$minimal_artifact" ]]; then
    run_stage p4_live_campaign "$P4_LIVE_CAMPAIGN_BASE" \
      env "${LIVE_ENV[@]}" \
      "$LIVE_RUNNER" campaign \
      --minimal-evidence-root "$minimal_artifact" \
      --service-runtime-dir "$SERVICE_RUNTIME_DIR" \
      --pairs "$P4_LIVE_PAIRS" \
      --max-duration-s "$P4_LIVE_MAX_DURATION_S" \
      --output-base "$P4_LIVE_CAMPAIGN_BASE"
  else
    record_skipped p4_live_campaign minimal_artifact_not_emitted "$P4_LIVE_CAMPAIGN_BASE"
  fi
fi

python3 "$SUMMARY_TOOL" --run-root "$OUTPUT_ROOT"
python3 "$ANALYSIS_TOOL" --run-root "$OUTPUT_ROOT"

printf '\ncontest-core full ablation orchestration finished\n'
printf 'run_root=%s\n' "$OUTPUT_ROOT"
printf 'stage_status=%s\n' "$STAGE_STATUS"
printf 'benefit_summary_json=%s\n' "$OUTPUT_ROOT/benefit_summary.json"
printf 'benefit_summary_markdown=%s\n' "$OUTPUT_ROOT/benefit_summary.md"
printf 'comprehensive_analysis_json=%s\n' "$OUTPUT_ROOT/comprehensive_analysis.json"
printf 'comprehensive_analysis_markdown=%s\n' "$OUTPUT_ROOT/comprehensive_analysis.md"
printf 'note=individual nonzero stages are recorded and did not stop later stages\n'
