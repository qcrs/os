# StateBus MRR-09A Gate Review V3 — Exact Memory Consequence

## Review scope

```text
Date = 2026-09-07
Branch = feat/mrr-09a-memory-admission-truth
Review mode = READ ONLY
Test rerun = NOT_REQUIRED
Competition Gate = UNVALIDATED
```

This review covers only the MRR-09A exact downstream Memory-consequence
boundary. V1 and V2 failures remain preserved in their original review
documents. MRR-09B and MRR-09C are not implementation targets.

## Frozen authority chain

```text
Attempt active
        ↓
RuntimeSessionManager.admit_attempt_result()
        ↓
AttemptResultAdmissionReceipt
        ↓
Artifact verification
        ↓
ArtifactVerificationReceipt
        ↓
Runtime MemoryProjectionBinding
        ↓
Attempt settlement
        ↓
AdaptiveRuntimeResult preserves the binding
        ↓
Mainline materializes the bound MemoryCommit
        ↓
MemoryAdmissionReceipt
        ↓
canonical Memory truth
```

The corrective pass closes the V2 gap by binding the exact deterministic
Memory projection and expected `MemoryCommit.commit_hash` before settlement.
`MemoryProjectionSpec` remains a mechanical input; `MemoryProjectionBinding`
is Runtime-issued consequence evidence; `MemoryAdmissionReceipt` remains the
separate Memory admission truth.

## Required checklist

| # | Review item | Result | Evidence / finding |
|---:|---|---|---|
| 1 | `MemoryProjectionSpec` is non-authoritative input | PASS | Mainline constructs the immutable spec from already-known request/context inputs. Spec presence alone does not create a commit or admission receipt. |
| 2 | `MemoryProjectionBinding` is Runtime-issued | PASS | `AdaptiveRuntimeEngine._bind_memory_projection()` creates the binding from the admitted result, verified Artifact, quality evidence, recipe, and query embedding. Mainline and Store do not issue it. |
| 3 | Binding issued before Attempt settlement | PASS | The binding call occurs after Artifact verification and before the completed-path `_settle_attempt()` call. Settlement implementation remains unchanged. |
| 4 | Binding ties exact semantic witness | PASS | Binding records `runtime_semantic_commit_receipt_hash`; Mainline requires the matching `AttemptResultAdmissionReceipt` for the same Step/Attempt and Artifact lineage. |
| 5 | Binding ties exact Artifact verification truth | PASS | Binding records the source Artifact ID/blob hash and `artifact_verification_receipt_hash`; Mainline cross-checks these against the verified Artifact and receipt. |
| 6 | All `MemoryCommit` identity fields frozen/bound | PASS | `build_memory_commit()` derives identity from the frozen spec plus Runtime-time Artifact, recipe, quality, State, embedding, and receipt inputs. The resulting hash is captured as `expected_memory_commit_hash`; any changed identity input fails the equality check. |
| 7 | Identity timestamp frozen if applicable | PASS | `MemoryProjectionSpec.created_at_ns` is assigned before Runtime execution and is used by `MemoryCommit`; Mainline does not generate a new commit timestamp. `MemoryAdmissionReceipt.admitted_at_ns` is separate admission metadata and is not part of `MemoryCommit.commit_hash`. |
| 8 | Expected MemoryCommit hash Runtime-bound | PASS | `_bind_memory_projection()` computes `build_memory_commit(...).commit_hash` and stores it in the binding before settlement. Mainline only verifies the materialized hash against that value. |
| 9 | Mainline cannot re-author projection | PASS | `_commit_verified_memory()` consumes the Runtime binding's spec, preserves its frozen timestamp/fields, and rejects a materialized commit whose hash differs from the Runtime-bound expected hash. Mutable request/context values cannot silently authorize a second projection. |
| 10 | Fresh Store cannot admit modified projection | PASS | The fresh-store corrective test changes an identity-bearing recipe and receives `terminal_executor_memory_projection_mismatch` before persistence. Rejection is caused by binding/hash mismatch, not by an existing Store record. |
| 11 | Historical witness authorizes only exact consequence | PASS | The semantic witness and Artifact receipt are necessary but insufficient without the matching binding and expected commit identity. A historical `A + X` can only reproduce the exact bound projection. |
| 12 | Exact consequence remains idempotent | PASS | Re-persisting the same bound `MemoryCommit` and matching admission receipt returns the existing pair under the existing identity rule. |
| 13 | No one-time token semantics | PASS | No spent/consumed witness, nonce registry, or single-use authority was added. Idempotence remains allowed for the same exact consequence. |
| 14 | No generation/epoch added | PASS | No memory generation, projection epoch, admission epoch, or freshness counter was introduced. |
| 15 | ArtifactVerificationReceipt semantics preserved | PASS | `ArtifactVerificationReceipt` remains issued by `RuntimeArtifactVerificationAuthority` for the Candidate → Verified transition. The projection binding only references its receipt hash and does not become Artifact authority. |
| 16 | `AttemptResultAdmissionReceipt` remains generic | PASS | The generic Session receipt was not extended with Memory-specific fields; Memory projection data lives in the separate Runtime binding. |
| 17 | `MemoryProjectionBinding != Memory Admission` | PASS | Binding is only exact consequence evidence. Canonical Memory still requires `MemoryCommit` plus matching `MemoryAdmissionReceipt(ADMITTED)` persisted by the Store. |
| 18 | `MemoryAdmissionReceipt` remains minimal | PASS | The receipt keeps a `memory_projection_binding_hash` reference plus existing Memory/Artifact/policy bindings; it does not copy the full Runtime witness or projection spec. |
| 19 | Store remains mechanical | PASS | `MemoryIndexStore.persist_admitted()` validates supplied commit/receipt identity and binding references, persists, reloads, and enforces idempotence/conflict rules. It does not create bindings, inspect active Attempts, or repair mismatches. |
| 20 | Admission policy identity bound | PASS | `MemoryProjectionSpec` and `MemoryProjectionBinding` carry the policy ID/version; Mainline requires the frozen current policy before admission. A historical binding is not reinterpreted under another policy. |
| 21 | Replay separation preserved | PASS | No replay eligibility, lookup-selection authority, `replay_ready` promotion, or replay execution was added. `replay_ready` remains false on the adaptive Artifact path. |
| 22 | `CapabilityGrant` unchanged | PASS | No `CapabilityGrant` Memory references or post-hoc Grant mutation were introduced. |
| 23 | Attempt settlement/fencing unchanged | PASS | The corrective only preserves the binding in `AdaptiveRuntimeResult`; `settle_attempt()` still records terminal state and clears the active Attempt pointer, while admission/fencing remains in Session Manager. |
| 24 | No MRR-09B/09C implementation | PASS | Changes are limited to exact Memory admission consequence binding and its mechanical validation; no Replay or future Slice behavior is present. |

