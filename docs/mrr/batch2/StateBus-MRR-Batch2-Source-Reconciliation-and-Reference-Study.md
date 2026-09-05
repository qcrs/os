# StateBus MRR Batch 2 — Source Reconciliation and Reference Study

## 1. Method

Every finding in this document is tagged conceptually as one of:

```text
CURRENT SOURCE FACT
HISTORICAL IMPLEMENTATION
HISTORICAL DESIGN
EXTERNAL REFERENCE
DESIGN DECISION
HYPOTHESIS
OPEN QUESTION
```

Historical audit documents were read as design archaeology. They were not promoted to current-source truth.

Source baseline:

```text
qcrs/os
branch: feat/mrr-04-capability-provider-binding
```

---

## 2. CURRENT SOURCE FACT — control layer

### Files

```text
statebus/control/messages.py
statebus/control/schema.py
statebus/control/statebus_control.proto
statebus/control/transport.py
statebus/control/subprocess_worker.py
```

### Typed protocol

Current event types:

```text
REQ_EXEC
ACK_RECV
RUN_START
HEARTBEAT
RES_SUCC
RES_ERR
CMD_CANCEL
TRAP_FATAL
CMD_GC
```

### Current identity projection

`ControlHeader`:

```text
trace_id
task_id
step_id
attempt_id
target_role
timeout_ms
schema_version
event_type
```

Missing as first-class wire identity:

```text
run_id
session_id
invocation_id
execution_binding_hash
```

`ExecRequest` separately contains `capability_grant_hash`.

### Current worker behavior

The protobuf subprocess:

```text
receives one ExecRequest
validates operation/request shape
emits ACK
emits RUN_START
emits HEARTBEAT
emits terminal Success/Error
exits
```

It uses the request header for response scope.

It does not independently reconstruct and authorize the full `CapabilityGrant` or `ExecutionBindingReceipt`.

### Current transport-derived events

`SubprocessExecutorTransport` has its own timeout and can append a synthetic `ErrorResult("subprocess_timeout")`.

The UTF-8 text carrier converts text markers back into typed control messages using request identity.

**Design implication:** event origin must be truthful.

---

## 3. CURRENT SOURCE FACT — Runtime/session/supervisor

### `AdaptiveRuntimeEngine`

Current chain creates attempt/binding/grant, then `_dispatch_lifecycle()` synthetically moves supervisor to ACKED/RUNNING before invoking the dispatcher.

### `RuntimeSupervisor`

Current map is keyed by `step_id`.

This makes it operationally impossible to retain A and B records for one Step in the same supervisor map.

### `RuntimeTaskSession`

Stores attempt history but has no `active_attempt(step)` authorization primitive.

### Current result validation

High-level result validation checks grant hash, optional Attempt ID, and output contract shape.

There is no single exact physical response-admission seam.

---

## 4. CURRENT SOURCE FACT — State readiness implications

### `LayeredStateStore`

The current state API is essentially:

```text
publish(ref_id, ...)
load(ref_id)
get(ref_id)
release(ref_id)
```

Knowing `ref_id` is sufficient for store access.

`release(ref_id)` is not logically idempotent because it pops the handle.

Ref ID reuse can overwrite the materialization map.

### `SemanticStateRef`

Carries content identity, but not a first-class generation or Attempt access grant.

### `DenseSemanticStateContract`

Contains:

```text
owner_session_id
lease_expires_at_ns
producer_pid
content/representation hashes
```

but resolve does not take current Attempt/CapabilityGrant as an authorization input.

**Design implication:** MRR-07 requires Batch 2 Attempt truth first.

---

## 5. CURRENT SOURCE FACT — Artifact/Memory ordering

### Artifact coupling

`ArtifactLifecycleManager.mark_verified()` currently sets:

```text
verification_state = VERIFIED
replay_ready = True
```

in the same state transition.

Therefore:

```text
Verified
!=
Replay Eligible
```

is not yet represented correctly.

`ExecutionArtifactRef` also lacks Attempt ID as a first-class field.

### Memory

`MemoryRef` carries persistent reuse metadata, producer run and artifact/state links.

Memory correctness depends on the upstream Artifact verification/replay split.

**Recommended later order:**

```text
State lifecycle
→ Artifact truth
→ Memory/replay truth
```

Artifact and State are not strictly sequential by theory, but State first has higher competition/mechanism priority and directly depends on Attempt access authority.

---

## 6. HISTORICAL DESIGN — what was proposed before

Historical documents proposed abstractions including:

