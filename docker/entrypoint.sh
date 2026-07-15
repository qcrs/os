#!/usr/bin/env bash
set -euo pipefail

export STATEBUS_MODELS_DIR="${STATEBUS_MODELS_DIR:-/statebus/models}"
export STATEBUS_CACHES_DIR="${STATEBUS_CACHES_DIR:-/statebus/caches}"
export STATEBUS_LOGS_DIR="${STATEBUS_LOGS_DIR:-/statebus/logs}"
export STATEBUS_RUNS_DIR="${STATEBUS_RUNS_DIR:-/statebus/runs}"
export STATEBUS_WORK_DIR="${STATEBUS_WORK_DIR:-/statebus/work}"
export STATEBUS_WORKSPACES_DIR="${STATEBUS_WORKSPACES_DIR:-/statebus/workspaces}"

mkdir -p \
  "${STATEBUS_MODELS_DIR}" \
  "${STATEBUS_CACHES_DIR}" \
  "${STATEBUS_LOGS_DIR}" \
  "${STATEBUS_RUNS_DIR}" \
  "${STATEBUS_WORK_DIR}" \
  "${STATEBUS_WORKSPACES_DIR}"

cd /workspace/statebus/project

exec "$@"
