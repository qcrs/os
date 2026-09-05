# StateBus MRR Batch 2 — Protocol / Attempt Truth Deep Design

## 1. Executive Summary

At `feat/mrr-04-capability-provider-binding@a8345d60f3a6e7078dda22e271e9d1ab02a931fd`, MRR-01 → MRR-04 have successfully established controller-side authority through:

```text
RuntimeIdentity
→ TaskContractIdentity
→ PlanProposal
→ PlanNormalizationReceipt
→ PlanPolicyReport
→ ApprovedPlan
→ ApprovedPlanBundle
→ AdaptiveRuntimeEngine
→ Attempt
→ LogicalCapabilityDescriptor
→ ProviderEligibilityProjection
→ deterministic provider admission
→ ExecutionBindingReceipt
→ CapabilityGrant
→ Dispatcher / Provider
```

The strongest remaining correctness gap is the boundary after the grant:

```text
controller authority
        ↓
physical invocation
        ↓
worker/control events
        ↓
candidate result
        ↓
runtime commit
```

Today, identity and lifecycle truth weaken at this boundary.

Batch 2 therefore has one objective:

> **A physical event/result may affect Runtime state only when it is correlated to the exact authorized invocation and the exact currently-active semantic Attempt.**

This is not an exactly-once-execution project. Duplicate/late physical execution may occur; stale effects must be fenced at admission/commit.

---

## 2. Current State after MRR-04

### CURRENT SOURCE FACT

MRR-04 introduced:

```text
LogicalCapabilityDescriptor
ExecutionProviderDescriptor
ProviderRuntimeFacts
ProviderEligibilityProjection
ExecutionBindingReceipt
BoundCapabilityGrant
ExecutionProviderRegistry
```

`compute_provider_eligibility()` filters candidates; `select_provider_deterministically()` selects from eligible providers; `create_execution_binding()` freezes the chosen provider; the grant/binding scope is checked before provider dispatch.

### DESIGN CONSEQUENCE

The protocol layer does **not** need to re-run provider eligibility or create another provider authority object.

Its job is projection and correlation.

---

## 3. Source-backed Current Runtime Map

```text
statebus/runtime/adaptive_mainline.py
AdaptiveMainlineRunner.run()
    │
    ├─ resolve/validate RuntimeIdentity
    ├─ assemble ApprovedPlan / ApprovedPlanBundle
    ├─ construct State/Memory/Workspace context
    └─ construct AdaptiveRuntimeRequest
            │
            ▼
statebus/runtime/adaptive_runtime.py
AdaptiveRuntimeEngine.run()
    │
    ├─ RuntimeSessionManager.start()
    ├─ attach_workflow()
    ├─ compute READY steps
    ├─ create attempt_id
    ├─ logical capability lookup
    ├─ compute_provider_eligibility()
    ├─ select_provider_deterministically()
    ├─ create_execution_binding()
    ├─ _issue_grant()
    ├─ _dispatch_lifecycle()
    │      ├─ supervisor.register()
    │      ├─ supervisor.dispatch()
    │      ├─ supervisor.ack()       [CURRENT: synthetic]
    │      └─ supervisor.run_start() [CURRENT: synthetic]
    │
    ├─ AdaptiveCapabilityDispatcher.dispatch()
    │      │
    │      ├─ retrieval adapter
    │      ├─ transform DSL
    │      ├─ bounded Python
    │      └─ runtime builtin
    │
    ├─ receive AdaptiveStepResult
    ├─ grant/attempt/output checks
    └─ complete/fail/fallback/replan
```

### Important physical sub-chain currently present

The current real subprocess control path is not the universal outer provider boundary. It is used inside the adaptive dispatcher for semantic-state selection.

```text
statebus/runtime/adaptive_dispatcher.py
AdaptiveCapabilityDispatcher._consume_retrieval_semantic_state()
    │
    ├─ publish dense semantic state
    ├─ construct ControlHeader
    ├─ construct ExecRequest(operation="semantic_select_v1")
    └─ SubprocessExecutorTransport.execute()
             │
             ▼
statebus/control/transport.py
SubprocessExecutorTransport.exchange_sequence()
    │
    ├─ bind/listen UDS
    ├─ Popen python -m statebus.control.subprocess_worker
    ├─ send ExecRequest
    └─ receive typed frames
             │
             ▼
statebus/control/subprocess_worker.py
run()
    │
    ├─ receive ExecRequest
    ├─ validate request shape
    ├─ AckReceived
    ├─ RunStart
    ├─ Heartbeat
    └─ SuccessResult / ErrorResult
```

