#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LIVE_RUNNER="$OS_ROOT/scripts/run_g6b2_live.sh"
CONTAINER_RUNNER="$OS_ROOT/scripts/run_g6b2_os_container.sh"
PYTHON_MODULE="statebus.benchmark.g6b2_live_validation"
LOCK_FILE="${STATEBUS_B2_LOCK_FILE:-$OS_ROOT/artifacts/.g6b2-live.lock}"

export STATEBUS_G6B2_PROFILE_ID="g6b2-live-qwen3-8b-gpu0-u050-qwen3-embedding-gpu1-v1"
export STATEBUS_G6B2_EMBEDDING_MODE="local"
export STATEBUS_G6B2_EMBEDDING_MODEL_PATH="/statebus/models/Qwen3-Embedding-0.6B"
export STATEBUS_G6B2_EMBEDDING_DEVICE="cuda:0"
export STATEBUS_EMBED_MODEL_PATH="/statebus/models/Qwen3-Embedding-0.6B"
export STATEBUS_EMBED_DEVICE="cuda:0"

usage() {
  cat <<'EOF'
Usage:
  scripts/run_g6b2_real_embedding.sh minimal [G6-B2 options]
  scripts/run_g6b2_real_embedding.sh recommended --minimal-evidence-root ROOT [options]
  scripts/run_g6b2_real_embedding.sh campaign --minimal-evidence-root ROOT [options]
  scripts/run_g6b2_real_embedding.sh verify --artifact-root ROOT
  scripts/run_g6b2_real_embedding.sh nontext-targeted [--output-base DIR]
  scripts/run_g6b2_real_embedding.sh nontext-full [--output-base DIR]

The live modes keep table document retrieval structural while using
Qwen3-Embedding-0.6B on physical GPU 1 (container cuda:0) for Memory query and
commit vectors. Campaign defaults to 8 pairs and rejects more than 16.

recommended runs the focused post-minimal validation: one 8-pair campaign,
then the three-case nontext-targeted set. It stops on the first failure and
does not run the optional 16-pair repetition or eight-case full holdout.

nontext-targeted runs three current-os semantic holdout cases: narrative-only,
table-only, and mixed. nontext-full runs all eight cases. These validate table
structure and dense SemanticStateRef transfer; image/audio/video are not tested.

This runner never starts, stops, restarts, or kills vLLM.
EOF
}

die() { printf 'error: %s\n' "$*" >&2; exit 2; }

mode="${1:-}"
[[ "$mode" == "--help" || "$mode" == "-h" ]] && { usage; exit 0; }
[[ -n "$mode" ]] || { usage >&2; exit 2; }
shift

case "$mode" in
  minimal|verify)
    exec "$LIVE_RUNNER" "$mode" "$@"
    ;;
  recommended)
    minimal_evidence_root=""
    service_runtime_dir="/home/qcrs/statebus/work/vllm-qwen3-8b-gpu0-u050"
    output_base="artifacts"
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --minimal-evidence-root)
          minimal_evidence_root="${2:?missing value}"
          shift 2
          ;;
        --service-runtime-dir)
          service_runtime_dir="${2:?missing value}"
          shift 2
          ;;
        --output-base)
          output_base="${2:?missing value}"
          shift 2
          ;;
        -h|--help)
          usage
          exit 0
          ;;
        *)
          die "recommended accepts only --minimal-evidence-root, --service-runtime-dir, and --output-base"
          ;;
      esac
    done
    [[ -n "$minimal_evidence_root" ]] || die "recommended requires --minimal-evidence-root"
    [[ -d "$minimal_evidence_root" ]] || die "minimal evidence root not found: $minimal_evidence_root"

    printf '%s\n' '=== focused real-embedding campaign: 8 pairs ==='
    "$0" campaign \
      --minimal-evidence-root "$minimal_evidence_root" \
      --service-runtime-dir "$service_runtime_dir" \
      --pairs 8 \
      --max-duration-s 1800 \
      --output-base "$output_base"

    printf '%s\n' '=== focused structured-nontext validation: 3 cases ==='
    "$0" nontext-targeted --output-base "$output_base"

    printf '%s\n' 'RECOMMENDED_REAL_EMBEDDING_VALIDATION_PASSED'
    ;;
  campaign)
    pairs=""
    has_duration=0
    args=("$@")
    for ((index=0; index<${#args[@]}; index++)); do
      case "${args[$index]}" in
        --pairs)
          ((index + 1 < ${#args[@]})) || die "--pairs requires a value"
          pairs="${args[$((index + 1))]}"
          ;;
        --max-duration-s) has_duration=1 ;;
      esac
    done
    pairs="${pairs:-8}"
    [[ "$pairs" =~ ^[0-9]+$ ]] || die "--pairs must be an integer"
    (( pairs >= 1 && pairs <= 16 )) || die "real embedding campaign --pairs must be 1..16"
    extra=(--pairs "$pairs")
    (( has_duration == 1 )) || extra+=(--max-duration-s 1800)
    exec "$LIVE_RUNNER" campaign "${extra[@]}" "$@"
    ;;
  nontext-targeted|nontext-full)
    scope="targeted"
    [[ "$mode" == "nontext-full" ]] && scope="full"
    cd "$OS_ROOT"
    mkdir -p artifacts
    exec 9>"$LOCK_FILE"
    flock -n 9 || die "another G6-B2 client is already running"
    "$CONTAINER_RUNNER" up
    "$CONTAINER_RUNNER" verify
    "$CONTAINER_RUNNER" smoke
    exec "$CONTAINER_RUNNER" exec python3 -m "$PYTHON_MODULE" nontext \
      --scope "$scope" "$@"
    ;;
  *)
    die "mode must be minimal, recommended, campaign, verify, nontext-targeted, or nontext-full"
    ;;
esac
