# MRR-05B Implementation Record

Date: 2026-09-05

## Branch

`feat/mrr-05b-response-correlation-admission`

The untracked Ready Pack at
`docs/mrr/packages/StateBus-MRR-Batch1-Codex-Ready-Pack.zip` was preserved.

## Goal

Prevent decoded subprocess control messages from reaching provider business
logic until the complete response sequence matches the exact physical request
scope, event contract, terminal cardinality, and current semantic-select result
contract.

## Architecture invariant

`PASS`: `RawControlMessage -> ControlResponseAdmission -> business
consumption`. A rejected sequence exposes no candidate messages through
`SubprocessExecutorTransport.exchange_sequence()` or `execute()`.

The admission receipt is audit evidence only. It does not select a provider,
issue a grant, create an Attempt, or replace Runtime authority.

## Files read

- `README.md`
- `docker/README.md`
- `deploy/activate_statebus_host.sh`
- `deploy/activate_statebus_local_vllm_profile.sh`
- `scripts/vllm/start_qwen3_32b.sh`
- `/home/qcrs/statebus/project/docs/reference/题目.md`
- `docs/mrr/batch2/StateBus-MRR-Batch2-Readiness-Review.md`
- `docs/mrr/batch2/StateBus-MRR-Batch2-Implementation-Plan.md`
- `docs/mrr/batch2/MRR-05B-Physical-Response-Correlation-Admission-Slice-Spec.md`
- `statebus/control/messages.py`
- `statebus/control/transport.py`
- `statebus/control/subprocess_worker.py`
- `statebus/control/__init__.py`
- `statebus/runtime/adaptive_dispatcher.py`
- Relevant subprocess, control-plane, invocation-wire, and adaptive integration tests.

## Files changed

Production:

- Added `statebus/control/admission.py`.
- Modified `statebus/control/__init__.py` for admission exports.
- Modified `statebus/control/transport.py` to admit a complete response sequence
  before returning it.
- Modified `statebus/runtime/adaptive_dispatcher.py` to retain admission receipts
  and require one admitted terminal before semantic selection consumption.

Tests:

- Added `tests/test_control_response_admission.py`.
- Extended `tests/test_subprocess_executor.py`.
- Extended the existing semantic subprocess test in
  `tests/test_adaptive_mainline_integration.py`.

Evidence and documentation:

- Added `artifacts/mrr-05b/`.
- Added this implementation record.

The staged MRR-05A production, test, evidence, and record files remain present
and were not reverted or restaged by this Slice.

## Contracts changed

`ControlResponseAdmissionReceipt` is an immutable audit contract containing the
invocation, Attempt, binding, grant, event, decision, reason, terminal flag,
origin, expected/observed scope, terminal count, and output-contract decision.

The validator checks exact trace/task/run/session/step/attempt/invocation/role/
timeout/binding/grant/schema equality, message-class/event agreement, lifecycle
order, at most one terminal, and success output-contract equality. For
`semantic_select_v1`, it also requires exactly one `semantic_state` input and
response ref, exact returned/consumed ref identity, equal selected-ID/score/row
cardinality, and a result count no greater than `semantic_top_k`.

Canonical scope is fail-closed: once any Batch 2 authority field is supplied,
all run/session/invocation/binding/grant fields are required. Requests with all
five fields empty retain the existing legacy compatibility startup. UTF-8
responses are explicitly `ADAPTER_DERIVED`; complete protobuf scope is
`NATIVE_TYPED_WORKER`; legacy protobuf is `LEGACY_COMPATIBILITY`.

The transport now reads until connection close or timeout so a second terminal
cannot hide behind the first. The existing locally synthesized timeout-shaped
`ErrorResult` remains intentionally unchanged for MRR-06B.

No State, Memory, Artifact, workspace, replay, routing, provider-binding,
scheduler, active-Attempt, or lifecycle-authority changes were made.

## Tests executed

All tests used this checkout's Conda activation:

```text
source ./deploy/activate_statebus_host.sh
```

Final focused set:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m pytest -q \
  --basetemp=/tmp/mrr-05b-final \
  tests/test_control_response_admission.py \
  tests/test_subprocess_executor.py \
  tests/test_invocation_wire_projection.py \
  tests/test_adaptive_mainline_integration.py::test_adaptive_product_retrieval_owns_cross_process_semantic_state \
  tests/test_control_plane.py
```

Result: `15 passed in 11.70s` on the final rerun after the empty-sequence
admission boundary fix.

This combines the Slice tests, MRR-05A request/wire compatibility, canonical
semantic-select integration, and one directly adjacent control-plane/memfd
regression suite.

The real UDS tests were run outside the restricted command sandbox because the
sandbox rejected Unix-domain socket bind with `Operation not permitted`. No
Docker, vLLM, benchmark, full pytest, coverage, or broad lint run was used.

## Source Gate

`SOURCE_GATE_PASS`

Before this Slice, `exchange_sequence()` returned decoded typed messages and
`execute()` returned the first success/error. The adaptive dispatcher then read
semantic selection fields directly. There was no exact 05A scope admission,
output-contract admission, or duplicate-terminal guard between decode and
business consumption.

## Mechanism Gate

`MECHANISM_GATE_PASS`

`artifacts/mrr-05b/valid_response_admission.json` records a distinct driver and
worker PID, real UDS/protobuf subprocess exchange, four admitted worker
messages, exact request/observed scope equality, one terminal, and a matched
output contract. Negative tests call the same validator used by transport.

## Integration Gate

`INTEGRATION_GATE_PASS`

The canonical adaptive semantic-state path completed after its real worker
sequence traversed admission. Dispatcher context retained the same receipts,
and selection was consumed only after exactly one admitted terminal was
observed. Legacy protobuf and UTF-8 subprocess startup also remained valid.

## Competition Gate

`COMPETITION_GATE_UNVALIDATED`

This Slice does not validate competition E2E, performance, latency, token,
stability, or score claims.

## Regressions

No unresolved regression remains. The first invocation-wire compatibility
rerun found that incomplete canonical requests could no longer expose the
worker's exact `invalid_exec_request` response. Admission was narrowed so only
that exact request-rejection terminal may cross the request-side completeness
check; ACK/RUN/Heartbeat/Success and unrelated errors remain rejected. The
final predecessor regression and aggregate focused set passed.

The first sandboxed targeted invocation also failed because its five UDS tests
could not bind Unix sockets; the same command passed outside the sandbox. No
unrelated baseline failure was encountered.

## Evidence

- `artifacts/mrr-05b/valid_response_admission.json`
- `artifacts/mrr-05b/response_mismatch_rejection.txt`
- `artifacts/mrr-05b/duplicate_terminal_rejection.txt`
- `artifacts/mrr-05b/targeted_tests.txt`

## Open questions

Transport timeout origin, semantic active-Attempt ownership, lifecycle-origin
truth, and late-result fencing remain intentionally deferred to MRR-06A and
MRR-06B. This Slice does not claim those behaviors.

## Next allowed slice

`NEXT_ALLOWED_SLICE = MRR-06A`

MRR-06A was not started.
