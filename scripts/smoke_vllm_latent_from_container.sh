#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf '%s\n' \
    'Usage: bash scripts/smoke_vllm_latent_from_container.sh [--health|--probe]' \
    '' \
    'The default --health probe checks authenticated plugin readiness.' \
    '--probe additionally POSTs JSON files named by STATEBUS_LATENT_PRODUCE_JSON_FILE' \
    'and STATEBUS_LATENT_COMPLETE_JSON_FILE. It never creates a token.'
}

mode="${1:---health}"
case "$mode" in
  --health|--probe) ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "$script_dir/check_vllm_latent_readiness.sh"

if [[ "$mode" == "--health" ]]; then
  exit 0
fi

token_file="${STATEBUS_LATENT_API_TOKEN_FILE:-${STATEBUS_LATENT_TOKEN_FILE:-}}"
produce_file="${STATEBUS_LATENT_PRODUCE_JSON_FILE:-}"
complete_file="${STATEBUS_LATENT_COMPLETE_JSON_FILE:-}"
endpoint_base="${STATEBUS_LATENT_API_BASE_URL:-http://127.0.0.1:53334}"

if [[ -z "$token_file" || ! -s "$token_file" ]]; then
  printf 'latent token file is missing or empty\n' >&2
  exit 2
fi
if [[ "$(stat -c '%a' "$token_file")" != "600" ]]; then
  printf 'latent token file must have mode 600\n' >&2
  exit 2
fi
if [[ -z "$produce_file" || ! -s "$produce_file" || -z "$complete_file" || ! -s "$complete_file" ]]; then
  printf -- '--probe requires two non-empty JSON payload files\n' >&2
  exit 2
fi

token="$(<"$token_file")"
produce_response="$(curl --silent --show-error --fail --max-time "${STATEBUS_LATENT_CURL_TIMEOUT_S:-120}" --config - <<CURL_CONFIG
url = "$endpoint_base/statebus/latent/produce"
header = "Authorization: Bearer $token"
header = "Content-Type: application/json"
data-binary = @$produce_file
CURL_CONFIG
)"

printf '%s\n' "$produce_response"
ref_id="$(printf '%s' "$produce_response" | python3 -c 'import json,sys; value=json.load(sys.stdin).get("ref_id"); raise SystemExit("missing ref_id") if not value else print(value)')"

python3 - "$complete_file" "$ref_id" <<'PY'
import json
import sys

path, ref_id = sys.argv[1:]
payload = json.loads(open(path, encoding="utf-8").read())
if payload.get("latent_ref_id") != ref_id:
    raise SystemExit("complete payload latent_ref_id must match producer response")
PY

curl --silent --show-error --fail --max-time "${STATEBUS_LATENT_CURL_TIMEOUT_S:-120}" --config - <<CURL_CONFIG
url = "$endpoint_base/statebus/latent/complete"
header = "Authorization: Bearer $token"
header = "Content-Type: application/json"
data-binary = @$complete_file
CURL_CONFIG