This distinction is critical:

> The real semantic-selection subprocess is a **provider-internal physical invocation** in the current source. Its ACK must not automatically be re-labeled as the entire semantic Step's remote-worker ACK.

---

## 4. Current Physical Protocol Chain — exact answers

| Question | CURRENT SOURCE FACT |
|---|---|
| Who creates the physical request? | `AdaptiveCapabilityDispatcher._consume_retrieval_semantic_state()` creates the integrated `ExecRequest` for `semantic_select_v1`. Test/harness code can also create requests. |
| Request identities | `ControlHeader`: trace/task/step/attempt/role/timeout/schema/event. `ExecRequest`: refs, operation, contracts, state path data, `capability_grant_hash`. |
| RuntimeTaskID on wire? | Functionally yes through legacy field `task_id` when canonical RuntimeIdentity projection is respected; there is no separately named `runtime_task_id` wire field. Do **not** duplicate it. |
| RunID on wire? | No first-class field. Explicit attempt labels may embed run_id text, but that is not a wire contract. |
| SessionID on wire? | No. |
| StepID on wire? | Yes. |
| AttemptID on wire? | Yes. |
| ExecutionBindingReceipt identity on wire? | No. |
| CapabilityGrant identity/hash on wire? | Only `capability_grant_hash` on `ExecRequest`; responses do not independently carry it except through future header changes. |
| What does worker validate? | Structural/operation prerequisites; semantic-select requires non-empty grant hash, but does not prove grant/binding/session authority. |
| Who creates ACK? | Real protobuf subprocess worker creates ACK; outer Adaptive Runtime also currently synthesizes semantic lifecycle ACK. |
| RUN_START real? | Real in subprocess protocol; also synthetic in outer Adaptive Runtime. |
| HEARTBEAT real? | The subprocess worker emits it. Canonical semantic supervisor does not consume that real stream as its truth. |
| How does result return? | Same UDS exchange; transport decodes `SuccessResult/ErrorResult`; dispatcher consumes it and returns higher-level provider result. |
| How does Runtime bind Result to Attempt? | High-level engine checks grant hash and optional attempt id; physical path lacks full invocation/session/binding admission. |
| stale/duplicate/replayed Result behavior? | No canonical stale-result fence or duplicate terminal admission ledger. Synchronous paths reduce exposure but do not establish an invariant. |

---

## 5. Current Attempt Lifecycle

### CURRENT SOURCE FACT

`AdaptiveRuntimeEngine` creates an `attempt_id`.

`RuntimeSessionManager` appends `StepAttemptRecord` records.

`RuntimeSupervisor` tracks operational state.

### Current responsibility split

```text
Engine:
creates attempt id and orchestrates transitions

Session:
records attempt history/current_attempt_id/workflow step mutation

Supervisor:
tracks one StepRuntimeRecord per step_id
```

There is no single semantic owner for:

```text
active_attempt(step)
```

### Source-backed failure mode

If Attempt A and B exist for the same Step, `RuntimeSupervisor.register(step_id, attempt_id)` overwrites the step-keyed record. A later event addressed only by `step_id` can no longer prove which Attempt it belongs to.

### Target ownership

```text
RuntimeTaskSession
    owns semantic active_attempt(step)

RuntimeSupervisor
    owns operational/liveness state for an Attempt key

AdaptiveRuntimeEngine
    coordinates policy and calls the two owners
```

This avoids making a short-lived transport supervisor the semantic commit authority.

---

## 6. Authority / Ownership Matrix

