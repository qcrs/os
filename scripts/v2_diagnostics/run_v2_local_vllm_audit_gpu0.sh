#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export STATEBUS_CUDA_VISIBLE_DEVICES="${STATEBUS_CUDA_VISIBLE_DEVICES:-0}"

exec bash "$script_dir/run_v2_local_vllm_audit_gpu1.sh" "$@"
