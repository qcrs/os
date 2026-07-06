# Command Log: 15 Fairness Gate Propagation

All commands were run inside `statebus-dev-qcrs` with:

```bash
source /usr/local/bin/activate_statebus_container.sh
cd /workspace/statebus/project
```

## Targeted Tests

```bash
/usr/bin/python3 -m pytest -q tests/v2/test_fixed_answer_and_external_baseline.py tests/v2/test_compare_diagnostics.py
```

Result: `38 passed in 21.82s`

Review follow-up result: `40 passed in 20.48s`

## Full v2 Tests

```bash
/usr/bin/python3 -m pytest -q tests/v2
```

Result: `212 passed, 100 warnings in 388.02s`

Review follow-up result: `214 passed, 100 warnings in 369.84s`

## Four-Mode Preflight

```bash
/usr/bin/python3 -m v2.benchmark.live_runner --suite preflight --role-path-mode api --embedding-mode local
/usr/bin/python3 -m v2.benchmark.live_runner --suite preflight --role-path-mode api --embedding-mode deterministic
/usr/bin/python3 -m v2.benchmark.live_runner --suite preflight --role-path-mode deterministic --embedding-mode local
/usr/bin/python3 -m v2.benchmark.live_runner --suite preflight --role-path-mode deterministic --embedding-mode deterministic
```

Result: all four returned `"ok": true`.

## Live Compare

```bash
/usr/bin/python3 -m v2.benchmark.live_runner \
  --suite compare \
  --benchmark-tier dev \
  --statebus-mode cold-start \
  --role-path-mode api \
  --embedding-mode local \
  --suite-id codex-fairness-gate-20260706 \
  --workspace-root /statebus/work/codex-fairness-gate-20260706/workspaces \
  --runtime-root /statebus/runs/codex-fairness-gate-20260706/runtime \
  --socket-path /tmp/cfg.sock
```

Result: `fixed_answer_external_comparison_valid=true`

Review follow-up live compare:

```bash
/usr/bin/python3 -m v2.benchmark.live_runner \
  --suite compare \
  --benchmark-tier dev \
  --statebus-mode cold-start \
  --role-path-mode api \
  --embedding-mode local \
  --suite-id codex-raw-fairness-20260706 \
  --workspace-root /statebus/work/codex-raw-fairness-20260706/workspaces \
  --runtime-root /statebus/runs/codex-raw-fairness-20260706/runtime \
  --socket-path /tmp/crf.sock
```

Result: `fixed_answer_external_comparison_valid=true`

## JSON Inspection

```bash
jq '.fairness_manifest | {pass_hard_gate, external_fairness_gate_coverage, no_external_fairness_gate_failures, external_fairness_gate_pass_count, external_fairness_gate_failed_case_count, external_fairness_gate_failed_check_count, external_fairness_gate_failed_checks}' \
  /home/qcrs/statebus/runs/codex-fairness-gate-20260706/runtime/benchmark_reports/codex-fairness-gate-20260706-cold-start-compare-api.json
```

Result: hard gate passed, coverage true, no external fairness failures.

Review follow-up JSON inspection used `/usr/bin/python3` because `jq` was not installed in the container.

Result: hard gate passed, coverage true, no external fairness failures, and all external case `failed_checks` lists were empty.

## Runtime Smoke

```bash
/usr/bin/python3 -m runtime.smoke
```

Result: text/protocol smoke passed and comparator artifact was generated.

## Full Repo Tests

```bash
/usr/bin/python3 -m pytest -q
```

Result: `507 passed, 101 warnings in 951.49s`

## Git

```bash
git add runtime/llm.py scripts/v2_diagnostics/compare_diagnostics.py tests/v2/test_compare_diagnostics.py tests/v2/test_fixed_answer_and_external_baseline.py v2/benchmark/comparator_runner.py v2/benchmark/external_text_baseline.py
git commit -m "Propagate external fairness gate failures"
```

Result: `a6e951e`
