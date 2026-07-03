# StateBus v2 Role Contract

Date: 2026-07-03

Scope: `Planner -> Retriever -> Executor -> Summarizer` role boundaries for
StateBus v2 reports and demos.

This document fixes the role boundary used by the v2 benchmark reports. It does
not claim general-purpose autonomous role behavior outside the recorded runtime
and benchmark contracts.

## Contract

| Role | Responsibility | Primary outputs | Must not do |
| --- | --- | --- | --- |
| Planner | Compile task intent into workflow steps, retrieval objective, and required outputs. | planner handoff, workflow steps, retrieval objective | Execute tools, materialize final artifact, commit memory |
| Retriever | Select bounded evidence, route/tool candidates, semantic state, and retrieval logs. | evidence pack, hydrate manifest, retrieval log, query embedding | Change required outputs, write final answer, settle execution artifact |
| Executor | Execute validated tool or bounded CodeAct action and publish execution artifact. | execution artifact ref, artifact manifest, execution step record | Select hidden evidence outside retrieved set, commit memory summary |
| Summarizer | Synthesize answer, quality-floor result, replay ledger, and memory commit. | summary artifact, memory commit, replay ledger | Reroute tools, mutate execution artifact payload |

## Audit

The machine-readable contract lives in `v2/runtime/role_contract.py`.

Use this command on a benchmark family report:

```bash
python3 scripts/v2_diagnostics/role_contract_audit.py \
  --report /statebus/runs/v2-live/runtime/benchmark_reports/statebus-v2-benchmark-cold-start-statebus.json \
  --output-root /statebus/runs/v2-diagnostics
```

The audit checks:

- report or nested layer metadata has `role_graph=planner->retriever->executor->summarizer`;
- each role has a positive call count;
- each role has at least one role-specific output metric.

This is a role-boundary audit, not a proof that the system solves arbitrary
multi-agent tasks.
