# StateBus MRR-09A Gate Review V2 — Memory Admission Authority

## Review scope

```text
Branch = feat/mrr-09a-memory-admission-truth
Review mode = READ ONLY
Test rerun = NOT_REQUIRED
Competition Gate = UNVALIDATED
```

This review covers only the MRR-09A corrective authority boundary. MRR-09B
and MRR-09C behavior are not implementation targets.

## Frozen receipt chain

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
Attempt settlement
        ↓
AdaptiveRuntimeResult preserves the exact witness
        ↓
AdaptiveMainlineRunner._commit_verified_memory()
        ↓
MemoryAdmissionReceipt
        ↓
canonical Memory truth
```

The corrective correctly reuses `AttemptResultAdmissionReceipt` as the
Runtime semantic commit witness. The witness is issued while the Attempt is
active, preserved on `AdaptiveRuntimeResult`, projected onto the verified
Artifact, and required by the mainline Memory admission gate after settlement.

## Required checklist

| # | Review item | Result | Evidence / finding |
|---:|---|---|---|
| 1 | Attempt settlement unchanged | PASS | `RuntimeSessionManager.settle_attempt()` still records terminal state and clears only the active Attempt pointer. No settlement delay, reactivation, or Mainline settlement was added. |
| 2 | `AttemptResultAdmissionReceipt` issued while Attempt authoritative | PASS | `RuntimeSessionManager.admit_attempt_result()` checks the registered active Attempt and issues `ACTIVE_ATTEMPT_COMMIT_ALLOWED` before settlement. |
| 3 | Preserved witness does not become live Attempt authority | PASS | `AdaptiveRuntimeResult` transports immutable receipts; the settled session retains no active Attempt pointer, and no Memory-owned Attempt authority was added. |
| 4 | Artifact verification binds exact semantic witness | PASS | Artifact verification projects `attempt_result_admission_receipt_hash`; Mainline checks that projection against the matching Runtime receipt hash. |
| 5 | `ArtifactVerificationReceipt` remains Artifact truth | PASS | The Artifact verifier remains the issuer of `ArtifactVerificationReceipt`; the semantic witness is only an upstream binding and does not replace the verification decision. |
| 6 | Memory admission requires semantic witness | PASS | `_commit_verified_memory()` requires exactly one authorized matching result admission and rejects a missing or mismatched Runtime witness. |
| 7 | Memory admission also requires `ArtifactVerificationReceipt` | PASS | Mainline checks the receipt decision, Artifact identity, Runtime identity, Step/Attempt, Grant, candidate hash/size, and projected verification-receipt hash. |
| 8 | Exact witness → Artifact → MemoryCommit lineage | **FAIL** | The witness hash is copied into Memory metadata and the `MemoryAdmissionReceipt`, but no expected Memory projection/commit identity is bound to the witness. `_commit_verified_memory()` derives `memory_type`, `memory_topic`, tags, recipe projection, embedding/state references, and `created_at_ns` from the current request/context. |
| 9 | Old witness cannot authorize unrelated `MemoryCommit` | **FAIL** | With the same historical witness and verified Artifact, a later caller can alter request/context-derived Memory projection fields and produce a different `MemoryCommit`. A fresh `MemoryIndexStore` has no prior identity conflict to reject it. |
| 10 | Conflicting commit identity rejected | PASS | Existing-store `persist_admitted()` rejects a different hash for an existing `memory_id`; exact supplied commit/receipt pairs remain mechanically bound. This does not cure the fresh-store consequence gap in items 8–9. |
| 11 | Mainline cannot self-sign semantic witness | PASS | `_commit_verified_memory()` consumes a receipt from `runtime.attempt_result_admissions`; it does not construct an `AttemptResultAdmissionReceipt` or infer authority from `runtime.completed`. |
| 12 | `AdaptiveRuntimeResult` only preserves witness | PASS | The added field is a tuple transport of existing Runtime-issued receipts; issuance remains in the Session Manager. |
| 13 | No duplicate semantic receipt authority | PASS | The corrective adds a hash projection/reference and does not create a second semantic commit receipt. |
| 14 | `MemoryAdmissionReceipt` remains minimal | PASS | It records Memory identity, Artifact binding, policy, decision, time/schema, and the semantic witness hash; it does not copy active Attempt or full producer provenance. |
| 15 | Store remains mechanical | PASS | `MemoryIndexStore.persist_admitted()` validates exact supplied bindings and persists/reloads them. It does not issue witnesses, query active Attempts, repair mismatches, or synthesize authority. |
| 16 | Verified receipt alone cannot admit | PASS | Corrective evidence records rejection when the Runtime semantic witness is absent. Source requires a matching authorized witness before Memory construction reaches persistence. |
| 17 | Mismatched semantic witness cannot admit | PASS | Corrective evidence records rejection for a witness from another Runtime transition; source checks Step/Attempt, Runtime identity, Grant/dispatch, Artifact projection, and witness hash. |
| 18 | Arbitrary later caller cannot manufacture new Memory truth | **FAIL** | The current checks prove upstream lineage but not the exact downstream Memory consequence. Historical witness plus valid Artifact receipt can be paired with a modified request-derived projection and admitted into a fresh Store. |
| 19 | No Memory-owned Attempt/freshness authority | PASS | No `memory_active_attempt`, generation, epoch, session owner, or equivalent authority was added. |
| 20 | Replay separation preserved | PASS | `replay_ready` remains false; no ReplayEligibilityReceipt, lookup selection authority, replay execution, or CapabilityGrant Memory plumbing was added. |
| 21 | MRR-08 Artifact authority preserved | PASS | Artifact verification ordering and `ArtifactVerificationReceipt` semantics remain intact; the corrective only records the existing witness hash as a projection. |
| 22 | Batch-2 Attempt/fencing preserved | PASS | Active-Attempt admission and stale-result fencing remain in the Session Manager; settlement ordering is unchanged. |

## Blocking finding — exact downstream Memory consequence is not bound

The corrective closes the original post-settlement authority gap only at the
upstream semantic-result level:

```text
AttemptResultAdmissionReceipt(A)
        ↓
