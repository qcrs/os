# MRR-09C Implementation Record — Canonical Memory Consumption + Current Attempt Commit

## Goal

Close the canonical Memory consumption path for the two frozen MRR-09 modes:
`ASSIST_CONTEXT` and `VERIFIED_PROCEDURE_REUSE`. Consumption must be scoped to
the current immutable `CapabilityGrant`; any resulting output must continue
through the current Attempt's normal `AttemptResultAdmissionReceipt` authority.

## Files changed

Production:

- `statebus/memory/models.py`
- `statebus/runtime/adaptive_dispatcher.py`
- `statebus/runtime/adaptive_runtime.py`

Tests and evidence:

- `tests/test_adaptive_mainline_integration.py`
- `artifacts/mrr-09c/targeted_tests.txt`

## Canonical Memory consumption seam

`AdaptiveCapabilityDispatcher._memory_inputs_for_step()` now treats every
`CapabilityGrant.memory_ref_ids` entry as an explicit current authority
requirement. It fail-closes when the admitted pair, compatibility decision, or
current validated eligibility receipt is missing or mismatched. It only
materializes Memory already present in the final Grant; lookup candidates and
`replay_ready` projections cannot enter the handler through a side channel.

`MemoryConsumptionRecord` remains an observation contract, not an authority
root. It now records the current consumer task/run/session/Attempt and the
exact `CapabilityGrant`, `MemoryCommit`, `MemoryAdmissionReceipt`, and (for
validated procedure reuse) `ReplayEligibilityReceipt` hashes.

## ASSIST_CONTEXT semantics

Assist Memory is supplied as current role context/input through the immutable
Grant. The normal handler still executes with current inputs, and no
`ReplayEligibilityReceipt` is created for assist mode. The consumption record
therefore has an empty eligibility reference and `recipe_recomputed=False`.

## VERIFIED_PROCEDURE_REUSE semantics

Validated procedure reuse requires the current Attempt-scoped
`ReplayEligibilityReceipt` before Memory materialization. The historical
recipe is recomputed against current input refs and current validators; the
result is a new current output, never a restored historical result.

## Current Attempt result authority

After the existing `RuntimeSessionManager.admit_attempt_result()` authorizes a
current result, `AdaptiveRuntimeEngine` binds that receipt hash onto matching
Memory consumption observations for the same step, Attempt, and Grant. No
Replay-specific result authority or producer Attempt resurrection was added.

## Provenance and authority separation

Historical producer Memory remains provenance only. Current consumption is
bound to the consumer Attempt and current Grant. `MemoryAdmissionReceipt`,
`ReplayEligibilityReceipt`, and `AttemptResultAdmissionReceipt` remain separate
truths. State access, Grant minting, Memory lookup/ranking, and final adoption
are unchanged.

## Tests actually run

Primary MRR-09C tests:

- `test_mrr_09c_assist_consumption_binds_current_attempt_result_admission`
- `test_mrr_09c_validated_procedure_consumption_binds_current_attempt_result`
- `test_mrr_09c_validated_consumption_without_eligibility_fails_closed`

Result: `3 passed`.

Adjacent regression:

- `test_mrr_09b_memory_lookup_hit_is_not_current_grant_authority`

Result: `1 passed`.

Targeted syntax validation for the changed modules and test file also passed.
No full test suite, Docker, vLLM, benchmark, coverage, or performance run was
performed.

## Gates

```text
SOURCE_GATE_PASS
MECHANISM_GATE_PASS
INTEGRATION_GATE_PASS
COMPETITION_GATE_UNVALIDATED
```

## Known limitations

- Exact historical Artifact/output restoration remains explicitly deferred.
- Consumption records are runtime-local audit projections; no distributed
  consumption ledger or single-use Memory semantics were introduced.
- Formal competition benefit and work-skip validation remain unvalidated.

## NEXT_ALLOWED_SLICE

`MRR-09C_GATE_REVIEW`
