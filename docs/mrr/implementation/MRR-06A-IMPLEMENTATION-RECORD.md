# MRR-06A Implementation Record

Date: 2026-09-05

## Branch

`feat/mrr-06a-attempt-lifecycle-origin-truth`

The untracked Ready Pack at
`docs/mrr/packages/StateBus-MRR-Batch1-Codex-Ready-Pack.zip` was preserved.
No commit, push, reset, clean, rebase, merge, or history-based source
analysis was performed.

## Goal

Give semantic active-Attempt authority to `RuntimeTaskSession`, make
`RuntimeSupervisor` retain independent `(session_id, step_id, attempt_id)`
records, and distinguish local, adapter-derived, and real worker lifecycle
observations.

## Architecture invariant

`PASS`: Session owns the semantic active Attempt pointer; Supervisor tracks
operational state for a concrete Attempt; local Runtime transitions are not
reported as worker ACKs; provider-internal worker observations remain audit
data and do not mutate the outer semantic Step.

## Files read

- `docs/mrr/batch2/MRR-06A-Attempt-Authority-Lifecycle-Origin-Truth-Slice-Spec.md`
- `statebus/runtime/session.py`
- `statebus/runtime/supervisor.py`
- `statebus/runtime/adaptive_runtime.py`
- `statebus/runtime/adaptive_dispatcher.py`
- `statebus/runtime/driver.py`
- `statebus/control/transport.py`
- `statebus/control/subprocess_worker.py`
- `tests/test_adaptive_driver.py`
- `tests/test_adaptive_mainline_integration.py`
- `tests/test_runtime_session_and_ledger.py`
- `tests/test_runtime_and_benchmark.py`
- `tests/test_subprocess_executor.py`
- `tests/test_invocation_wire_projection.py`

MRR-05A and MRR-05B control-scope/admission behavior was treated as
downstream context and kept unchanged.

## Files changed

Production:

- Modified `statebus/runtime/session.py`.
- Modified `statebus/runtime/supervisor.py`.
- Modified `statebus/runtime/adaptive_runtime.py`.
- Modified `statebus/runtime/adaptive_dispatcher.py`.
- Modified `statebus/runtime/driver.py`.
- Modified `statebus/runtime/__init__.py` to export `LifecycleOrigin`.

Tests:

- Added `tests/test_mrr_06a_attempt_lifecycle.py`.
- Extended `tests/test_adaptive_mainline_integration.py` with physical worker
  origin and outer semantic-step assertions.

Evidence and documentation:

- Added `artifacts/mrr-06a/` evidence files.
- Added this implementation record.

## Contracts changed

`RuntimeTaskSession` now retains `active_attempt_by_step` and exposes explicit
activation, lookup, and settlement operations. Historical `StepAttemptRecord`
entries remain append-only. Settling Attempt A cannot clear active Attempt B,
and non-active Attempts cannot perform commit-authoritative workflow mutation.

`RuntimeSupervisor` stores records under `(session_id, step_id, attempt_id)`.
The historical `steps[step_id]` view remains a latest-record compatibility
projection. Lifecycle transitions carry `LifecycleOrigin` values:
`LOCAL_RUNTIME`, `WORKER_OBSERVED`, or `ADAPTER_DERIVED`. Local ACK and local
heartbeat observations are rejected.

Adaptive local execution now records `DISPATCHED` and `RUNNING` as
`LOCAL_RUNTIME` without synthesizing `ACKED`. A grant that expires before
dispatch is recorded as a failed, settled Attempt so it cannot leave an active
pointer behind. The real strict driver records typed protobuf ACK, RUN_START,
HEARTBEAT, and terminal events as `WORKER_OBSERVED`.

The semantic-select subprocess remains provider-internal. Its admitted
physical lifecycle receipts are retained in
`AdaptiveDispatchContext.physical_lifecycle_observations`; they do not mutate
the outer semantic retrieval Step. UTF-8 text responses remain
`ADAPTER_DERIVED` through the existing transport contract.

