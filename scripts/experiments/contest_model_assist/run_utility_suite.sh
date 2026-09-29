#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "${SCRIPT_DIR}/../../.." && pwd)"
cd -- "$ROOT"

PYTHON="${STATEBUS_HOST_PYTHON:-/home/qcrs/statebus/conda-envs/statebus_host/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  printf 'statebus_host Python is missing: %s\n' "$PYTHON" >&2
  exit 2
fi

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:${PYTHONPATH}}"
exec "$PYTHON" "$SCRIPT_DIR/run_utility_suite.py" "$@"