| Object | Creator Authority | Owner | Immutable Identity | Wire Projection | Validator | Commit Authority | Lifetime |
|---|---|---|---|---|---|---|---|
| RuntimeIdentity | Runtime identity resolver | Runtime | `runtime_identity_hash` | partial today | identity contract | Runtime | run |
| ApprovedPlanBundle | Runtime plan policy/assembly | Runtime | bundle/plan hash | no | plan policy | Runtime | run/replan epoch |
| RuntimeWorkflowStep | Session from ApprovedPlan | Session | step_id within plan | step_id only | session transitions | Session/Runtime | session |
| Attempt / StepAttemptRecord | Runtime engine | **current split; target Session** | attempt_id | yes | session + supervisor | **target active-attempt admission** | until terminal/GC |
| LogicalCapabilityDescriptor | capability registry/projection | Runtime registry | semantic contract hash | logical ID only | registry | Plan/Runtime policy | registry epoch |
| ProviderEligibilityProjection | Runtime | Runtime | projection hash | no | provider binding rules | Runtime | attempt |
| ExecutionBindingReceipt | Runtime | Runtime | binding hash | **missing today** | BoundGrant checks | Runtime | attempt |
| CapabilityGrant | Runtime | Runtime | grant hash | request hash only | grant/binding checks | Runtime | attempt/expiry |
| Protocol request | dispatcher/provider | transport invocation | **target invocation_id + header scope** | yes | worker structural + controller admission | none; candidate execution | invocation |
| Worker invocation | physical worker | worker | target invocation scope | received request | worker | none | process/call |
| ACK | real worker OR synthetic runtime today | target invocation lifecycle | request scope | yes | target response admission | no | invocation |
| RUN_START | real worker OR synthetic runtime today | target invocation lifecycle | request scope | yes | target response admission | no | invocation |
| HEARTBEAT | subprocess worker | invocation lifecycle | request scope | yes | target response admission | no | invocation |
| Result | worker/provider | candidate until admitted | request/attempt scope | partial | response + runtime result admission | Runtime | invocation/attempt |
| StateRef | producer + StateStore | State Runtime | ref/content hash | id/kind today | representation validators | future StateAccess authority | state lease |
| ArtifactRef | producer-local today | artifact maps/lifecycle | artifact/content hash | refs | producer validators today | future Runtime Artifact Authority | durable |
| MemoryRef | Memory Runtime | persistent store | memory hash | memory IDs | compatibility policy | Memory admission | cross-task |

The dominant defects are **authority loss at wire projection**, **semantic active-attempt ambiguity**, and **truth-source ambiguity for lifecycle events**.

---

## 7. Identified Correctness Gaps

### P0-1 — Invocation scope loss

`session_id` and binding identity disappear before the physical worker boundary.

### P0-2 — No physical invocation identity

Attempt ID is semantic; one Attempt can contain more than one physical control operation. A separate `invocation_id` is required for request/response correlation.

### P0-3 — Synthetic lifecycle truth

The Runtime marks ACK/RUNNING before real provider dispatch.

### P0-4 — Step-keyed Supervisor

No safe coexistence of A and B attempts.

### P0-5 — Candidate result and committed result are not a formal boundary

Physical decode success can flow into business consumption without one canonical response admission seam.

### P0-6 — Locally derived timeout masquerades as worker result

The subprocess transport can append an `ErrorResult` for its own timeout.

### P1-1 — schema/version identity can be inferred

Current message decode behavior historically permits missing schema version to default to current version. Sender-declared identity and receiver inference must not be conflated.

### P1-2 — `.proto` and dynamic `schema.py` are dual schema definitions

This is a drift risk. Batch 2 should add parity evidence but **not** turn schema generation into a side project.

### P1-3 — text carrier event provenance

The UTF-8 compatibility path adapts strings into typed events using the request header. Those are adapter-derived, not native typed-worker facts.

---

## 8. External Systems Study — conclusions only

Detailed references are in the companion Reference Study.

Patterns adopted:

```text
Temporal:
completion token is execution-specific;
retry creates another execution;
stale completion token becomes invalid.

Ray:
Task identity and attempt number are separate;
task events are indexed by task attempt.

Dask:
worker/client stimuli drive scheduler transitions;
transition state is centrally validated.

Chubby:
a small sequencer/fencing witness prevents delayed old holders
from committing protected operations.

Kubernetes:
stable name != incarnation identity;
UID/resourceVersion prevent stale object assumptions.

gRPC:
transport retry/deadline/cancel are not semantic task retry;
deadline expiry does not magically stop application work.

Celery:
late acknowledgment/redelivery can execute a task more than once;
correctness cannot rely on exactly-once execution.
```

StateBus adopts the authority/fencing patterns, not the surrounding platforms.

---

## 9. Protocol Invocation Design

### 9.1 Option A — extend current wire contract

Extend `ControlHeader` with additive fields:

```text
run_id
session_id
invocation_id
execution_binding_hash
capability_grant_hash
```

