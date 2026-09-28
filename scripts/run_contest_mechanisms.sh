#!/usr/bin/env bash
# Thin bounded caller for design 40/41; never starts or restarts services.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON=/home/qcrs/statebus/conda-envs/statebus_host/bin/python
CONTAINER_SOURCE=/workspace/statebus/os
container=statebus-runtime
mechanism=all
mode=live
family=all
memory_variant=all
output=""
collect_output=""
dry_run=0
collect_only=0
task_ids=()
case_ids=()
usage() {
  cat <<'HELP'
Usage: bash scripts/run_contest_mechanisms.sh [options]
  --mechanism memory|state|all   Default: all (formal matrix = 16 + 8 = 24)
  --mode dry-run|offline|live   Default: live
  --output PATH                 New raw run root inside this os checkout
  --family all|finance|service_ops
  --memory-variant off|on|all   Default: all
  --task-id ID                  Repeat to bound Memory (for smoke/debug only)
  --case-id ID                  Repeat to bound State (for smoke/debug only)
  --container-name NAME         Default: statebus-runtime
  --collect-output PATH         New report directory; collect after execution
  --collect-only               Read --output and create --collect-output; run no tasks
  --dry-run                    Alias for --mode dry-run
  --help

Fixed live environment: qwen3-32b at 127.0.0.1:53334/v1, context 8192,
physical GPU 2 for vLLM; local Qwen3-Embedding-0.6B on physical GPU 1
(logical cuda:0 in statebus-runtime); container source /workspace/statebus/os.
The wrapper runs serially, refuses an existing output, preserves failures, and
returns 130 on Ctrl-C. It never starts/restarts vLLM or Docker.
HELP
}
while (($#)); do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --dry-run) mode=dry-run; dry_run=1; shift ;;
    --collect-only) collect_only=1; shift ;;
    --mechanism|--mode|--output|--family|--memory-variant|--container-name|--collect-output|--task-id|--case-id)
      (($# >= 2)) || { echo "Missing value: $1" >&2; exit 2; }
      case "$1" in
        --mechanism) mechanism="$2" ;;
        --mode) mode="$2" ;;
        --output) output="$2" ;;
        --family) family="$2" ;;
        --memory-variant) memory_variant="$2" ;;
        --container-name) container="$2" ;;
        --collect-output) collect_output="$2" ;;
        --task-id) task_ids+=("$2") ;;
        --case-id) case_ids+=("$2") ;;
      esac
      shift 2 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done
