# V2 Diagnostics

This folder contains a dedicated compare diagnostics entrypoint for the current `v2` dev benchmark lane.

Use it when you need a mounted artifact bundle that answers three questions together:

1. Is the current compare formally fair or only debug-grade?
2. Is the external text lane a reasonable debug baseline or an unfair formal comparator?
3. Is the current delta caused by prompt/LLM cost or by runtime non-LLM overhead?

## Commands

Analyze an existing compare report:

```bash
python3 scripts/v2_diagnostics/compare_diagnostics.py \
  --compare-suite-report /statebus/runs/v2-live/runtime/benchmark_reports/statebus-v2-benchmark-cold-start-compare.json \
  --output-root /statebus/runs/v2-diagnostics
```

Run a fresh deterministic cold-start dev compare and immediately build a diagnostics bundle:

```bash
python3 scripts/v2_diagnostics/compare_diagnostics.py \
  --family-dir v2/benchmark/samples/fixed_answer_family \
  --role-path-mode deterministic \
  --embedding-mode deterministic \
  --statebus-mode cold-start \
  --output-root /statebus/runs/v2-diagnostics
```

Run a fresh same-mainline deterministic carrier compare (`text_collaboration` vs `structured_collaboration`) and write a diagnostics bundle:

```bash
python3 scripts/v2_diagnostics/compare_diagnostics.py \
  --compare-kind carrier \
  --suite-id statebus-v2-diagnostics-carrier-compare \
  --family-dir v2/benchmark/samples/fixed_answer_family \
  --role-path-mode deterministic \
  --embedding-mode deterministic \
  --statebus-mode cold-start \
  --output-root /statebus/runs/v2-diagnostics
```

The bundle writes JSON, Markdown, and CSV outputs under:

```text
/statebus/runs/v2-diagnostics/<suite-id>-<timestamp>/
```

Key files:

- `summary.md`
- `summary.json`
- `fairness_diagnostics.json`
- `text_lane_diagnostics.json`
- `runtime_bottleneck_diagnostics.json`
- `case_matrix.csv`

## Runtime Persistence Breakdown

Run a fresh cold-start smoke lane and retain the runtime/workspace bundle plus sidecar size summaries:

```bash
python3 scripts/v2_diagnostics/runtime_persistence_breakdown.py \
  --output-root /statebus/runs/v2-diagnostics
```

Key files:

- `summary.md`
- `summary.json`
- `file_sizes.csv`
- `sidecar_sizes.csv`
- `manifest_sizes.csv`
