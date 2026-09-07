# MRR-09A Implementation Record — Memory Admission Truth

## Goal

Encode the invariant that a Runtime-verified Artifact does not become
authoritative Memory until Runtime performs an explicit receipt-backed Memory
admission transition.

## Files changed

Production:

- `statebus/contracts/constants.py`
- `statebus/contracts/__init__.py`
- `statebus/memory/models.py`
- `statebus/memory/__init__.py`
- `statebus/memory/store.py`
- `statebus/runtime/memory_projection.py`
- `statebus/runtime/adaptive_runtime.py`
- `statebus/runtime/adaptive_mainline.py`

Tests and evidence:

- `tests/test_adaptive_mainline_integration.py`
- `artifacts/mrr-09a/`
- `docs/mrr/implementation/MRR-09A-IMPLEMENTATION-RECORD.md`

## Current canonical Memory admission seam

`AdaptiveMainlineRunner._commit_verified_memory()` remains the Runtime-owned
canonical seam. After the existing MRR-08 ArtifactVerificationReceipt, byte
hash, quality report, recipe, and non-benchmark checks pass, it explicitly
constructs a `MemoryAdmissionReceipt` and calls
`MemoryIndexStore.persist_admitted()`.

`MemoryIndexStore.put_commit()` and `commit_candidate()` remain raw
legacy/compatibility persistence primitives. They do not create admission
authority. Canonical `lookup_hybrid()` treats such records as candidates and
does not approve them without a matching admission receipt.

## MemoryAdmissionReceipt

The receipt binds:

- `memory_admission_receipt_id`
- `memory_id`
- exact `memory_commit_hash`
- `memory_type`
- source Artifact ID and blob hash
- exact `ArtifactVerificationReceipt` hash
- exact Runtime projection binding hash
- admission policy ID/version
- decision, reason, and `admitted_at_ns`
- schema version

It is persisted separately from `MemoryCommit` in
`admission_receipt_registry.json`.

## Relationship to ArtifactVerificationReceipt

`ArtifactVerificationReceipt` remains the necessary upstream Artifact truth.
`MemoryAdmissionReceipt` links to its exact receipt hash and does not copy
producer Attempt, binding, grant, validator, or blob provenance into a second
authority object.

## Admission policy

The current minimal policy accepts only the existing adaptive executor
Artifact path for strategy/procedure Memory types. It requires a verified
Artifact receipt, matching source Artifact ID/hash, a quality-passed committed
Memory projection, and a non-empty policy identity. Benchmark-gold data is not
admitted.

The Store enforces exact receipt/commit binding and immutable Memory identity:
the same `memory_id` plus commit hash is idempotent; a different hash is
rejected.

## Authoritative Memory entry semantics

Canonical reusable Memory is the pair:

```text
MemoryCommit(COMMITTED/PASSED)
+ matching MemoryAdmissionReceipt(ADMITTED)
```

An unreceipted or mismatched commit remains non-canonical. Lookup may retain it
as an identity candidate, but it cannot become an approved Memory match.

## Legacy compatibility boundary

Existing direct write APIs remain available for legacy fixtures and raw
persistence. They do not synthesize an admission receipt and are rejected by
the canonical compatibility gate when presented as authoritative Memory.

## Replay separation

Admission does not create replay eligibility, does not change
`ExecutionArtifactRef.replay_ready`, and does not alter `CapabilityGrant` or
Memory lookup authority. `replay_ready` remains false on the canonical
adaptive Artifact/Memory path.

## Tests actually run

Targeted tests:

- `test_mrr_09a_verified_artifact_does_not_imply_memory_admission`
- `test_mrr_09a_runtime_admission_persists_exact_receipt_binding`
- `test_mrr_09a_fake_or_mismatched_verified_artifact_cannot_admit` (2 cases)
- `test_adaptive_memory_commit_gate_requires_runtime_verification_receipt`

Result: `5 passed`.

Additional check: targeted `compileall` passed.

## Results

The production adaptive path now has an explicit Runtime Memory admission
transition and persists its immutable witness. Fresh Store reload preserves the
exact commit/receipt linkage. Missing or mismatched upstream receipt evidence
creates no canonical Memory entry.

## Source Gate

`SOURCE_GATE_PASS`

- Verified and Memory Admitted are separate truth dimensions.
- ArtifactVerificationReceipt remains required upstream truth.
- MemoryAdmissionReceipt is Runtime-issued admission truth.
- Store/index persistence is mechanical and cannot approve an unreceipted
  commit.
- Legacy/fake VERIFIED records do not become canonical Memory.
- No replay eligibility, CapabilityGrant replay plumbing, second Attempt
  authority, or MRR-09B/09C logic was added.

## Mechanism Gate

`MECHANISM_GATE_PASS`

The real adaptive Runtime candidate -> Artifact verification -> explicit Memory
admission -> receipt persistence chain was exercised, including fresh reload
and idempotent same-commit persistence.

## Integration Gate

`INTEGRATION_GATE_PASS`

Receipt-backed adaptive Memory admission succeeds through the existing
mainline, while the existing MRR-08 receipt gate continues to reject missing
or mismatched verification evidence.

## Competition Gate

`COMPETITION_GATE_UNVALIDATED`

## Known limitations

- Legacy raw Memory APIs can still persist non-canonical records for
  compatibility; canonical lookup does not approve them without a receipt.
