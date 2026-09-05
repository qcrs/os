# StateBus MRR Batch 2 — Readiness Review

## 0. Review identity

```text
Repository:
https://github.com/qcrs/os

Current Source of Truth:
feat/mrr-04-capability-provider-binding

Historical repo:
qcrs/os1
= archaeology only

Historical audit docs:
docs/reference/statebus-audit/*
= historical design/evidence only, never CURRENT SOURCE FACT
```

## 1. Decision

```text
Batch 1:
CLOSED

Batch 2:
DESIGNED
CODEX READY

First implementation Slice:
MRR-05A

GO / NO-GO:
GO
```

The first unresolved Runtime correctness boundary after MRR-04 is not provider selection. MRR-04 already makes provider eligibility and execution binding explicit.

The next unresolved boundary is:

> **The Runtime-authorized Attempt/Binding/Grant is not faithfully projected to the physical control invocation, and returned physical messages are not admitted against an exact invocation witness before business consumption.**

This becomes dangerous as soon as retry/rebind/timeout creates more than one Attempt for the same Step.

---

## 2. Frozen contracts inherited from MRR-01 → MRR-04

Unless a future source contradiction is found, the following are frozen:

```text
Agent Proposes;
Runtime Authorizes.

Logical Capability
!=
Physical Provider.

Eligibility
!=
Binding.

Execution Binding
precedes
CapabilityGrant.

Planner does not choose physical provider.

Runtime owns semantic Attempt.

ApprovedPlan owns semantic graph.

Provider executes only an already-bound capability.
```

Batch 2 must extend these laws to the physical execution/result boundary.

---

## 3. Current source facts that make Batch 2 necessary

### 3.1 Wire identity is incomplete

Current `statebus/control/messages.py::ControlHeader` contains:

```text
trace_id
task_id
step_id
attempt_id
target_role
timeout_ms
event_type
schema_version
```

Current `ExecRequest` adds `capability_grant_hash`, but the wire does not carry:

```text
run_id
session_id
physical invocation identity
ExecutionBindingReceipt identity/hash
```

`task_id` is the legacy wire spelling of `RuntimeIdentity.runtime_task_id`; adding a second `runtime_task_id` field would duplicate identity. The target should retain `task_id` as the wire field and validate it as the RuntimeTaskID projection.

### 3.2 Worker validation does not enforce Runtime authority

`statebus/control/subprocess_worker.py` validates request shape and operation prerequisites. For the semantic-state operation it requires `capability_grant_hash` to be non-empty, but the worker does not prove:

```text
grant belongs to this session
grant belongs to this attempt
grant belongs to this binding
binding selected this provider
request operation is committed by the expected invocation
```

This does **not** mean the worker must become a trust root. The Runtime remains the authority root; the immediate Batch 2 problem is exact correlation/admission.

### 3.3 There are two lifecycle truths

`AdaptiveRuntimeEngine._dispatch_lifecycle()` currently advances:

```text
DISPATCHED
→ ACKED
→ RUNNING
```

before the provider dispatch happens.

Separately, `subprocess_worker.py` sends real:

```text
AckReceived
RunStart
Heartbeat
SuccessResult / ErrorResult
```

over UDS.

Therefore `ACKED/RUNNING` in the semantic Runtime currently can be Runtime-synthetic while a real worker lifecycle exists on an inner control path.

### 3.4 Supervisor is Step-keyed

`RuntimeSupervisor.steps` is:

```text
dict[str, StepRuntimeRecord]
```

keyed by `step_id`.

`register(step_id, attempt_id, ...)` overwrites the previous Step record. This is not safe once Step S can have Attempt A then Attempt B and A can still emit a delayed event.

### 3.5 Session records Attempts but does not own active-attempt admission

`RuntimeTaskSession` stores:

```text
attempt_records
current_attempt_id
workflow_steps
```

but there is no exact:

```text
active_attempt(step_id)
```

authority check at result commit.

`update_attempt_record()` is record-oriented; it does not function as a stale-attempt fence.

### 3.6 Result admission is partial

High-level `AdaptiveRuntimeEngine` currently validates primarily:

```text
result.grant_hash == grant.grant_hash
result.attempt_id == attempt_id   (when supplied)
output refs/kinds/cardinality
```

The physical semantic-state dispatcher checks selected state identity/PID-related properties, but there is no single admission seam proving:

```text
task
session
step
attempt
invocation
binding
grant
result type
output contract
```

before physical result content is used.

### 3.7 Timeout truth is fragmented

There are currently at least three notions:

```text
RuntimeSupervisor ack timeout
RuntimeSupervisor lease/heartbeat timeout
SubprocessExecutorTransport timeout
```

The canonical Adaptive Runtime does not drive its state from the real worker event stream, and the subprocess transport can synthesize an `ErrorResult` for timeout.

A Runtime-derived timeout must not masquerade as a worker-emitted result.

---

## 4. Why Batch 2 should be four slices

### Rejected: one `MRR-05` mega-slice

Would touch wire schema, worker, transport, dispatcher, session, supervisor and runtime at once.

Problems:

```text
poor rollback boundary
hard to isolate protocol vs Attempt bugs
mechanism tests become ambiguous
likely > 6 primary production files
Codex would be forced to redesign while implementing
```

### Rejected: merge `MRR-05 + MRR-06`

Physical correlation and semantic active-attempt authority are related but not the same invariant.

### Accepted

```text
05A
The request/event carries exact invocation scope.

05B
A physical response cannot be consumed unless it matches that request scope and result contract.

06A
Lifecycle mutation belongs to an Attempt, and lifecycle origin is truthful.

06B
A terminal/superseded Attempt can never commit a late event/result.
```

This ordering supplies the witness before using it for fencing.

---

## 5. First Slice GO criteria

`MRR-05A` is GO because:

```text
source truth is clear:
YES

current physical path exists:
YES
UDS + Protobuf + real subprocess worker

architecture choice is bounded:
YES
extend current wire rather than duplicate authority

expected files known:
YES

targeted mechanism test known:
YES
real subprocess physical round trip

external pattern research complete enough:
YES

requires State Lifecycle redesign first:
NO

requires persistent worker:
NO

requires scheduler:
NO

requires benchmark:
NO
```

---

## 6. What MRR-05A proves

It proves:

```text
Runtime/Binding/Grant scope is not lost at the control boundary.

Every physical invocation has an invocation_id.

Worker responses echo the exact immutable request scope.

Missing/unsupported protocol identity is not silently fabricated.

The real UDS/subprocess path transports the new scope.
```

It does **not** prove:

```text
worker is trusted
exactly-once execution
late result fencing
real semantic Attempt retry
cancel correctness
StateRef access authority
Artifact verification correctness
performance improvement
```

---

## 7. State Lifecycle readiness

Current state:

```text
MRR-07 State Lifecycle:
NOT READY TO IMPLEMENT
```

Reason:

State access cannot be safely scoped to an Attempt while active-attempt truth, timeout settlement and late-result fencing are still incomplete.

After MRR-05A → 05B → 06A → 06B all pass:

```text
MRR-07 State Lifecycle:
READY TO DESIGN / IMPLEMENT
```

It can then bind state consumption to:

```text
session
step
attempt
binding/grant
consumer
immutable ref identity
```

without inventing a parallel authority model.
