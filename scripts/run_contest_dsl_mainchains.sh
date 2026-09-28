#!/usr/bin/env bash
# Thin caller: two isolated 12-round chains; never starts or restarts services.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON=/home/qcrs/statebus/conda-envs/statebus_host/bin/python
CONTAINER_SOURCE=/workspace/statebus/os
container=statebus-runtime
variant=SB-FULL
family=all
output=""
codeact_fallback=off
model_assist_profile=off
dry_run=0
usage() {
  cat <<'HELP'
Usage: bash scripts/run_contest_dsl_mainchains.sh [options]
  --variant SB-FULL|P-TEXT        Default: SB-FULL
  --family all|finance|service_ops Default: all (12 rounds per family)
  --output PATH                  New directory inside this os checkout
  --container-name NAME          Default: statebus-runtime
  --codeact-fallback off|on     Default: off; after DSL initial + one repair fail,
                                authorize one fresh bounded-Python attempt
  --model-assist-profile PROFILE Default: off; off|logit|apc|kv_replay|kv_continuation|kv_logit|auto
  --container-source-root PATH   Container-visible checkout; default /workspace/statebus/os
  --dry-run                      Print real runner arguments/contracts; no Docker,
                                 GPU probe, service startup or provider request
  --help                         Show this help

Fixed: mechanism_simple_v2, live, 12 rounds, qwen3-32b at :53334/v1,
8192 context, Executor 3072/Summarizer 1536, provider timeout 480s, one repair,
local Embedding cuda:0. No implicit provider retry is enabled.
Reuse existing services; prepare them separately with scripts/start_statebus.sh.
Failures only block rounds whose declared history depends on the failed task;
independent rounds continue, and the other family still runs.
Returns 0 only if every requested chain succeeds; Ctrl-C stops the wrapper.
Each family gets separate Memory, history, ledger and evidence directories.
HELP
}
while (($#)); do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --dry-run) dry_run=1; shift ;;
    --variant|--family|--output|--container-name|--codeact-fallback|--model-assist-profile|--container-source-root)
      (($# >= 2)) || { echo "Missing value: $1" >&2; exit 2; }
      case "$1" in
        --variant) variant="$2" ;;
        --family) family="$2" ;;
        --output) output="$2" ;;
        --container-name) container="$2" ;;
        --codeact-fallback) codeact_fallback="$2" ;;
        --model-assist-profile) model_assist_profile="$2" ;;
        --container-source-root) CONTAINER_SOURCE="$2" ;;
      esac
      shift 2 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done
[[ "$variant" == SB-FULL || "$variant" == P-TEXT ]] || { echo 'Invalid variant' >&2; exit 2; }
[[ "$codeact_fallback" == off || "$codeact_fallback" == on ]] || { echo 'Invalid --codeact-fallback (use off|on)' >&2; exit 2; }
case "$model_assist_profile" in
  off|logit|apc|kv_replay|kv_continuation|kv_logit|auto) ;;
  *) echo 'Invalid --model-assist-profile' >&2; exit 2 ;;
