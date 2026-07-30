#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
CONTAINER_NAME="${STATEBUS_SUPPLEMENTAL_CONTAINER:-statebus-dev-qcrs}"
HOST_RUNS_ROOT="${STATEBUS_SUPPLEMENTAL_RUNS_ROOT:-/home/qcrs/statebus/runs}"
EMBED_GPU="${STATEBUS_SUPPLEMENTAL_EMBED_GPU:-2}"
EMBED_MODEL_PATH="${STATEBUS_SUPPLEMENTAL_EMBED_MODEL_PATH:-/statebus/models/Qwen3-Embedding-0.6B}"
VLLM_BASE_URL="${STATEBUS_SUPPLEMENTAL_VLLM_BASE_URL:-http://127.0.0.1:53334/v1}"
VLLM_HEALTH_URL="${STATEBUS_SUPPLEMENTAL_VLLM_HEALTH_URL:-http://127.0.0.1:53334/health}"
SKIP_WARMUP="${STATEBUS_SUPPLEMENTAL_SKIP_WARMUP:-0}"

usage() {
  cat <<'EOF'
Usage:
  scripts/experiments/run_supplemental_experiments_gpu2.sh latency [RESULT_ROOT]
  scripts/experiments/run_supplemental_experiments_gpu2.sh memory  [RESULT_ROOT]
  scripts/experiments/run_supplemental_experiments_gpu2.sh all     [RESULT_ROOT]

Experiments:
  latency  P0-lite: L0/L3, one L0->L3 block and one L3->L0 block.
  memory   P1-lite: L2/L3, one OFF->ON block and one ON->OFF block.
  all      Run both experiments. T2 is intentionally excluded.

The default result root is a new directory under /home/qcrs/statebus/runs.
Set STATEBUS_SUPPLEMENTAL_SKIP_WARMUP=1 to omit excluded one-case warm-ups.
EOF
}

MODE="${1:-}"
case "$MODE" in
  latency|memory|all) ;;
  -h|--help|help)
    usage
    exit 0
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

RUN_STAMP="$(date +%Y%m%d_%H%M%S)"
DEFAULT_RUN_ROOT="${HOST_RUNS_ROOT}/contest_recovery_supplemental_${MODE}_${RUN_STAMP}"
HOST_RUN_ROOT="${2:-$DEFAULT_RUN_ROOT}"