```text
ProtocolInvocationBinding
ExecutionResultBinding / ControlResponseBinder
WorkerEvent
StateAccessGrant
DispatchPermit
PersistentWorkerBroker
ReadyStepScheduler
```

These remain useful hypotheses, not mandatory objects.

MRR-04 has already changed the source by making Provider Binding first-class. Therefore historical protocol design must be re-reconciled against the new `ExecutionBindingReceipt + BoundCapabilityGrant`.

Batch 2 decision:

```text
keep the problems
re-evaluate the object shapes
```

---

## 7. External Reference → StateBus Mapping

### 7.1 Temporal

External system:
`temporalio/temporal`

Relevant source/docs:
- `service/history/api/activity_util.go`
- `service/history/api/respondactivitytaskcompleted/api.go`
- Temporal Activity Task Token documentation

Pattern:
Activity Task Token is specific to an Activity Task Execution. Temporal source compares token Attempt to current Activity attempt; retry creates another execution.

Problem solved there:
A completion must prove it belongs to the currently valid activity execution.

Equivalent StateBus problem:
Attempt A times out, Attempt B becomes active, completion for A arrives.

What StateBus adopts:
- attempt-scoped completion witness;
- stale completion rejection at admission;
- completion does not gain authority merely because payload is valid.

What StateBus explicitly does NOT adopt:
- durable workflow history;
- Temporal server architecture;
- event sourcing;
- workflow determinism/replay model.

Reference:
https://docs.temporal.io/
https://github.com/temporalio/temporal

---

### 7.2 Ray

External system:
`ray-project/ray`

Relevant source:
`src/ray/protobuf/common.proto`

Pattern:
Ray explicitly models `TaskAttempt` as task ID + attempt number; task events and retry state include attempt number.

Problem solved there:
A logical task can be executed more than once and task/event identity must distinguish attempts.

Equivalent StateBus problem:
One semantic Step can have multiple Attempts after timeout/retry/rebind.

What StateBus adopts:
- Attempt is not an incidental integer;
- operational records/events are Attempt-scoped;
- future state owner/borrower ideas can inform pinning.

What StateBus explicitly does NOT adopt:
- raylet;
- cluster scheduler;
- distributed object store;
- distributed reference-count protocol;
- actor runtime.

Reference:
https://github.com/ray-project/ray

---

### 7.3 Dask Distributed

External system:
`dask/distributed`

Pattern:
Scheduler state transitions are driven by explicit stimuli from workers/clients. `stimulus_task_finished` carries a run identifier in current source; scheduler centralizes transition validation.

Problem solved there:
Keep authoritative task state consistent despite asynchronous worker messages.

Equivalent StateBus problem:
Current Runtime synthesizes ACK/RUNNING instead of consuming observed lifecycle facts.

What StateBus adopts:
- events/stimuli drive lifecycle transitions;
- centralized transition checks;
- event identity must identify the concrete execution.

What StateBus explicitly does NOT adopt:
- READY scheduler policy;
- work stealing;
- cluster worker accounting;
- Dask task graph machinery.

Reference:
https://distributed.dask.org/en/latest/scheduling-state.html

---

### 7.4 Chubby

External system:
Google Chubby lock service.

Pattern:
A lock holder can obtain a sequencer containing lock identity/mode/generation. Servers reject requests carrying an obsolete sequencer.

Problem solved there:
A delayed request from a former lock holder must not mutate protected state after ownership changed.

Equivalent StateBus problem:
A delayed result/event from Attempt A must not mutate Step S after B becomes active.

What StateBus adopts:
- small fencing witness;
- validate freshness at the protected operation/commit boundary.

What StateBus explicitly does NOT adopt:
- distributed locks;
- Chubby service;
- consensus;
- leases as a global coordination service.

Reference:
Mike Burrows, “The Chubby Lock Service for Loosely-Coupled Distributed Systems”, OSDI 2006:
https://www.usenix.org/legacy/event/osdi06/tech/full_papers/burrows/burrows_html/

---

### 7.5 Kubernetes

External system:
Kubernetes

Pattern:
`name` is not enough to identify an object incarnation; `uid` identifies a specific occurrence, and `resourceVersion` is an opaque change/concurrency witness.

Problem solved there:
Stale clients should not confuse a recreated or updated object with an older incarnation.

Equivalent StateBus problem:
`step_id` is a semantic name, not an execution incarnation. Attempt/invocation identity must disambiguate incarnations.

What StateBus adopts:
- separate stable semantic name from execution incarnation;
- do not key mutable execution state by Step name alone.

