# StateBus MRR-09 — Memory / Replay Deep Design

> Project: StateBus Mainline Runtime Reconciliation
> Phase: Batch 4 / MRR-09 — Memory / Replay
> Mode: DESIGN ONLY / READ ONLY
> Design input: Batch 3 closed truth + current MRR-09 source reconciliation.
> No SHA/history identity is used as design evidence.
> No source/test modification, no test execution, no benchmark.

Frozen prerequisites:

```text
Batch 1 = CLOSED
Batch 2 = CLOSED
Batch 3 = CLOSED
MRR-07 = CLOSED
MRR-08 = CLOSED

State Identity / Authority / Lifetime = FROZEN
Artifact Candidate / Runtime Verification Truth = FROZEN
```


## 1. Goal

MRR-09 extends frozen Runtime authority into reusable historical Memory without creating a second semantic authority.

```text
Historical producer truth
+
Current consumer authority
=
safe cross-task Memory reuse
```

Never:

```text
Memory owns Attempt
Memory lookup owns Step
Replay resurrects producer Attempt
Cache hit commits workflow
```

---

## 2. Matrix C — Truth Dimensions

| Truth | Meaning | Authority owner | Required predecessor | Does NOT imply |
|---|---|---|---|---|
| Verified Artifact | producer candidate became Runtime-verified truth | MRR-08 Runtime authority | active producer Attempt + admitted result + candidate/evidence validation | Memory admitted, replay eligible, final adopted |
| Memory Admitted | exact Memory record accepted into persistent shared Memory under policy | Runtime Memory admission authority | matching ArtifactVerificationReceipt | replay eligibility, visibility, commit |
| Replay Eligible | admitted Memory is procedure-reusable for current Attempt/context | Runtime replay-eligibility authority | Memory admission + current active Attempt + current Grant + compatibility | result commit, final adoption |
| Memory/Replay Consumed | current consumer actually uses assist/procedure Memory | current consumer Attempt/capability | current Grant Memory authority; eligibility receipt for procedure reuse | semantic commit |
| Current Result Committed | current result accepted into workflow | existing active-Attempt authority | current result | final task adoption |
| Final Adopted | current Runtime chooses final workflow/task output | Runtime workflow authority | committed workflow truth | historical producer authority |

---

## 3. MemoryAdmissionReceipt = REQUIRED

### Why

Current `MemoryCommit` and `COMMITTED/PASSED` fields are persistent status, but do not form immutable evidence of:
- which Runtime admitted the entry;
- which exact MRR-08 ArtifactVerificationReceipt justified it;
- which policy admitted it.

`put_commit()` also remains a raw persistence primitive.

### Semantics

`MemoryAdmissionReceipt` states only:

> Runtime admitted this exact `MemoryCommit` into this Memory class/store under this policy.

Recommended **minimum authoritative fields**:

```text
memory_id
memory_commit_hash
memory_type

source_artifact_id
source_artifact_blob_hash
artifact_verification_receipt_hash

admission_policy_id
admission_policy_version
admitted_at_ns
schema_version
```

The receipt should **link** to upstream MRR-08 truth rather than copy every
producer field into a second persistent authority object. Producer
task/run/session/Step/Attempt, Binding/Grant, validator evidence, capability
version, recipe and output-contract provenance remain available through the
matching `ArtifactVerificationReceipt` and the exact `MemoryCommit`.

They may be projected into Memory metadata for diagnostics/querying when the
current source already needs them, but duplicated projections are not
independent admission predicates.

If the current store exposes a stable logical store/namespace identity, the
receipt may also bind that existing scope. Do not invent a new distributed
store identity solely for MRR-09A.

Canonical persistent truth:

```text
MemoryCommit
+
matching MemoryAdmissionReceipt
```

### Identity rule

```text
same memory_id + same memory_commit_hash
→ idempotent persist allowed

same memory_id + different memory_commit_hash
→ reject
```

No generation.

---

## 4. Memory lookup = identity candidate only

Freeze:

```text
Memory lookup hit
=
IDENTITY CANDIDATE ONLY
```

It may mean:
- candidate Memory identity;
- retrieval score/rank;
- non-authoritative compatibility hints.

It may not:
- authorize Memory visibility;
- authorize replay;
- mutate workflow;
- skip execution.

---

## 5. Current CapabilityGrant must remain authority owner

### Reject

```text
Memory lookup hit → authority
ReplayEligibilityReceipt → access authority
Memory-owned AccessGrant
```

