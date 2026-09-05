# MRR-03A Implementation Record

Date: 2026-09-04

## Goal

Allow policy-valid `STRICT_FIXED` and `ADAPTIVE_BOUNDED` plans to execute
through the same `AdaptiveRuntimeEngine` without invoking the legacy strict
`RuntimeDriver.run()` path.

## Files changed

- `statebus/runtime/adaptive_runtime.py`
- `tests/test_canonical_runtime_modes.py`
- `artifacts/mrr-03a/strict_same_engine_session.json`
- `artifacts/mrr-03a/no_legacy_driver_call.txt`
- `artifacts/mrr-03a/targeted_tests.txt`
- `docs/mrr/implementation/MRR-03A-IMPLEMENTATION-RECORD.md`

## What changed

`AdaptiveRuntimeEngine.run()` now explicitly accepts the existing
`STRICT_FIXED`, `ADAPTIVE_SHADOW`, and `ADAPTIVE_BOUNDED` modes and rejects any
unsupported value. The prior unconditional `STRICT_FIXED` rejection was
removed. No second engine, mode registry, request contract, or execution path
was added.

The canonical strict test uses the existing ApprovedPlan projection,
`RuntimeWorkflowStep`, Runtime-created attempt IDs, `StepAttemptRecord`,
`CapabilityGrant`, and deterministic `execute_step` callback. The legacy
`RuntimeDriver.run()` entrypoint remains unchanged as a compatibility path.

## Tests run

All tests used:

```text
source /home/qcrs/statebus/project/deploy/activate_statebus_host.sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/qcrs/statebus/os python -m pytest -q \
  tests/test_canonical_runtime_modes.py \
  tests/test_adaptive_driver.py::test_driver_executes_approved_nonfixed_dag_with_one_grant_per_step \
  tests/test_adaptive_driver.py::test_shadow_plan_never_dispatches_role_work
```

## Test results

`5 passed in 0.81s`.

The targeted coverage proves:

- `STRICT_FIXED` completes the deterministic three-step ApprovedPlan.
- Runtime creates and binds all workflow steps, attempts, and grants.
- `RuntimeDriver.run()` is not called by canonical strict execution.
- The same ApprovedPlan executes through the same workflow projection in
  `STRICT_FIXED` and `ADAPTIVE_BOUNDED`.
- `ADAPTIVE_SHADOW` retains its no-dispatch behavior.
- Unsupported workflow mode values are rejected before dispatch.

## Source Gate

`SOURCE_GATE_PASS`

The unconditional strict rejection is gone, no second engine was added, and
the directly related adaptive and shadow tests pass.

## Mechanism Gate

`MECHANISM_GATE_PASS`

The deterministic callback ran once per strict plan step under a
Runtime-created CapabilityGrant linked to its Runtime-created attempt.

## Integration Gate

`INTEGRATION_GATE_PASS`

`STRICT_FIXED` completed all three ApprovedPlan steps through
`AdaptiveRuntimeEngine`; the legacy strict driver was not invoked.

## Competition Gate

`COMPETITION_GATE_UNVALIDATED`

No Docker, vLLM, benchmark, cross-process, or competition end-to-end run was
performed.

## Known limitation

The legacy `RuntimeDriver.run(RuntimeDriverInput)` product path remains in
place. Connecting the full Fixed product assembly to the canonical engine is
deferred to MRR-03B. Existing adaptive-prefixed type and attempt names are
unchanged.

## Next allowed slice

`NEXT_ALLOWED_SLICE = MRR-03B`
