#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_PREFIX="${STATEBUS_ENV_PREFIX:-${HOME}/statebus/conda-envs/statebus_host}"
PYTHON_VERSION="${STATEBUS_PYTHON_VERSION:-3.11}"
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: deploy/install_statebus_host.sh [options]
  --prefix PATH       Conda environment path (default: ~/statebus/conda-envs/statebus_host)
  --python VERSION    Python version (default: 3.11)
  --dry-run           Print commands without creating or changing an environment
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
install=("$CONDA_EXE" run -p "$ENV_PREFIX" python -m pip install -r "$ROOT/requirements-host.txt" -r "$ROOT/requirements-studio.txt")
editable=("$CONDA_EXE" run -p "$ENV_PREFIX" python -m pip install -e "$ROOT")
verify=("$CONDA_EXE" run -p "$ENV_PREFIX" python -c 'import statebus; print(statebus.__file__)')

printf '[statebus-host] prefix=%s python=%s\n' "$ENV_PREFIX" "$PYTHON_VERSION"
printf '[statebus-host] requirements=%s\n' "$ROOT/requirements-host.txt"
if [[ ! -d "$ENV_PREFIX" ]]; then
  printf '[statebus-host] '; printf '%q ' "${create[@]}"; printf '\n'
  ((DRY_RUN)) || "${create[@]}"
fi
for step in install editable verify; do
  case "$step" in
    install) current=("${install[@]}") ;;
    editable) current=("${editable[@]}") ;;
    verify) current=("${verify[@]}") ;;
  esac
  printf '[statebus-host] '; printf '%q ' "${current[@]}"; printf '\n'
  ((DRY_RUN)) || "${current[@]}"
done
