# MRR-05A Slice Spec — Invocation Identity / Wire Projection

## Goal

Extend the existing StateBus control wire so one physical invocation carries the exact Runtime/Attempt/Binding/Grant scope required for correlation.

## Why this Slice exists

MRR-04 closes logical capability → provider binding inside the controller, but the integrated `ExecRequest` loses `run_id`, `session_id`, physical invocation identity and execution-binding identity.

The worker currently sees a grant hash string but cannot even echo the complete Runtime authorization scope because it was never sent.

## Architecture invariant

```text
For every physical control invocation I:

response(I).scope
==
request(I).scope

and request(I).scope is derived only from
the already-authorized RuntimeIdentity + Attempt + Binding + Grant.
```

No new provider/capability decision occurs in control code.

## Current source truth

Read exact branch:

```text
feat/mrr-04-capability-provider-binding
```

Do not perform SHA/history/merge-base analysis for this Slice.

Current facts:

- `ControlHeader`: trace/task/step/attempt/role/timeout/schema/event.
- `ExecRequest`: includes `capability_grant_hash`.
- `AdaptiveCapabilityDispatcher._consume_retrieval_semantic_state()` creates the current integrated physical request.
- it currently uses a synthetic trace string `adaptive:<task_id>`.
- protobuf subprocess sends typed ACK/RUN_START/HEARTBEAT/result by echoing request header.
- `session_id`, binding hash and physical invocation ID are absent.

## Exact symbols involved

```text
statebus.control.messages.ControlHeader
statebus.control.messages.ExecRequest
encode_message / decode_message

statebus.control.schema.build_control_file_descriptor

statebus.control.subprocess_worker.run

statebus.runtime.adaptive_dispatcher.AdaptiveCapabilityDispatcher.dispatch
statebus.runtime.adaptive_dispatcher.AdaptiveCapabilityDispatcher._consume_retrieval_semantic_state

statebus.runtime.adaptive_runtime.AdaptiveRuntimeEngine.run
```

`AdaptiveRuntimeEngine` only needs change if exact RuntimeIdentity must be explicitly passed to dispatcher; do not otherwise refactor it.

## Files to read

```text
statebus/contracts/identity.py
statebus/contracts/provider_binding.py
statebus/contracts/adaptive.py
statebus/control/messages.py
statebus/control/statebus_control.proto
statebus/control/schema.py
statebus/control/transport.py
statebus/control/subprocess_worker.py
statebus/runtime/adaptive_runtime.py
statebus/runtime/adaptive_dispatcher.py
```

## Expected production files changed

Target <= 6:

```text
statebus/control/messages.py
statebus/control/statebus_control.proto
statebus/control/schema.py
statebus/control/subprocess_worker.py
statebus/runtime/adaptive_dispatcher.py
statebus/runtime/adaptive_runtime.py   # only if identity handoff is required
```

Do not modify `transport.py` unless the existing encoder/text adapter cannot preserve the expanded header without change.

## Contracts changed

Recommended additive `ControlHeader` fields:

```text
run_id
session_id
invocation_id
execution_binding_hash
capability_grant_hash
```

Keep:

```text
task_id
```

as the legacy wire name for `RuntimeIdentity.runtime_task_id`.

Do **not** add another `runtime_task_id`.

Keep `ExecRequest.capability_grant_hash` during the compatibility window; require:

```text
ExecRequest.capability_grant_hash
==
ControlHeader.capability_grant_hash
```

`invocation_id` is created once for each physical exchange. It is not the semantic Attempt ID.

## Protocol version rule

Sender must explicitly declare supported `schema_version`.

Canonical Batch 2 path must reject missing/unsupported version; do not default an absent version and then claim the sender declared it.

Keep `statebus.control.v1` for protobuf-additive changes.

## Compatibility strategy

- additive protobuf field numbers only;
- update both `.proto` and current dynamic `schema.py`;
- add a focused schema parity test;
- UTF-8 carrier may reuse/echo the request scope;
- canonical new runtime does not silently accept old physical workers missing mandatory scope.

## Implementation sequence

1. Record current field numbers.
2. Add new Header fields in Python.
3. Add matching protobuf fields with unused numbers.
4. Add matching dynamic descriptor fields.
5. Update encode/decode.
6. Add strict required-scope validation at canonical physical invocation boundary.
7. Generate `invocation_id` once at request construction.
8. Use real Runtime trace/run/session values, not `adaptive:<task>`.
9. Project `binding.binding_hash` and `grant.grant_hash`.
10. Worker checks required scope and duplicate grant-hash equality.
11. Worker echoes immutable header on all typed events/results.
12. Run real subprocess round-trip targeted test.

## Non-goals

```text
ProtocolInvocationBinding
ControlResponseBinder
active Attempt fencing
Supervisor refactor
retry/rebind
StateAccessGrant
schema codegen migration
persistent worker
generic worker event type
```

## Targeted tests

Coverage requirements — consolidate these into the smallest useful test set; do **not** create one test per bullet. Target <= 4 targeted test functions plus at most 1 adjacent regression:

```text
1. one protobuf/header roundtrip test covers all added scope fields;
2. one real UDS/subprocess test observes ACK + RUN_START + HEARTBEAT + terminal result and verifies the same scope;
3. one parameterized/batched boundary-negative test covers missing required scope and grant-hash mismatch;
4. one canonical integration test only if it is not already covered by (2).
```

## Integration test

Use the current real `semantic_select_v1` subprocess path through UDS.

Do not substitute pure dataclass/hash tests for the mechanism gate.

## Evidence

Record request and observed worker message scopes:

```text
task_id
run_id
session_id
step_id
attempt_id
invocation_id
execution_binding_hash
capability_grant_hash
schema_version
```

## Source Gate

PASS only if the current source gap is confirmed by direct code inspection and the implementation adds the missing wire projection without introducing a new authority object. Do not create a historical/SHA regression harness.

## Mechanism Gate

PASS only if a real subprocess receives and returns the exact new scope over UDS/Protobuf.

## Integration Gate

PASS only if canonical adaptive semantic-state integration still completes successfully.

## Competition Gate

`UNVALIDATED` in this Slice.

MRR-05A only makes later structured-protocol evidence trustworthy; it does not by itself validate competition E2E, latency, token, stability, or score claims.

## Execution discipline

- no Git SHA/history analysis or source-hash ledger;
- no defensive/future-proof abstractions, silent fallback, generic retry framework, or unrelated cleanup;
- no full pytest/Docker/vLLM/benchmark;
- after targeted tests, real mechanism evidence, `git diff --check`, and scope check, stop;
- do not commit/push/reset/clean/rebase/merge and do not use `git add .`.

If the real UDS/subprocess mechanism is blocked only by the execution sandbox/permission environment, report `MECHANISM_GATE_BLOCKED_ENVIRONMENT`; do not replace it with a fake dataclass test and do not expand testing to compensate.

## Rollback

Revert only the additive control fields/identity handoff. No state/data migration.

## DESIGN_CONFLICT stop conditions

Stop if:

- RuntimeIdentity cannot be obtained without moving provider selection;
- supporting fields requires changes in State/Memory/Artifact modules;
- old-worker compatibility would require silent identity fabrication;
- more than one new authority object is proposed.

## NEXT_ALLOWED_SLICE

```text
MRR-05B
Physical Response Correlation + Admission
```
