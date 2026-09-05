# MRR-06B Implementation Record

## Goal

Enforce the Batch 2 freshness invariant: once Attempt A is terminal or
superseded and Attempt B is active for the same Step, a physically valid late
result from A is correlated and audited but cannot mutate semantic workflow
state or outputs.

## Files changed

Production:

- `statebus/runtime/session.py`
- `statebus/runtime/adaptive_runtime.py`
- `statebus/control/transport.py`

Tests:

- `tests/test_mrr_06b_late_result_fencing.py`
- `tests/fixtures/mrr_06b_delayed_worker.py`

Evidence and documentation:

- `artifacts/mrr-06b/late_result_fencing_trace.txt`
- `artifacts/mrr-06b/timeout_settlement.json`
- `artifacts/mrr-06b/targeted_tests.txt`
- `docs/mrr/implementation/MRR-06B-IMPLEMENTATION-RECORD.md`

## Timeout truth change

`SubprocessExecutorTransport` no longer synthesizes worker-shaped
`ErrorResult(subprocess_timeout)`. A local deadline raises
`SubprocessTransportTimeout` with origin `LOCAL_TRANSPORT`, retains the
physical process/receive context, and exposes the eventual response only
through the existing 05B response admission path.

The execution deadline starts after the worker has connected and received its
`ExecRequest`; process startup uses a separate bounded connection window.

## Settlement rule

Adaptive Runtime translates the local transport timeout into a Runtime-owned
`TRAPPED` transition, updates Attempt A history, updates the active workflow
Step, and settles A before invoking best-effort process termination. Physical
termination success is not required to protect semantic state.

Settling an old A only clears the active pointer when A is still active. It
cannot clear B after B activation. The cancellation support case verifies the
same ordering and ownership rule for a cancelled A.

## Late-result fence rule

`RuntimeSessionManager.admit_attempt_result()` produces an immutable Runtime
receipt containing Step, observed Attempt, active Attempt, invocation,
decision, and reason. Only `ACTIVE_ATTEMPT_COMMIT_ALLOWED` authorizes the
Adaptive Runtime result path. Any known or unknown non-active Attempt receives
`FENCED_STALE_ATTEMPT` before adaptive audit hashes, data-plane events,
workflow completion, or output refs can be mutated.

Repeated late A observations create repeated fence audit receipts but perform
no semantic mutation. B remains active and can commit through its own positive
receipt.

## Tests actually run

All commands used:

```text
source /home/qcrs/statebus/project/deploy/activate_statebus_host.sh
PYTHONDONTWRITEBYTECODE=1
PYTHONPATH=/home/qcrs/statebus/os
```

Focused Slice tests:

```text
python -m pytest -q tests/test_mrr_06b_late_result_fencing.py
```

Single adjacent regression:

```text
python -m pytest -q tests/test_adaptive_mainline_integration.py::test_adaptive_product_retrieval_owns_cross_process_semantic_state
```

No container, vLLM, benchmark, full pytest, or competition run was performed.

## Results

Focused Slice tests: `2 passed in 1.89s`.

Adjacent canonical mainline regression: `1 passed in 1.86s`.

Final same-scope aggregate rerun: `3 passed in 3.09s`.

The primary test traversed real UDS, typed protobuf, a delayed subprocess
worker, 05B response admission, and Runtime active-Attempt admission after B
activation. The late A success was fenced; B alone committed `output-b`.

The restricted command sandbox initially denied UDS `bind` with `Operation not
permitted`. The identical tests passed in the approved local Conda context.

## Source Gate

`SOURCE_GATE_PASS`

Pre-Slice source had no Runtime result-admission receipt, checked active
Attempt only after adaptive audit/data-plane handling, and represented a local
subprocess deadline as synthetic worker `ErrorResult(subprocess_timeout)`.

## Mechanism Gate

`MECHANISM_GATE_PASS`

Attempt A crossed the physical UDS/protobuf path, timed out locally, remained
alive after best-effort termination, and delivered `SuccessResult(A)` after B
activation. 05B admitted the exact A invocation as `NATIVE_TYPED_WORKER`; the
Runtime receipt then recorded `FENCED_STALE_ATTEMPT` and no A output committed.

## Integration Gate

`INTEGRATION_GATE_PASS`

The single adjacent adaptive product mainline completed normally through its
real semantic subprocess path and left no active Attempt pointer. The Slice
test also proved that an active B can commit and settle after fencing A.

## Competition Gate

`COMPETITION_GATE_UNVALIDATED`

This Slice does not validate competition E2E, performance, latency, token,
stability, or score claims.

## Known limitation

This Slice intentionally does not add a persistent worker, generic retry
engine, distributed lease, scheduler, or State/Artifact lifecycle changes.
The delayed-response wait is a narrow transport completion seam; production
policy still attempts physical termination after semantic settlement.

## Batch 2 Gate readiness

`BATCH_2_GATE_READINESS = READY`

MRR-05A/05B physical correlation, MRR-06A active-Attempt ownership, and
MRR-06B late-result fencing now have focused passing evidence. Competition
validation remains explicitly separate.

## NEXT_ALLOWED_SLICE

`NEXT_ALLOWED_SLICE = BATCH_2_GATE_REVIEW`

MRR-07 was not started.
