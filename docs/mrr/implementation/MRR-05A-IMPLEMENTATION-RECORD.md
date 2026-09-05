# MRR-05A Implementation Record

Date: 2026-09-05

## Source identity

Branch: `feat/mrr-05a-invocation-wire-projection`

Source SHA: `d9b181b069f6cc72fa5bfe210c74eb6523d8cee9`

The current checkout and Slice branch were used directly. No reset, rebase,
merge, push, or history-based source analysis was performed.

## Goal

Project the already-authorized Runtime, Attempt, execution-binding, and grant
scope onto every physical control invocation while preserving the existing
`task_id` wire name as the `RuntimeIdentity.runtime_task_id` compatibility
projection.

## Architecture invariant

`PASS`: for each physical invocation, the worker response scope equals the
request scope. The implementation adds no provider or capability decision to
the control path and does not introduce a second authority graph.

## Files read

- `docs/mrr/batch2/StateBus-MRR-Batch2-Readiness-Review.md`
- `docs/mrr/batch2/StateBus-MRR-Batch2-Protocol-Attempt-Truth-Deep-Design.md`
- `docs/mrr/batch2/StateBus-MRR-Batch2-Implementation-Plan.md`
- `docs/mrr/batch2/MRR-05A-Invocation-Identity-Wire-Projection-Slice-Spec.md`
- `statebus/contracts/identity.py`
- `statebus/contracts/provider_binding.py`
- `statebus/contracts/adaptive.py`
- `statebus/control/messages.py`
- `statebus/control/statebus_control.proto`
- `statebus/control/schema.py`
- `statebus/control/transport.py`
- `statebus/control/subprocess_worker.py`
- `statebus/runtime/adaptive_runtime.py`
- `statebus/runtime/adaptive_dispatcher.py`
- Relevant existing adaptive, subprocess, and provider-binding tests.

## Files changed

Production:

- Modified `statebus/control/messages.py`.
- Modified `statebus/control/statebus_control.proto`.
- Modified `statebus/control/schema.py`.
- Modified `statebus/control/subprocess_worker.py`.
- Modified `statebus/runtime/adaptive_dispatcher.py`.
- Modified `statebus/runtime/adaptive_runtime.py`.

Tests:

- Added `tests/test_invocation_wire_projection.py`.
- Extended `tests/test_adaptive_mainline_integration.py`.
- Extended `tests/test_adaptive_dispatcher.py`.
- Extended `tests/test_adaptive_codeact_integration.py`.
- Extended `tests/test_provider_binding_reconciliation.py`.

Evidence and documentation:

- Added the files under `artifacts/mrr-05a/`.
- Added this implementation record.

The unrelated untracked Ready Pack at
`docs/mrr/packages/StateBus-MRR-Batch1-Codex-Ready-Pack.zip` was preserved.

## Contracts changed

`ControlHeader` now carries additive `run_id`, `session_id`, `invocation_id`,
`execution_binding_hash`, and `capability_grant_hash` fields. Protobuf field
numbers 9 through 13 and the dynamic descriptor are kept in parity. The
existing `task_id` field remains the legacy wire projection of
`RuntimeIdentity.runtime_task_id`; no second `runtime_task_id` field was added.

`ExecRequest.capability_grant_hash` remains during the compatibility window and
is required to equal the header grant hash. The canonical sender explicitly
uses `statebus.control.v1`; the worker rejects a missing or unsupported schema
version and rejects missing canonical scope rather than fabricating identity.

The dispatcher creates one physical `invocation_id` per exchange and projects
the already-authorized RuntimeIdentity, Attempt, binding receipt, and grant.
The worker validates the required scope and echoes the immutable header on all
typed messages.

No State, Memory, Artifact, workspace-layout, provider-selection, scheduler,
or authority migration was made.

## Tests executed

```text
source /home/qcrs/statebus/project/deploy/activate_statebus_host.sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/qcrs/statebus/os python -m pytest -q \
  --basetemp=/tmp/mrr-05a-targeted \
  tests/test_invocation_wire_projection.py \
  tests/test_adaptive_mainline_integration.py::test_adaptive_product_retrieval_owns_cross_process_semantic_state \
  tests/test_subprocess_executor.py::test_subprocess_executor_valid_round_trip
```

## Test results

`4 passed in 8.55s`.

Coverage includes protobuf/dynamic-schema parity and header round-trip,
missing/unsupported schema and required-scope rejection, duplicate grant-hash
validation, a real UDS to protobuf to `subprocess_worker` exchange, exact scope
echo across `ACK_RECV`, `RUN_START`, `HEARTBEAT`, and terminal success, and
canonical adaptive semantic-state completion. The real mechanism test ran
outside the restricted sandbox after the sandbox itself rejected Unix-domain
socket creation with `Operation not permitted`.

## Source Gate

`SOURCE_GATE_PASS`

Direct source inspection confirmed the pre-Slice gap: the control header had
only trace/task/step/attempt/role/timeout/schema/event fields, the integrated
dispatcher used a synthetic `adaptive:<task_id>` trace, and run/session,
binding, and physical invocation identity were absent from the wire. The
implementation fills that exact projection gap with additive fields and keeps
authority in the existing Runtime/Attempt/Binding/Grant chain.

## Mechanism Gate

`MECHANISM_GATE_PASS`

The real UDS/subprocess evidence shows a distinct driver and worker process,
typed protobuf transport, and four typed worker messages. Every returned
message carries the exact request scope recorded in
`artifacts/mrr-05a/real_subprocess_scope.txt`.

## Integration Gate

`INTEGRATION_GATE_PASS`

The canonical adaptive semantic-state integration completed successfully while
observing the new physical request and all typed responses. The request uses
the real Runtime trace/run/session values, the projected binding hash, the
grant hash, and one generated physical invocation ID.

## Competition Gate

`COMPETITION_GATE_UNVALIDATED`

This Slice does not validate competition E2E, latency, token, stability, or
score claims.

## Regressions

No regression was observed in the targeted canonical integration or existing
subprocess round-trip. No full pytest suite, Docker, vLLM, benchmark, or
competition run was executed. No unrelated baseline failure was encountered in
the executed tests.

## Evidence

- `artifacts/mrr-05a/wire_roundtrip.json`
- `artifacts/mrr-05a/real_subprocess_scope.txt`
- `artifacts/mrr-05a/targeted_tests.txt`

## Open questions

Physical response admission, correlation policy, and late-result handling are
intentionally deferred to MRR-05B and later Batch 2 slices. This record does
not claim those behaviors are implemented.

## Next allowed slice

`NEXT_ALLOWED_SLICE = MRR-05B`

MRR-05B was not started.