### Do not overload semantic `input_ref_ids`

Current `input_ref_ids` represent ApprovedPlan semantic data edges. Runtime-discovered Memory should not silently change the frozen semantic graph.

### Recommended additive projection

Keep `CapabilityGrant` as the sole current capability authority, with a Runtime-only supplemental field such as:

```text
CapabilityGrant.memory_ref_ids
```

Semantics:
- Planner cannot populate it;
- Runtime selects it only from valid admitted Memory;
- selected Memory must be permitted by the current Memory policy/capability;
- field participates in Grant hash;
- it is current Step/Attempt authority, not historical producer authority.

This is not a second authority system.

### Grant mint ordering — freeze before implementation

The current source gap exists because Memory selection happens after Grant
issuance. MRR-09B must not fix this by mutating an already-issued immutable
Grant.

Freeze the intended order:

```text
active Attempt
    ↓
logical capability / provider eligibility
    ↓
ExecutionBindingReceipt
    ↓
Memory lookup candidates             # identity/ranking only
    ↓
validate MemoryAdmissionReceipt
+ current capability/policy compatibility
    ↓
Runtime selects authorized memory_ref_ids
    ↓
mint immutable CapabilityGrant(memory_ref_ids=...)
    ↓
if procedure reuse:
    ReplayEligibilityReceipt bound to this exact Grant
    ↓
dispatch / consume
```

For `ASSIST_CONTEXT`, the Memory IDs still require current Grant authority but
do not require `ReplayEligibilityReceipt`.

No post-hoc mutation of `CapabilityGrant` is allowed.

---

## 6. ReplayEligibilityReceipt = REQUIRED

Current `MemoryCompatibilityDecision` lacks full current execution binding:
- run/session/Step/Attempt;
- BoundCapabilityGrant;
- provider binding;
- capability version.

It also relies on legacy `replay_ready`.

Therefore procedure replay needs current-context immutable Runtime evidence.

### Semantics

> This exact admitted Memory is eligible for verified procedure reuse by this exact current consumer Attempt under this exact current Grant/context.

Minimum authoritative fields:

```text
memory_id
memory_admission_receipt_hash

consumer_runtime_task_id
consumer_run_id
consumer_session_id
consumer_step_id
consumer_attempt_id

consumer_execution_binding_hash
consumer_capability_grant_hash

reuse_mode
current_task_contract_hash
current_input_schema_digest
current_runtime_signature_hash
current_validator_digest
current_output_contract_version
execution_recipe_hash

decision
reason
policy_version
issued_at_ns
schema_version
```

Capability ID/version are validated from the bound current
`ExecutionBindingReceipt` / `CapabilityGrant`; they need not be duplicated as
independent receipt authority fields unless the existing contract requires a
projection for audit.

`current_input_lineage_hashes` are **not a required compatibility field for
`VERIFIED_PROCEDURE_REUSE`**. The procedure intentionally reruns on current
inputs. Current lineage may be retained as optional audit context, but it must
not be compared to historical lineage as an eligibility predicate. Exact
lineage equality belongs only to future true exact Artifact replay.

Canonical MRR-09 v1 replay mode:

```text
VERIFIED_PROCEDURE_REUSE
```

Assist context is not replay and does not require a ReplayEligibilityReceipt.

---

## 7. Compatibility dimensions for procedure reuse

Do not add a generic policy DSL.

Use only current source-backed dimensions:

```text
MemoryAdmissionReceipt valid
producer/current capability semantic identity compatible
execution kind compatible
recipe hash valid
task family
intent
required outputs
required tools / argument shape where represented
output contract
input schema
Runtime compatibility signature
validator digest
```

Exact input lineage is intentionally NOT required for procedure reuse because the historical recipe reruns on current inputs.

Exact lineage belongs to future true exact Artifact replay.

---

## 8. Exact replay vs procedure reuse

### Canonical MRR-09

```text
ASSIST_CONTEXT
historical Memory → current input/context → current execution

VERIFIED_PROCEDURE_REUSE
historical verified recipe → CURRENT input → current execution/validator
```

### Adaptive `EXACT_REPLAY`

Current adaptive “exact” still re-executes the recipe, so it is not truthful exact Artifact replay.

### Strict/history replay

`runtime/replay.py` is closer to exact Artifact reuse, but is a separate legacy policy and still depends on `replay_ready`.

Decision:

