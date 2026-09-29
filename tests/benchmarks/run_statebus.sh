#!/usr/bin/env bash
set -Eeuo pipefail

# Stable dispatcher for the contest and performance entry points. The existing
# runners remain the implementation owners; this script only selects one.
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
COMMAND="${1:-help}"
if (($# > 0)); then
  shift
fi

usage() {
  cat <<'EOF'
Usage: tests/benchmarks/run_statebus.sh <command> [options]

Commands:
  smoke                Local-vLLM container smoke check
  mainline-24          24-round contest mainline (two 12-round families)
  mainline             Alias for mainline-24
  mainline-mechanisms  Mainline mechanism ablation runner
  mechanisms           Alias for mainline-mechanisms
  apc                  Long-text APC utility phase
  kv                   Long-text explicit-KV utility phase
  logit                Long-text Logit utility phase
  utility              Full longtext-demo-v3 utility suite
  longtext             Alias for utility

The --dry-run flag is routed to runners that support it. For smoke it only
prints the underlying command. Live experiments still require their runner's
explicit --execute/--yes and service-management arguments.
EOF
}

if [[ "$COMMAND" == help || "$COMMAND" == --help || "$COMMAND" == -h ]]; then
  usage
  exit 0
fi

dry_run=0
forwarded=()
for arg in "$@"; do
  if [[ "$arg" == --dry-run ]]; then
    dry_run=1
  else
    forwarded+=("$arg")
  fi
done

print_command() {
  printf '[statebus-dispatch] '
  printf '%q ' "$@"
  printf '\n'
}

case "$COMMAND" in
  smoke)
    cmd=("$ROOT/scripts/run_local_vllm_container_check.sh" "${forwarded[@]}")
    if ((dry_run)); then
      print_command "${cmd[@]}"
      exit 0
    fi
    exec "${cmd[@]}"
    ;;
  mainline-24|mainline)
    cmd=("$ROOT/scripts/run_contest_dsl_mainchains.sh" --family all "${forwarded[@]}")
    ((dry_run)) && cmd+=(--dry-run)
    exec "${cmd[@]}"
    ;;
  mainline-mechanisms|mechanisms)
    cmd=("$ROOT/scripts/run_contest_mechanisms.sh" "${forwarded[@]}")
    ((dry_run)) && cmd+=(--dry-run)
    exec "${cmd[@]}"
    ;;
  apc|kv|logit)
    cmd=("$ROOT/scripts/experiments/contest_model_assist/run_utility_suite.sh" --mode formal --phase "$COMMAND" "${forwarded[@]}")
    ((dry_run)) && cmd+=(--dry-run)
    exec "${cmd[@]}"
    ;;
  utility|longtext)
    cmd=("$ROOT/scripts/experiments/contest_model_assist/run_utility_suite.sh" --mode formal --phase all "${forwarded[@]}")
    ((dry_run)) && cmd+=(--dry-run)
    exec "${cmd[@]}"
    ;;
  *)
    printf 'Unknown command: %s\n\n' "$COMMAND" >&2
    usage >&2
    exit 2
    ;;
esac