ArtifactVerificationReceipt(X)
```

The remaining production seam is:

```text
statebus/runtime/adaptive_mainline.py:_commit_verified_memory()
```

At the Memory construction point, the method derives the Memory projection
from the current `request` and `context`:

```text
memory_type
memory_topic
memory_tags
execution_recipe
semantic_state_ref_id
embedding_ref_id
input lineage metadata
created_at_ns
```

The resulting `MemoryCommit.commit_hash` includes those values, while the
semantic witness only appears as a metadata hash. `MemoryIndexStore` validates
that the supplied receipt and commit carry the same witness hash, but it has
no Runtime-issued expected commit/projection identity. Its conflicting hash
check applies only when the same `memory_id` is already present in that Store.

Therefore this source-level path remains possible:

```text
historical AttemptResultAdmissionReceipt(A)
        + exact ArtifactVerificationReceipt(X)
        + altered current Memory projection
        ↓
different MemoryCommit(M2)
        ↓
MemoryAdmissionReceipt(M2)
        ↓
canonical truth in a fresh MemoryIndexStore
```

This contradicts the V2 requirement that a historical witness may authorize
only the exact downstream consequence of its Runtime transition. The existing
corrective evidence covers missing and mismatched witnesses, but it does not
cover this consequence-binding boundary.

## Minimum corrective action

Keep the existing `AttemptResultAdmissionReceipt` and unchanged Attempt
settlement. Add one minimal Runtime-owned binding that makes the authorized
semantic transition determine the exact deterministic Memory projection or
its expected `MemoryCommit` identity. Then require that binding in Mainline and
mechanically validate it in the Store. Do not add a Memory-owned Attempt,
delay/reopen settlement, or introduce Replay/CapabilityGrant behavior.

## Non-blocking observations

- Legacy `put_commit()` and `commit_candidate()` remain raw compatibility APIs;
  canonical lookup still requires a matching admission receipt.
- Admission receipt persistence remains local to the existing Memory store;
  distributed crash recovery is outside MRR-09A.
- Memory lookup compatibility and current Grant authority remain future
  MRR-09B work.
- Competition and performance remain unvalidated.

## Gate result

```text
SOURCE_GATE_FAIL
MECHANISM_GATE_FAIL — exact downstream Memory consequence is not bound
INTEGRATION_GATE_FAIL — fresh-store historical-witness path remains possible
COMPETITION_GATE_UNVALIDATED
```

```text
MRR-09A_GATE_FAIL
MRR-09A STATUS = OPEN
NEXT_ALLOWED_SLICE = CORRECTIVE_PASS_2
```

No production source, test, or evidence file was modified by this review.
