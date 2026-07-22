#!/usr/bin/env bash
set -euo pipefail

endpoint="${STATEBUS_LATENT_API_URL:-http://127.0.0.1:53334/statebus/latent/health}"
token_file="${STATEBUS_LATENT_API_TOKEN_FILE:-${STATEBUS_LATENT_TOKEN_FILE:-}}"

if [[ -z "$token_file" || ! -s "$token_file" ]]; then
  printf 'latent token file is missing or empty\n' >&2
  exit 2
fi
if [[ "$(stat -c '%a' "$token_file")" != "600" ]]; then
  printf 'latent token file must have mode 600\n' >&2
  exit 2
fi

token="$(<"$token_file")"
if [[ -z "$token" || "$token" =~ [[:space:]] ]]; then
  printf 'latent token file is invalid\n' >&2
  exit 2
fi

response="$(curl --silent --show-error --fail --max-time "${STATEBUS_LATENT_CURL_TIMEOUT_S:-3}" --config - <<CURL_CONFIG
url = "$endpoint"
header = "Authorization: Bearer $token"
header = "Accept: application/json"
CURL_CONFIG
)"

printf '%s' "$response" | python3 -c '
import json
import sys

payload = json.load(sys.stdin)
required = ("status", "plugin_version", "compatibility_digest")
missing = [key for key in required if not payload.get(key)]
if missing:
    raise SystemExit("latent readiness response missing: " + ",".join(missing))
if payload.get("status") != "ready":
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    raise SystemExit(1)
if not payload.get("worker_extension_ready") or not payload.get("prompt_embeds_enabled"):
    raise SystemExit("latent readiness worker or prompt-embeds gate failed")
if int(payload.get("max_num_seqs", 0)) != 1:
    raise SystemExit("latent readiness max_num_seqs gate failed")
print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
'