Keep existing:

```text
task_id
```

as the wire projection of `RuntimeIdentity.runtime_task_id`.

Keep `ExecRequest.capability_grant_hash` during the compatibility transition, but require equality with the header value.

The request continues to carry operation/input/output commitments directly:

```text
operation
state/artifact/memory refs
input_manifest_hash
output_contract_version
workspace/state roots as required by operation
```

### 9.2 Option B — historical full `ProtocolInvocationBinding`

A new canonical contract would freeze and hash:

```text
protocol/schema
RuntimeIdentity
step/attempt
binding/grant
operation
inputs
outputs
```

### 9.3 Decision

**Recommend Option A, with a new physical `invocation_id`; reject full Option B for Batch 2.**

Why:

1. `RuntimeIdentity`, `ExecutionBindingReceipt`, and `CapabilityGrant` already are first-class immutable authority contracts.
2. Another hash over the same fields does not add independent security in the current trusted-controller/local-UDS trust model.
3. Runtime already holds the outbound request, so exact response comparison is stronger and simpler than comparing one more derived hash.
4. The genuinely missing identity is **physical invocation identity**, because Attempt and physical RPC are not identical concepts.
5. If a later remote/untrusted provider boundary needs portable signed delegation, a compact invocation token can be introduced then with source-backed motivation.

### 9.4 Protocol version

Keep `statebus.control.v1` if changes are protobuf-additive, but make sender declaration explicit and fail closed for missing/unsupported version on the Batch 2 physical path.

Do not add semver negotiation, feature registries, or a handshake RTT.

---

## 10. Result Admission Design

### 10.1 Required invariant

```text
decoded physical response
!=
admitted physical response
!=
committed semantic Step result
```

### 10.2 Physical response admission

Add a narrow validator/receipt, not a generic binder framework.

Conceptual interface:

```text
admit_control_response(
    expected_request,
    observed_message,
    observed_sequence_state,
)
→ ControlResponseAdmissionReceipt
```

It must validate:

```text
protocol version
task_id
run_id
session_id
step_id
attempt_id
invocation_id
execution_binding_hash
capability_grant_hash
legal response event type
single terminal response
output_contract_version
operation-specific ref type/cardinality
```

Wrong or duplicate responses are rejected before dispatcher business logic consumes payload.

### 10.3 Why not `ControlResponseBinder`

The historical name suggests a new object hierarchy. Current source already has typed messages and one transport seam. A narrow admission function/receipt has the same correctness value with less surface.

### 10.4 Semantic result admission

After provider return, Runtime separately checks:

```text
session active_attempt(step) == attempt_id
grant still belongs to attempt
binding/grant expected for attempt
provider result satisfies logical output contract
attempt is not terminal/superseded
```

Only then can workflow Step state/output refs mutate.

---

## 11. Attempt Lifecycle Design

### 11.1 Minimal state machine

Do **not** introduce every proposed state.

Reuse existing lifecycle where possible:

```text
PENDING      = Attempt created
BOUND        = binding + grant frozen          [new, source-backed value]
DISPATCHED   = provider invocation submitted
ACKED        = remote worker/control ACK observed, only where applicable
RUNNING      = local invocation entered OR real worker RUN_START observed
COMPLETED
FAILED
TRAPPED
CANCELLED
```

No `SETTLED` enum is required. Settlement is a terminal action that:

```text
records terminal reason
clears active_attempt(step) if still equal
retains audit history
```

No `FENCED` lifecycle enum is required. A late event for an already terminal Attempt produces a **fencing/admission receipt**; it must not overwrite the original terminal reason.

`TIMED_OUT` does not need a new enum in Batch 2 if timeout is represented as `TRAPPED` plus explicit timeout reason. Avoid enum churn until source demonstrates a consumer that requires a separate state.

### 11.2 BOUND is justified

MRR-04 established that binding precedes grant. Today the Attempt record is effectively created at dispatch time. A `BOUND` transition makes the frozen provider/grant authority observable before physical dispatch without introducing a new Attempt object hierarchy.

---

## 12. WorkerEvent Design

### Decision: do not introduce a generic `WorkerEvent` class now.

Existing first-class control messages already represent:

```text
AckReceived
RunStart
Heartbeat
SuccessResult
ErrorResult
TrapFatal
CancelCommand
```

The missing seam is:

