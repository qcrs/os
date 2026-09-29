#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:---help}"

usage() {
  cat <<'EOF'
Usage: demo/run_demo.sh --offline | --local-vllm

  --offline     Show the fixed recorded evidence entry without contacting a service
  --local-vllm  Start the existing StateBus Studio launcher against local services
EOF
}

case "$MODE" in
  --help|-h)
    usage
    ;;
  --offline)
    evidence="$ROOT/tests/evidence/utility/longtext-demo-v3"
    [[ -f "$evidence/README.md" ]] || { echo "Missing offline evidence: $evidence" >&2; exit 2; }
    printf 'offline_demo=recorded_replay\n'
    printf 'evidence_root=%s\n' "$evidence"
    printf 'summary=%s\n' "$evidence/longtext-demo-v3-summary.md"
    printf 'business_quality_passed=false (recorded run; see README)\n'
    ;;
  --local-vllm)
    shift
    exec "$ROOT/scripts/run_statebus_studio.sh" "$@"
    ;;
  *)
    echo "Unknown demo mode: $MODE" >&2
    usage >&2
    exit 2
    ;;
esac
