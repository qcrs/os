#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"
if ! python -m grpc_tools.protoc --version >/dev/null 2>&1; then
  echo "grpcio-tools is required to regenerate protocol/statebus_pb2.py." >&2
  echo "The checked-in protocol/statebus_pb2.py should be used for normal host-side runs." >&2
  echo "Install grpcio-tools in the active env before re-running this script." >&2
  exit 1
fi

python -m grpc_tools.protoc --proto_path=protocol --python_out=protocol protocol/statebus.proto