```text
event admission
event origin
attempt-aware mutation
```

not event typing.

### Event-origin rule

```text
protobuf subprocess message:
WORKER_OBSERVED

utf8_text converted message:
ADAPTER_DERIVED

in-process handler start:
LOCAL_RUNTIME
```

Only `WORKER_OBSERVED` can support the claim “real worker ACK/RUN_START/HEARTBEAT”.

No `LocalProviderEventAdapter` is required. Local providers simply have no ACK and may use:

```text
DISPATCHED → RUNNING
```

when entering the trusted local handler.

---

## 13. Retry / Rebind / Replan Semantics

Freeze vocabulary:

```text
TRANSPORT RETRY
same physical semantic invocation intent
same semantic Attempt
only legal when transport can prove app logic did not observe it,
or operation is explicitly idempotent.
Does not mint a new semantic Attempt.

RETRY / RE-EXECUTION
same semantic Step
new Attempt
provider may remain the same
new Grant
binding may be re-issued to the same provider.

REBIND
same semantic Step
new Attempt
different provider
new ExecutionBindingReceipt
new CapabilityGrant
ApprovedPlan unchanged.

CAPABILITY FALLBACK
same Step goal but different logical capability under explicit
pre-approved fallback policy.
Not ordinary provider rebind.

REPLAN
semantic graph changes
new PlanProposal
new policy evaluation
new ApprovedPlanBundle / replan provenance.

FAIL
terminal semantic failure.
```

### Current-source classifications

- `AdaptiveRuntimeEngine` fallback path that creates a new Attempt and may switch fallback capability is **CAPABILITY FALLBACK**, not a simple provider retry.
- Runtime replan callback is **REPLAN**.
- `result.retryable` exists in result shape but is not a complete semantic retry engine.
- LLM/code/schema repair inside a provider before a committed side effect is **INTERNAL REPAIR**, not semantic Attempt retry.
- HTTP/client library transparent retries are **TRANSPORT/PROVIDER-INTERNAL RETRY** and must not silently become semantic retry.
- logit gate “retry” is a **decision-state policy outcome** unless it actually re-executes a Step; do not name it semantic retry by default.

---

## 14. Late Result Fencing

Required invariant:

```text
Step S

Attempt A active
    ↓
A timeout/trap
    ↓ settle A
Attempt B active
    ↓
late Result(A)
    ↓
FENCE + AUDIT
    ↓
NO workflow mutation
NO Artifact/State adoption
NO overwrite of Attempt B
```

Admission order:

```text
1. parse/decode
2. physical invocation correlation (05B)
3. lookup session
4. compare active_attempt(step)
5. compare binding/grant
6. validate result contract
7. commit
```

The active-attempt comparison occurs **before** output refs can enter Session/workflow state.

---

## 15. Cancellation / Timeout

### Timeout authority

Runtime decides that an Attempt has exceeded an applicable deadline/lease.

A transport can report:

```text
TransportTimeout
ConnectionClosed
WorkerProcessExited
```

as observations.

It must not manufacture:

```text
ErrorResult
```

and pretend the worker sent it.

### Cancellation

Cancellation is best-effort physical cleanup plus immediate semantic fencing:

```text
Runtime marks Attempt CANCELLED/TRAPPED
→ clears active attempt if appropriate
→ sends CancelCommand / terminates subprocess when supported
→ any later event from the old invocation is fenced
```

Physical cancellation success is not required for semantic safety.

---

## 16. Settlement / Minimal GC

Batch 2 settlement is intentionally small.

On terminal Attempt:

```text
retain StepAttemptRecord
retain binding/grant hashes
retain terminal/fence receipts
clear active_attempt(step) only if it still points to this Attempt
release supervisor liveness bookkeeping when safe
```

Do **not** implement:

```text
distributed garbage collector
persistent worker pool
resource scheduler
orphan state reclamation
```

State resource ownership is Batch 3.

---

## 17. Compatibility Strategy

1. Preserve `task_id` field and define it as the RuntimeTaskID wire projection.
2. Add protobuf fields with new field numbers; never reuse existing field numbers.
3. Keep control package `statebus.control.v1` for additive wire change.
4. Update both `.proto` and current dynamic `schema.py`; add a focused parity test.
5. Keep `ExecRequest.capability_grant_hash` temporarily and require equality with header grant hash.
6. Preserve UTF-8 control carrier for benchmark compatibility, but label its converted lifecycle events adapter-derived.
7. Do not support old workers that omit required Batch 2 authority fields on the canonical path; fail closed rather than silently repairing them.