## Exact consequence closure

The source and corrective evidence establish the following lineage:

```text
AttemptResultAdmissionReceipt(A)
        ↓ runtime_semantic_commit_receipt_hash
ArtifactVerificationReceipt(X)
        ↓ artifact_verification_receipt_hash + Artifact ID/blob hash
MemoryProjectionBinding(P)
        ↓ expected_memory_commit_hash
MemoryCommit(M)
        ↓ memory_projection_binding_hash + memory_commit_hash
MemoryAdmissionReceipt(R)
```

The binding is issued while the producer Attempt is authoritative, then
preserved across settlement. Mainline may materialize the projection, but it
cannot select a different authoritative projection: the resulting commit hash
must equal the Runtime-issued expected hash. The Store performs only the
supplied identity and persistence checks.

Required consequence questions:

```text
Can a later caller change current request/context and generate M2 from A + X?
NO — the Runtime-bound expected commit hash check fails closed.

Can a fresh Store make that unsafe?
NO — rejection occurs before persistence and does not depend on prior records.

Can exact M be re-observed idempotently?
YES — the unchanged Memory ID/commit identity rule returns the same truth.

Does MemoryProjectionBinding mean Memory is already admitted?
NO — only the matching ADMITTED MemoryAdmissionReceipt plus MemoryCommit is canonical.
```

## Gate result

```text
SOURCE_GATE_PASS
MECHANISM_GATE_PASS
INTEGRATION_GATE_PASS
COMPETITION_GATE_UNVALIDATED
```

```text
MRR-09A_GATE_PASS
MRR-09A STATUS = CLOSED
NEXT_ALLOWED_SLICE = MRR-09B
```

No production source, test, or evidence file was modified by this review.