```text
EXACT_ARTIFACT_REPLAY
=
DEFERRED ADVANCED OPTIMIZATION
NOT REQUIRED FOR MRR-09 CLOSURE
```

Any future exact path must create current consumer authority and never reactivate historical Attempt A.

---

## 9. ReplayAdmissionReceipt = NOT_REQUIRED

Procedure reuse already returns a normal current `AdaptiveStepResult`.

Existing Batch 2 authority remains:

```text
current Attempt B
→ current result B
→ RuntimeSessionManager.admit_attempt_result(B)
→ COMMIT or FENCE
```

A new Replay-specific commit receipt would duplicate semantic authority.

Audit provenance should use:

```text
MemoryAdmissionReceipt
ReplayEligibilityReceipt
MemoryConsumptionRecord / ledger projection
existing AttemptResultAdmissionReceipt
```

---

## 10. `ExecutionArtifactRef.replay_ready`

```text
COMPATIBILITY PROJECTION / REMOVE LATER
```

MRR-08 already proves Verified != Replay Eligible.

Canonical MRR-09 eligibility must not use `replay_ready` as authority.

---

## 11. Cross-task/session reuse

Correct provenance model:

```text
Historical producer:
Task A / Session A / Step X / Attempt A1
        ↓
ArtifactVerificationReceipt A
        ↓
MemoryAdmissionReceipt M

Current consumer:
Task B / Session B / Step Y / Attempt B3
        ↓
current CapabilityGrant B
        ↓
ReplayEligibilityReceipt B
        ↓
B consumes/recomputes historical procedure
```

Never:

```text
Attempt A1 becomes active again
```

---

## 12. Failure/stale semantics

### B becomes stale before result

```text
Memory remains admitted
B eligibility cannot authorize C
late B result → FENCED_STALE_ATTEMPT
no workflow mutation
no Artifact promotion
no final adoption
```

### Current context changes

New Attempt/Grant/context requires a new eligibility decision. No revocation daemon.

### Missing historical Artifact file

```text
ASSIST_CONTEXT:
may remain usable if admitted Memory payload itself is intact

VERIFIED_PROCEDURE_REUSE:
may remain usable if admitted recipe is intact and current execution revalidates

EXACT_ARTIFACT_REPLAY:
must fail closed
```

### Recipe hash mismatch

```text
procedure replay → INELIGIBLE
assist may remain available if current policy allows
```

### MemoryCommit/AdmissionReceipt mismatch

```text
reject all canonical use
```

---

## 13. Memory lifetime != State lifetime

Freeze:

```text
Memory logical retention != StatePin
```

`semantic_state_ref_id` is provenance-only for MRR-09.

No persistent Memory entry keeps Runtime-local State alive.

---

## 14. Matrix D — Memory Classes

| Memory class | Exact replay? | Assist/context reuse? | Cross-task? | Required authority/provenance |
|---|---:|---:|---:|---|
| `STRATEGY` | no | yes | yes with shared store root | MemoryAdmissionReceipt + current Grant Memory authority |
| `VALIDATED_REPLAY` | current adaptive semantics = procedure reuse | yes/fallback | yes | admission receipt + current Grant Memory authority + ReplayEligibilityReceipt |
| `EXACT_REPLAY` | legacy label / strict history surface | may downgrade | possible legacy | not canonical MRR-09 authority |
| other enum classes | not proven by inspected canonical writer | potentially | not frozen | no new MRR-09 semantics assigned |

MRR-09 intentionally does not redesign the full Memory taxonomy.

---

## 15. Competition relevance

MRR-09 A/B/C creates a truthful path for:

```text
Task N
→ verified Artifact
→ Memory Admission
→ persistent shared Memory

Task N+K / later Agent
→ keyword/tag/semantic lookup
→ candidate retrieval
→ current Runtime authorization
→ assist or verified procedure reuse
→ current validation/commit
```

This is directly relevant to the competition shared-memory hard requirement.

Still required later:
- 2 related task groups;
- 10-round stability;
- Memory hit rate;
- latency/token/work-skip evidence.

Therefore:

```text
COMPETITION_GATE = UNVALIDATED
```

---

## 16. Rejected overdesign

```text
distributed vector DB
global Memory service
Ray-style distributed refcount
cluster cache coherency
cross-cluster lease
generic cache-key DSL
Memory-owned Attempt
Replay-owned Session
Memory-owned workflow commit
Memory lookup as access authority
ReplayEligibilityReceipt as access grant
StatePin as Memory retention
```
