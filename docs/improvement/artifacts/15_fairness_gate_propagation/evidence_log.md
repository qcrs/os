# Evidence Log: 15 Fairness Gate Propagation

## Strong Evidence

- Targeted tests passed: `38 passed`.
- Full v2 tests passed: `212 passed`.
- Full repo tests passed: `507 passed`.
- Runtime smoke passed.
- `api + local` preflight passed.
- Live `api + local` compare passed and generated inspectable JSON.
- JSON inspection confirmed:
  - `pass_hard_gate = true`
  - `external_fairness_gate_coverage = true`
  - `no_external_fairness_gate_failures = true`
  - `external_fairness_gate_pass_count = 3`
  - `external_fairness_gate_failed_case_count = 0`
  - `external_fairness_gate_failed_check_count = 0`
  - per-case `failed_checks = []`

## Medium Evidence

- `api + deterministic`, `deterministic + local`, and `deterministic + deterministic` preflight all passed.
- Prior full-audit rollup remains the strongest evidence for full replay collection and broader benchmark sweep.

## Weak / Capability Evidence

- Subprocess transport, memfd, and persistent mmap benchmark activation were not newly benchmarked in this pass.
- CodeAct LLM code generation was not newly benchmarked in this pass.

## Report Paths

- `/home/qcrs/statebus/runs/codex-fairness-gate-20260706/runtime/benchmark_reports/codex-fairness-gate-20260706-cold-start-compare.json`
- `/home/qcrs/statebus/runs/codex-fairness-gate-20260706/runtime/benchmark_reports/codex-fairness-gate-20260706-cold-start-compare-api.json`

