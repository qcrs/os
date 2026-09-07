# MRR-09B Implementation Record — Replay Eligibility + Current Grant Authority

## Goal

Make Memory lookup a candidate-only operation and require Runtime to select
receipt-backed Memory for the current active Attempt before minting the
immutable `CapabilityGrant` used for dispatch.

## Files changed

Production:

- `statebus/contracts/adaptive.py`
- `statebus/contracts/constants.py`
- `statebus/contracts/__init__.py`
- `statebus/memory/models.py`
- `statebus/memory/__init__.py`
- `statebus/memory/store.py`
- `statebus/runtime/adaptive_runtime.py`
- `statebus/runtime/adaptive_dispatcher.py`
- `statebus/runtime/adaptive_mainline.py`

Tests and evidence:

- `tests/test_adaptive_mainline_integration.py`
- `artifacts/mrr-09b/targeted_tests.txt`

## Current STEP_READY Memory seam

After the Runtime activates an Attempt and establishes the provider
`ExecutionBindingReceipt`, it consumes the existing Memory query result. The
Runtime checks the matching admission pair through `MemoryIndexStore.get_admitted`
and evaluates the current capability, contract, schema, validator, runtime
signature, task family, intent, required outputs, tools, and stored procedure
recipe. Selection occurs before `_issue_grant` and is recorded as
`CapabilityGrant.memory_ref_ids`.

`MemoryIndexStore.lookup_hybrid()` continues to return candidates and
compatibility decisions only. It does not select a current Attempt input.

## Replay eligibility authority

For `VALIDATED_REPLAY`, Runtime issues a `ReplayEligibilityReceipt` after
selection and before dispatch. The receipt binds the admitted Memory receipt,
current task/run/session/Step/Attempt, current execution binding, current
capability identity, current contracts/signatures, recipe hash, and the
current Grant hash. `ASSIST` Memory is represented in the current Grant but
does not receive a replay-eligibility receipt. Legacy `EXACT_REPLAY` matches
are downgraded to assist context; exact artifact restoration remains outside
09B.

Historical producer Attempts remain provenance only. The current Attempt is
the sole eligibility authority root, and the dispatcher rejects a stale
Attempt before invoking a provider.

## CapabilityGrant integration and dispatcher enforcement

`CapabilityGrant.memory_ref_ids` is immutable and included in its canonical
payload/hash. The dispatcher materializes Memory inputs only for those exact
Grant references, verifies the corresponding admitted pair, and requires a
matching `ReplayEligibilityReceipt` for validated procedure reuse. It cannot
search, select, or append unbound Memory after Grant mint.

The Runtime result and mainline manifest preserve eligibility receipts as
transport/audit data. They do not become a second authority owner.

## Reuse-mode separation

Lookup candidates, compatible matches, selected Grant Memory, and consumed
inputs remain distinct stages. `ReplayEligibilityReceipt` means only that an
admitted Memory entry is eligible for the current Attempt and reuse mode. No
replay execution, historical output restoration, provider skip, consumption
ledger, or final adoption was added. `replay_ready` remains non-canonical.

## Tests actually run

Targeted MRR-09B tests:

- `test_mrr_09b_memory_lookup_hit_is_not_current_grant_authority`
- `test_mrr_09b_current_runtime_selection_enters_immutable_grant_and_receipt`
- `test_mrr_09b_incompatible_current_runtime_fails_closed_before_grant_memory_binding`

Result: `3 passed`.

During implementation, the existing validated-replay and assist integration
regressions were also exercised and passed; no full suite was run.

## Gates

```text
SOURCE_GATE_PASS
MECHANISM_GATE_PASS
INTEGRATION_GATE_PASS
COMPETITION_GATE_UNVALIDATED
```

## Known limitations

- `replay_ready` remains a legacy compatibility projection and is not a
  canonical eligibility authority.
- Exact artifact replay and replay result adoption are deferred to MRR-09C.
- Memory lookup ranking and retrieval quality are unchanged.
- Eligibility receipts are runtime-local; no distributed replay ledger or
  single-use token service was introduced.

## NEXT_ALLOWED_SLICE

`MRR-09B_GATE_REVIEW`