- Receipt persistence remains local to the existing Memory store; distributed
  crash recovery and lifecycle redesign are outside this Slice.
- Memory lookup selection, replay compatibility, and current Grant Memory
  authority remain future slices.

## NEXT_ALLOWED_SLICE

`MRR-09A_GATE_REVIEW`

# Corrective Pass

## Gate blocker

The first Gate Review found that post-settlement
`AdaptiveMainlineRunner._commit_verified_memory()` consumed Artifact
verification truth but no Runtime-owned witness proving that the transition was
the downstream consequence of an authorized semantic result admission.

## Chosen Runtime semantic witness

The corrective reuses the existing `AttemptResultAdmissionReceipt` created by
`RuntimeSessionManager.admit_attempt_result()` while the producer Attempt is
still active. `AdaptiveRuntimeResult` now preserves the exact authorized
receipts after settlement; no new Attempt authority or settlement redesign was
introduced.

Artifact verification records the witness hash on the verified Artifact as a
mechanical projection. Mainline admission requires the matching witness,
Runtime identity, approved plan, bound Grant, and executor dispatch. The
`MemoryAdmissionReceipt` and `MemoryCommit` each bind the same witness hash,
while the upstream `ArtifactVerificationReceipt` remains unchanged and owns
Artifact truth.

## Corrective tests and results

- `test_mrr_09a_corrective_runtime_witness_survives_settlement`
- `test_mrr_09a_corrective_verified_receipt_alone_cannot_admit`
- `test_mrr_09a_corrective_mismatched_runtime_witness_cannot_admit`
- `test_mrr_09a_runtime_admission_persists_exact_receipt_binding`

Result: `4 passed`.

The normal production path retained the witness after the Attempt became
settled and admitted canonical Memory. Verification truth alone and a witness
from another Runtime transition both failed closed without persistence.

## Scope constraints preserved

- Attempt settlement remains unchanged.
- `ArtifactVerificationReceipt` authority remains unchanged.
- `MemoryAdmissionReceipt` remains a minimal admission truth object, with only
  a witness-hash reference added.
- `MemoryIndexStore` remains mechanical persistence and binding validation.
- No Replay, `replay_ready` promotion, `CapabilityGrant` Memory plumbing, or
  MRR-09B/09C behavior was added.

## Corrective status

`NEXT_ALLOWED_ACTION = MRR-09A_GATE_REVIEW_V2`

# Corrective Pass 2

## V2 blocker

Gate Review V2 found that a historical semantic witness could still be
combined with changed Mainline request/context projection inputs to create a
different `MemoryCommit` in a fresh `MemoryIndexStore`.

## Chosen exact consequence binding

`MemoryProjectionSpec` is constructed by Mainline from the already-known
canonical Memory inputs before Runtime execution. `AdaptiveRuntimeEngine`
creates the Runtime-owned `MemoryProjectionBinding` after executor Artifact
verification and before Attempt settlement. The binding freezes the exact
projection inputs, the final committed `MemoryCommit` identity, the verified
Artifact receipt hash, and the `AttemptResultAdmissionReceipt` hash.

`AdaptiveRuntimeResult` preserves the immutable binding after settlement.
Mainline materializes the current projection with the frozen timestamp and
bound inputs, then requires the resulting `MemoryCommit.commit_hash` to equal
the Runtime-bound commit hash before constructing `MemoryAdmissionReceipt`.
The admission receipt also retains only the binding hash as a reference to
that exact Runtime projection binding; the Store validates the supplied
receipt/commit pair without creating or reconstructing the binding.
Any changed recipe, quality projection, embedding/state reference, or other
commit-identity input fails closed before persistence.

## Commit-identity fields frozen

The binding covers all fields used by the existing `MemoryCommit` identity,
including:

- Memory type/replay class, topic, tags, source identity, and frozen creation time
- canonical task specification and required outputs
- Artifact identity/hash and manifest
- quality/validator/input projection metadata
- execution recipe and recipe hash
- semantic state and embedding reference identities
- `ArtifactVerificationReceipt` and `AttemptResultAdmissionReceipt` hashes
- admission policy identity

No existing `MemoryCommit.commit_hash` semantics were changed.

## Fresh-store safety and idempotence

A fresh `MemoryIndexStore` cannot admit a modified projection: Mainline
materialization must match the Runtime-issued binding commit hash. Exact
re-observation of the same bound commit remains idempotent under the existing
Store identity rule; a conflicting commit hash remains rejected.

## Tests and results

- `test_mrr_09a_corrective_pass2_runtime_binds_exact_memory_projection`
- `test_mrr_09a_corrective_pass2_fresh_store_rejects_modified_projection`
- `test_mrr_09a_corrective_pass2_exact_projection_is_idempotent`
- `test_mrr_09a_corrective_verified_receipt_alone_cannot_admit`

Result: `4 passed`.

Additional targeted `compileall` passed.

Attempt settlement remains unchanged. `ArtifactVerificationReceipt` remains
Artifact truth, `MemoryAdmissionReceipt` remains Memory admission truth, and
the Store remains mechanical persistence/binding validation. No Replay,
CapabilityGrant Memory plumbing, State lifetime change, or 09B/09C behavior
was added.

## Corrective status

`NEXT_ALLOWED_ACTION = MRR-09A_GATE_REVIEW_V3`
