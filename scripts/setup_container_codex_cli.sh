#!/usr/bin/env bash
set -euo pipefail

if [[ ! -f "/.dockerenv" ]]; then
  echo "[statebus] scripts/setup_container_codex_cli.sh is intended for the Docker dev container." >&2
  exit 1
fi

CODEX_NPM_PACKAGE="${CODEX_NPM_PACKAGE:-@openai/codex}"
CODEX_NPM_SPEC="${CODEX_NPM_SPEC:-$CODEX_NPM_PACKAGE}"
CODEX_HOME_VALUE="${CODEX_HOME:-/statebus/work/codex-home}"
NPM_CONFIG_PREFIX_VALUE="${NPM_CONFIG_PREFIX:-$HOME/.local}"
NPM_CACHE_VALUE="${NPM_CACHE:-/statebus/caches/npm}"

mkdir -p "$CODEX_HOME_VALUE" "$NPM_CONFIG_PREFIX_VALUE" "$NPM_CACHE_VALUE"

echo "[statebus] codex npm spec: $CODEX_NPM_SPEC"
echo "[statebus] codex home: $CODEX_HOME_VALUE"
echo "[statebus] npm prefix: $NPM_CONFIG_PREFIX_VALUE"
echo "[statebus] npm cache: $NPM_CACHE_VALUE"
echo "[statebus] node: $(node --version 2>/dev/null || echo missing)"
echo "[statebus] npm: $(npm --version 2>/dev/null || echo missing)"

if ! command -v node >/dev/null 2>&1; then
  echo "[statebus] node is not installed in this container image." >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "[statebus] npm is not installed in this container image." >&2
  exit 1
fi

export CODEX_HOME="$CODEX_HOME_VALUE"
export NPM_CONFIG_PREFIX="$NPM_CONFIG_PREFIX_VALUE"
export NPM_CACHE="$NPM_CACHE_VALUE"
export PATH="$NPM_CONFIG_PREFIX_VALUE/bin${PATH:+:${PATH}}"

npm install -g "$CODEX_NPM_SPEC"

echo "[statebus] codex cli installed under $NPM_CONFIG_PREFIX_VALUE/bin"
echo "[statebus] codex home persisted at $CODEX_HOME_VALUE"
echo "[statebus] run: source /usr/local/bin/activate_statebus_container.sh && codex --help"
