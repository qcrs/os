#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
container_name="${STATEBUS_V2_CONTAINER_NAME:-statebus-dev-qcrs}"
stage="${STATEBUS_CONTEST_STAGE:-}"
gpu_index="${STATEBUS_CUDA_VISIBLE_DEVICES:-1}"
embedding_device="${STATEBUS_EMBED_DEVICE:-cuda:0}"
vllm_base_url="${STATEBUS_LOCAL_VLLM_BASE_URL:-http://127.0.0.1:53334/v1}"
vllm_model="${STATEBUS_LOCAL_VLLM_MODEL:-qwen3-32b}"
host_runs_base="${STATEBUS_HOST_RUNS_ROOT:-$HOME/statebus/runs}/contest_evidence_closure_20260720"
container_runs_base="${STATEBUS_CONTAINER_RUNS_ROOT:-/statebus/runs}/contest_evidence_closure_20260720"

case "$stage" in
  focused|causal|stress|adaptive-memory|semantic-holdout|adaptive|full|all) ;;
  *)
    printf 'STATEBUS_CONTEST_STAGE must be one of focused, causal, stress, adaptive-memory, semantic-holdout, adaptive, full, or all; got %q\n' "$stage" >&2
    exit 2
    ;;
esac
if [[ ! "$gpu_index" =~ ^[0-9]+$ ]]; then
  printf 'STATEBUS_CUDA_VISIBLE_DEVICES must be one physical GPU index, got %q\n' "$gpu_index" >&2
  exit 2
fi
if [[ "$stage" == "all" ]]; then
  all_run_id="${STATEBUS_CONTEST_RUN_ID:-contest_all_$(date +%Y%m%d_%H%M%S)}"
  for child_stage in focused causal stress adaptive-memory semantic-holdout adaptive full; do
    STATEBUS_CONTEST_STAGE="$child_stage" \
    STATEBUS_CONTEST_RUN_ID="${all_run_id}_${child_stage}" \
      bash "$0"
  done
  exit 0
fi

mkdir -p "$host_runs_base"
stage_lock_path="$host_runs_base/.formal_stage.lock"
exec {stage_lock_fd}>"$stage_lock_path"
if ! flock -n "$stage_lock_fd"; then
  printf 'another contest evidence-closure stage holds the serial execution lock: %s\n' \
    "$stage_lock_path" >&2
  exit 3
fi

running="$(docker inspect --format '{{.State.Running}}' "$container_name" 2>/dev/null || true)"
if [[ "$running" != "true" ]]; then
  printf 'container is not running: %s\n' "$container_name" >&2
  exit 2
fi

run_id="${STATEBUS_CONTEST_RUN_ID:-${stage}_$(date +%Y%m%d_%H%M%S)}"
host_result_root="$host_runs_base/$run_id"
container_result_root="$container_runs_base/$run_id"
if [[ -e "$host_result_root" ]]; then
  printf 'refusing to overwrite existing run root: %s\n' "$host_result_root" >&2
  exit 2
fi
mkdir "$host_result_root"

image_name="$(docker inspect --format '{{.Config.Image}}' "$container_name")"
image_id="$(docker inspect --format '{{.Image}}' "$container_name")"
image_digest="$(docker image inspect --format '{{index .RepoDigests 0}}' "$image_name" 2>/dev/null || true)"
if [[ -z "$image_digest" || "$image_digest" == "<no value>" ]]; then
  image_digest="$image_id"
fi
git_sha="$(git -C "$project_root" rev-parse HEAD)"
git_dirty=0
if [[ -n "$(git -C "$project_root" status --porcelain)" ]]; then
  git_dirty=1
fi

printf '[contest-closure] stage: %s\n' "$stage"
printf '[contest-closure] container: %s (%s)\n' "$container_name" "$image_name"
printf '[contest-closure] physical GPU: %s; embedding device: %s\n' "$gpu_index" "$embedding_device"
printf '[contest-closure] result root: %s\n' "$host_result_root"

