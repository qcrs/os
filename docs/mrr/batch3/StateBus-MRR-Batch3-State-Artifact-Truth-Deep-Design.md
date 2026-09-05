# StateBus MRR Batch 3 — State / Artifact Truth Deep Design

> Source of Truth: `https://github.com/qcrs/os`  
> Branch: `feat/mrr-06b-late-result-fencing-settlement`  
> Phase: **Batch 3 Design Freeze / Research & Review only**  
> 本包不包含源码实现、不包含 benchmark、不包含正式测试执行。  
> Frozen prerequisite: **Batch 1 CLOSED + Batch 2 CLOSED / BATCH_2_GATE_PASS**.


## 1. Batch 3 invariant model

Batch 3 freezes three planes that must never again be conflated.

### Identity Plane

Question:

> Which object is this?

State identity consists of immutable publication facts such as:

```text
ref_id
ref_kind
storage_kind
blob_hash
length
representation/schema
manifest/contract identity
```

Identity does not grant permission.

### Authority Plane

Question:

> Who may perform which operation, under which Runtime execution?

Authority derives from:

```text
RuntimeIdentity
Attempt
ExecutionBindingReceipt
CapabilityGrant
```

For State READ, this is projected into a derived State access witness.

### Lifetime Plane

Question:

> What keeps this physical object alive, and when may Runtime reclaim it?

Lifetime is controlled by:

```text
publication owner
live consumer pins
logical owner release
consumer unpin/cleanup
physical reclaim
```

A ref ID is none of these lifetime facts.

---

# 2. Current State truth chain

```text
Producer / Runtime Dispatcher
        ↓
mint state_id
        ↓
publish_dense_semantic_state / publish_logit_state
        ↓
LayeredStateStore.publish(ref_id, payload)
        ↓
MaterializedStateHandle
        ├─ SharedMemory name
        ├─ memfd fd
        ├─ mmap path
        └─ inline bytes
        ↓
sidecar under state_root/metadata
        ↓
SemanticStateRef / LogitStateRef
        ↓
RefHandle(ref_id, ref_kind)
        ↓
ExecRequest + state_root
        ↓
Worker
        ↓
*_ref_from_sidecar(state_root, ref_id)
        ↓
resolve_*(...)
        ↓
physical state
```

### Existing checks

```text
Identity:
YES

Integrity:
YES

Representation/schema validity:
YES

Lease/liveness:
YES for semantic/logit State

Caller access authorization:
NO

Owner/consumer pin:
NO

Idempotent logical release:
NO
```

---

# 3. MRR-07A frozen design

## 3.1 Single invariant

> **Knowing a valid StateRef identity is not sufficient authority to acquire State.**

07A solves only:

```text
immutable publication identity
+
derived access authorization
+
canonical worker enforcement
```

It does not implement consumer lifetime/pinning.

---

## 3.2 Immutable publication identity

Freeze:

```text
REF_REUSE_FORBIDDEN
```

Canonical `LayeredStateStore.publish()` must reject a `ref_id` already registered/materialized.

Do not add `generation`.

Reason:

1. current state IDs are naturally execution/publication-specific;
2. no current requirement needs a logical StateRef to be rebound;
3. generation would preserve a mutable-name abstraction that StateBus does not need;
4. POSIX shared-memory semantics show why name reuse is dangerous: old mappings may remain alive while the same name is later bound to a new distinct object.

If the future needs mutable names, introduce a separate alias/catalog pointer:

```text
logical alias
→ immutable StateRef
```

Do not mutate publication identity.

---

## 3.3 State identity hash

07A should define one canonical immutable State identity digest from already-known publication facts, for example:

```text
StateIdentityHash =
H(
  ref_id,
  ref_kind,
  storage_kind,
  blob_hash,
  length,
  representation/schema identity,
  manifest/contract hash where applicable
)
```

This hash answers **which exact publication**, not who may use it.

---

## 3.4 Why CapabilityGrant.input_ref_ids is necessary but insufficient

`CapabilityGrant.input_ref_ids` is already the correct semantic allowlist for upstream inputs.

For an existing State input:

```text
ref_id ∈ CapabilityGrant.input_ref_ids
```

must remain a precondition.

However current semantic-state physical path mints an intermediate State *during* execution after the Grant has been issued.

Mutating the hashed CapabilityGrant is forbidden.

Therefore 07A needs two allowed authority bases:

```text
CAPABILITY_INPUT
    ref already authorized by grant.input_ref_ids

RUNTIME_INTERMEDIATE
    Runtime creates/registers a new intermediate State
    inside the same active BoundCapabilityGrant
```

Both bases derive from the same Attempt/Binding/Grant. The second is not a provider-owned authority extension.

