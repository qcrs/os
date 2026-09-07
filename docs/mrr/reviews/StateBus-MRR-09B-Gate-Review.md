# StateBus MRR-09B Gate Review

## Review scope

```text
Slice = MRR-09B Replay Eligibility + Current Grant Authority
Branch = feat/mrr-09b-replay-eligibility-current-grant-authority
Review mode = READ ONLY
Test rerun = NOT_REQUIRED
SHA/history audit = NOT_PERFORMED
Competition Gate = UNVALIDATED
```

The review used the Batch 4 design and MRR-09B Slice Spec, the frozen MRR-09A
Gate Review V3, the MRR-09B implementation record, and the current narrow
Runtime, dispatcher, Memory model, and Store seams. No source, test, or
evidence file was modified by this review.

## Authority chain

```text
current Step READY
        ↓
current Attempt active
        ↓
ExecutionBindingReceipt
        ↓
Memory lookup candidate pool
        ↓
receipt-backed admission and current-context compatibility
        ↓
Runtime eligibility and selection
        ↓
immutable CapabilityGrant(memory_ref_ids)
        ↓
ReplayEligibilityReceipt bound to final Grant
        ↓
BoundCapabilityGrant / dispatcher enforcement
```

`MemoryIndexStore.lookup_hybrid()` remains a candidate and compatibility
surface. Runtime calls `get_admitted()` before selection, and
`_select_memory_for_attempt()` runs while the current Attempt is active and
before `_issue_grant()`. `CapabilityGrant.memory_ref_ids` is frozen and part of
the canonical Grant payload/hash. The dispatcher only materializes Memory IDs
listed by that Grant and requires the matching current eligibility receipt for
validated procedure reuse.

## Required checklist