---

## 18. Explicit Non-goals

```text
Temporal-style durable history
Raft / consensus
distributed lock service
Kubernetes controller model
generic scheduler
persistent worker pool
resource-aware ranking
provider performance ranking
generic plugin framework
mTLS / PKI
exactly-once execution
distributed reference counting
State lifecycle implementation
Artifact truth implementation
Memory redesign
benchmark optimization
APC / Explicit KV / Latent Runtime
```

---

## 19. Alternatives Considered

### Full ProtocolInvocationBinding
Rejected now: duplicate authority with little new correctness value.

### ControlResponseBinder hierarchy
Rejected: narrow validator/receipt is enough.

### Generic WorkerEvent
Rejected: current typed control messages already provide event types.

### Supervisor owns active Attempt
Rejected: supervisor is operational/liveness state; semantic commit authority belongs to Runtime Session.

### Engine-local active Attempt dict
Rejected: non-auditable and easy to bypass through other session mutation paths.

### Exactly-once worker execution
Rejected: unnecessary and unrealistic; use fencing/idempotence.

### Generation on every StateRef now
Deferred. Prefer future one-publication-one-ref-id immutability; add generation only if mutable/reused logical IDs remain source-backed.

---

## 20. Risks / Open Questions

1. Current only integrated real subprocess is provider-internal semantic selection; do not over-claim it as universal semantic Step worker.
2. Protocol `.proto` and dynamic schema remain dual source until a later small schema-source cleanup.
3. Async late-result mechanism may require transport event streaming/callback in 06B; keep it narrowly scoped.
4. Current fallback capability semantics may need a separate future reconciliation from provider rebind.
5. Local provider exceptions occur synchronously; worker heartbeat semantics do not apply.
6. Artifact/State outputs can be physically created by an attempt before result admission; Batch 3/Artifact Truth must ensure stale attempt outputs cannot be promoted just because files exist.

---

## 21. File-Level Reconciliation Map

### KEEP

```text
statebus/contracts/identity.py
statebus/contracts/provider_binding.py
statebus/runtime/provider_registry.py
statebus/runtime/capability_registry.py
```

They are upstream authority.

### EXTEND — Batch 2

```text
statebus/control/messages.py
statebus/control/statebus_control.proto
statebus/control/schema.py
statebus/control/transport.py
statebus/control/subprocess_worker.py

statebus/runtime/adaptive_runtime.py
statebus/runtime/adaptive_dispatcher.py
statebus/runtime/session.py
statebus/runtime/supervisor.py
```

Not every file changes in every slice.

### ADD

```text
statebus/control/admission.py
```

Only if the implementation follows the recommended narrow response-admission seam.

### COMPATIBILITY BRIDGE

```text
utf8_text control carrier
legacy task_id wire spelling
ExecRequest.capability_grant_hash duplicate during migration
```

### TEST ONLY

Focused protocol, subprocess, session/supervisor and adaptive runtime tests.

### DO NOT TOUCH in Batch 2

```text
statebus/state/**
statebus/memory/**
statebus/runtime/workspace.py
statebus/runtime/replay.py
deploy/**
docker/**
scripts/**
scheduler/inference optimization areas
```

---

## 22. Target Runtime Call Chain

```text
ApprovedPlan READY Step
    ↓
RuntimeSession.activate_attempt()
    ↓
Attempt PENDING
    ↓
ProviderEligibilityProjection
    ↓
ExecutionBindingReceipt
    ↓
CapabilityGrant
    ↓
Attempt BOUND
    ↓
dispatch
    ├───────────────────────────────────────────────┐
    │ local provider                                │ physical control invocation
    │                                               │
    ↓                                               ↓
DISPATCHED                                     ControlHeader
    ↓                                          + invocation_id
LOCAL RUN START                                + run/session/attempt
    │                                          + binding/grant hashes
    │                                               ↓
    │                                          UDS / worker
    │                                               ↓
    │                                          typed event/result
    │                                               ↓
    │                                      ControlResponseAdmission
    └──────────────────────┬────────────────────────┘
                           ↓
                  Candidate Provider Result
                           ↓
                 active_attempt(step)?
                           ↓ yes
                   grant/binding valid?
                           ↓ yes
                  output contract valid?
                           ↓ yes
                     COMMIT RESULT
                           ↓
                    settle Attempt
                           ↓
                    Step COMPLETED
```

