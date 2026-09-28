#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
OS_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
CONTAINER_HELPER="$SCRIPT_DIR/run_g6b2_os_container.sh"
STARTER="$SCRIPT_DIR/start_statebus.sh"
MODEL_PROFILE="${STATEBUS_LOCAL_VLLM_PROFILE:-qwen3-32b-gpu2-u050}"
CONTAINER_NAME="${STATEBUS_CONTAINER_NAME:-statebus-runtime}"
EMBED_GPU="${STATEBUS_EMBED_PHYSICAL_GPU:-1}"
RUNTIME_PYTHON="${STATEBUS_RUNTIME_PYTHON:-/home/qcrs/statebus/conda-envs/statebus_host/bin/python}"
RUN_ROOT=""
STAGE=""
DRY_RUN=0
PREFLIGHT_ONLY=0
START_SERVICES=0
MECHANISM="all"
STAGE1_ROOT=""
SMOKE=0
STOP_ON_FAILURE=0
OFFLINE=0
CHECKPOINT_ROUNDS=0

usage() {
  cat <<'EOF'
Usage: scripts/run_contest_measurement_stages.sh --stage 1|2|3|all [options]

  1  SB-NO-MEMORY -> SB-FULL -> P-TEXT; four tasks each, fail at batch boundary.
  2  Stage 2 mechanism runner; requires --stage1-root and --mechanism.
     --smoke runs bounded F01/F02 Memory and semantic-state smoke only.
  3  A main campaign: Finance F01-F10 and Service Ops O01-O10, SB-FULL/P-TEXT (40 slots).
  all  Stage 1, then Stage 2 only when explicitly configured.

Options:
  --profile NAME         qwen3-32b-gpu2-u050 (default) or qwen3-8b-gpu0-u050
  --embedding-gpu INDEX   Physical GPU, default 1; must differ from service GPU
  --container-name NAME  Existing container, default statebus-runtime
  --runtime-python PATH Explicit container interpreter; default mounted statebus_host
  --run-root DIR         New directory under os/, never overwrite existing runs
  --stage1-root DIR      Existing Stage 1 evidence root for Stage 2
  --mechanism NAME       memory|state|communication|codeact|cross-agent|all
  --checkpoint-rounds N  Stage 3 only: append 0, 1 or 2 audit rechecks per chain (40/44/48 slots)
  --smoke                Bounded Stage 2 mechanism smoke; no full campaign
  --offline              Build/audit Stage 2 contracts without live services
  --stop-on-failure      Stop the whole campaign after a real failure; without
                         it, Stage 3 blocks only the failed chain's successors
  --dry-run              Show resolved configuration and exact commands; no live probes
  --preflight-only       Check health, actual config and one GPU embedding; no LLM tasks
  --start-services       Explicitly invoke start_statebus.sh before preflight
                         (existing workspace-root container only; sends LLM smoke)

Without --start-services, only existing services are reused. No CPU fallback.
An 8B run is a separate development profile, not a replacement for 32B results.
EOF
}

