# StateBus MRR-09A Gate Review — Memory Admission Truth

## Review scope

```text
Branch = feat/mrr-09a-memory-admission-truth
Review mode = READ ONLY
Test rerun = NOT_REQUIRED
Competition Gate = UNVALIDATED
```

The review checks only the MRR-09A Memory admission boundary. MRR-09B and
MRR-09C behavior are not treated as implementation targets.

## Frozen truth chain

```text
ExecutionArtifactRef(CANDIDATE)
        ↓
Runtime Artifact Verification
        ↓
ArtifactVerificationReceipt
        ↓
Runtime Memory admission
        ↓
MemoryAdmissionReceipt
        ↓
MemoryCommit + matching admission receipt
```

The implementation correctly separates `Verified` from `Memory Admitted` in
the normal adaptive path. One required authority boundary remains unproven:
the Memory admission transition is not bound to a current Runtime semantic
commit authority after the producer Attempt has settled.

## Required checklist

| # | Review item | Result | Evidence / finding |
|---:|---|---|---|
| 1 | Verified != Memory Admitted | PASS | Verification-only execution leaves both `commits` and `admission_receipts` empty; `_commit_verified_memory()` is a separate transition. |
| 2 | Runtime owns Memory admission | PASS | Canonical call site is `AdaptiveMainlineRunner.run()` -> `_commit_verified_memory()`; the Store accepts a Runtime-supplied receipt and performs mechanical checks. |
| 3 | MemoryAdmissionReceipt is independent Memory truth | PASS | `MemoryAdmissionReceipt` records the admission decision and exact Memory bindings rather than another verification flag. |
| 4 | Receipt references, not duplicates, Artifact truth | PASS | Receipt contains Artifact ID/blob hash and verification-receipt hash, without producer Attempt, Binding, Grant, or validator authority copies. |
| 5 | Exact ArtifactVerificationReceipt binding | PASS | Canonical mainline checks receipt decision, Artifact ID, task/run/session, Step/Attempt, Grant hash, candidate hash/size, and projected receipt hash before admission. |
| 6 | Exact MemoryCommit binding | PASS | `persist_admitted()` requires matching `memory_id`, `memory_commit_hash`, type, Artifact ID, and Artifact blob hash. |
| 7 | Same admission is idempotent; conflicting identity rejected | PASS | Same Memory ID/commit hash returns the existing pair; a different commit hash is rejected on the canonical admitted path. Raw legacy writes remain non-canonical. |
| 8 | Memory Store is mechanical, not admission authority | PASS | `persist_admitted()` validates and persists a receipt/commit pair; `put_commit()` and `commit_candidate()` do not synthesize admission authority. |
| 9 | Legacy raw Memory cannot become canonical admitted truth | PASS | `lookup_hybrid()` rejects missing or mismatched admission receipts; legacy records remain candidate/raw compatibility data. |
| 10 | Lookup does not grant Replay authority | PASS | Hybrid lookup produces candidate/compatibility results; no current Attempt or replay authorization is minted by lookup. |
| 11 | Memory Admitted != Replay Eligible | PASS | Admission receipt has no replay-eligibility decision; replay selection remains outside MRR-09A. |
| 12 | `replay_ready` not promoted | PASS | Canonical adaptive Artifact/Memory metadata retains `replay_ready=False`; admission does not update it. |
| 13 | CapabilityGrant replay plumbing not introduced | PASS | No MRR-09A change adds `CapabilityGrant.memory_ref_ids` or lookup-to-Grant authorization. |
| 14 | No MRR-09B/09C implementation | PASS | No ReplayEligibilityReceipt, current-input replay compatibility, replay execution, or replay commit path was added. |
| 15 | Admission rejection does not invalidate Artifact verification | PASS | `_commit_verified_memory()` returns a rejected decision before Memory persistence; it does not downgrade, delete, or invalidate the verified Artifact/receipt. |
| 16 | Stale/non-authoritative execution cannot create new Memory truth | **FAIL** | See the blocking finding below. `_commit_verified_memory()` has no current Attempt/admission-authority check at its transition point. |
| 17 | No Memory-owned Attempt authority | PASS | No Memory session, generation, epoch, or active-Attempt authority was added. |
| 18 | Persistence/reload preserves receipt-backed admission boundary | PASS | Reload reconstructs commits and receipts separately; `_is_admitted()` and hybrid compatibility require their exact binding before approval. |
| 19 | No State lifetime coupling | PASS | Memory admission does not create or extend `StatePin`, State ownership, or Attempt lifetime. |
| 20 | No overdesign / distributed Memory machinery | PASS | Changes stay within contracts, Memory models/store, and adaptive mainline; no generic policy DSL, distributed cache, or storage redesign was added. |