set +e
docker exec -i -u 0 \
  -e CUDA_VISIBLE_DEVICES="$gpu_index" \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e STATEBUS_V2_CONTAINER_NAME="$container_name" \
  -e STATEBUS_CONTEST_IMAGE="$image_name" \
  -e STATEBUS_CONTEST_IMAGE_ID="$image_id" \
  -e STATEBUS_CONTEST_IMAGE_DIGEST="$image_digest" \
  -e STATEBUS_CONTEST_GIT_SHA="$git_sha" \
  -e STATEBUS_CONTEST_GIT_DIRTY="$git_dirty" \
  -e STATEBUS_EMBED_DEVICE="$embedding_device" \
  -e STATEBUS_EMBEDDING_MODE=local \
  -e STATEBUS_EMBED_MODEL_PATH="${STATEBUS_EMBED_MODEL_PATH:-/statebus/models/Qwen3-Embedding-0.6B}" \
  -e STATEBUS_LOCAL_VLLM_BASE_URL="$vllm_base_url" \
  -e STATEBUS_LOCAL_VLLM_MODEL="$vllm_model" \
  -e STATEBUS_ADAPTIVE_ROLE_HTTP_TIMEOUT_S="${STATEBUS_ADAPTIVE_ROLE_HTTP_TIMEOUT_S:-240}" \
  -e STATEBUS_ADAPTIVE_ROLE_WORKER_TIMEOUT_S="${STATEBUS_ADAPTIVE_ROLE_WORKER_TIMEOUT_S:-300}" \
  -e STATEBUS_ADAPTIVE_SUMMARIZER_MAX_TOKENS="${STATEBUS_ADAPTIVE_SUMMARIZER_MAX_TOKENS:-1400}" \
  -e STATEBUS_ADAPTIVE_FORMAL_CODE_MAX_TOKENS="${STATEBUS_ADAPTIVE_FORMAL_CODE_MAX_TOKENS:-1400}" \
  "$container_name" /bin/bash -s -- "$stage" "$container_result_root" <<'CONTAINER_BASH' \
  > "$host_result_root/wrapper.log" 2>&1
set -uo pipefail

stage="$1"
run_root="$2"
source /workspace/statebus/project/docker/activate_statebus_container.sh
cd /workspace/statebus/project
mkdir -p "$run_root"

vllm_health_status=failed
health_url="${STATEBUS_LOCAL_VLLM_BASE_URL%/v1}/health"
if curl -fsS "$health_url" > "$run_root/vllm_health.txt" 2>&1; then
  vllm_health_status=ok
fi
python3 - "$STATEBUS_LOCAL_VLLM_BASE_URL" > "$run_root/vllm_models.json" 2>&1 <<'PY' || true
import json
import sys
import urllib.request

base = sys.argv[1].rstrip("/")
with urllib.request.urlopen(base + "/models", timeout=10) as response:
    payload = json.load(response)
print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
PY

cuda_status=failed
if python3 - > "$run_root/cuda_probe.txt" 2>&1 <<'PY'
import os
import torch

device = os.environ["STATEBUS_EMBED_DEVICE"]
if not torch.cuda.is_available():
    raise SystemExit("PyTorch CUDA is unavailable")
probe = torch.arange(8, device=device).sum().item()
print(f"device={device} count={torch.cuda.device_count()} probe={probe}")
PY
then
  cuda_status=ok
fi

bwrap_status=failed
if python3 scripts/v2_diagnostics/check_codeact_bwrap_sandbox.py \
    > "$run_root/bwrap_readiness.json" 2>&1 \
  && python3 - "$run_root/bwrap_readiness.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], "r", encoding="utf-8"))
readiness = payload.get("llm_bwrap_readiness", {})
if not payload.get("ok") or not readiness.get("ready"):
    raise SystemExit(1)
if readiness.get("actual_backend") != "bwrap":
    raise SystemExit(1)
if int(readiness.get("sandbox_uid", 0)) == 0 or int(readiness.get("sandbox_gid", 0)) == 0:
    raise SystemExit(1)
PY
then
  bwrap_status=ok
fi

export STATEBUS_CONTEST_VLLM_HEALTH_STATUS="$vllm_health_status"
export STATEBUS_CONTEST_CUDA_STATUS="$cuda_status"
export STATEBUS_CONTEST_BWRAP_STATUS="$bwrap_status"

python3 -m v2.benchmark.contest_evidence_closure \
  --stage "$stage" \
  --run-root "$run_root"
CONTAINER_BASH
exit_code=$?
set -e

if (( exit_code == 0 )); then
  printf '[contest-closure] PASS stage=%s\n' "$stage"
else
  printf '[contest-closure] FAIL stage=%s exit=%s\n' "$stage" "$exit_code" >&2
fi
printf '[contest-closure] manifest: %s/run_manifest.json\n' "$host_result_root"
printf '[contest-closure] summary: %s/summary.json\n' "$host_result_root"
printf '[contest-closure] console: %s/console.log\n' "$host_result_root"
exit "$exit_code"