No State, Memory, Artifact, workspace layout, replay identity, routing,
scheduler, provider-selection, persistent-worker, or late-result-fencing
mechanism was introduced.

## Tests executed

All tests used this checkout's host Conda activation:

```text
source ./deploy/activate_statebus_host.sh
```

Focused MRR-06A set:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:tests python -m pytest -q \
  --basetemp=/tmp/mrr-06a-targeted \
  tests/test_mrr_06a_attempt_lifecycle.py \
  tests/test_adaptive_driver.py \
  tests/test_runtime_session_and_ledger.py \
  tests/test_runtime_and_benchmark.py::test_runtime_supervisor_enforces_lifecycle_transitions \
  tests/test_runtime_and_benchmark.py::test_runtime_supervisor_traps_ack_timeout_and_lease_expiry \
  tests/test_subprocess_executor.py \
  tests/test_invocation_wire_projection.py \
  tests/test_adaptive_mainline_integration.py::test_adaptive_product_retrieval_owns_cross_process_semantic_state
```

## Test results

`22 passed in 10.14s`.

Coverage includes active Attempt A/B ownership and settlement, independent
Supervisor records, illegal local ACK and invalid transitions, local provider
no-ACK lifecycle, expired-grant settlement, legacy adaptive startup, typed
protobuf worker-origin observations, UTF-8 adapter-derived observations,
invocation-scope regressions, and the canonical semantic subprocess path.

The semantic subprocess test first failed inside the restricted command
sandbox because Unix-domain socket `bind` returned `Operation not permitted`.
The same test passed in the approved local Conda environment outside that
restriction. No container, vLLM, benchmark, full pytest, or competition run
was performed.

## Source Gate

`SOURCE_GATE_PASS`

The pre-Slice source facts in the Slice Spec were reproduced: the semantic
adaptive path had synthetic ACK/RUNNING transitions before provider dispatch,
and Supervisor state was step-keyed. The updated code removes those fake
worker transitions and adds explicit Attempt scope without renaming the
legacy `task_id` projection.

## Mechanism Gate

`MECHANISM_GATE_PASS`

The local path has no ACK state and records `RUNNING` as `LOCAL_RUNTIME`. The
real typed protobuf path produced and admitted `ACK_RECV`, `RUN_START`,
`HEARTBEAT`, and terminal success with `NATIVE_TYPED_WORKER`, mapped to
`WORKER_OBSERVED`. Existing UTF-8 transport coverage records
`ADAPTER_DERIVED`.

## Integration Gate

`INTEGRATION_GATE_PASS`

The canonical adaptive semantic-state mainline completed through the real
subprocess path. Physical worker receipts were retained for audit, while the
outer semantic retrieval Step remained `LOCAL_RUNTIME` with no worker ACK
claim. Legacy requests without an explicit `RuntimeIdentity` continued to
start through the compatibility projection.

## Competition Gate

`COMPETITION_GATE_UNVALIDATED`

This Slice does not validate competition E2E, performance, latency, token,
stability, or score claims.

## Regressions

No unresolved regression remains in the executed targeted set. The only
environment issue was the restricted-sandbox UDS bind denial described above;
the approved local rerun passed. Existing compatibility callers that use
`RuntimeSupervisor.steps` and legacy adaptive identity inputs remained valid.

## Evidence

- `artifacts/mrr-06a/active_attempt_authority.json`
- `artifacts/mrr-06a/worker_lifecycle_origin.txt`
- `artifacts/mrr-06a/local_provider_lifecycle.txt`
- `artifacts/mrr-06a/targeted_tests.txt`

## Open questions

Late-result fencing, timeout/cancel settlement policy, retry scheduling,
rebind policy, and persistent worker lifecycle remain intentionally deferred
to MRR-06B and later slices.

## Next allowed slice

`NEXT_ALLOWED_SLICE = MRR-06B`

MRR-06B was not started.
