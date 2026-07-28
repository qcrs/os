#!/usr/bin/env bash

set -uo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
container_name="${STATEBUS_V2_CONTAINER_NAME:-statebus-dev-qcrs}"
physical_gpu="${STATEBUS_CUDA_VISIBLE_DEVICES:-2}"
embedding_device="${STATEBUS_EMBED_DEVICE:-cuda:0}"

if [[ "${STATEBUS_LOGIT_EXPERIMENT_INSIDE:-0}" != "1" ]]; then
  if [[ "$(docker inspect -f '{{.State.Running}}' "$container_name" 2>/dev/null || true)" != "true" ]]; then
    export STATEBUS_UID="$(id -u)"
    export STATEBUS_GID="$(id -g)"
    export STATEBUS_DOCKER_TARGET="${STATEBUS_DOCKER_TARGET:-embed}"
    docker compose -f "$project_root/docker/compose.yaml" up -d --no-build statebus-dev || exit $?
  fi

  experiment_stamp="$(date +%Y%m%d_%H%M%S)"
  experiment_root="${STATEBUS_LOGIT_EXPERIMENT_ROOT:-/statebus/runs/logit_retry_gate_${experiment_stamp}}"
  docker exec \
    -e CUDA_VISIBLE_DEVICES="$physical_gpu" \
    -e STATEBUS_EMBED_DEVICE="$embedding_device" \
    -e STATEBUS_LOGIT_EXPERIMENT_INSIDE=1 \
    -e STATEBUS_LOGIT_EXPERIMENT_ROOT="$experiment_root" \
    "$container_name" \
    bash -lc '
      source /workspace/statebus/project/docker/activate_statebus_container.sh >/dev/null
      exec bash /workspace/statebus/project/scripts/v2_diagnostics/run_logit_retry_gate_gpu2.sh
    '
  exit $?
fi

source "$project_root/docker/activate_statebus_container.sh" >/dev/null || exit $?

experiment_root="${STATEBUS_LOGIT_EXPERIMENT_ROOT:?missing experiment root}"
if [[ -e "$experiment_root" ]]; then
  printf 'Experiment root already exists: %s\n' "$experiment_root" >&2
  exit 2
fi

mkdir -p "$experiment_root"
printf 'mode\ttask_id\texit_code\n' > "$experiment_root/status.tsv"

CUDA_VISIBLE_DEVICES="$physical_gpu" \
STATEBUS_EMBED_DEVICE="$embedding_device" \
STATEBUS_LOGIT_GATE_MODE=off \
python3 -m v2.benchmark.live_runner \
  --suite preflight \
  --role-path-mode local_vllm \
  --embedding-mode local \
  > "$experiment_root/preflight.json" \
  2> "$experiment_root/preflight.stderr.log" || exit $?

task_ids=(
  benchmark-sample-1
  formal-trend-003
  formal-join-004
  formal-agg-002
  formal-anomaly-001
)
gate_modes=(off retry_once)
failed_count=0

for gate_mode in "${gate_modes[@]}"; do
  for task_id in "${task_ids[@]}"; do
    case_root="$experiment_root/$gate_mode/$task_id"
    suite_id="logit-gate-$gate_mode-$task_id"
    mkdir -p "$case_root"
    printf '[logit-gate] start mode=%s task=%s\n' "$gate_mode" "$task_id"

    set +e
    CUDA_VISIBLE_DEVICES="$physical_gpu" \
    STATEBUS_EMBED_DEVICE="$embedding_device" \
    STATEBUS_LOGIT_GATE_MODE="$gate_mode" \
    python3 -m v2.benchmark.live_runner \
      --suite statebus \
      --benchmark-tier formal \
      --case-id "$task_id" \
      --layer L3 \
      --role-path-mode local_vllm \
      --embedding-mode local \
      --state-pool-mode shared_memory \
      --statebus-mode cold-start \
      --persistence-profile audit_full \
      --suite-id "$suite_id" \
      --workspace-root "$case_root/workspaces" \
      --runtime-root "$case_root/runtime" \
      --socket-path "$case_root/control.sock" \
      > "$case_root/runner.stdout.json" \
      2> "$case_root/runner.stderr.log"
    case_status=$?
    set -e

    printf '%s\t%s\t%s\n' "$gate_mode" "$task_id" "$case_status" \
      >> "$experiment_root/status.tsv"
    printf '[logit-gate] done mode=%s task=%s exit=%s\n' \
      "$gate_mode" "$task_id" "$case_status"
    if [[ "$case_status" -ne 0 ]]; then
      failed_count=$((failed_count + 1))
    fi
  done
done

python3 "$project_root/scripts/v2_diagnostics/summarize_logit_retry_gate.py" \
  "$experiment_root" || exit $?

printf '[logit-gate] experiment_root=%s failures=%s\n' \
  "$experiment_root" "$failed_count"
if [[ "$failed_count" -ne 0 ]]; then
  exit 1
fi