esac
[[ "$CONTAINER_SOURCE" = /* ]] || { echo 'Container source root must be absolute' >&2; exit 2; }
case "$family" in
  all) families=(finance service_ops) ;;
  finance|service_ops) families=("$family") ;;
  *) echo 'Invalid family' >&2; exit 2 ;;
esac
output="${output:-runs/contest39-${variant,,}-$(date +%Y%m%d_%H%M%S)-$$}"
[[ "$output" = /* ]] || output="$ROOT/$output"
output="$(realpath -m "$output")"
case "$output" in "$ROOT"/*) ;; *) echo 'Output must be inside the os checkout (shared container mount)' >&2; exit 2 ;; esac
container_output="$CONTAINER_SOURCE/${output#"$ROOT"/}"
args=(--profile mechanism_simple_v2 --variant "$variant" --rounds 12 --mode live
      --codeact-fallback "$codeact_fallback"
      --model-assist-profile "$model_assist_profile"
      --model qwen3-32b --base-url http://127.0.0.1:53334/v1 --max-context 8192
      --provider-timeout-s 480
      --embedding-mode local --embedding-model /statebus/models/Qwen3-Embedding-0.6B
      --embedding-device cuda:0 --tokenizer-path /data/models/Qwen3-32B)
cd "$ROOT"
container_env=(
  -e "PYTHONDONTWRITEBYTECODE=1"
  -e "PYTHONPATH=$CONTAINER_SOURCE"
  -e "PROJECT_ROOT=$CONTAINER_SOURCE"
  -e "STATEBUS_LLM_CONFIG_FILE=$CONTAINER_SOURCE/deploy/statebus_llm.g6b2-qwen3-32b.example"
)
if [[ "$model_assist_profile" != off ]]; then
  for name in \
    STATEBUS_KV_API_BASE_URL STATEBUS_KV_API_TOKEN_FILE STATEBUS_KV_API_TIMEOUT_S STATEBUS_KV_TOKENIZER_TIMEOUT_S \
    STATEBUS_ENGINE_LOCAL_KV_PARENT_TOKENS STATEBUS_ENGINE_LOCAL_KV_TTL_S STATEBUS_ENGINE_LOCAL_KV_SEED \
    STATEBUS_APC_ENABLED STATEBUS_APC_SERVICE_READY STATEBUS_APC_METRICS_URL STATEBUS_APC_METRICS_EXCLUSIVE; do
    if [[ -n "${!name-}" ]]; then
      container_env+=("-e" "$name=${!name}")
    fi
  done
fi
if ((dry_run)); then
  for current in "${families[@]}"; do
    printf '\nHOST_SOURCE_ROOT=%s\nCONTAINER_SOURCE_ROOT=%s\nPYTHONPATH=%s\nPROJECT_ROOT=%s\nLLM_CONFIG=%s\nHOST_OUTPUT=%s/%s\nCONTAINER_OUTPUT=%s/%s\nCOMMAND=' \
      "$ROOT" "$CONTAINER_SOURCE" "$CONTAINER_SOURCE" "$CONTAINER_SOURCE" \
      "$CONTAINER_SOURCE/deploy/statebus_llm.g6b2-qwen3-32b.example" "$output" "$current" "$container_output" "$current"
    printf '%q ' docker exec -w "$CONTAINER_SOURCE" "${container_env[@]}" "$container" "$PYTHON" -m statebus.benchmark.contest_dsl_mainline \
      "${args[@]}" --family "$current" --output "$container_output/$current"
    printf '\n'
    PYTHONPATH="$ROOT" PROJECT_ROOT="$ROOT" STATEBUS_LLM_CONFIG_FILE="$ROOT/deploy/statebus_llm.g6b2-qwen3-32b.example" \
      "$PYTHON" -m statebus.benchmark.contest_dsl_mainline "${args[@]}" --family "$current" \
      --output "$container_output/$current" --dry-run
  done
  exit 0
fi
[[ ! -e "$output" ]] || { echo "Refusing existing output: $output" >&2; exit 2; }
# Read-only checks, not a startup smoke. Never kill/reconfigure other jobs.
nvidia-smi -L
nvidia-smi --query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu --format=csv
nvidia-smi --query-compute-apps=gpu_uuid,pid,process_name,used_memory --format=csv
state="$(docker inspect "$container" --format '{{.State.Status}}')"
[[ "$state" == running ]] || { echo "Container is not running: $container" >&2; exit 2; }
curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:53334/health
curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:53334/v1/models | "$PYTHON" -c \
 'import json,sys; models=json.load(sys.stdin)["data"]; assert any(m["id"]=="qwen3-32b" and m.get("root")=="/data/models/Qwen3-32B" and m.get("max_model_len")==8192 for m in models), "served_model_or_context_mismatch"'
gpu_uuid="$(nvidia-smi -i 1 --query-gpu=uuid --format=csv,noheader)"
mkdir -p "$(dirname "$output")"
mkdir "$output"
# Reuse the existing single-encode GPU validation (no LLM call).
docker exec -w "$CONTAINER_SOURCE" \
  "${container_env[@]}" \
  "$container" "$PYTHON" -m statebus.benchmark.contest_preflight \
  --output "$container_output/embedding-preflight.json" --model qwen3-32b \
  --base-url http://127.0.0.1:53334/v1 \
  --embedding-model-path /statebus/models/Qwen3-Embedding-0.6B --gpu-uuid "$gpu_uuid" \
  --expected-source-root "$CONTAINER_SOURCE" \
  > "$output/embedding-preflight.log" 2>&1
trap 'echo "Interrupted; preserve $output (no automatic retry)." >&2; exit 130' INT
trap 'echo "Terminated; preserve $output (no automatic retry)." >&2; exit 143' TERM
rc=0
printf 'family\treturncode\n' > "$output/chain-exit-codes.tsv"
for current in "${families[@]}"; do
  printf '\n[contest39] %s %s: 12 slots -> %s/%s\n' "$current" "$variant" "$output" "$current"
  if docker exec -w "$CONTAINER_SOURCE" "${container_env[@]}" "$container" "$PYTHON" -u -m statebus.benchmark.contest_dsl_mainline \
    "${args[@]}" --family "$current" --output "$container_output/$current" \
    > "$output/$current.log" 2>&1; then
    chain_rc=0
  else
    chain_rc=$?
    rc=1
  fi
  printf '%s\t%s\n' "$current" "$chain_rc" >> "$output/chain-exit-codes.tsv"
  printf '[contest39] %s returncode=%s; log=%s/%s.log\n' "$current" "$chain_rc" "$output" "$current"
  if ((chain_rc == 130 || chain_rc == 143)); then exit "$chain_rc"; fi
done
"$PYTHON" scripts/show_contest_dsl_results.py "$output"
exit "$rc"
