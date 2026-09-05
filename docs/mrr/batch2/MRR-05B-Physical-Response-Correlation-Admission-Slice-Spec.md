# MRR-05B Slice Spec — Physical Response Correlation / Admission

## Goal

Ensure a decoded control response is not consumed by provider business logic until it is proven to belong to the exact physical invocation and expected result contract.

## Why this Slice exists

After MRR-05A the wire carries enough identity, but merely transporting fields does not enforce them.

Current semantic-state dispatcher can decode a physical success and consume selection data without a single canonical check of session/invocation/binding/grant scope.

## Architecture invariant

```text
RawControlMessage
    ↓
ControlResponseAdmission
    ↓ only if exact scope + legal contract
AdmittedControlMessage
    ↓
business consumption
```

A protobuf-decodable message is only a candidate.

## Current source truth

- `SubprocessExecutorTransport.exchange_sequence()` returns typed messages.
- `AdaptiveCapabilityDispatcher` directly interprets terminal response.
- no canonical response admission module exists.
- transport can collect lifecycle and terminal messages.
- current response header lacks 05A fields until previous Slice lands.

## Exact symbols involved

```text
statebus.control.transport.SubprocessExecutorTransport
statebus.control.messages.ControlHeader
AckReceived
RunStart
Heartbeat
SuccessResult
ErrorResult
TrapFatal

statebus.runtime.adaptive_dispatcher.AdaptiveCapabilityDispatcher._consume_retrieval_semantic_state
```

## Files to read

```text
statebus/control/messages.py
statebus/control/transport.py
statebus/control/subprocess_worker.py
statebus/runtime/adaptive_dispatcher.py
tests around control/subprocess/adaptive semantic state
```

## Expected production files changed

```text
statebus/control/admission.py        # ADD
statebus/control/transport.py        # EXTEND
statebus/runtime/adaptive_dispatcher.py
```

Optionally `statebus/control/__init__.py` for export only.

Avoid changes outside this set unless source proves necessary.

## Contracts added/changed

Add a narrow immutable receipt, e.g.:

```text
ControlResponseAdmissionReceipt
```

Minimum contents:

```text
invocation_id
attempt_id
execution_binding_hash
capability_grant_hash
event_type
admitted
reason_code
terminal
```

The receipt is audit evidence, not a new execution authority.

Recommended validator responsibilities:

```text
exact ControlHeader scope equality
allowed response event types
legal event ordering where currently observable
at most one terminal result per invocation
terminal output_contract_version equals request expectation
operation-specific ref/cardinality constraints needed by current path
```

## Why not ControlResponseBinder

Do not create an inheritance tree or a generic binding service. One validator/receipt at the physical boundary is enough.

## Compatibility strategy

05A fields are mandatory for canonical response admission.

UTF-8 converted messages can be admitted as:

```text
origin = ADAPTER_DERIVED
```

but cannot be counted as native typed worker evidence.

## Implementation sequence

1. Define exact scope comparison.
2. Define legal lifecycle/terminal type set.
3. Define terminal duplication guard for one exchange.
4. Implement response admission receipt.
5. Apply to received worker messages.
6. Ensure terminal payload is not returned to dispatcher as usable until admitted.
7. Add current `semantic_select_v1` result-contract checks.
8. Negative tests.
9. Real subprocess integration.

## Non-goals

```text
active-attempt stale fencing
semantic retry
Supervisor redesign
generic protocol router
malicious-worker framework
artifact verification
StateRef access grant
```

## Targeted tests

These are coverage conditions, not separate mandatory test functions. Prefer <= 4 targeted functions by parameterizing correlation failures.

```text
reject wrong task
reject wrong run/session
reject wrong step
reject wrong attempt
reject wrong invocation
reject wrong binding
reject wrong grant
reject illegal terminal type
reject wrong output contract
reject wrong ref type/cardinality
reject duplicate terminal
accept valid lifecycle + success
```

## Negative test note

Not every negative case must launch a custom subprocess. Validator unit tests may fabricate the candidate message.

Mechanism Gate still requires at least one real UDS/subprocess result to pass through the real admission seam.

## Integration test

Current `semantic_select_v1` path:

```text
publish state
→ UDS request
→ real worker events
→ real SuccessResult
→ admission
→ selection consumption
```

## Evidence

Save:

```text
expected invocation scope
observed message scope
admission decision
terminal count
output contract decision
```

## Source Gate

PASS only if the old dispatcher could business-consume a physical result without exact 05A scope admission.

## Mechanism Gate

PASS only if real UDS/subprocess success traverses the admission validator.

## Integration Gate

PASS if adaptive retrieval semantic selection remains correct and no raw terminal bypass exists.

## Competition Gate

`UNVALIDATED` in this Slice. This Slice may improve the truthfulness of later competition evidence but does not validate competition E2E or performance claims.

## Execution discipline

- no Git SHA/history/merge-base analysis or source-SHA ledger;
- testing bullets are coverage requirements, not test-count requirements; consolidate/parameterize aggressively;
- targeted tests only plus at most 1 directly adjacent regression by default;
- no defensive/future-proof abstraction, generic fallback/retry framework, silent repair, or unrelated cleanup;
- after required gate evidence, `git diff --check`, and scope check, stop; no broad post-implementation audit;
- do not commit/push/reset/clean/rebase/merge and do not use `git add .`.

## Rollback

Delete admission module and call sites; 05A wire can remain but Batch 2 must be marked incomplete.

## DESIGN_CONFLICT stop conditions

Stop if validator design starts duplicating:

```text
PlanPolicy
ProviderEligibility
ExecutionBinding
ArtifactVerification
```

or if exact scope cannot be compared without changing upstream authority contracts.

## NEXT_ALLOWED_SLICE

```text
MRR-06A
Attempt Authority + Lifecycle Origin Truth
```
