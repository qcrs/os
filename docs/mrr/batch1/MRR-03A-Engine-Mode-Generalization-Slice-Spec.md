# MRR-03A — Engine Mode Generalization Slice Spec


> **Source freeze**
>
> - Current Source of Truth: `qcrs/os`
> - Branch: `master`
> - Audited commit: `8bfc6464ec236c0e121911095fc283129b0e7696`
> - Historical/context evidence: `statebus.7z` (reference only)
> - This document is a **source-level implementation specification**, not an implementation record.
> - No production source was modified and no formal benchmark was executed in this review.


## 1. Goal

Remove the architectural rule that `STRICT_FIXED` must use the legacy `RuntimeDriver.run()` execution engine.

This slice proves only:

```text
STRICT_FIXED ApprovedPlan
-> AdaptiveRuntimeEngine
-> RuntimeWorkflowStep
-> Runtime-created Attempt
-> CapabilityGrant
-> deterministic test execution
-> committed step result
```

It does not yet connect the full Fixed product assembly.

---

## 2. Architecture Invariant

```text
WorkflowMode may change plan-source policy.
WorkflowMode must not select a second execution authority.
```

After this slice:

```text
AdaptiveRuntimeEngine
```

is capable of executing policy-valid `STRICT_FIXED` and `ADAPTIVE_BOUNDED` ApprovedPlans.

---

## 3. Current Source Truth

`AdaptiveRuntimeEngine.run()` currently contains:

```text
if workflow_mode == STRICT_FIXED:
    raise strict_fixed_must_use_RuntimeDriver_run
```

The same function already:

- validates ApprovedPlan;
- creates a RuntimeTaskSession;
- projects ApprovedPlan to RuntimeWorkflowStep;
- computes READY set;
- creates attempt ids;
- resolves typed inputs;
- issues CapabilityGrant;
- invokes dispatcher/callback;
- validates grant binding;
- commits lifecycle.

Therefore the engine itself is already the correct target.

The current source does not show a technical need for a second engine.

---

## 4. Exact Source Files to Read

```text
statebus/runtime/adaptive_runtime.py
statebus/runtime/session.py
statebus/runtime/supervisor.py
statebus/runtime/driver.py
statebus/contracts/adaptive.py
tests/test_adaptive_driver.py
tests/test_adaptive_mainline_integration.py
```

Read for compatibility but do not modify:

```text
statebus/runtime/smoke.py
statebus/runtime/adaptive_mainline.py
```

unless request mode validation is factored in a narrowly scoped change.

---

## 5. Exact Files Expected to Change

Primary production:

```text
MODIFY statebus/runtime/adaptive_runtime.py
MODIFY statebus/runtime/driver.py
```

Conditional:

```text
MODIFY statebus/runtime/adaptive_mainline.py
```

only if a shared mode-validation helper is required.

Tests:

```text
ADD    tests/test_canonical_runtime_modes.py
EXTEND tests/test_adaptive_driver.py
```

Target is <=3 production files.

---

## 6. Exact Classes / Functions Affected

`AdaptiveRuntimeEngine.run`
- replace unconditional STRICT_FIXED rejection with explicit accepted-mode validation
- retain `ADAPTIVE_SHADOW` no-dispatch behavior only where still semantically valid
- do not weaken ApprovedPlan validation

`AdaptiveRuntimeEngine._workflow`
- no semantic change expected
- tests must prove both modes use it

`AdaptiveRuntimeEngine._issue_grant`
- no provider-binding redesign yet
- must use MRR-01 explicit session identity if available

`RuntimeDriver.run_adaptive`
- may be renamed/generalized internally or retain name as compatibility facade
- it must not create a new engine

`RuntimeDriver.run_mode`
- may add an opt-in canonical STRICT_FIXED request route
- legacy `strict_input -> self.run(strict_input)` must remain available as compatibility until MRR-03B/later benchmark migration

---

## 7. Contract Changes

Prefer **no new semantic contract** in MRR-03A.

Use existing:

```text
AdaptiveTaskEnvelope(workflow_mode=STRICT_FIXED)
ApprovedPlan
AdaptiveRuntimeRequest
RuntimeTaskSession
StepAttemptRecord
CapabilityGrant
AdaptiveStepResult
```

If a generic name is desired for `AdaptiveRuntimeRequest`, defer renaming. Renaming is not needed to prove one engine.

---

## 8. Compatibility Bridge

Two strict lanes coexist temporarily:

