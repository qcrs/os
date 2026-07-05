#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="${STATEBUS_V2_CONTAINER_NAME:-statebus-dev-qcrs}"
HOST_RUNS_ROOT="${STATEBUS_HOST_RUNS_ROOT:-/home/qcrs/statebus/runs}"
CONTAINER_RUNS_ROOT="${STATEBUS_CONTAINER_RUNS_ROOT:-/statebus/runs}"
RESULT_ROOT_INPUT="${1:-${STATEBUS_AUDIT_RESULT_ROOT:-}}"
TARGET_CUDA_VISIBLE_DEVICES="${STATEBUS_CUDA_VISIBLE_DEVICES:-1}"
TARGET_EMBED_DEVICE="${STATEBUS_EMBED_DEVICE:-cuda:0}"
TARGET_TOKENIZERS_PARALLELISM="${TOKENIZERS_PARALLELISM:-false}"
TARGET_PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"
SMOKE_TIMEOUT_SECONDS="${STATEBUS_AUDIT_SMOKE_TIMEOUT_SECONDS:-900}"
PREFLIGHT_TIMEOUT_SECONDS="${STATEBUS_AUDIT_PREFLIGHT_TIMEOUT_SECONDS:-300}"
FORMAL_TIMEOUT_SECONDS="${STATEBUS_AUDIT_FORMAL_TIMEOUT_SECONDS:-900}"
COMPARE_TIMEOUT_SECONDS="${STATEBUS_AUDIT_COMPARE_TIMEOUT_SECONDS:-900}"
REPLAY_TIMEOUT_SECONDS="${STATEBUS_AUDIT_REPLAY_TIMEOUT_SECONDS:-1800}"
REPLAY_NEGATIVE_TIMEOUT_SECONDS="${STATEBUS_AUDIT_REPLAY_NEGATIVE_TIMEOUT_SECONDS:-600}"
FLAGSHIP_TIMEOUT_SECONDS="${STATEBUS_AUDIT_FLAGSHIP_TIMEOUT_SECONDS:-7200}"

if [[ -z "$RESULT_ROOT_INPUT" ]]; then
  echo "usage: $0 /home/qcrs/statebus/runs/v2-full-audit-YYYYMMDD_HHMMSS" >&2
  exit 2
fi

if [[ ! -d "$RESULT_ROOT_INPUT" ]]; then
  echo "missing result root: $RESULT_ROOT_INPUT" >&2
  exit 2
fi

RESULT_BASENAME="$(basename "$RESULT_ROOT_INPUT")"
HOST_RESULT_ROOT="${HOST_RUNS_ROOT}/${RESULT_BASENAME}"
CONTAINER_RESULT_ROOT="${CONTAINER_RUNS_ROOT}/${RESULT_BASENAME}"

if [[ ! -f "${HOST_RESULT_ROOT}/status.tsv" ]]; then
  echo "missing status.tsv under ${HOST_RESULT_ROOT}" >&2
  exit 2
fi

printf '[statebus-v2] rerunning failed audit stages only\n'
printf '[statebus-v2] host result root: %s\n' "$HOST_RESULT_ROOT"

docker exec -i -u 0 \
  -e STATEBUS_RESULT_ROOT="$CONTAINER_RESULT_ROOT" \
  -e CUDA_VISIBLE_DEVICES="$TARGET_CUDA_VISIBLE_DEVICES" \
  -e STATEBUS_EMBED_DEVICE="$TARGET_EMBED_DEVICE" \
  -e TOKENIZERS_PARALLELISM="$TARGET_TOKENIZERS_PARALLELISM" \
  -e PYTORCH_CUDA_ALLOC_CONF="$TARGET_PYTORCH_CUDA_ALLOC_CONF" \
  -e SMOKE_TIMEOUT_SECONDS="$SMOKE_TIMEOUT_SECONDS" \
  -e PREFLIGHT_TIMEOUT_SECONDS="$PREFLIGHT_TIMEOUT_SECONDS" \
  -e FORMAL_TIMEOUT_SECONDS="$FORMAL_TIMEOUT_SECONDS" \
  -e COMPARE_TIMEOUT_SECONDS="$COMPARE_TIMEOUT_SECONDS" \
  -e REPLAY_TIMEOUT_SECONDS="$REPLAY_TIMEOUT_SECONDS" \
  -e REPLAY_NEGATIVE_TIMEOUT_SECONDS="$REPLAY_NEGATIVE_TIMEOUT_SECONDS" \
  -e FLAGSHIP_TIMEOUT_SECONDS="$FLAGSHIP_TIMEOUT_SECONDS" \
  "$CONTAINER_NAME" bash -lc 'bash -s' <<'EOF'
