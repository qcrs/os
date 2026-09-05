# MRR-03B Implementation Record

Date: 2026-09-05

## Goal

Connect the MRR-02 Static Role Recipe and `ApprovedPlanBundle` to the
generalized canonical Mainline and the existing `AdaptiveRuntimeEngine` with
three deterministic compatibility handlers. This validates canonical Fixed
control-flow integration only, not Fixed feature parity.

## Files changed

Production:

- Added `statebus/runtime/fixed_mainline.py`.
- Modified `statebus/runtime/adaptive_mainline.py`.
- Modified `statebus/runtime/driver.py`.

Tests and evidence:

- Added `tests/test_fixed_canonical_mainline.py`.
- Added the four required files under `artifacts/mrr-03b/`.
- Added this implementation record.

The pre-existing deployment, README, Batch-1 spec, package, and audit changes
were preserved. `smoke.py`, `role_path.py`, `adaptive_dispatcher.py`, State,
Memory, retrieval, provider binding, and benchmark sources were not modified.

## What changed

`FixedMainlineRequest` now assembles a `STRICT_FIXED` envelope, a minimal
`RUNTIME_BUILTIN` compatibility registry, an MRR-02 `ApprovedPlanBundle`, and
bindings for deterministic retrieve, execute, and summarize handlers. It then
hands the request to `AdaptiveMainlineRunner`; it does not execute a DAG or
create Attempts or Grants.

`AdaptiveMainlineRunner` admits the existing canonical workflow modes and can
consume a hash-linked, task/contract/registry-scoped `ApprovedPlanBundle`
without invoking a planner callback. `RuntimeDriver.run_mode()` accepts an
opt-in `fixed_request` while retaining the legacy `strict_input` and `run()`
path unchanged.

Memory commit is explicitly disabled for the Fixed compatibility bridge.

## Tests run

All tests used the requested host environment:

```text
source /home/qcrs/statebus/project/deploy/activate_statebus_host.sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/qcrs/statebus/os python -m pytest -q \
  tests/test_fixed_canonical_mainline.py \
  tests/test_adaptive_mainline_integration.py::test_product_adaptive_mainline_owns_runtime_infrastructure_and_role_records
```

## Results

`6 passed in 0.98s`: five MRR-03B tests and one adjacent
`ADAPTIVE_BOUNDED` Mainline regression.

The tests cover strict envelope assembly, Static Role Recipe and bundle
provenance, three Runtime-granted handler executions, completed Runtime session
state, and rejection of wrong grant hash, wrong Attempt ID, and wrong output
Ref kind. Fail-if-called patches prove that the canonical Fixed path does not
invoke `RolePathRunner`, `run_smoke()`, `build_default_workflow()`, or legacy
`RuntimeDriver.run(RuntimeDriverInput)`.

## Source Gate

`SOURCE_GATE_PASS`

`FixedMainlineRequest` exists, `AdaptiveMainlineRunner` accepts the strict
canonical path, no second execution engine was added, and legacy smoke source
is untouched.

## Mechanism Gate

`MECHANISM_GATE_PASS`

The retrieve, execute, and summarize compatibility handlers each executed
once under a Runtime-created `CapabilityGrant`. The session contains three
Runtime-created `StepAttemptRecord` objects and their three grant hashes.

## Integration Gate

`INTEGRATION_GATE_PASS`

The fixed recipe produced an MRR-02 `ApprovedPlanBundle`, entered the canonical
Mainline, completed through the existing `AdaptiveRuntimeEngine`, and produced
a completed three-step Runtime result without a legacy orchestration call.

## Competition Gate

`COMPETITION_GATE_UNVALIDATED`

No Docker container, vLLM service, benchmark, live model, or competition E2E
run was started.

## Known limitations

The three handlers are deterministic typed-result bridges only. They do not
provide real retrieval, LLM execution, semantic State, Memory/replay, CodeAct,
artifact verification, provider selection, or Fixed feature parity. Physical
provider eligibility and binding remain deferred to MRR-04.

## Next allowed slice

`NEXT_ALLOWED_SLICE = MRR-04`

MRR-04 was not started.