```text
legacy strict:
RuntimeDriver.run(RuntimeDriverInput)

canonical strict experimental:
AdaptiveRuntimeEngine.run(AdaptiveRuntimeRequest[STRICT_FIXED])
```

This temporary coexistence is allowed because only the new lane claims canonical execution authority; legacy lane remains a regression oracle.

MRR-03B will create the product assembly bridge. Later deprecation removes the old entrypoint.

---

## 9. Explicit Non-Goals

Do not:

```text
change run_smoke orchestration
move RolePath
move retrieval
move semantic state
move memory
move CodeAct
move artifact creation
add ProviderRegistry
change physical worker protocol
change scheduler/READY ordering
```

---

## 10. Implementation Sequence

1. Add a test showing current STRICT_FIXED engine rejection.
2. Replace rejection with allowed-mode validation.
3. Construct a minimal policy-approved STRICT_FIXED plan using existing capability descriptors.
4. Execute it through `AdaptiveRuntimeEngine` using deterministic callback/handler.
5. Assert Runtime creates all attempts.
6. Assert workflow steps come from ApprovedPlan.
7. Assert legacy `RuntimeDriver.run` is not invoked.
8. Re-run existing Adaptive driver tests.

---

## 11. Unit Tests

```text
test_engine_accepts_policy_valid_strict_fixed_plan
test_engine_accepts_adaptive_bounded_plan
test_engine_rejects_unknown_or_invalid_mode
test_strict_and_adaptive_project_steps_through_same_workflow_function
test_strict_attempt_ids_are_runtime_created
test_strict_grants_are_runtime_created
```

---

## 12. Negative Tests

Primary family: **no second execution authority**.

```text
test_canonical_strict_does_not_call_legacy_runtime_driver_run
test_canonical_strict_rejects_unapproved_plan
test_canonical_strict_rejects_registry_digest_mismatch
test_canonical_strict_rejects_missing_required_input_kind_before_dispatch
test_canonical_strict_rejects_expired_grant_before_dispatch
```

Reuse existing adaptive negative behavior where possible.

---

## 13. Integration Test

Build one deterministic three-step ApprovedPlan:

```text
retrieve -> execute -> summarize
```

Use existing lightweight `execute_step` callback.

Run once as:

```text
STRICT_FIXED
```

and once as:

```text
ADAPTIVE_BOUNDED
```

Assert both produce:

```text
RuntimeTaskSession
RuntimeWorkflowStep[]
StepAttemptRecord[]
AdaptiveDispatchRecord[]
```

through the same `AdaptiveRuntimeEngine`.

Do **not** assert output feature parity with `run_smoke`.

---

## 14. Source Gate

PASS:

```text
STRICT_FIXED rejection removed/replaced safely
existing adaptive tests pass
no new engine class added
```

---

## 15. Mechanism Gate

PASS when deterministic capability callbacks are physically invoked under Runtime-created Grants for STRICT_FIXED.

---

## 16. Integration Gate

PASS when STRICT_FIXED completes all plan steps through `AdaptiveRuntimeEngine` and test evidence proves the legacy strict runner was not called.

---

## 17. Regression Risk

1. Existing code may use rejection as safety assertion.
2. `AdaptiveRuntimeSignature` name/metrics contain “adaptive”.
3. session naming may currently be adaptive-specific.
4. shadow semantics must not accidentally begin dispatching.
5. Mode-specific telemetry expectations may fail.

Do not clean up naming in this slice unless required for correctness.

---

## 18. Rollback

Reinstate the STRICT_FIXED guard.

No persisted data migration should make rollback difficult.

---

## 19. DESIGN_CONFLICT Stop Conditions

Stop if:

1. engine correctness genuinely requires Fixed precomputed `RuntimeDriverInput`;
2. ApprovedPlan cannot encode a Fixed deterministic DAG;
3. Runtime must delegate attempt creation back to the legacy strict path;
4. accepting STRICT_FIXED changes Adaptive execution semantics rather than only mode admission.

No such conflict is currently evidenced.

---

## 20. Evidence Artifacts

```text
artifacts/mrr-03a/strict_same_engine_session.json
artifacts/mrr-03a/strict_attempt_records.json
artifacts/mrr-03a/strict_dispatch_records.json
artifacts/mrr-03a/no_legacy_driver_call.txt
artifacts/mrr-03a/adaptive_regression_tests.txt
```

---

## 21. Next Allowed Slice

```text
MRR-03B Fixed Compatibility Mainline Bridge
```