die() { printf '[contest-stages] ERROR: %s\n' "$*" >&2; exit 2; }
log() { printf '[contest-stages] %s\n' "$*"; }
run_container() { "$CONTAINER_HELPER" exec "$RUNTIME_PYTHON" "$@"; }
map_path() { "$CONTAINER_HELPER" map-path "$1"; }

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --stage|--run-root|--stage1-root|--mechanism|--profile|--embedding-gpu|--container-name|--runtime-python|--checkpoint-rounds)
        [[ $# -ge 2 ]] || die "$1 requires a value"
        case "$1" in
          --stage) STAGE="$2" ;; --run-root) RUN_ROOT="$2" ;; --stage1-root) STAGE1_ROOT="$2" ;; --mechanism) MECHANISM="$2" ;; --profile) MODEL_PROFILE="$2" ;;
          --embedding-gpu) EMBED_GPU="$2" ;; --container-name) CONTAINER_NAME="$2" ;;
          --runtime-python) RUNTIME_PYTHON="$2" ;;
          --checkpoint-rounds) CHECKPOINT_ROUNDS="$2" ;;
        esac
        shift 2 ;;
      --dry-run) DRY_RUN=1; shift ;;
      --preflight-only) PREFLIGHT_ONLY=1; shift ;;
      --start-services) START_SERVICES=1; shift ;;
      --smoke) SMOKE=1; shift ;;
      --offline) OFFLINE=1; shift ;;
      --stop-on-failure) STOP_ON_FAILURE=1; shift ;;
      -h|--help) usage; exit 0 ;;
      *) die "Unknown argument: $1" ;;
    esac
  done
  case "$STAGE" in 1|2|3|all) ;; *) die 'Specify --stage 1|2|3|all' ;; esac
  case "$CHECKPOINT_ROUNDS" in 0|1|2) ;; *) die '--checkpoint-rounds must be 0, 1 or 2' ;; esac
  [[ "$CHECKPOINT_ROUNDS" == 0 || "$STAGE" == 3 ]] || die '--checkpoint-rounds requires --stage 3'
  [[ "$RUNTIME_PYTHON" = /* ]] || die 'Runtime interpreter must be an absolute container path'
  # Host activation defaults to auto; this campaign resolves it explicitly to CUDA.
  case "${STATEBUS_EMBED_DEVICE:-auto}" in
    auto|cuda:0) ;; *) die 'This campaign requires cuda:0; unset conflicting STATEBUS_EMBED_DEVICE first' ;;
  esac
  (( ! PREFLIGHT_ONLY || ! START_SERVICES )) || die '--preflight-only cannot start services or send startup smoke requests'
  case "$MECHANISM" in memory|state|communication|codeact|cross-agent|all) ;; *) die 'Unknown --mechanism' ;; esac
  if [[ "$STAGE" == 2 && -n "$STAGE1_ROOT" ]]; then
    STAGE1_ROOT="$(realpath -m "$STAGE1_ROOT")"
    [[ -d "$STAGE1_ROOT" ]] || die "--stage1-root does not exist: $STAGE1_ROOT"
  fi
}

load_configuration() {
  export STATEBUS_RUNTIME_PYTHON="$RUNTIME_PYTHON"
  local resolved
  # Only evaluate our own existing profile loader's explicitly shell-quoted output.
  resolved="$("$STARTER" "$MODEL_PROFILE" --embedding-gpu "$EMBED_GPU" --container-name "$CONTAINER_NAME" --print-env)"
  eval "$resolved"
  MODEL_PROFILE="$STATEBUS_VLLM_PROFILE"
  [[ -n "$RUN_ROOT" ]] || RUN_ROOT="$OS_ROOT/runs/contest-stages-$(date +%Y%m%d_%H%M%S)"
  RUN_ROOT="$(realpath -m "$RUN_ROOT")"
  [[ "$RUN_ROOT" == "$OS_ROOT"/* ]] || die "--run-root must be below $OS_ROOT"
  [[ ! -e "$RUN_ROOT" ]] || die "Output directory already exists: $RUN_ROOT"
}

stage_command() {
  local label="$1" profile="$2" policy="$3" root="$4"
  printf '%q ' "$CONTAINER_HELPER" exec "$RUNTIME_PYTHON" -m statebus.benchmark.contest_stage1 \
    --output-root "$root/stage1/$label" --profile "$profile" --family all --sb-memory-policy "$policy" \
    --model-context-tokens "$STATEBUS_VLLM_MAX_MODEL_LEN" \
    --embedding-model-path "$STATEBUS_EMBED_MODEL_PATH" --embedding-device cuda:0
  printf '\n'
}

stage2_admission() {
  jq -n '{ok:false, formal_campaign_executed:false,
    live_memory:{status:"implemented_not_run", required_tasks:12, deterministic_is_substitute:false},
    semantic_state:{status:"implemented_not_run", required_tasks:6},
    structured_communication:{status:"not_implemented", required_tasks:4},
    codeact_off:{status:"not_applicable", blocking:false, reason:"no_validated_legal_common_route"},
    cross_agent_memory:{status:"blocked", reason:"live_cross_agent_caller_not_closed"},
    blocking_reasons:["stage2_explicit_invocation_required","task_level_communication_runner_missing","live_cross_agent_caller_not_closed"]}'
}

stage2_dry_run() {
  local stage1_root="$1"
  local command=("$RUNTIME_PYTHON" -m statebus.benchmark.contest_stage2
    --output-root "$RUN_ROOT" --stage1-root "$stage1_root" --mechanism "$MECHANISM"
    --profile "$MODEL_PROFILE" --embedding-model-path "$STATEBUS_EMBED_MODEL_PATH"
    --embedding-device cuda:0 --dry-run)
  (( SMOKE )) && command+=(--smoke)
  (( OFFLINE )) && command+=(--offline)
  PYTHONPATH="$OS_ROOT" "${command[@]}"
}

run_stage2_runner() {
  local container_root status=0
  local stage1_container_root
  if (( OFFLINE )); then
    container_root="$RUN_ROOT"
    stage1_container_root="$STAGE1_ROOT"
  else
    container_root="$(map_path "$RUN_ROOT")"
    stage1_container_root="$(map_path "$STAGE1_ROOT")"
  fi
  local args=( -m statebus.benchmark.contest_stage2
    --output-root "$container_root" --stage1-root "$stage1_container_root"
    --mechanism "$MECHANISM" --profile "$MODEL_PROFILE"
    --embedding-model-path "$STATEBUS_EMBED_MODEL_PATH" --embedding-device cuda:0 )
  (( SMOKE )) && args+=(--smoke)
  (( STOP_ON_FAILURE )) && args+=(--stop-on-failure)
  (( OFFLINE )) && args+=(--offline)
  [[ -f "$RUN_ROOT/preflight.json" ]] && args+=(--preflight-json "$container_root/preflight.json")
  log "Stage 2: mechanism=$MECHANISM smoke=$SMOKE offline=$OFFLINE"
  if (( OFFLINE )); then
    PYTHONPATH="$OS_ROOT" "$RUNTIME_PYTHON" "${args[@]}" >"$RUN_ROOT/stage2.log" 2>&1 || status=$?
  else
    run_container "${args[@]}" >"$RUN_ROOT/stage2.log" 2>&1 || status=$?
  fi
  [[ -f "$RUN_ROOT/acceptance.json" ]] || die "Stage 2 runner did not write acceptance.json; see $RUN_ROOT/stage2.log"
  if (( status != 0 )); then
    if [[ -f "$RUN_ROOT/failures.json" ]]; then
      jq -r '.rows[] | "[contest-stages] failure: \(.mechanism) \(.variant // "") \(.task_id // "") \(.status): \(.error // .reason // "see task log")"' "$RUN_ROOT/failures.json" >&2
    fi
    die "Stage 2 runner failed (exit=$status); see $RUN_ROOT/failures.json and $RUN_ROOT/stage2.log"
  fi
  log "Stage 2 completed; see $RUN_ROOT/acceptance.json"
}

run_main_campaign() {
  local container_root status=0
  container_root="$(map_path "$RUN_ROOT")"
  log "Stage 3/A: $((20 + 2 * CHECKPOINT_ROUNDS)) ordered tasks x SB-FULL/P-TEXT"
  local args=(-m statebus.benchmark.contest_stage1
    --output-root "$container_root/main" --main-chain --checkpoint-rounds "$CHECKPOINT_ROUNDS" --profile both --family all
    --model-context-tokens "$STATEBUS_VLLM_MAX_MODEL_LEN"
    --sb-memory-policy validated_replay --embedding-model-path "$STATEBUS_EMBED_MODEL_PATH"
    --embedding-device cuda:0 --block-failed-chain)
  (( STOP_ON_FAILURE )) && args+=(--stop-on-failure)
  run_container "${args[@]}" >"$RUN_ROOT/main-campaign.log" 2>&1 || status=$?
  [[ -f "$RUN_ROOT/main/summary.json" ]] || die "Main campaign did not write summary.json; see $RUN_ROOT/main-campaign.log"
  [[ "$(source_digest)" == "$SOURCE_DIGEST" ]] || die 'Source changed during main campaign; do not treat this as a frozen run'
  (( status == 0 )) || die "Main campaign failed (exit=$status); see $RUN_ROOT/main/summary.json and $RUN_ROOT/main-campaign.log"
  jq -e --argjson count "$((4 * (10 + CHECKPOINT_ROUNDS)))" --arg scope "main_chain_$((20 + 2 * CHECKPOINT_ROUNDS))_tasks" \
    '.planned_count == $count and .passed_count == $count and .main_chain_completed == true
    and .scope == $scope and (.chain_results | length == 4)
    and all(.chain_results[]; .completed_ten_rounds == true)' "$RUN_ROOT/main/summary.json" >/dev/null \
    || die "Main campaign did not complete all planned rounds"
  log "Main campaign completed; see $RUN_ROOT/main/summary.json"
}

source_digest() {
  rg --files -0 statebus scripts deploy -g '*.py' -g '*.sh' -g '*.example' -g '*.yaml' \
    | sort -z | xargs -0 sha256sum | sha256sum | cut -d ' ' -f 1
}

gpu_snapshot() {
  nvidia-smi -L
  nvidia-smi --query-gpu=index,uuid,name,memory.total,memory.free,utilization.gpu --format=csv
  nvidia-smi --query-compute-apps=gpu_uuid,pid,process_name,used_memory --format=csv
}

preflight() {
  local gpu_uuid container_root
  gpu_snapshot
  "$SCRIPT_DIR/vllm/manage_qwen3_32b.sh" status
  curl --noproxy '*' -fsS --max-time 5 "$STATEBUS_LOCAL_VLLM_HEALTH_URL" >/dev/null
  curl --noproxy '*' -fsS --max-time 5 "$STATEBUS_LOCAL_VLLM_BASE_URL/models" \
    | jq -e --arg model "$STATEBUS_LOCAL_VLLM_MODEL" --argjson context "$STATEBUS_VLLM_MAX_MODEL_LEN" \
        '.data | length == 1 and .[0].id == $model and .[0].max_model_len == $context'
  "$CONTAINER_HELPER" verify
  container_root="$(map_path "$RUN_ROOT")"
  gpu_uuid="$(nvidia-smi -i "$EMBED_GPU" --query-gpu=uuid --format=csv,noheader)"
  # Checks the exact interpreter, all real role configs, physical UUID, parameter
  # device and an actual 1024-dimensional encode. Never installs dependencies.
  run_container -m statebus.benchmark.contest_preflight --output "$container_root/preflight.json" \
    --model "$STATEBUS_LOCAL_VLLM_MODEL" --base-url "$STATEBUS_LOCAL_VLLM_BASE_URL" \
    --embedding-model-path "$STATEBUS_EMBED_MODEL_PATH" --gpu-uuid "$gpu_uuid"
}

run_stage1_variant() {
  local label="$1" profile="$2" policy="$3" container_root status=0
  [[ "$(source_digest)" == "$SOURCE_DIGEST" ]] || die 'Source changed between batches; start a new campaign after review'
  container_root="$(map_path "$RUN_ROOT")"
  log "Stage 1: $label"
  run_container -m statebus.benchmark.contest_stage1 \
    --output-root "$container_root/stage1/$label" --profile "$profile" --family all --sb-memory-policy "$policy" \
    --model-context-tokens "$STATEBUS_VLLM_MAX_MODEL_LEN" \
    --embedding-model-path "$STATEBUS_EMBED_MODEL_PATH" --embedding-device cuda:0 \
    --dry-run --plan-output "$container_root/stage1-$label-plan.json" \
    >"$RUN_ROOT/stage1-$label-plan.log" 2>&1
  jq -e '.planned_count == 4 and .embedding_device == "cuda:0"' "$RUN_ROOT/stage1-$label-plan.json" >/dev/null
  run_container -m statebus.benchmark.contest_stage1 \
    --output-root "$container_root/stage1/$label" --profile "$profile" --family all --sb-memory-policy "$policy" \
    --model-context-tokens "$STATEBUS_VLLM_MAX_MODEL_LEN" \
    --embedding-model-path "$STATEBUS_EMBED_MODEL_PATH" --embedding-device cuda:0 \
    >"$RUN_ROOT/stage1-$label.log" 2>&1 || status=$?
  # Audit failed batches too, so acceptance failure is persisted alongside costs.
  run_container -m statebus.benchmark.contest_stage_gate --root "$container_root/stage1/$label" --variant "$label" \
    >"$RUN_ROOT/stage1-$label-gate.log" 2>&1 || die "$label acceptance failed; see $RUN_ROOT/stage1-$label-gate.log"
  (( status == 0 )) || die "$label runner failed (exit=$status)"
  [[ "$(source_digest)" == "$SOURCE_DIGEST" ]] || die 'Source changed during batch; not a frozen campaign'
  if [[ "$label" != 'sb-no-memory' ]]; then
    jq -e -s '.[0].effective_configuration_hash == .[1].effective_configuration_hash and .[0].effective_budget == .[1].effective_budget' \
      "$RUN_ROOT/stage1/sb-no-memory/acceptance.json" "$RUN_ROOT/stage1/$label/acceptance.json" >/dev/null \
      || die 'Effective provider settings or budgets differ across variants'
  fi
  log "$label passed; see $RUN_ROOT/stage1/$label/acceptance.json"
}

main() {
  parse_args "$@"
  load_configuration
  cd "$OS_ROOT"
  log "stage=$STAGE profile=$MODEL_PROFILE model_gpu=$STATEBUS_VLLM_CUDA_VISIBLE_DEVICES embedding_gpu=$EMBED_GPU"
  log "runtime_python=$RUNTIME_PYTHON run_root=$RUN_ROOT"
  if (( DRY_RUN )); then
    log 'Resolved plan only; no environment readiness is claimed. Use --preflight-only to test it.'
    if [[ "$STAGE" == 1 || "$STAGE" == all ]]; then
      local container_plan_root="/workspace/statebus/os/${RUN_ROOT#"$OS_ROOT"/}"
      stage_command sb-no-memory SB-FULL none "$container_plan_root"
      stage_command sb-full SB-FULL validated_replay "$container_plan_root"
      stage_command p-text P-TEXT none "$container_plan_root"
    fi
    if [[ "$STAGE" == 2 || "$STAGE" == all ]]; then
      if [[ -n "$STAGE1_ROOT" ]]; then
        stage2_dry_run "$STAGE1_ROOT"
      else
        stage2_admission
      fi
    fi
    if [[ "$STAGE" == 3 || "$STAGE" == all ]]; then
      printf '%q ' "$CONTAINER_HELPER" exec "$RUNTIME_PYTHON" -m statebus.benchmark.contest_stage1 \
        --output-root "/workspace/statebus/os/${RUN_ROOT#"$OS_ROOT"/}/main" --main-chain --checkpoint-rounds "$CHECKPOINT_ROUNDS" --profile both --family all \
        --model-context-tokens "$STATEBUS_VLLM_MAX_MODEL_LEN" \
        --sb-memory-policy validated_replay --embedding-model-path "$STATEBUS_EMBED_MODEL_PATH" --embedding-device cuda:0 --block-failed-chain
      (( STOP_ON_FAILURE )) && printf '%q ' --stop-on-failure
      printf '\n'
    fi
    return
  fi
  mkdir -p "$(dirname "$RUN_ROOT")"
  mkdir "$RUN_ROOT"
  # Keep the old no-argument admission response for callers that have not
  # supplied a Stage 1 evidence root. The real runner is only entered through
  # the explicit Stage 2 contract.
  if [[ "$STAGE" == 2 && -z "$STAGE1_ROOT" ]]; then
    stage2_admission >"$RUN_ROOT/stage2-admission.json"
    die "Stage 2 requires --stage1-root and --mechanism; see $RUN_ROOT/stage2-admission.json"
  fi
  if (( START_SERVICES )); then
    # The existing helper's up command can recreate legacy mounts. This entry
    # only authorizes reuse/start, never creating or replacing a container.
    [[ "$("$CONTAINER_HELPER" mount-mode)" == workspace-root ]] \
      || die 'Startup requires an existing workspace-root container; recreation is not authorized'
    gpu_snapshot 2>&1 | tee "$RUN_ROOT/start-gpu-preflight.log"
    "$STARTER" "$MODEL_PROFILE" --embedding-gpu "$EMBED_GPU" --container-name "$CONTAINER_NAME" \
      2>&1 | tee "$RUN_ROOT/start-services.log"
  fi
  if (( OFFLINE )); then
    : >"$RUN_ROOT/preflight.log"
  else
    preflight 2>&1 | tee "$RUN_ROOT/preflight.log"
  fi
  if (( PREFLIGHT_ONLY )); then log 'Preflight passed; no business tasks executed'; return; fi
  SOURCE_DIGEST="$(source_digest)"
  printf '%s\n' "$SOURCE_DIGEST" >"$RUN_ROOT/source-digest.txt"
  if [[ "$STAGE" == 2 ]]; then
    run_stage2_runner
    return
  fi
  if [[ "$STAGE" == 3 ]]; then
    run_main_campaign
    return
  fi
  run_stage1_variant sb-no-memory SB-FULL none
  run_stage1_variant sb-full SB-FULL validated_replay
  run_stage1_variant p-text P-TEXT none
  log "Stage 1 passed (12 development tasks); semantic review still required: $RUN_ROOT/stage1"
  if [[ "$STAGE" == all ]]; then
    stage2_admission >"$RUN_ROOT/stage2-admission.json"
    die 'Stage 1 retained; run Stage 2 explicitly with --stage1-root and --mechanism. Communication and cross-agent callers remain incomplete'
  fi
}

main "$@"