### 3.4.1 `RUNTIME_INTERMEDIATE` is not a general Runtime expansion privilege

Freeze the narrower rule:

```text
RUNTIME_INTERMEDIATE is allowed only when:

session.active_attempt(step) == attempt_id

AND

the publication is created through the Runtime-owned publication boundary

AND

the ref kind / State kind is permitted by the already-authorized
capability output contract or current execution contract

AND

ExecutionBinding / CapabilityGrant / provider scope still matches
the current execution

AND

the immutable publication is registered successfully
before any derived READ witness is minted
```

Therefore:

```text
active BoundCapabilityGrant
!=
authority to mint arbitrary State kinds
```

A Provider may return candidate bytes or an allowed candidate State payload,
but it cannot enlarge the logical capability by choosing an arbitrary new State
kind. Runtime registration remains constrained by the already-authorized
capability/output contract.

---

## 3.5 StateAccessGrant: derived witness, not new authority

Recommended contract name:

```text
StateAccessGrant
```

Semantic classification:

```text
DERIVED AUTHORIZATION WITNESS
NOT ROOT AUTHORITY
```

Minimum fields to freeze:

```text
access_grant_id

runtime_task_id
run_id
session_id
step_id
attempt_id

execution_binding_hash
capability_grant_hash

ref_id
ref_kind
state_identity_hash

access_mode
authority_basis

consumer_provider_id
consumer_role
physical_invocation_id   # required on cross-process path

expires_at_ns
schema_version
```

`expires_at_ns` must be bounded by:

```text
min(
  CapabilityGrant.expires_at_ns,
  State lease expiry if the State has one
)
```

### Access modes in 07A

Canonical StateAccessGrant should initially authorize:

```text
READ
```

Do not overload the READ witness to mean owner release or pin.

#### PUBLISH

PUBLISH is creation of a new authoritative State publication, not access to an existing object.

Freeze the rule:

```text
Provider may produce bytes.
Runtime-owned publication boundary mints/registers immutable ref identity
only while the BoundCapabilityGrant's Attempt is active.
```

No independent State-owned execution authority.

#### RELEASE / PIN / UNPIN

Defined by 07B Lifetime Plane, not by 07A READ authority.

---

## 3.6 RefHandle remains identity-only

Reject a new `BoundRefHandle`.

Current:

```text
RefHandle(ref_id, ref_kind)
```

is a useful identity projection.

Target physical request should carry:

```text
state_refs: RefHandle[]
state_access_grants: StateAccessGrant[]
```

or an equivalent repeated access-witness envelope keyed by `ref_id`.

This preserves:

```text
RefHandle = Identity Plane
StateAccessGrant = Authority Plane
```

and avoids a “fat ref” that silently mixes lifetime/security semantics.

---

## 3.7 Runtime-side issuance

Runtime may derive StateAccessGrant only if all are true:

```text
session.active_attempt(step) == attempt_id

BoundCapabilityGrant:
  task/session/step/attempt match

ExecutionBinding:
  selected provider == actual provider

State identity:
  immutable publication exists
  identity hash matches

authority basis:
  CAPABILITY_INPUT
  OR registered RUNTIME_INTERMEDIATE

consumer:
  matches bound provider / role

expiry:
  still live
```

A stale Attempt cannot receive a new StateAccessGrant.

---

## 3.8 Worker-side enforcement

Worker-side enforcement is required on the canonical cross-process path.

Before:

```text
semantic_ref_from_sidecar(...)
resolve_dense_semantic_state(...)
resolve_logit_state(...)
```

the worker/State resolver boundary must verify:

```text
StateAccessGrant exists
ref_id/ref_kind match
state_identity_hash matches sidecar/publication
task/run/session/step/attempt match ControlHeader
binding hash matches ControlHeader
grant hash matches ControlHeader
physical invocation id matches ControlHeader
consumer/provider scope matches
access mode includes READ
expiry valid
```

Only then may sidecar/SHM/mmap/memfd acquisition occur.

This is **correctness enforcement inside trusted StateBus worker code**, not a claim of hostile-process isolation. A malicious native process with OS permissions could bypass Python APIs; that is outside Batch 3 competition scope.

### 3.8.1 Canonical State access boundary applies to local and cross-process consumers

07A is not only a wire-path hardening exercise.

Freeze:

```text
All canonical State consumers must enter acquisition through
the same StateAccessGrant admission semantics, including:

- local / in-process provider
- subprocess worker
- provider-internal semantic-state worker
```

`LayeredStateStore.load/get` and low-level `resolve_*` helpers remain
materialization primitives. They are **not** business-level access-authority
APIs.

Canonical Runtime/provider business paths must not bypass authorization by
calling:

```text
store.load(ref_id)
store.get(ref_id)
resolve_*(state_root, ref)
```

directly from a consumer execution path without a valid derived access witness.

This closes the otherwise-invalid split:

```text
cross-process consumer:
Ref + StateAccessGrant -> checked

local consumer:
ref_id -> get()/resolve() -> unchecked
```

The implementation may use one shared admission helper or equivalent narrow
boundary; it must not build separate local and remote authority systems.

---

## 3.9 Stale Attempt semantics

Freeze operation matrix:

| Operation | Active Attempt | Settled/stale Attempt | Why |
|---|---|---|---|
| acquire new READ witness | allow if Grant/Binding/ref valid | **deny** | new authority |
| reuse witness under different invocation | deny | deny | invocation-scoped |
| publish authoritative State | allow under active BoundGrant | **deny** | new semantic state |
| acquire new PIN | 07B allow if access valid | **deny** | extends lifetime |
| UNPIN own prior pin | allow | **allow** | cleanup only |
| owner logical release | Runtime owner only | Runtime cleanup may allow | reduces lifetime |
| physical reclaim | Store/lifetime manager only | same | not caller authority |

Important:

> An already-running A invocation that acquired its access witness while A was active is not required to lose an already-open mapping mid-operation.

This is consistent with Batch 2: physical work may outlive semantic settlement; its output is fenced.

### 3.9.1 Settlement revokes new authority, not already-dispatched physical work

Freeze the exact revocation semantics:

```text
Attempt settlement revokes:

- minting a new StateAccessGrant
- starting a new authorized State acquisition
- acquiring a new StatePin
- authoritative State publication
```

It does **not** retroactively revoke a `StateAccessGrant` that was validly
derived and bound to an already-dispatched physical invocation while the
Attempt was active.

Therefore an already-dispatched invocation may finish its physical read/work
using an already-acquired mapping or already-bound witness.

Its eventual result is still governed by Batch 2:

```text
physical work may finish
        ↓
physical result may correlate/admit
        ↓
active-Attempt admission
        ↓
stale result -> FENCED_STALE_ATTEMPT
        ↓
NEVER COMMIT
```

07A must not introduce:

```text
remote mapping revocation
worker-side active-Attempt registry
revocation daemon
new cancellation protocol
```

merely to revoke an already-issued witness mid-flight.

---

# 4. MRR-07B frozen design

## 4.1 Single invariant

> **A physical State object cannot be reclaimed while an authorized live consumer still depends on it, and logical release is safe/idempotent.**

---

## 4.2 Minimal ownership model

Do not implement Ray distributed reference counting.

StateBus needs one Runtime-local lifetime registry.

For each immutable ref:

```text
StateLifetimeRecord
  ref_id
  owner_session_id
  producer_step_id
  producer_attempt_id
  owner_released: bool
  live_pins: map[pin_id -> StatePin]
  physical_reclaimed: bool
```

This may be an internal store structure; it does not need to become a large distributed protocol.

### Publication owner

The semantic owner should be Runtime/session scope, with producer Attempt recorded as provenance.

Reason:

- a State produced by Step A may intentionally be consumed by downstream Step B after producer Attempt A has completed;
- therefore producer Attempt settlement cannot universally destroy the publication.

For strictly invocation-local intermediate State, Runtime may declare an explicit attempt-local lifetime scope and owner-release it when that invocation/Attempt ends.

Do not infer attempt-local from ref naming.

---

## 4.3 Consumer pin

Pin acquisition:

```text
valid StateAccessGrant(READ)
+
active Attempt at acquisition
→ new pin_id
```

Pin binds:

```text
ref_id
session_id
step_id
attempt_id
consumer/provider
access_grant_id/hash
acquired_at_ns
```

Multiple pins are allowed.

Pin is a Lifetime Plane dependency, not State authority by itself.

---

## 4.4 Logical owner release

Replace the semantic meaning of public `release(ref_id)` with a logical owner release:

```text
owner_released = True
```

It must be idempotent.

No physical unlink occurs while any live pin exists.

---

## 4.5 UNPIN

`unpin(pin_id)`:

- idempotent;
- allowed to clean up an already-existing pin even if its Attempt later becomes stale;
- cannot create or transfer new authority;
- may trigger physical reclaim if owner is already released and this was the final pin.

---

## 4.6 Physical reclaim condition

Freeze:

```text
physical_reclaim_allowed(ref)
=
owner_released(ref)
AND
live_pin_count(ref) == 0
AND
not already_reclaimed(ref)
```

Backend action then remains existing behavior:

```text
SharedMemory:
close Runtime handle
unlink once

memfd:
close Runtime-owned FD after consumer FD dependencies gone

mmap:
unlink file after no StateBus pin depends on reopening/mapping it

inline:
drop bytes
```

Do not rely on OS delayed-destruction semantics as the application pin model.

---

## 4.7 Attempt settlement

Attempt settlement must:

```text
revoke ability to mint new access grants for A
revoke ability to acquire new pins for A
release/unpin A-owned live consumer pins
```

It must **not** blindly unlink every State produced by A.

Publication owner release is separate.

This gives:

```text
Attempt settle
!=
State physical unlink
```

---

# 5. MRR-08 frozen design

## 5.1 Single invariant

> **Only an active, admitted producer Attempt may cause Runtime to promote candidate artifact bytes into verified Artifact truth. Verification must not automatically imply replay eligibility, Memory admission, or final adoption.**

---

## 5.2 Artifact truth dimensions

Do not create one giant Artifact enum.

Keep independent decisions:

### Production identity

```text
artifact_id
task/session
producer step
producer Attempt
grant/binding provenance
blob hash
size/path/manifest
```

### Verification

```text
CANDIDATE
VERIFIED
INVALIDATED
```

### Replay eligibility

Separate Runtime decision:

```text
NOT_EVALUATED
ELIGIBLE
INELIGIBLE
```

or an explicit ReplayEligibilityReceipt.

### Memory admission

Owned by Memory commit gate.

### Existing `ExecutionArtifactRef` compatibility projection

Current `ExecutionArtifactRef` already exposes legacy fields similar to:

```text
verification_state
replay_ready
```

Freeze:

```text
These are compatibility projections.
They are NOT independent Artifact authority sources.
```

Provider-created candidate artifacts must begin as:

```text
verification_state = CANDIDATE
replay_ready = False
```

Only Runtime-owned verification and replay-eligibility decisions may later
justify authoritative projection of VERIFIED / replay-ready state onto those
legacy fields.

A future verification receipt and the legacy ref fields must never become two
competing truths.

### Final adoption

Owned by Runtime/task outcome, not ArtifactLifecycleManager.

---

## 5.3 Provider boundary

Provider/dispatcher may:

```text
write candidate bytes
compute candidate blob hash
produce validator / quality evidence
return candidate ref in AdaptiveStepResult
```

Provider must not authoritatively:

```text
mark Artifact VERIFIED
set replay_ready
commit Memory
final-adopt result
```

---

## 5.4 Runtime promotion seam

Target:

```text
provider candidate result
        ↓
physical/local result admission
        ↓
active-Attempt admission
        ↓
candidate identity/hash/path validation
        ↓
validator/quality evidence validation
        ↓
Runtime artifact verification promotion
        ↓
independent replay eligibility decision
        ↓
optional Memory admission
        ↓
optional final adoption
```

A stale A may leave candidate bytes in its attempt workspace for audit/cleanup, but they never become Verified truth.

---

## 5.5 Artifact dependencies across Attempts

A consumer Step B does **not** require producer Attempt A to equal B's Attempt.

Instead:

```text
artifact_id ∈ B.CapabilityGrant.input_ref_ids
AND
artifact was VERIFIED by Runtime
AND
artifact producer Attempt had committed authority at verification
AND
task/session provenance compatible
```

This is why simply checking `metadata.attempt_id == current_grant.attempt_id` would be wrong.

---

## 5.6 Replay and Memory

Freeze:

```text
Verified Artifact
does not imply Replay Eligible
```

Memory admission requires at least verified Artifact truth.

Replay Memory additionally requires explicit replay eligibility + compatibility/recipe checks.

Assist memory may be admitted from a verified Artifact without becoming executable replay, if Memory policy allows.

---

# 6. Cross-plane invariants

```text
StateRef identity
!= StateAccessGrant
!= StatePin

Artifact Candidate
!= Runtime Verified Artifact

Verified Artifact
!= Replay Eligible Artifact

Replay Eligible Artifact
!= Memory Commit

Memory Commit
!= current-task Final Adoption
```

---

# 7. Rejected architectures

## Generation by default

Rejected because immutable publication IDs solve the current problem more simply.

## BoundRefHandle

Rejected because it mixes Identity and Authority planes.

## State-owned active Attempt

Rejected because RuntimeTaskSession already owns it.

## Worker consults its own State attempt registry

Rejected because that creates a second freshness truth.

## Immediate revocation of already-open mappings on Attempt settle

Rejected as unnecessary and inconsistent with Batch 2's physically-late-work model.

## Distributed reference counting

Rejected because current Runtime is bounded/local and does not need cluster-wide object reachability.

## Provider-side Artifact verification

Rejected because it precedes Runtime active-Attempt commit authority.
