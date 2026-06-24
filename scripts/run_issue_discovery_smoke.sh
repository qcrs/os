#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="/home/qcrs/statebus/conda-envs/statebus_host/bin/python"

cd "$ROOT"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "missing python: $PYTHON_BIN" >&2
  exit 1
fi

unset all_proxy || true
unset ALL_PROXY || true

exec "$PYTHON_BIN" scripts/run_issue_discovery_smoke.py "$@"