| # | Review item | Result | Evidence / finding |
|---:|---|---|---|
| 1 | Memory lookup is candidate-only | PASS | Lookup returns candidate/rank/compatibility data; it does not issue eligibility, mutate Grants, or dispatch. |
| 2 | Only admitted Memory enters eligibility | PASS | Runtime selection requires `MemoryIndexStore.get_admitted()` and the matching admission pair. |
| 3 | Historical producer authority does not transfer | PASS | Consumer receipts and Grants use the current task/run/session/Step/Attempt; producer identity remains Memory provenance. |
| 4 | Eligibility is current-Attempt scoped | PASS | `ReplayEligibilityReceipt` binds all current runtime and Attempt identities plus execution binding and Grant hashes. |
| 5 | Attempt active during eligibility/selection | PASS | Runtime checks the active Attempt before selection and before issuing eligibility receipts. |
| 6 | Selection occurs before Grant mint | PASS | Both normal and fallback paths select Memory before `_issue_grant()` and never mutate a minted Grant. |
| 7 | Eligibility receipt / Grant ordering is non-circular | PASS | Selection is decided first, the final Grant is minted, then the receipt binds that Grant hash. |
| 8 | ReplayEligibilityReceipt means eligibility only | PASS | Receipt contains decision/compatibility bindings only; no replay result, final adoption, or provider-bypass authority. |
| 9 | CapabilityGrant memory refs are immutable authority | PASS | `CapabilityGrant` is frozen and `memory_ref_ids` is the sole current Grant Memory edge. |
| 10 | Memory refs participate in Grant identity/hash | PASS | `memory_ref_ids` is included in `canonical_payload()` and therefore `grant_hash`. |
| 11 | BoundCapabilityGrant uses final Grant hash | PASS | Bound wrapper is built from the final Grant and exposes its hash through the existing MRR-04 chain. |
| 12 | No post-mint Grant mutation | PASS | Runtime supplies refs during Grant construction; no append, replacement, or context-side injection exists. |
| 13 | Dispatcher cannot independently select Memory | PASS | Dispatcher indexes existing match results only to materialize IDs already present in the Grant. |
| 14 | Dispatcher rejects unbound Memory | PASS | Memory inputs iterate only `grant.memory_ref_ids`; lookup candidates outside that set are ignored. |
| 15 | Validated replay requires matching current eligibility receipt | PASS | Validated inputs require an `ELIGIBLE` receipt matching Memory admission, current Step/Attempt, and final Grant hash. |
| 16 | ASSIST remains context-only | PASS | Assist selection requires current Grant authority but produces no `ReplayEligibilityReceipt` and no validated recipe path. |
| 17 | Legacy EXACT_REPLAY does not execute exact restore | PASS | Runtime downgrades legacy exact matches to `ASSIST`; `_validated_recipe()` accepts only `VALIDATED_REPLAY`. |
| 18 | Procedure reuse uses current inputs | PASS | Existing transform/CodeAct handlers consume current Grant input refs and recompute against current inputs; historical lineage is not an equality predicate. |
| 19 | Compatibility checks current contract/capability | PASS | Runtime checks capability execution kind/id, task family/intent, required outputs/tools, output contract, input schema, runtime signature, validator digest, and recipe shape. |
| 20 | Candidate != Compatible != Selected | PASS | Store compatibility decisions are separate from Runtime selection and Grant binding. |
| 21 | Selected != Consumed | PASS | Grant/eligibility authority is established before handler materialization; consumption records remain downstream observations and no new replay result commit is added. |
| 22 | `replay_ready` remains non-authoritative | PASS | Canonical validated eligibility does not read it; legacy exact compatibility is downgraded to assist and cannot authorize replay. |
| 23 | Grant cannot authorize another Attempt | PASS | Existing Grant task/session/Step/Attempt scope checks remain in dispatcher validation. |
| 24 | Eligibility receipt cannot authorize another Attempt | PASS | Receipt matching includes current Attempt/Step and final Grant hash; another Attempt receives a distinct Grant/receipt. |
| 25 | Existing stale-Attempt fence still applies before dispatch | PASS | Runtime stores the session manager in dispatch context and dispatcher rejects a non-active Grant Attempt before provider handler execution. |
| 26 | Memory authority does not replace State authority | PASS | No StateAccessGrant, StatePin, or State lifetime seam changed; physical State access remains on the Batch 3 plane. |
| 27 | No MRR-09C execution behavior | PASS | No historical output restoration, provider skip, replay commit receipt, final adoption, or replay execution was added. |
| 28 | Runtime remains sole current reuse authority root | PASS | Store persists/queries, dispatcher enforces, and Runtime alone issues eligibility/selection and current Grant authority. |

## Primary evidence adjudication

The recorded three primary tests exercise the production Mainline path:

```text
test_mrr_09b_memory_lookup_hit_is_not_current_grant_authority
test_mrr_09b_current_runtime_selection_enters_immutable_grant_and_receipt
test_mrr_09b_incompatible_current_runtime_fails_closed_before_grant_memory_binding
```

The implementation record and evidence report `3 passed`. Existing validated
procedure and assist regressions also passed during implementation. No test
rerun was required because the current source matches the recorded evidence.

## Source contradiction

```text
NONE
```

The legacy exact branch in `lookup_hybrid()` still reads `replay_ready` as a
compatibility projection. This is consistent with the frozen design because
09B downgrades such matches to assist context and never treats the projection
as canonical replay authority.

## Non-blocking observations

- Exact Artifact replay, replay result commit, and final adoption remain
  deferred to MRR-09C.
- Eligibility receipts are runtime-local audit/authority objects; no
  distributed replay ledger or single-use token service was introduced.
- Lookup ranking and retrieval quality remain unchanged.
- Competition validation remains unvalidated.

## Gate result

```text
SOURCE_GATE_PASS
MECHANISM_GATE_PASS
INTEGRATION_GATE_PASS
COMPETITION_GATE_UNVALIDATED
```

```text
MRR-09B_GATE_PASS
MRR-09B Replay Eligibility + Current Grant Authority = CLOSED
NEXT_ALLOWED_SLICE = MRR-09C
```

No MRR-09C implementation was started by this review.
