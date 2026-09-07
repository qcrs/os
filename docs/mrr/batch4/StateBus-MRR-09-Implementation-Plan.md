# StateBus MRR-09 — Implementation Plan

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


## Design verdict

```text
MRR-09_DESIGN_READY
```

Dependency DAG:

```text
MRR-09A
Memory Admission Truth
        ↓
MRR-09A Gate Review
        ↓
MRR-09B
Replay Eligibility + Current Grant Memory Authority
        ↓
MRR-09B Gate Review
        ↓
MRR-09C
Canonical Memory Consumption + Current Attempt Commit
        ↓
MRR-09C Gate Review
        ↓
Batch 4 Gate Review
```

---

## MRR-09A — Memory Admission Truth

### Invariant

> A persistent Memory entry is canonical only when Runtime admits the exact `MemoryCommit` from matching MRR-08 Verified Artifact truth under a defined Memory admission policy.

### Likely production files

```text
statebus/memory/models.py
statebus/memory/store.py
statebus/contracts/*memory*
statebus/contracts/__init__.py
statebus/runtime/adaptive_mainline.py
statebus/runtime/memory_admission.py   # optional narrow authority module
```

### Explicit non-goals

```text
Replay eligibility
Memory query redesign
role-specific query service
exact replay
vector DB replacement
distributed invalidation
```

### Primary tests

```text
09A-T1 receipt-backed admission + persistent reload
09A-T2 missing/mismatched ArtifactVerificationReceipt rejected
09A-T3 immutable memory_id: same hash idempotent, different hash rejected
```

Adjacent:
- one MRR-08 adaptive Memory-gate regression.

### Gates

```text
Source Gate:
current COMMITTED/PASSED state shown insufficient as durable authority.

Mechanism Gate:
only Runtime receipt-backed admission creates canonical persistent Memory.

Integration Gate:
Verified Artifact → admitted Memory → reload with exact receipt linkage.

Competition Gate:
Memory unit retains required metadata; no performance claim.
```

---

## MRR-09B — Replay Eligibility + Current Grant Memory Authority

### Invariant

> A Memory lookup result is only a candidate; reusable Memory must be explicitly authorized by the current CapabilityGrant, and procedure replay requires a current-Attempt Runtime eligibility receipt.

### Likely production files

```text
statebus/contracts/adaptive.py
statebus/contracts/*memory*
statebus/memory/store.py
statebus/runtime/adaptive_runtime.py
statebus/runtime/adaptive_dispatcher.py
statebus/runtime/replay_eligibility.py   # optional narrow module
```

Do not make `runtime/replay.py` canonical.

### Authority ordering

Because the current source selects Memory after Grant issuance, implementation
must move Memory authorization before final immutable Grant mint:

```text
current Attempt active
        ↓
ExecutionBindingReceipt
        ↓
MemoryMatch candidate
        ↓
validate MemoryAdmissionReceipt
+ current compatibility/policy
        ↓
Runtime selects memory_ref_ids
        ↓
CapabilityGrant(memory_ref_ids=...)
        ↓
ReplayEligibilityReceipt            # procedure reuse only
        ↓
dispatcher
```

No post-hoc mutation of an issued Grant.

### Primary tests

```text
09B-T1 Task A admitted Memory → Task B current Grant + eligible procedure receipt
09B-T2 identity/hash/compatibility mismatch → no ReplayEligibilityReceipt
09B-T3 B stale / C active → B eligibility cannot authorize C
```

Adjacent:
- one existing `lookup_hybrid()` ranking/compatibility regression.

### Gates

```text
Source Gate:
current Memory injection occurs outside explicit Grant Memory authority.

Mechanism Gate:
lookup hit alone cannot reach consumer/replay.

Integration Gate:
cross-task producer A remains historical; consumer B gets fresh authority.

Competition Gate:
later Agent can retrieve and be authorized to reuse historical Memory.
```

---

## MRR-09C — Canonical Memory Consumption + Current Attempt Commit

### Invariant

> Memory reuse may reduce current execution work, but no assist/procedure-reuse path may bypass the current consumer Attempt's normal result admission and Runtime Artifact truth.

Canonical v1 modes:

```text
ASSIST_CONTEXT
VERIFIED_PROCEDURE_REUSE
```

True exact Artifact replay is out of MRR-09C.

### Likely production files

```text
statebus/runtime/adaptive_dispatcher.py
statebus/runtime/adaptive_runtime.py
statebus/memory/models.py
statebus/runtime/adaptive_mainline.py
```

### Primary tests

```text
09C-T1 historical A procedure → B current-input recompute → current B commit
09C-T2 B stale after eligibility → FENCED_STALE_ATTEMPT
09C-T3 assist remains normal execution and creates no false skip claim
```

Adjacent:
- one current MRR-08 Artifact verification integration.

### Gates

```text
Source Gate:
assist vs procedure reuse mechanics are distinguishable.

Mechanism Gate:
reuse result still traverses current Attempt admission.

Integration Gate:
historical A → current B actual reuse → current Artifact truth.

Competition Gate:
producer/consumer reuse is auditable; benefit remains unvalidated.
```

---

## Implementation discipline for all MRR-09 slices

```text
NO SHA / HISTORY AUDIT
NO DEFENSIVE FALLBACK
NO OVERPROGRAMMING
NO OVERTESTING
ONE SLICE = ONE CORRECTNESS INVARIANT
```

Per Slice:

```text
<= 3 primary targeted test functions
+ at most 1 directly adjacent regression
```

No full-suite pytest, Docker, vLLM, benchmark, coverage, broad lint/mypy or
next-Slice implementation unless a Gate explicitly authorizes it.

Every implementation Slice must end in its own Gate Review before the next
Slice begins. Git commit/push/branch operations remain user-owned.

## Exact Artifact replay

Not a canonical MRR-09 Slice.

If separately authorized later it must preserve:
- exact historical byte identity;
- exact input/runtime/output compatibility;
- current consumer Attempt;
- no fake worker lifecycle;
- normal active-Attempt semantic admission;
- original producer + current consumer provenance.

---

## Stop conditions

Report `DESIGN_CONFLICT` if implementation would require:
1. Memory lookup selecting active Attempt;
2. canonical COMMITTED Memory without MemoryAdmissionReceipt;
3. ReplayEligibilityReceipt authorizing visibility by itself;
4. changing ApprovedPlan semantic graph to inject Memory;
5. restoring `replay_ready=True` as authority;
6. bypassing current result admission;
7. reactivating producer Attempt;
8. Memory persistence keeping a StatePin;
9. strict `runtime/replay.py` becoming a second canonical authority.

---

## Next allowed Slice

```text
NEXT_ALLOWED_SLICE
=
MRR-09A-Memory-Admission-Truth
```
