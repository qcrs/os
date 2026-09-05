# MRR-04 Implementation Record

Date: 2026-09-05

## Goal

Separate logical capability authority from physical execution-provider binding
while preserving the existing capability registry and handlers through an
additive compatibility bridge.

## Files changed

Production:

- Added `statebus/contracts/provider_binding.py`.
- Added `statebus/runtime/provider_registry.py`.
- Modified `statebus/contracts/__init__.py`.
- Modified `statebus/runtime/capability_registry.py`.
- Modified `statebus/runtime/adaptive_runtime.py`.
- Modified `statebus/runtime/adaptive_dispatcher.py`.

Tests and evidence:

- Added `tests/test_provider_binding_reconciliation.py`.
- Adapted direct-dispatch fixtures in `tests/test_adaptive_dispatcher.py` and
  `tests/test_adaptive_codeact_integration.py` to supply a bound grant.
- Added the five required files under `artifacts/mrr-04/`.
- Added this implementation record.

Pre-existing README, deployment, vLLM, Batch-1 specification, package, audit,
and workspace-instruction changes were preserved and not modified by MRR-04.

## What changed

`LogicalCapabilityDescriptor` contains the semantic capability surface and no
provider identity or `ExecutionKind`. `ExecutionProviderDescriptor` contains
the physical implementation surface. `CapabilityRegistry` now exposes a
provider-neutral logical projection while retaining its existing API and
legacy digest.

`ExecutionProviderRegistry` projects current descriptors to stable legacy
providers. Runtime eligibility uses only hard compatibility, risk, runtime,
readiness, health, and prerequisite facts. Eligible providers are selected by
stable provider ID order and recorded in an immutable
`ExecutionBindingReceipt`.

For every canonical Runtime Attempt, eligibility and binding now occur before
grant issuance. `BoundCapabilityGrant` links the unchanged v1
`CapabilityGrant` hash to the binding and eligibility identities. The
Dispatcher derives its handler key from the bound implementation, verifies it
against the compatibility descriptor, and rejects an unbound or mismatched
grant before invoking any handler.

## Compatibility bridge

Existing `CapabilityDescriptor`, `CapabilityRegistry`, `ExecutionKind`, domain
pack registrations, `CapabilityGrant`, and handler signatures remain intact.
Runtime creates logical and provider projections from the current descriptors;
the Dispatcher consumes the bound wrapper and passes the existing plain Grant
to the already registered handler. No DomainPack, State, Memory, Ref, routing,
scheduler, protocol, worker, or LLM provider source was changed.

## Tests run

All tests used the requested host environment:

```text
source /home/qcrs/statebus/project/deploy/activate_statebus_host.sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/qcrs/statebus/os python -m pytest -q \
  tests/test_provider_binding_reconciliation.py \
  tests/test_fixed_canonical_mainline.py::test_fixed_mainline_completes_through_runtime_grants_without_legacy_paths \
  tests/test_adaptive_driver.py::test_driver_executes_approved_nonfixed_dag_with_one_grant_per_step
```

## Results

`8 passed in 0.97s`: six MRR-04 tests, one canonical Fixed regression,
and one existing adaptive execution regression.

Coverage includes logical/provider isolation, deterministic legacy projection,
hard eligibility rejection, stable binding, provider-neutral ApprovedPlan
identity, binding-before-Grant order, fail-closed no-provider behavior,
Dispatcher rejection before handler invocation, and completed canonical Fixed
execution with exactly one projection, binding, and bound Grant per Attempt.

The direct Dispatcher and CodeAct suites were not run, as required by the
Slice test boundary; their direct-call fixtures were updated for the new bound
grant API. No Docker, vLLM, benchmark, full suite, State/Memory, replay,
performance, or competition test was run.

## Source Gate

`SOURCE_GATE_PASS`

Logical and physical contracts import independently, current descriptors
project without a DomainPack rewrite, the new logical planning projection has
no provider identity or execution kind, eligibility and binding are distinct,
and the ApprovedPlan remains provider-neutral.

## Mechanism Gate

`MECHANISM_GATE_PASS`

The canonical Fixed compatibility providers were admitted, bound, granted,
verified by the Dispatcher, and their existing handlers actually executed.
The result is not represented as a real IPC or persistent-worker mechanism.

## Integration Gate

`INTEGRATION_GATE_PASS`

The MRR-03B canonical Fixed task completed three Runtime Attempts. Each has
one `ProviderEligibilityProjection`, one `ExecutionBindingReceipt`, and one
`BoundCapabilityGrant`, with binding identity recorded before dispatch.

## Competition Gate

`COMPETITION_GATE_UNVALIDATED`

## Known limitation

Provider runtime facts are caller-supplied hard facts; compatibility providers
default to ready and healthy. Selection is stable provider-ID ordering only.
There is no live health collector, routing optimization, scheduler, rebind
lifecycle, protocol binding, worker lifecycle, or competition validation in
this Slice.

## Next allowed slice

`NEXT_ALLOWED_SLICE = MRR-05`

MRR-05 was not started.
