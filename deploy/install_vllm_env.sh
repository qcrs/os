#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_PREFIX="${STATEBUS_VLLM_ENV_PREFIX:-${HOME}/statebus/conda-envs/vllm-qwen-cu121}"
PYTHON_VERSION="${STATEBUS_VLLM_PYTHON_VERSION:-3.11}"
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: deploy/install_vllm_env.sh [options]
  --prefix PATH       Conda environment path (default: ~/statebus/conda-envs/vllm-qwen-cu121)
  --python VERSION    Python version (default: 3.11)
  --dry-run           Print commands without creating or changing an environment

This installs the pinned host-side vLLM requirements. It does not start vLLM.
Check GPU ownership and the resolved vLLM config separately before starting it.
EOF
}

while (($#)); do
  case "$1" in
    --prefix) (($# >= 2)) || { echo '--prefix requires a value' >&2; exit 2; }; ENV_PREFIX="$2"; shift 2 ;;
    --python) (($# >= 2)) || { echo '--python requires a value' >&2; exit 2; }; PYTHON_VERSION="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

CONDA_EXE="${CONDA_EXE:-$(command -v conda || true)}"
[[ -n "$CONDA_EXE" ]] || { echo 'conda is required; set CONDA_EXE or add conda to PATH' >&2; exit 2; }

create=("$CONDA_EXE" create -y -p "$ENV_PREFIX" "python=$PYTHON_VERSION")
upgrade=("$CONDA_EXE" run -p "$ENV_PREFIX" python -m pip install --upgrade pip setuptools wheel)
install=("$CONDA_EXE" run -p "$ENV_PREFIX" python -m pip install -r "$ROOT/requirements-vllm.txt")
check=("$CONDA_EXE" run -p "$ENV_PREFIX" python -m pip check)

printf '[statebus-vllm] prefix=%s python=%s\n' "$ENV_PREFIX" "$PYTHON_VERSION"
if [[ ! -d "$ENV_PREFIX" ]]; then
  printf '[statebus-vllm] '; printf '%q ' "${create[@]}"; printf '\n'
  ((DRY_RUN)) || "${create[@]}"
fi
for step in upgrade install check; do
  case "$step" in
    upgrade) command=("${upgrade[@]}") ;;
    install) command=("${install[@]}") ;;
    check) command=("${check[@]}") ;;
  esac
  printf '[statebus-vllm] '; printf '%q ' "${command[@]}"; printf '\n'
  ((DRY_RUN)) || "${command[@]}"
done