Late/stale branch:

```text
active_attempt(step) != observed_attempt
    ↓
FENCE receipt
    ↓
audit only
```

---

## 23. Batch 2 Slice DAG

```text
MRR-05A
Invocation Identity / Wire Projection
  files: control schema/messages/worker + construction seam
  proves: authority scope physically crosses UDS
        ↓
MRR-05B
Physical Response Correlation / Admission
  files: control admission + transport/dispatcher
  proves: raw response cannot reach business consumption unbound
        ↓
MRR-06A
Attempt Authority / Lifecycle Origin Truth
  files: session/supervisor/runtime
  proves: active Attempt has a semantic owner; no fake worker ACK
        ↓
MRR-06B
Late Result Fencing / Timeout-Cancel Settlement
  files: session/supervisor/runtime/transport as needed
  proves: terminal A cannot mutate active B
```

---

## 24. Gate Strategy

Every Slice has four gates:

```text
SOURCE GATE
Exact current source fact reproduced.

MECHANISM GATE
The new invariant is exercised through the real mechanism relevant to the Slice.

INTEGRATION GATE
Canonical mainline still runs the intended path.

COMPETITION GATE
The change preserves or strengthens a competition-relevant claim without inventing performance evidence.
```

Mechanism gates must never be passed by dataclass construction alone.

---

## 25. Evidence Strategy

### MRR-05A
Real UDS + subprocess exchange; inspect sent/received header scope.

### MRR-05B
Real physical round trip admitted; negative wrong invocation/grant/binding/result-type tests rejected before business use.

### MRR-06A
No semantic ACK before provider execution. Protobuf worker emits real ACK/RUN_START/HEARTBEAT on control path; local provider path has no fake ACK.

### MRR-06B
Controlled delayed worker fixture:

```text
A starts
A exceeds deadline
A settles
B becomes active
A sends late success
runtime fences A
B remains active/committable
```

No PASS without this exact behavior.

---

## 26. Competition Relationship

The contest hard requirements include:

```text
structured communication with action/input/result/capability
handshake/capability discovery/protocol mapping
non-text intermediate-state transfer
shared memory storage/retrieval/reuse
3+ agents / 3 role classes
2 related continuous-task groups
10+ continuous runs
text-vs-structured comparison
communication/time/memory-reuse metrics
openEuler 24.03-LTS-SP3
```

Batch 2 is primarily a **correctness substrate**.

Direct competition relevance:

- strengthens the structured communication/protocol claim;
- improves system completeness/stability;
- makes worker/result evidence auditable;
- prevents retries/timeouts from corrupting the 10-run stability lane.

Batch 2 does **not** itself prove:

```text
token savings
latency improvement
state-transfer innovation score
memory reuse gain
```

Those still require the competition experiments.

Do not turn Batch 2 into an engineering-cleanliness project. Every change must support a concrete runtime truth needed by the executable prototype or its evidence.

---

## 27. Batch 3 Readiness

State Lifecycle depends on Batch 2 because state access and publication must be scoped to a still-authorized Attempt.

Future authority model:

```text
Committed/Published StateRef
        ↓
wire-bound immutable ref identity
        ↓
StateAccessGrant or equivalent access witness
        ↓
Bound CapabilityGrant / Attempt
        ↓
Consumer
```

### Future decisions pre-frozen

**BoundRefHandle:** do not introduce the name automatically. First try extending current `RefHandle` with immutable content/access commitments.

**generation:** not required if Batch 3 enforces one-publication-one-ref-id and rejects ref-id reuse. Add generation only if mutable/reused logical IDs are intentionally retained.

**StateAccessGrant:** likely necessary because knowing `ref_id` currently equals access. It should be attempt/grant/consumer scoped, but exact object shape is Batch 3 work.

**pin/unpin:** use a small Runtime-local owner/consumer reference model; do not copy Ray distributed reference counting.

**release idempotence:** required. Logical release should be repeat-safe even if physical unlink is one-shot.

### Readiness status

```text
NOW:
MRR-07 NOT READY TO IMPLEMENT.

AFTER MRR-06B PASSES:
MRR-07 READY.
```