## Blocking finding — stale Attempt safety

The canonical production ordering is:

```text
statebus/runtime/adaptive_mainline.py:395
AdaptiveRuntimeEngine().run(runtime_request)

statebus/runtime/adaptive_mainline.py:396-403
_commit_verified_memory(...)
```

`AdaptiveRuntimeEngine.run()` settles completed Attempts before returning its
`AdaptiveRuntimeResult`. `RuntimeSessionManager.settle_attempt()` clears the
per-step active Attempt pointer (`statebus/runtime/session.py:598-645`). The
returned runtime result is then passed to the static
`AdaptiveMainlineRunner._commit_verified_memory()` seam.

At `statebus/runtime/adaptive_mainline.py:739-801`, the Memory admission gate
checks `runtime.completed`, the verified Artifact projection, and the exact
`ArtifactVerificationReceipt`/Artifact identity and content bindings. It does
not check any current `RuntimeTaskSession` active Attempt, an
`AttemptResultAdmissionReceipt`, or another Runtime-owned admission witness
that proves the transition still belongs to an authorized semantic commit
path.

Therefore the existing evidence proves historical producer verification, but
does not prove that a stale or later caller holding that verification receipt
cannot invoke this seam and create a new `MemoryAdmissionReceipt` and
canonical Memory entry. The receipt hash is necessary upstream truth; it is
not by itself current Memory-admission authority.

This is a source-level contradiction with the MRR-09A requirement that a
stale/non-authoritative execution cannot manufacture new reusable Memory
truth. The normal-path tests and persistence evidence do not exercise this
boundary, so the recorded Mechanism/Integration PASS claims are insufficient
for Gate closure.

## Minimum corrective Slice

```text
MRR-09A-CORRECTIVE — bind Memory admission to a Runtime-owned
post-verification semantic commit authority.
```

The corrective slice must make the admission transition consume an explicit
Runtime authority from the authorized mainline transition (or perform an
equivalent narrow current-authority check) while preserving the existing
`ArtifactVerificationReceipt` and `MemoryAdmissionReceipt` bindings. It must
not modify CapabilityGrant replay inputs, implement replay eligibility, or
redesign State lifetime.

## Non-blocking observations

- `put_commit()` and `commit_candidate()` remain legacy/raw compatibility APIs;
  they can persist non-canonical records, but canonical hybrid lookup does not
  approve them without an admission receipt.
- Admission receipt persistence is local to the existing Memory store; no
  distributed crash-recovery claim is made.
- Lookup compatibility, current Grant Memory authority, and replay selection
  remain future MRR-09B work.
- Competition behavior and performance remain unvalidated.

## Gate result

```text
SOURCE_GATE_FAIL
MECHANISM_GATE_BLOCKED_BY_STALE_AUTHORITY_GAP
INTEGRATION_GATE_BLOCKED_BY_STALE_AUTHORITY_GAP
COMPETITION_GATE_UNVALIDATED
```

```text
MRR-09A_GATE_FAIL
MRR-09A STATUS = OPEN
NEXT_ALLOWED_SLICE = CORRECTIVE_SLICE
```

No production source, test, or evidence file was modified by this review.
