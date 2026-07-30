#!/usr/bin/env bash

set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
container_name="${STATEBUS_CONTAINER_NAME:-statebus-dev-qcrs}"
physical_gpu="${STATEBUS_CUDA_VISIBLE_DEVICES:-2}"
embedding_device="${STATEBUS_EMBED_DEVICE:-cuda:0}"

if [[ "${STATEBUS_LOGIT_CHALLENGE_INSIDE:-0}" != "1" ]]; then
  if [[ "$(docker inspect -f '{{.State.Running}}' "$container_name" 2>/dev/null || true)" != "true" ]]; then
    export STATEBUS_UID="$(id -u)"
    export STATEBUS_GID="$(id -g)"
    export STATEBUS_DOCKER_TARGET="${STATEBUS_DOCKER_TARGET:-embed}"
    docker compose -f "$project_root/docker/compose.yaml" up -d --no-build statebus-dev
  fi

  experiment_stamp="$(date +%Y%m%d_%H%M%S)"
  experiment_root="${STATEBUS_LOGIT_CHALLENGE_ROOT:-/statebus/runs/logit_retry_challenge_${experiment_stamp}}"
  docker exec \
    -e CUDA_VISIBLE_DEVICES="$physical_gpu" \
    -e STATEBUS_EMBED_DEVICE="$embedding_device" \
    -e STATEBUS_EMBED_MODEL_PATH=/statebus/models/Qwen3-Embedding-0.6B \
    -e STATEBUS_LOGIT_CHALLENGE_INSIDE=1 \
    -e STATEBUS_LOGIT_CHALLENGE_ROOT="$experiment_root" \
    "$container_name" \
    bash -lc '
      source /workspace/statebus/project/docker/activate_statebus_container.sh >/dev/null
      exec bash /workspace/statebus/project/scripts/diagnostics/run_logit_retry_challenge_gpu2.sh
    '
  exit $?
fi

source "$project_root/docker/activate_statebus_container.sh" >/dev/null

experiment_root="${STATEBUS_LOGIT_CHALLENGE_ROOT:?missing experiment root}"
curl -fsS http://127.0.0.1:53334/health >/dev/null

CUDA_VISIBLE_DEVICES="$physical_gpu" \
STATEBUS_EMBED_DEVICE="$embedding_device" \
python3 -m statebus.benchmark.live_runner \
  --suite preflight \
  --role-path-mode local_vllm \
  --embedding-mode local \
  > "${experiment_root}.preflight.json"

CUDA_VISIBLE_DEVICES="$physical_gpu" \
STATEBUS_EMBED_DEVICE="$embedding_device" \
STATEBUS_LLM_MODE=local_vllm \
python3 -m statebus.benchmark.logit_retry_challenge \
  --output-root "$experiment_root"

printf '[logit-challenge] output_root=%s\n' "$experiment_root"