#!/usr/bin/env bash
set -uo pipefail

source /usr/local/bin/activate_statebus_container.sh
cd /workspace/statebus/project

RESULT_ROOT="$STATEBUS_RESULT_ROOT"
STATUS_TSV="$RESULT_ROOT/status.tsv"
SUMMARY_JSON="$RESULT_ROOT/summary.json"
RERUN_STATUS_TSV="$RESULT_ROOT/rerun_status.tsv"
LATEST_STATUS_TSV="$RESULT_ROOT/status.latest.tsv"
LATEST_SUMMARY_MD="$RESULT_ROOT/summary.latest.md"
LATEST_SUMMARY_JSON="$RESULT_ROOT/summary.latest.json"
RERUN_CONSOLE="$RESULT_ROOT/rerun.console.log"

if [[ ! -f "$STATUS_TSV" ]]; then
  echo "missing status.tsv: $STATUS_TSV" >&2
  exit 2
fi

if [[ ! -f "$RERUN_STATUS_TSV" ]]; then
  printf 'stage\texit_code\tkind\tartifact\tlog_path\n' > "$RERUN_STATUS_TSV"
fi

exec > >(tee -a "$RERUN_CONSOLE") 2>&1

short_socket_path() {
  local label="$1"
  local digest
  digest="$(
    /usr/bin/python3 - "$label" <<'PY'
import hashlib
import sys

print(hashlib.sha1(sys.argv[1].encode("utf-8")).hexdigest()[:12])
PY
  )"
  printf '/tmp/sb-%s.sock' "$digest"
}

load_primary_mode() {
  if [[ -f "$SUMMARY_JSON" ]]; then
    mapfile -t primary_mode < <(
      /usr/bin/python3 - "$SUMMARY_JSON" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], "r", encoding="utf-8"))
mode = payload.get("primary_mode", {})
print(mode.get("role_path_mode", "api"))
print(mode.get("embedding_mode", "local"))
PY
    )
    PRIMARY_ROLE_PATH_MODE="${primary_mode[0]:-api}"
    PRIMARY_EMBEDDING_MODE="${primary_mode[1]:-local}"
  else
    PRIMARY_ROLE_PATH_MODE="api"
    PRIMARY_EMBEDDING_MODE="local"
  fi
}

record_rerun_stage() {
  local stage="$1"
  local exit_code="$2"
  local kind="$3"
  local artifact="$4"
  local log_path="$5"
  printf '%s\t%s\t%s\t%s\t%s\n' "$stage" "$exit_code" "$kind" "$artifact" "$log_path" >> "$RERUN_STATUS_TSV"
}

backup_stage_dir() {
  local stage="$1"
  local stage_dir="$RESULT_ROOT/stages/$stage"
  if [[ -d "$stage_dir" ]]; then
    local stamp
    stamp="$(date +%Y%m%d_%H%M%S)"
    local backup_root="$RESULT_ROOT/rerun_backups/${stage}-${stamp}"
    mkdir -p "$(dirname "$backup_root")"
    mv "$stage_dir" "$backup_root"
  fi
}

run_text_stage() {
  local stage="$1"
  local timeout_s="$2"
  shift 2
  local stage_dir="$RESULT_ROOT/stages/$stage"
  local log_path="$stage_dir/console.log"
  backup_stage_dir "$stage"
  mkdir -p "$stage_dir"
  echo
  echo "=== ${stage} ==="
  timeout "$timeout_s" "$@" 2>&1 | tee "$log_path"
  local exit_code=${PIPESTATUS[0]}
  record_rerun_stage "$stage" "$exit_code" "text" "-" "$log_path"
  echo "[rerun] ${stage} exit=${exit_code}"
  return 0
}

