# MRR-09A Slice Spec — Memory Admission Truth

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


## Status

```text
READY_FOR_IMPLEMENTATION_AFTER_EXPLICIT_AUTHORIZATION
```

## Invariant

> **A Memory entry becomes canonical long-lived Memory only when Runtime admits the exact `MemoryCommit` from matching MRR-08 Verified Artifact truth under a defined Memory admission policy.**

## Current source gap

The canonical adaptive mainline verifies a matching `ArtifactVerificationReceipt` before `MemoryIndexStore.commit_candidate()`, but the persisted Memory authority later collapses to:

```text
commit_status=COMMITTED
validation_status=PASSED
```

The persistent commit does not carry an immutable Memory admission witness binding it to the MRR-08 receipt/provenance. `put_commit()` is also a raw persistence primitive.

## Frozen design

Introduce:

```text
MemoryAdmissionReceipt
```

Required authoritative binding:

```text
memory_id
memory_commit_hash
memory_type
source artifact ID/hash
ArtifactVerificationReceipt hash
admission policy ID/version
admitted_at
schema version
```

Do not copy the entire producer Runtime authority into a second receipt.
Producer task/run/session/Step/Attempt, Binding/Grant, validator evidence,
capability/version, recipe and output-contract provenance remain linked through
the exact upstream `ArtifactVerificationReceipt` and `MemoryCommit`.

Existing projections may remain in Memory metadata for query/audit, but they
are not independent admission authority.

Canonical persistent Memory:

```text
MemoryCommit + matching MemoryAdmissionReceipt
```

Neither alone is sufficient.

## Admission policy v1

Only current real canonical producer:

```text
Runtime-verified executor Artifact
→ strategy/procedure Memory
```

Require:
- matching ArtifactVerificationReceipt;
- Artifact bytes/hash match at admission;
- matching quality/validator evidence;
- recipe for procedure-capable Memory;
- current Runtime Memory policy allows admission;
- no benchmark-gold admission.

Do not invent writer paths for unused MemoryType enum categories.

## Memory identity

```text
same memory_id + same memory_commit_hash → idempotent
same memory_id + different memory_commit_hash → reject
```

No generation.

## Likely production files

```text
statebus/memory/models.py
statebus/memory/store.py
statebus/contracts/*memory*
statebus/contracts/__init__.py
statebus/runtime/adaptive_mainline.py
statebus/runtime/memory_admission.py  # optional
```

## Explicit non-goals

```text
ReplayEligibilityReceipt
Memory query placement
role-specific Memory query
procedure execution
exact Artifact replay
distributed persistence
cache eviction
vector index redesign
```

## Test blueprint

Primary <= 3:
1. receipt-backed admission + persistent reload;
2. missing/mismatched ArtifactVerificationReceipt rejected;
3. immutable memory_id / idempotent same-commit persist.

Adjacent:
- one MRR-08 adaptive Memory receipt-gate regression.

## Implementation discipline

When implementation is explicitly authorized:

```text
NO SHA / HISTORY AUDIT
NO DEFENSIVE FALLBACK
NO OVERPROGRAMMING
NO FULL-SUITE TESTING
NO MRR-09B WORK
```

Testing limit:

```text
<= 3 primary targeted test functions
+ at most 1 directly adjacent regression
```

Do not run Docker, vLLM, benchmarks, coverage, whole-repo lint/mypy or broad
pytest unless a later Gate explicitly requires it.

User owns Git commit/push/branch operations. After required tests and
`git diff --check`, STOP and request `MRR-09A_GATE_REVIEW`.

## Gates

```text
SOURCE_GATE:
current stored COMMITTED state is insufficient durable authority.

MECHANISM_GATE:
MemoryAdmissionReceipt is the only canonical admission witness.

INTEGRATION_GATE:
Verified Artifact → admitted Memory → reload → receipt hash linkage intact.

COMPETITION_GATE:
Memory unit persists required ID/source/time/theme/summary metadata.
Performance remains UNVALIDATED.
```

## PASS

```text
No canonical lookup can treat an unreceipted MemoryCommit as admitted truth.
```

## Next

```text
MRR-09A_GATE_REVIEW
```

Only after Gate PASS:

```text
MRR-09B-Replay-Eligibility-Current-Grant-Authority
```