[[ "$mechanism" =~ ^(memory|state|all)$ ]] || { echo 'Invalid mechanism' >&2; exit 2; }
[[ "$mode" =~ ^(dry-run|offline|live)$ ]] || { echo 'Invalid mode' >&2; exit 2; }
[[ "$family" =~ ^(all|finance|service_ops)$ ]] || { echo 'Invalid family' >&2; exit 2; }
[[ "$memory_variant" =~ ^(off|on|all)$ ]] || { echo 'Invalid memory variant' >&2; exit 2; }
[[ -n "$output" ]] || output="runs/contest-mechanisms-$(date +%Y%m%d_%H%M%S)-$$"
[[ "$output" = /* ]] || output="$ROOT/$output"
output="$(realpath -m "$output")"
case "$output" in "$ROOT"/*) ;; *) echo 'Output must be inside the os checkout' >&2; exit 2 ;; esac
container_output="$CONTAINER_SOURCE/${output#"$ROOT"/}"
if [[ -n "$collect_output" ]]; then
  [[ "$collect_output" = /* ]] || collect_output="$ROOT/$collect_output"
  collect_output="$(realpath -m "$collect_output")"
  case "$collect_output" in "$ROOT"/*) ;; *) echo 'Collect output must be inside the os checkout' >&2; exit 2 ;; esac
fi
cd "$ROOT"
collect() {
  [[ -n "$collect_output" ]] || { echo '--collect-output is required for collection' >&2; return 2; }
  "$PYTHON" tools/measurement/collect_contest_mechanism_results.py --input "$output" --output "$collect_output"
}
if ((collect_only)); then collect; exit $?; fi
if [[ "$mode" == offline && -n "$collect_output" ]]; then
  echo 'Offline validation does not produce live evidence; omit --collect-output.' >&2
  exit 2
fi
args=(--mechanism "$mechanism" --mode "${mode/dry-run/offline}" --output "$container_output"
      --family "$family" --memory-variant "$memory_variant"
      --model qwen3-32b --base-url http://127.0.0.1:53334/v1 --max-context 8192
      --provider-timeout-s 480 --embedding-mode local
      --embedding-model /statebus/models/Qwen3-Embedding-0.6B --embedding-device cuda:0
      --tokenizer-path /data/models/Qwen3-32B)
for id in "${task_ids[@]}"; do args+=(--task-id "$id"); done
for id in "${case_ids[@]}"; do args+=(--case-id "$id"); done
if [[ "$mode" == dry-run ]]; then
  printf 'HOST_OUTPUT=%s\nCOMMAND=' "$output"
  printf '%q ' docker exec -w "$CONTAINER_SOURCE" "$container" "$PYTHON" -m statebus.benchmark.contest_mechanisms "${args[@]}"
  printf '\n'
  "$PYTHON" -m statebus.benchmark.contest_mechanisms "${args[@]}" --dry-run
  exit 0
fi
[[ ! -e "$output" ]] || { echo "Refusing existing output: $output" >&2; exit 2; }
mkdir -p "$(dirname "$output")"
mkdir "$output"
if [[ "$mode" == live ]]; then
  nvidia-smi -L
  nvidia-smi --query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu --format=csv
  nvidia-smi --query-compute-apps=gpu_uuid,pid,process_name,used_memory --format=csv
  state="$(docker inspect "$container" --format '{{.State.Status}}')"
  [[ "$state" == running ]] || { echo "Container is not running: $container" >&2; exit 2; }
  STATEBUS_CONTAINER_NAME="$container" bash scripts/run_g6b2_os_container.sh verify
  curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:53334/health
  curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:53334/v1/models | "$PYTHON" -c \
   'import json,sys; models=json.load(sys.stdin)["data"]; assert any(m["id"]=="qwen3-32b" and m.get("root")=="/data/models/Qwen3-32B" and m.get("max_model_len")==8192 for m in models), "served_model_or_context_mismatch"'
  gpu_uuid="$(nvidia-smi -i 1 --query-gpu=uuid --format=csv,noheader)"
  STATEBUS_CONTAINER_NAME="$container" bash scripts/run_g6b2_os_container.sh exec \
    "$PYTHON" -m statebus.benchmark.contest_preflight \
    --output "$container_output/embedding-preflight.json" --model qwen3-32b \
    --base-url http://127.0.0.1:53334/v1 \
    --embedding-model-path /statebus/models/Qwen3-Embedding-0.6B --gpu-uuid "$gpu_uuid" \
    > "$output/embedding-preflight.log" 2>&1
fi
trap 'echo "Interrupted; preserve $output (no automatic retry)." >&2; exit 130' INT
trap 'echo "Terminated; preserve $output (no automatic retry)." >&2; exit 143' TERM
if [[ "$mode" == offline ]]; then
  # Offline validates plans, input publication, and contracts only. It makes
  # no Docker, provider, tokenizer, or embedding request and produces no live
  # task result rows.
  args=(--mechanism "$mechanism" --mode offline --output "$output"
        --family "$family" --memory-variant "$memory_variant"
        --model qwen3-32b --base-url http://127.0.0.1:53334/v1 --max-context 8192
        --provider-timeout-s 480 --embedding-mode deterministic)
  for id in "${task_ids[@]}"; do args+=(--task-id "$id"); done
  for id in "${case_ids[@]}"; do args+=(--case-id "$id"); done
fi
rc=0
if [[ "$mode" == offline ]]; then
  "$PYTHON" -u -m statebus.benchmark.contest_mechanisms "${args[@]}" \
    > "$output/run.log" 2>&1 || rc=$?
else
  STATEBUS_CONTAINER_NAME="$container" bash scripts/run_g6b2_os_container.sh exec \
    env STATEBUS_CONTEST_HOST_OUTPUT="$output" \
    "$PYTHON" -u -m statebus.benchmark.contest_mechanisms "${args[@]}" \
    > "$output/run.log" 2>&1 || rc=$?
fi
printf '%s\n' "$rc" > "$output/run.returncode"
if [[ -n "$collect_output" ]]; then collect || rc=$?; fi
echo "RUN_RC=$rc"
echo "RESULT_DIR=$output"
exit "$rc"