run_live_stage() {
  local stage="$1"
  local timeout_s="$2"
  local role_path_mode="$3"
  local embedding_mode="$4"
  local suite="$5"
  shift 5
  local stage_dir="$RESULT_ROOT/stages/$stage"
  local runtime_root="$stage_dir/runtime"
  local workspace_root="$stage_dir/workspaces"
  local socket_path
  local stdout_json="$stage_dir/stdout.json"
  local log_path="$stage_dir/console.log"
  backup_stage_dir "$stage"
  mkdir -p "$stage_dir" "$runtime_root" "$workspace_root"
  socket_path="$(short_socket_path "$stage")"
  rm -f "$socket_path"
  echo
  echo "=== ${stage} ==="
  timeout "$timeout_s" /usr/bin/python3 -m v2.benchmark.live_runner \
    --suite "$suite" \
    --role-path-mode "$role_path_mode" \
    --embedding-mode "$embedding_mode" \
    --runtime-root "$runtime_root" \
    --workspace-root "$workspace_root" \
    --socket-path "$socket_path" \
    --suite-id "${RESULT_ROOT##*/}-${stage}" \
    "$@" \
    > >(tee "$stdout_json") \
    2> >(tee "$log_path" >&2)
  local exit_code=$?
  if [[ "$exit_code" -eq 0 ]]; then
    /usr/bin/python3 - "$stdout_json" <<'PY'
import json
import sys

json.load(open(sys.argv[1], "r", encoding="utf-8"))
PY
  fi
  record_rerun_stage "$stage" "$exit_code" "live_runner" "$stdout_json" "$log_path"
  echo "[rerun] ${stage} exit=${exit_code}"
  return 0
}

run_stage_by_name() {
  local stage="$1"
  case "$stage" in
    00_env_probe)
      run_text_stage "$stage" 120 bash -lc 'pwd && /usr/bin/python3 --version && git branch --show-current && git rev-parse HEAD'
      ;;
    01_pytest_full)
      run_text_stage "$stage" "$PYTEST_TIMEOUT_SECONDS" /usr/bin/python3 -m pytest -q
      ;;
    02_runtime_smoke)
      run_text_stage "$stage" "$SMOKE_TIMEOUT_SECONDS" /usr/bin/python3 -m runtime.smoke
      ;;
    03_preflight_api_local)
      run_live_stage "$stage" "$PREFLIGHT_TIMEOUT_SECONDS" api local preflight
      ;;
    04_preflight_api_deterministic)
      run_live_stage "$stage" "$PREFLIGHT_TIMEOUT_SECONDS" api deterministic preflight
      ;;
    05_preflight_deterministic_local)
      run_live_stage "$stage" "$PREFLIGHT_TIMEOUT_SECONDS" deterministic local preflight
      ;;
    06_preflight_deterministic_deterministic)
      run_live_stage "$stage" "$PREFLIGHT_TIMEOUT_SECONDS" deterministic deterministic preflight
      ;;
    07_formal_primary)
      run_live_stage "$stage" "$FORMAL_TIMEOUT_SECONDS" "$PRIMARY_ROLE_PATH_MODE" "$PRIMARY_EMBEDDING_MODE" formal --benchmark-tier formal
      ;;
    08_compare_primary)
      run_live_stage "$stage" "$COMPARE_TIMEOUT_SECONDS" "$PRIMARY_ROLE_PATH_MODE" "$PRIMARY_EMBEDDING_MODE" compare --benchmark-tier dev
      ;;
    09_replay_negative_primary)
      run_live_stage "$stage" "$REPLAY_NEGATIVE_TIMEOUT_SECONDS" "$PRIMARY_ROLE_PATH_MODE" "$PRIMARY_EMBEDDING_MODE" replay-negative-audit
      ;;
    10_continuous_replay_collection_primary)
      run_live_stage "$stage" "$REPLAY_TIMEOUT_SECONDS" "$PRIMARY_ROLE_PATH_MODE" "$PRIMARY_EMBEDDING_MODE" continuous-replay --benchmark-tier dev
      ;;
    11_continuous_replay_cross_period_primary)
      run_live_stage "$stage" "$REPLAY_TIMEOUT_SECONDS" "$PRIMARY_ROLE_PATH_MODE" "$PRIMARY_EMBEDDING_MODE" continuous-replay --benchmark-tier dev --family cross_period_financial_v1
      ;;
    12_continuous_replay_csv_primary)
      run_live_stage "$stage" "$REPLAY_TIMEOUT_SECONDS" "$PRIMARY_ROLE_PATH_MODE" "$PRIMARY_EMBEDDING_MODE" continuous-replay --benchmark-tier dev --family csv_correlation_replay_v1
      ;;
    13_continuous_replay_long_doc_primary)
      run_live_stage "$stage" "$REPLAY_TIMEOUT_SECONDS" "$PRIMARY_ROLE_PATH_MODE" "$PRIMARY_EMBEDDING_MODE" continuous-replay --benchmark-tier dev --family long_doc_metric_replay_v1
      ;;
    14_continuous_replay_collection_det_local_fallback)
      run_live_stage "$stage" "$REPLAY_TIMEOUT_SECONDS" deterministic local continuous-replay --benchmark-tier dev
      ;;
    15_flagship_ablation_primary)
      run_live_stage "$stage" "$FLAGSHIP_TIMEOUT_SECONDS" "$PRIMARY_ROLE_PATH_MODE" "$PRIMARY_EMBEDDING_MODE" flagship-ablation
      ;;
    *)
      echo "unsupported stage for rerun: $stage" >&2
      return 1
      ;;
  esac
}

