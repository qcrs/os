# StateBus Batch 4 — Design Review and v2 Amendments

## Verdict

```text
BATCH_4_DESIGN
=
APPROVED_WITH_AMENDMENTS

MRR-09_DESIGN_READY
NEXT_ALLOWED_SLICE = MRR-09A-Memory-Admission-Truth
```

The v1 package has the correct three-Slice architecture. The v2 amendments
tighten authority ordering and implementation discipline without changing the
core MRR-09 direction.

## A1 — MemoryAdmissionReceipt is a link, not a provenance duplicate

The admission receipt must bind the exact `MemoryCommit` to the exact upstream
MRR-08 `ArtifactVerificationReceipt` and admission policy.

It should not copy the entire producer Runtime authority into a second
persistent truth object. Duplicate producer/validator/capability fields may
remain as metadata projections where useful, but they are not independent
admission authority.

Frozen minimum:

```text
memory_id
memory_commit_hash
memory_type
source_artifact_id
source_artifact_blob_hash
artifact_verification_receipt_hash
admission_policy_id/version
admitted_at_ns
schema_version
```

## A2 — Memory authorization must precede immutable Grant mint

The current source gap is that Memory selection occurs after CapabilityGrant
issuance. MRR-09B must not solve that by mutating an issued Grant.

Freeze:

```text
Attempt
→ ExecutionBindingReceipt
→ Memory lookup candidates
→ validate MemoryAdmissionReceipt + compatibility
→ Runtime selects memory_ref_ids
→ mint immutable CapabilityGrant
→ ReplayEligibilityReceipt for procedure reuse
→ dispatch
```

`ASSIST_CONTEXT` needs current Grant Memory authority but no replay-eligibility
receipt.

## A3 — Procedure reuse does not require exact historical input lineage

`VERIFIED_PROCEDURE_REUSE` reruns a verified historical recipe on current
inputs.

Therefore exact historical/current input-lineage equality is not an
eligibility predicate. Current lineage may be retained as audit context.
Exact lineage belongs to future true exact Artifact replay.

## A4 — Gate reviews are mandatory between implementation slices

Frozen execution DAG:

```text
09A implementation
→ 09A Gate Review
→ 09B implementation
→ 09B Gate Review
→ 09C implementation
→ 09C Gate Review
→ Batch 4 Gate Review
```

Implementation test discipline:

```text
<= 3 primary targeted test functions
+ at most 1 adjacent regression
```

No SHA/history audit, defensive fallback, full-suite testing, unrelated
refactor or next-Slice implementation.

## Unchanged architecture decisions

```text
MemoryAdmissionReceipt = REQUIRED
ReplayEligibilityReceipt = REQUIRED
ReplayAdmissionReceipt = NOT_REQUIRED

Memory lookup hit = identity candidate only
CapabilityGrant remains current Memory authority owner
ExecutionArtifactRef.replay_ready = compatibility projection only

ASSIST_CONTEXT != replay
VERIFIED_PROCEDURE_REUSE = current-input recompute under current Attempt
EXACT_ARTIFACT_REPLAY = deferred advanced path
```

## Rejected additions

```text
MemoryAccessGrant
Memory-owned Attempt
Replay-owned Session
post-hoc CapabilityGrant mutation
provider-side replay authority
distributed cache/GC service
generic policy DSL
exact replay in MRR-09C
```
