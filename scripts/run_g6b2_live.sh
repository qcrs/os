#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONTAINER_SCRIPT="$OS_ROOT/scripts/run_g6b2_os_container.sh"
PYTHON_MODULE="statebus.benchmark.g6b2_live_validation"
LOCK_FILE="${STATEBUS_B2_LOCK_FILE:-$OS_ROOT/artifacts/.g6b2-live.lock}"

selected_model="${STATEBUS_LOCAL_VLLM_MODEL:-qwen3-32b}"
case "$selected_model" in
  qwen3-8b)
    export STATEBUS_G6B2_PROFILE_ID="${STATEBUS_G6B2_PROFILE_ID:-g6b2-live-qwen3-8b-gpu0-u050-qwen3-embedding-gpu1-v1}"
    export STATEBUS_G6B2_SERVICE_PHYSICAL_GPU="${STATEBUS_G6B2_SERVICE_PHYSICAL_GPU:-0}"
    export STATEBUS_G6B2_SERVICE_GPU_UUID="${STATEBUS_G6B2_SERVICE_GPU_UUID:-GPU-3ecfad62-035b-2626-e769-79c785e7665d}"
    export STATEBUS_LLM_CONFIG_FILE="${STATEBUS_LLM_CONFIG_FILE:-/workspace/statebus/os/deploy/statebus_llm.g6b2-qwen3-8b.example}"
    export STATEBUS_CONTAINER_LLM_CONFIG_FILE="${STATEBUS_CONTAINER_LLM_CONFIG_FILE:-/workspace/statebus/os/deploy/statebus_llm.g6b2-qwen3-8b.example}"
    default_service_runtime_dir="/home/qcrs/statebus/work/vllm-qwen3-8b-gpu0-u050"
    ;;
  qwen3-32b)
    export STATEBUS_G6B2_PROFILE_ID="${STATEBUS_G6B2_PROFILE_ID:-g6b2-live-qwen3-32b-gpu2-u050-qwen3-embedding-gpu1-v1}"
    export STATEBUS_G6B2_SERVICE_PHYSICAL_GPU="${STATEBUS_G6B2_SERVICE_PHYSICAL_GPU:-2}"
    export STATEBUS_G6B2_SERVICE_GPU_UUID="${STATEBUS_G6B2_SERVICE_GPU_UUID:-GPU-25019de8-09aa-328a-be23-4bec986badad}"
    export STATEBUS_LLM_CONFIG_FILE="${STATEBUS_LLM_CONFIG_FILE:-/workspace/statebus/os/deploy/statebus_llm.g6b2-qwen3-32b.example}"
    export STATEBUS_CONTAINER_LLM_CONFIG_FILE="${STATEBUS_CONTAINER_LLM_CONFIG_FILE:-/workspace/statebus/os/deploy/statebus_llm.g6b2-qwen3-32b.example}"
    default_service_runtime_dir="/home/qcrs/statebus/work/vllm-qwen3-32b-gpu2-u050"
    ;;
  *)
    printf 'unsupported STATEBUS_LOCAL_VLLM_MODEL: %s\n' "$selected_model" >&2
    exit 2
    ;;
esac
export STATEBUS_LOCAL_VLLM_MODEL="$selected_model"
export STATEBUS_CONTAINER_NAME="${STATEBUS_CONTAINER_NAME:-statebus-runtime}"
export STATEBUS_B2_CONTAINER_NAME="$STATEBUS_CONTAINER_NAME"
export STATEBUS_G6B2_EMBEDDING_MODE="${STATEBUS_G6B2_EMBEDDING_MODE:-local}"
export STATEBUS_G6B2_EMBEDDING_MODEL_PATH="${STATEBUS_G6B2_EMBEDDING_MODEL_PATH:-/statebus/models/Qwen3-Embedding-0.6B}"
export STATEBUS_G6B2_EMBEDDING_DEVICE="${STATEBUS_G6B2_EMBEDDING_DEVICE:-cuda:0}"
export STATEBUS_G6B2_EMBEDDING_PHYSICAL_GPU="${STATEBUS_G6B2_EMBEDDING_PHYSICAL_GPU:-${STATEBUS_EMBED_PHYSICAL_GPU:-1}}"
export STATEBUS_EMBED_PHYSICAL_GPU="$STATEBUS_G6B2_EMBEDDING_PHYSICAL_GPU"
export STATEBUS_EMBED_MODEL_PATH="$STATEBUS_G6B2_EMBEDDING_MODEL_PATH"
export STATEBUS_EMBED_DEVICE="$STATEBUS_G6B2_EMBEDDING_DEVICE"

usage() {
  cat <<'EOF'
Usage:
  scripts/run_g6b2_live.sh --help
  scripts/run_g6b2_live.sh minimal [options]
  scripts/run_g6b2_live.sh campaign --minimal-evidence-root ROOT [options]
  scripts/run_g6b2_live.sh soak --campaign-evidence-root ROOT [options]
  scripts/run_g6b2_live.sh verify --artifact-root ROOT

The runner reuses the user-owned Qwen3-32B service at 127.0.0.1:53334.
It never starts, stops, restarts, or kills vLLM. Runs are foreground-only;
Ctrl-C stops this client and keeps the service and evidence roots.
GPU coexistence is operator-managed. --coexist-pids is accepted only as a
deprecated compatibility option and is not inspected or enforced.
EOF
}