build_latest_summary() {
  /usr/bin/python3 - "$STATUS_TSV" "$RERUN_STATUS_TSV" "$LATEST_STATUS_TSV" "$LATEST_SUMMARY_MD" "$LATEST_SUMMARY_JSON" <<'PY'
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

status_path = Path(sys.argv[1])
rerun_path = Path(sys.argv[2])
latest_status_path = Path(sys.argv[3])
latest_summary_md = Path(sys.argv[4])
latest_summary_json = Path(sys.argv[5])

def load_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))

base_rows = load_rows(status_path)
rerun_rows = load_rows(rerun_path)

merged: dict[str, dict[str, str]] = {}
order: list[str] = []
for row in base_rows:
    stage = row["stage"]
    if stage not in merged:
        order.append(stage)
    merged[stage] = row
for row in rerun_rows:
    stage = row["stage"]
    if stage not in merged:
        order.append(stage)
    merged[stage] = row

with latest_status_path.open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=["stage", "exit_code", "kind", "artifact", "log_path"], delimiter="\t")
    writer.writeheader()
    for stage in order:
        writer.writerow(merged[stage])

failed = [row for row in (merged[stage] for stage in order) if row["exit_code"] != "0"]
payload = {
    "stage_count": len(order),
    "failed_stage_count": len(failed),
    "failed_stages": [row["stage"] for row in failed],
    "rerun_stage_count": len(rerun_rows),
    "stages": [merged[stage] for stage in order],
}
latest_summary_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

lines = [
    "# StateBus v2 Latest Audit Status",
    "",
    f"- Stage count: `{len(order)}`",
    f"- Failed stage count: `{len(failed)}`",
    f"- Rerun stage count: `{len(rerun_rows)}`",
    "",
    "## Failed Stages",
]
if failed:
    for row in failed:
        lines.append(f"- `{row['stage']}` exit `{row['exit_code']}`")
else:
    lines.append("- none")
lines.extend(["", "## Latest Stage Log", ""])
for stage in order:
    row = merged[stage]
    lines.append(f"- `{row['stage']}` exit `{row['exit_code']}` kind `{row['kind']}` artifact `{row['artifact']}`")
latest_summary_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
}

load_primary_mode

mapfile -t failed_stages < <(
  /usr/bin/python3 - "$STATUS_TSV" <<'PY'
import csv
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    rows = csv.DictReader(handle, delimiter="\t")
    for row in rows:
        if row["exit_code"] != "0":
            print(row["stage"])
PY
)

if [[ "${#failed_stages[@]}" -eq 0 ]]; then
  echo "no failed stages found in $STATUS_TSV"
  build_latest_summary
  exit 0
fi

echo "[statebus-v2] primary mode from summary: ${PRIMARY_ROLE_PATH_MODE} + ${PRIMARY_EMBEDDING_MODE}"
echo "[statebus-v2] failed stages to rerun:"
printf '  - %s\n' "${failed_stages[@]}"

for stage in "${failed_stages[@]}"; do
  run_stage_by_name "$stage"
done

build_latest_summary

echo
echo "=== rerun outputs ==="
echo "$RERUN_STATUS_TSV"
echo "$LATEST_STATUS_TSV"
echo "$LATEST_SUMMARY_MD"
echo "$LATEST_SUMMARY_JSON"
EOF

printf '[statebus-v2] rerun bundle updated: %s\n' "$HOST_RESULT_ROOT"
