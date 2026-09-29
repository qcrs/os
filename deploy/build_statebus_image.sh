#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${STATEBUS_DOCKER_ENV_FILE:-$ROOT/docker/.env}"
DRY_RUN=0
BUILD_ARGS=()

usage() {
  cat <<'EOF'
Usage: deploy/build_statebus_image.sh [options] [service]
  --env-file PATH    Compose environment file (default: docker/.env)
  --no-cache         Pass --no-cache to docker compose build
  --dry-run          Print the build command without running Docker

This builds the existing Dockerfile target selected by docker/.env. It only
builds an image; it never creates, replaces, starts, or stops a container.
EOF
}

while (($#)); do
  case "$1" in
    --env-file) (($# >= 2)) || { echo '--env-file requires a value' >&2; exit 2; }; ENV_FILE="$2"; shift 2 ;;
    --no-cache) BUILD_ARGS+=(--no-cache); shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) BUILD_ARGS+=("$1"); shift ;;
  esac
done

[[ -f "$ENV_FILE" ]] || { echo "Docker env file does not exist: $ENV_FILE" >&2; exit 2; }
command=(docker compose --env-file "$ENV_FILE" -f "$ROOT/docker/compose.yaml" build "${BUILD_ARGS[@]}")
printf '[statebus-docker] '; printf '%q ' "${command[@]}"; printf '\n'
((DRY_RUN)) || exec "${command[@]}"