die() { printf 'error: %s\n' "$*" >&2; exit 2; }

mode="${1:-}"
[[ "$mode" == "--help" || "$mode" == "-h" ]] && { usage; exit 0; }
[[ -n "$mode" ]] || { usage >&2; exit 2; }
shift

service_runtime_dir="$default_service_runtime_dir"
coexist_pids=""
output_base="artifacts"
pairs=""
max_duration_s=""
min_slot_interval_s="0"
artifact_root=""
minimal_evidence_root=""
campaign_evidence_root=""

container_artifact_root() {
  local root="$1" mapped
  mapped="$($CONTAINER_SCRIPT map-path "$root")" || {
    die "artifact root is not visible through the current statebus-runtime mounts: $root"
  }
  printf '%s\n' "$mapped"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --service-runtime-dir) service_runtime_dir="${2:?missing value}"; shift 2;;
    --coexist-pids) coexist_pids="${2:?missing value}"; shift 2;;
    --output-base) output_base="${2:?missing value}"; shift 2;;
    --pairs) pairs="${2:?missing value}"; shift 2;;
    --max-duration-s) max_duration_s="${2:?missing value}"; shift 2;;
    --min-slot-interval-s) min_slot_interval_s="${2:?missing value}"; shift 2;;
    --artifact-root) artifact_root="${2:?missing value}"; shift 2;;
    --minimal-evidence-root) minimal_evidence_root="${2:?missing value}"; shift 2;;
    --campaign-evidence-root) campaign_evidence_root="${2:?missing value}"; shift 2;;
    -h|--help) usage; exit 0;;
    *) die "unknown option: $1";;
  esac
done

cd "$OS_ROOT"
mkdir -p "$output_base"
exec 9>"$LOCK_FILE"
flock -n 9 || die "another G6-B2 client is already running"

if [[ "$mode" == "verify" ]]; then
  [[ -n "$artifact_root" ]] || die "verify requires --artifact-root"
  exec python3 -m "$PYTHON_MODULE" verify --artifact-root "$artifact_root"
fi

case "$mode" in
  minimal)
    pairs="${pairs:-1}"
    max_duration_s="${max_duration_s:-600}"
    [[ "$pairs" == 1 ]] || die "minimal requires --pairs 1"
    ;;
  campaign)
    [[ -n "$minimal_evidence_root" ]] || die "campaign requires --minimal-evidence-root"
    pairs="${pairs:-120}"
    max_duration_s="${max_duration_s:-7200}"
    [[ "$pairs" -le 120 ]] || die "campaign --pairs must be <= 120"
    python3 -m "$PYTHON_MODULE" verify --artifact-root "$minimal_evidence_root" --require-mode minimal >/dev/null || die "minimal evidence root did not pass offline verify"
    ;;
  soak)
    [[ -n "$campaign_evidence_root" ]] || die "soak requires --campaign-evidence-root"
    pairs="${pairs:-480}"
    max_duration_s="${max_duration_s:-28800}"
    [[ "$pairs" -le 480 ]] || die "soak --pairs must be <= 480"
    [[ "$min_slot_interval_s" -ge 60 ]] || die "soak requires --min-slot-interval-s >= 60"
    python3 -m "$PYTHON_MODULE" verify --artifact-root "$campaign_evidence_root" --require-mode campaign >/dev/null || die "campaign evidence root did not pass offline verify"
    ;;
  *) die "mode must be minimal, campaign, soak, or verify";;
esac

preflight_output="$(python3 -m "$PYTHON_MODULE" host-preflight \
  --mode "$mode" \
  --output-base "$output_base" \
  --service-runtime-dir "$service_runtime_dir" \
  --coexist-pids "$coexist_pids" \
  --pairs "$pairs" \
  --max-duration-s "$max_duration_s")" || {
    printf '%s\n' "$preflight_output"
    exit 1
  }
artifact_root="$(printf '%s\n' "$preflight_output" | tail -n 1)"
printf 'artifact_root=%s\n' "$artifact_root"

"$CONTAINER_SCRIPT" up
"$CONTAINER_SCRIPT" verify
"$CONTAINER_SCRIPT" smoke
python3 -m "$PYTHON_MODULE" container-profile \
  --artifact-root "$artifact_root" \
  --container-name "$STATEBUS_CONTAINER_NAME"
container_root="$(container_artifact_root "$artifact_root")"
if [[ "${STATEBUS_G6B2_EMBEDDING_MODE:-deterministic}" == "local" ]]; then
  "$CONTAINER_SCRIPT" exec python3 -m "$PYTHON_MODULE" embedding-probe \
    --artifact-root "$container_root"
fi
"$CONTAINER_SCRIPT" exec python3 -m "$PYTHON_MODULE" smoke --artifact-root "$container_root"
"$CONTAINER_SCRIPT" exec python3 -m "$PYTHON_MODULE" execute \
  --mode "$mode" \
  --artifact-root "$container_root" \
  --pairs "$pairs" \
  --max-duration-s "$max_duration_s" \
  --min-slot-interval-s "$min_slot_interval_s"