What StateBus explicitly does NOT adopt:
- controllers;
- reconciliation loops;
- API server;
- etcd;
- resourceVersion mechanics.

Reference:
https://kubernetes.io/docs/concepts/overview/working-with-objects/names/
https://kubernetes.io/docs/reference/kubernetes-api/definitions/object-meta-v1-meta/

---

### 7.6 gRPC

External system:
gRPC

Patterns:
- deadlines are caller willingness-to-wait bounds;
- cancellation is cooperative and does not forcibly stop arbitrary server application work;
- retry creates RPC attempts;
- transparent retry is restricted to cases where server application processing is known not to have observed the call.

Problem solved there:
Transport failure/retry semantics must not be confused with application semantics.

Equivalent StateBus problem:
HTTP/UDS/client retry must not silently become semantic Step retry; timeout must not be misreported as worker business failure.

What StateBus adopts:
- transport retry vs semantic re-execution split;
- explicit deadline/cancel outcome;
- cancellation does not grant permission to accept a later result.

What StateBus explicitly does NOT adopt:
- replacing UDS/Protobuf with gRPC;
- service mesh;
- generic retry framework.

Reference:
https://grpc.io/docs/guides/retry/
https://grpc.io/docs/guides/deadlines/
https://grpc.io/docs/guides/cancellation/

---

### 7.7 Celery

External system:
Celery

Pattern:
late ACK/redelivery can cause a task to execute multiple times; tasks must be idempotent when relying on such behavior.

Problem solved there:
Reliable delivery does not imply exactly-once execution.

Equivalent StateBus problem:
Timeout/retry can create overlapping physical execution.

What StateBus adopts:
- do not claim exactly once;
- side-effecting providers must use idempotence/commit fencing where needed;
- stale result suppression is mandatory.

What StateBus explicitly does NOT adopt:
- message broker;
- Celery result backend;
- broker ACK semantics as StateBus semantics.

Reference:
https://docs.celeryq.dev/en/stable/userguide/tasks.html

---

### 7.8 Ray ObjectRef / shared memory — future MRR-07

Pattern:
Object identity, ownership and references keep objects pinned while consumers still hold references.

Equivalent StateBus problem:
Shared-memory state must not be physically released while an authorized Attempt still consumes it.

What StateBus may adopt:
a **small local owner/consumer pin count**, explicit owner, idempotent release.

What StateBus does NOT adopt:
distributed reference counting or a cluster object store.

---

## 8. Why full ProtocolInvocationBinding is not adopted

Historical design expected the protocol binding object to add a strong new authority layer.

Current source has since gained:

```text
RuntimeIdentity
ExecutionBindingReceipt
BoundCapabilityGrant
```

A new canonical hash over all of them would mostly repeat existing commitments.

The correctness delta that remains source-backed is narrower:

```text
A. make missing authority visible on wire
B. identify the physical invocation
C. correlate response exactly
D. fence against active Attempt at commit
```

Therefore use:

```text
ControlHeader
+ ExecRequest
+ existing binding/grant
+ invocation_id
+ response admission receipt
```

until a future trust boundary proves a portable invocation token is necessary.

---

## 9. Why generic WorkerEvent is not adopted

Current source already has typed messages.

Adding:

```text
WorkerEvent(type, payload)
```

would either:

1. wrap those messages with no new correctness value, or
2. force local in-process execution to fake remote-worker semantics.

Instead:

```text
existing typed control messages
→ response/lifecycle admission
→ attempt-aware supervisor transition
```

and:

```text
local provider
→ explicit local RUNNING transition
```

---

## 10. Competition Constraint Reconciliation

Hard requirements directly found in `docs/reference/statebus-audit/题目.md`:

```text
>= 3 agents
>= 3 role/task classes
structured communication
action / input / result / capability
handshake/discovery/protocol mapping
text and structured collaboration modes
non-text intermediate state transfer
shared memory store/retrieve/reuse
2 related continuous-task groups
communication/time/state/memory metrics
>= 10 continuous runs
openEuler 24.03-LTS-SP3
```

Scoring:

```text
Communication efficiency 25
State transfer innovation 20
Memory reuse 20
System completeness 20
Experiment validation 15
```

Batch 2 is not a direct “25 point optimization”. It ensures the structured protocol and stability claims are true under retry/timeout and can be evidenced without synthetic lifecycle claims.

The correct competition priority remains:

```text
Correctness substrate
→ runnable mainline
→ controlled mechanism evidence
→ fair text/structured/state/memory experiments
→ optional optimization
```