case "$HOST_RUN_ROOT" in
  "${HOST_RUNS_ROOT}"/*) ;;
  *)
    echo "RESULT_ROOT must be below ${HOST_RUNS_ROOT}: ${HOST_RUN_ROOT}" >&2
    exit 2
    ;;
esac

if [[ -e "$HOST_RUN_ROOT" ]]; then
  echo "Refusing to reuse an existing result root: ${HOST_RUN_ROOT}" >&2
  exit 2
fi

RUN_RELATIVE="${HOST_RUN_ROOT#${HOST_RUNS_ROOT}/}"
CONTAINER_RUN_ROOT="/statebus/runs/${RUN_RELATIVE}"
LOCK_PATH="/tmp/statebus-contest-supplemental.lock"

mkdir -p "$HOST_RUN_ROOT"
exec 9>"$LOCK_PATH"
if ! flock -n 9; then
  echo "Another supplemental experiment is already running (lock: ${LOCK_PATH})." >&2
  exit 2
fi

GIT_SHA="$(git -C "$PROJECT_ROOT" rev-parse HEAD)"
if [[ -n "$(git -C "$PROJECT_ROOT" status --porcelain)" ]]; then
  GIT_DIRTY=true
else
  GIT_DIRTY=false
fi

printf '%s\n' \
  "{\"schema_version\":\"statebus.contest_supplemental_run.v1\",\"mode\":\"${MODE}\",\"git_sha\":\"${GIT_SHA}\",\"git_dirty\":${GIT_DIRTY},\"embedding_host_gpu\":\"${EMBED_GPU}\",\"embedding_container_device\":\"cuda:0\",\"embedding_model_path\":\"${EMBED_MODEL_PATH}\",\"vllm_base_url\":\"${VLLM_BASE_URL}\",\"vllm_policy\":\"reuse_existing_only_never_restart\",\"apc_boundary\":\"shared_service_state_no_prefix_attribution\",\"warmup_enabled\":$([[ "$SKIP_WARMUP" == "1" ]] && printf false || printf true),\"warmup_excluded_from_summary\":true}" \
  >"${HOST_RUN_ROOT}/run_manifest.json"

ensure_container() {
  if docker container inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
    if [[ "$(docker inspect --format '{{.State.Running}}' "$CONTAINER_NAME")" != "true" ]]; then
      docker start "$CONTAINER_NAME" >"${HOST_RUN_ROOT}/container_start.log" 2>&1
    fi
    return
  fi

  (
    cd "$PROJECT_ROOT"
    export STATEBUS_UID="$(id -u)"
    export STATEBUS_GID="$(id -g)"
    export STATEBUS_DOCKER_TARGET=embed
    export STATEBUS_NVIDIA_VISIBLE_DEVICES=all
    docker compose -f docker/compose.yaml up -d --no-build statebus-dev
  ) >"${HOST_RUN_ROOT}/container_start.log" 2>&1
}

container_preflight() {
  docker exec \
    -e "CUDA_VISIBLE_DEVICES=${EMBED_GPU}" \
    -e "STATEBUS_EMBED_DEVICE=cuda:0" \
    -e "STATEBUS_EMBED_MODEL_PATH=${EMBED_MODEL_PATH}" \
    -e "STATEBUS_LOCAL_VLLM_BASE_URL=${VLLM_BASE_URL}" \
    -e "STATEBUS_LOCAL_VLLM_HEALTH_URL=${VLLM_HEALTH_URL}" \
    "$CONTAINER_NAME" \
    bash -lc '
      set -Eeuo pipefail
      source /workspace/statebus/project/docker/activate_statebus_container.sh >/dev/null
      test -d "$STATEBUS_EMBED_MODEL_PATH"
      python3 -c "import torch; assert torch.cuda.is_available(); assert torch.cuda.device_count() == 1"
      python3 -c "import os, urllib.request; response = urllib.request.urlopen(os.environ[\"STATEBUS_LOCAL_VLLM_HEALTH_URL\"], timeout=10); assert response.status == 200"
      python3 -c "import os; from statebus.integrations.llm import LLMConfig; config = LLMConfig.from_runtime(); actual = config.provider_config(\"default\").base_url.rstrip(\"/\"); expected = os.environ[\"STATEBUS_LOCAL_VLLM_BASE_URL\"].rstrip(\"/\"); assert actual == expected, f\"configured vLLM URL mismatch: {actual} != {expected}\"; assert {config.role_config(role).model for role in (\"planner\", \"retriever\", \"summarizer\")} == {\"qwen3-32b\"}"
    ' >"${HOST_RUN_ROOT}/preflight.log" 2>&1
}

write_lane_manifest() {
  local lane_dir="$1"
  local experiment="$2"
  local cycle="$3"
  local order="$4"
  local layer="$5"
  local measured="$6"

  printf '%s\n' \
    "{\"schema_version\":\"statebus.contest_supplemental_lane.v1\",\"experiment\":\"${experiment}\",\"cycle\":\"${cycle}\",\"order\":${order},\"layer\":\"${layer}\",\"measured\":${measured}}" \
    >"${lane_dir}/lane_manifest.json"
}

run_lane() {
  local experiment="$1"
  local cycle="$2"
  local order="$3"
  local layer="$4"
  local measured="$5"
  local family_mode="$6"
  local lane_name
  local host_lane_dir
  local container_lane_dir
  local socket_path
  local start_ns
  local end_ns
  local elapsed_ms
  local status

  lane_name="$(printf '%02d-%s' "$order" "$layer")"
  host_lane_dir="${HOST_RUN_ROOT}/${experiment}/${cycle}/${lane_name}"
  container_lane_dir="${CONTAINER_RUN_ROOT}/${experiment}/${cycle}/${lane_name}"
  socket_path="/tmp/sb-${RUN_STAMP}-${experiment}-${cycle}-${layer}.sock"
  mkdir -p "$host_lane_dir"
  write_lane_manifest "$host_lane_dir" "$experiment" "$cycle" "$order" "$layer" "$measured"

  local -a selection_args
  if [[ "$family_mode" == "warmup" ]]; then
    selection_args=(--family formal_financial_reports --max-cases 1)
  else
    selection_args=(--round-view causal_core)
  fi

  local -a runner_args=(
    --suite continuous
    --benchmark-tier formal
    "${selection_args[@]}"
    --layer "$layer"
    --role-path-mode local_vllm
    --executor-mode deterministic_codeact
    --embedding-mode local
    --state-pool-mode shared_memory
    --transport subprocess
    --persistence-profile audit_full
    --workspace-root "${container_lane_dir}/workspaces"
    --runtime-root "${container_lane_dir}/runtime"
    --socket-path "$socket_path"
    --suite-id "supp-${RUN_STAMP}-${experiment}-${cycle}-${layer}"
  )

  start_ns="$(date +%s%N)"
  set +e
  docker exec \
    --workdir /workspace/statebus/project \
    -e "CUDA_VISIBLE_DEVICES=${EMBED_GPU}" \
    -e "STATEBUS_EMBED_DEVICE=cuda:0" \
    -e "STATEBUS_EMBED_MODEL_PATH=${EMBED_MODEL_PATH}" \
    -e "STATEBUS_LOCAL_VLLM_BASE_URL=${VLLM_BASE_URL}" \
    -e "STATEBUS_LOCAL_VLLM_HEALTH_URL=${VLLM_HEALTH_URL}" \
    -e "TOKENIZERS_PARALLELISM=false" \
    "$CONTAINER_NAME" \
    bash -lc 'source docker/activate_statebus_container.sh >/dev/null && exec python3 -m statebus.benchmark.live_runner "$@"' \
    statebus-supplemental "${runner_args[@]}" \
    >"${host_lane_dir}/console.log" 2>&1
  status=$?
  set -e
  end_ns="$(date +%s%N)"
  elapsed_ms=$(((end_ns - start_ns) / 1000000))

  printf '%s\n' \
    "{\"schema_version\":\"statebus.contest_supplemental_operator_timing.v1\",\"elapsed_ms\":${elapsed_ms},\"exit_code\":${status}}" \
    >"${host_lane_dir}/operator_timing.json"

  if ((status != 0)); then
    echo "Experiment failed: ${experiment}/${cycle}/${lane_name}" >&2
    echo "Log: ${host_lane_dir}/console.log" >&2
    tail -n 80 "${host_lane_dir}/console.log" >&2
    return "$status"
  fi
}

run_warmups() {
  [[ "$SKIP_WARMUP" == "1" ]] && return

  if [[ "$MODE" == "latency" || "$MODE" == "all" ]]; then
    run_lane warmup latency 1 L0 false warmup
  fi
  if [[ "$MODE" == "memory" || "$MODE" == "all" ]]; then
    run_lane warmup memory 2 L2 false warmup
  fi
  run_lane warmup shared 3 L3 false warmup
}

run_latency() {
  run_lane latency AB 1 L0 true measured
  run_lane latency AB 2 L3 true measured
  run_lane latency BA 1 L3 true measured
  run_lane latency BA 2 L0 true measured
}

run_memory() {
  run_lane memory AB 1 L2 true measured
  run_lane memory AB 2 L3 true measured
  run_lane memory BA 1 L3 true measured
  run_lane memory BA 2 L2 true measured
}

summarize_results() {
  docker exec \
    --workdir /workspace/statebus/project \
    "$CONTAINER_NAME" \
    python3 scripts/experiments/summarize_supplemental_experiments.py "$CONTAINER_RUN_ROOT" \
    >"${HOST_RUN_ROOT}/summarizer.log" 2>&1
}

on_error() {
  local status=$?
  echo "Supplemental experiment stopped with exit code ${status}." >&2
  echo "Partial results: ${HOST_RUN_ROOT}" >&2
  exit "$status"
}
trap on_error ERR

echo "Preparing container and fixed local services. Results: ${HOST_RUN_ROOT}"
ensure_container
container_preflight
echo "Preflight passed. The experiment now runs silently until completion or error."

run_warmups
case "$MODE" in
  latency) run_latency ;;
  memory) run_memory ;;
  all)
    run_latency
    run_memory
    ;;
esac
summarize_results

QUALITY_STATUS="$(python3 -c 'import json, sys; print("PASS" if json.load(open(sys.argv[1], encoding="utf-8")).get("overall_quality_gate_pass") else "REVIEW")' "${HOST_RUN_ROOT}/supplemental_summary.json")"
echo "Completed. Quality gate: ${QUALITY_STATUS}"
echo "Summary: ${HOST_RUN_ROOT}/supplemental_summary.md"
echo "Machine report: ${HOST_RUN_ROOT}/supplemental_summary.json"
