#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="/home/qcrs/statebus/conda-envs/statebus_host/bin/python"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT_ROOT="${STATEBUS_RUNS_DIR:-$HOME/statebus/runs}"
RUN_ROOT="${1:-$OUT_ROOT/host_test_then_api_repeat1_micro_surface_${STAMP}}"
LLM_CONFIG_PATH="${STATEBUS_LLM_CONFIG_PATH:-deploy/statebus_llm.yaml.local}"
PYTEST_EXPR="${STATEBUS_TARGETED_PYTEST_EXPR:-planner_support_v3 or validate_gate or typed_state_mechanism_v3 or wrong_family or contest_dual_mode_controlled_v3_repeat_one_does_not_pass_formal_stability_gate}"

mkdir -p "$RUN_ROOT/task_sets"

cd "$ROOT"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "missing python: $PYTHON_BIN" >&2
  exit 1
fi

unset all_proxy || true
unset ALL_PROXY || true

echo "[statebus] run root: $RUN_ROOT"
echo "[statebus] python: $PYTHON_BIN"
echo "[statebus] note: this is a micro repeat=1 API probe for issue discovery only, not formal stability evidence."

"$PYTHON_BIN" -m pytest -q \
  tests/test_llm_runtime.py \
  tests/test_state_channels_and_graph.py \
  tests/test_smoke.py \
  -k "$PYTEST_EXPR" | tee "$RUN_ROOT/targeted_pytest.log"

"$PYTHON_BIN" -m runtime.smoke | tee "$RUN_ROOT/runtime_smoke.log"

"$PYTHON_BIN" - <<PY
from pathlib import Path
import yaml

ROOT = Path("/home/qcrs/statebus/project")
OUT = Path("${RUN_ROOT}") / "task_sets"

SPECS = [
    (
        "contest_micro",
        ROOT / "tasks" / "contest_dual_mode_controlled_v3_benchmark.yaml",
        [
            "rr-auth-distractor-text-001",
            "rr-auth-distractor-protocol-001",
            "rr-cache-distractor-text-001",
            "rr-cache-distractor-protocol-001",
        ],
        "Micro contest probe covering wrong-family-prone distractor rows in matched text/protocol pairs.",
    ),
    (
        "typed_state_micro",
        ROOT / "tasks" / "typed_state_mechanism_v3_benchmark.yaml",
        [
            "rr-checkout-distractor-natural-handoff-001",
            "rr-checkout-distractor-state-packet-101",
        ],
        "Micro typed-state probe covering natural_handoff_text vs state_packet_minimal on the same distractor case.",
    ),
    (
        "planner_micro",
        ROOT / "tasks" / "planner_support_v3_benchmark.yaml",
        [
            "planner-support-auth-llm-001",
            "planner-support-cache-llm-001",
        ],
        "Micro planner probe covering llm plan compilation plus validate-before-execute on two route families.",
    ),
    (
        "memory_fairness_micro",
        ROOT / "tasks" / "memory_dual_mode_fairness_v3_benchmark.yaml",
        [
            "memory-dual-01-cold_start-text-001",
            "memory-dual-01-cold_start-protocol-001",
            "memory-dual-01-assist-text-001",
            "memory-dual-01-assist-protocol-001",
        ],
        "Micro memory fairness probe covering cold-start vs assist under matched text/protocol rows.",
    ),
]

for bundle_name, source_path, task_ids, description in SPECS:
    payload = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    metadata = dict(payload.get("task_set", {}) or {})
    all_tasks = list(payload["tasks"])
    selected = [task for task in all_tasks if str(task.get("task_id", "")).strip() in set(task_ids)]
    missing = [task_id for task_id in task_ids if task_id not in {str(task.get("task_id", "")).strip() for task in selected}]
    if missing:
        raise SystemExit(f"{bundle_name}: missing task ids: {missing}")
    metadata["name"] = f"{metadata.get('name', bundle_name)}__micro"
    metadata["description"] = description
    out_path = OUT / f"{bundle_name}.yaml"
    out_path.write_text(
        yaml.safe_dump({"task_set": metadata, "tasks": selected}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(out_path)
PY

for task_set in "$RUN_ROOT"/task_sets/*.yaml; do
  name="$(basename "$task_set" .yaml)"
  pack_out="$RUN_ROOT/benchmarks/$name"
  mkdir -p "$pack_out"
  echo "[statebus] api repeat=1 task set: $name"
  "$PYTHON_BIN" -m eval.runner \
    --task-set "$task_set" \
    --repeat 1 \
    --modes text,protocol \
    --llm-mode api \
    --llm-config "$LLM_CONFIG_PATH" \
    --embedding-mode deterministic \
    --out "$pack_out" \
    --quiet-progress | tee "$RUN_ROOT/${name}.log"
done

cat > "$RUN_ROOT/README.txt" <<EOF
StateBus host test then API repeat=1 micro surface run

Python:
  $PYTHON_BIN

Micro coverage:
  - contest wrong-family-prone distractors: 4 tasks
  - typed-state mechanism parity: 2 tasks
  - planner llm + validate-before-execute: 2 tasks
  - memory fairness cold-start vs assist: 4 tasks

Contract:
  - targeted tests and runtime.smoke run first
  - API benchmark runs are serialized repeat=1 micro probes
  - this package is for issue discovery and report/flow correctness only
  - do not treat it as formal stability evidence or headline proof
EOF

echo "[statebus] done: $RUN_ROOT"
