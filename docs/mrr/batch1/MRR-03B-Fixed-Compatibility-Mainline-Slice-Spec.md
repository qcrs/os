# MRR-03B — Fixed Compatibility Mainline Bridge Slice Spec


> **Source freeze**
>
> - Current Source of Truth: `qcrs/os`
> - Branch: `master`
> - Audited commit: `8bfc6464ec236c0e121911095fc283129b0e7696`
> - Historical/context evidence: `statebus.7z` (reference only)
> - This document is a **source-level implementation specification**, not an implementation record.
> - No production source was modified and no formal benchmark was executed in this review.


## 1. Goal

Connect the MRR-02 Static Role Recipe to the MRR-03A generalized Runtime through the product assembly seam, using a deliberately minimal deterministic compatibility provider set.

This slice proves:

```text
Fixed PlanSource
-> PlanPolicy
-> ApprovedPlanBundle
-> generalized Mainline assembly
-> same AdaptiveRuntimeEngine
-> deterministic compatibility execution
```

It does not migrate the legacy Fixed feature stack.

---

## 2. Architecture Invariant

```text
one execution engine
multiple plan sources
temporary compatibility providers
```

The compatibility layer may adapt old deterministic behavior into capability handlers.

It may not regain route/step/retry authority.

---

## 3. Current Source Truth

Legacy `run_smoke()` currently owns or pre-executes:

```text
TaskCompiler
RolePath planner
semantic plan
retrieval
semantic-state transfer
workspace/input artifacts
memory/replay selection
retriever selection
executor selection
Logit gate
CodeAct
summarizer
output materialization
validator/quality floor
memory candidate
```

before calling legacy `RuntimeDriver.run()`.

`AdaptiveMainlineRunner`, by contrast, already owns Runtime infrastructure and passes an `AdaptiveCapabilityDispatcher` into `AdaptiveRuntimeEngine`.

`AdaptiveMainlineBindings.builtin_handlers` already provides a low-cost compatibility seam.

---

## 4. Exact Source Files to Read

```text
statebus/runtime/static_role_recipe.py       # created MRR-02
statebus/runtime/adaptive_mainline.py
statebus/runtime/adaptive_runtime.py
statebus/runtime/adaptive_dispatcher.py
statebus/runtime/driver.py
statebus/runtime/smoke.py
tests/test_adaptive_mainline_integration.py
```

Read-only source references:

```text
statebus/runtime/role_path.py
statebus/retrieval/*
statebus/memory/*
statebus/state/*
```

---

## 5. Exact Files Expected to Change

Primary production:

```text
ADD    statebus/runtime/fixed_mainline.py
MODIFY statebus/runtime/adaptive_mainline.py
MODIFY statebus/runtime/driver.py
```

Prefer **no change** to `adaptive_dispatcher.py` because `builtin_handlers` already exists.

Tests:

```text
ADD tests/test_fixed_canonical_mainline.py
```

Optional import export file:

```text
MODIFY statebus/runtime/__init__.py
```

---

## 6. Exact Classes / Functions Affected

### New `FixedMainlineRequest` / builder

Responsibility:

```text
accept RuntimeIdentity
accept CanonicalTaskSpec
accept fixed recipe or ApprovedPlanBundle
construct STRICT_FIXED AdaptiveTaskEnvelope
construct compatibility CapabilityRegistry
construct AdaptiveMainlineBindings with deterministic builtin_handlers
delegate to generalized mainline
```

It must not execute steps itself.

### New `FixedCompatibilityHandlers`

Can be functions rather than a class.

Minimum handlers:

```text
retriever compatibility handler
executor compatibility handler
summarizer compatibility handler
```

They return typed `AdaptiveStepResult`.

### `AdaptiveMainlineRunner.run`

Generalize mode admission from:

```text
ADAPTIVE_BOUNDED only
```

to the canonical executable modes required by MRR-03A/03B.

Do not duplicate execution logic.

### `RuntimeDriver.run_mode`

Add canonical fixed request path/facade while retaining legacy strict input for regression.

---

## 7. Contract Changes

No provider abstraction yet.

Compatibility capability descriptors may continue to use:

```text
ExecutionKind.RUNTIME_BUILTIN
```

until MRR-04.

The fixed recipe and ApprovedPlan remain provider-neutral from the PlanSource perspective.

The compatibility registry is runtime assembly data, not planner-visible physical selection.

---

## 8. Minimum Deterministic Compatibility Provider

### It MUST

- receive `PlanStepProposal` and one-attempt `CapabilityGrant`;
- verify task/step/attempt binding;
- return an `AdaptiveStepResult`;
- produce exactly the output ref kind declared by its capability;
- write only within the provided attempt workspace if it writes at all;
- be deterministic and fixture-backed for tests.

### It MUST NOT

- call `RolePathRunner`;
- perform model routing;
- call remote/local LLM;
- perform semantic-state transfer;
- query shared memory;
- perform replay;
- run CodeAct;
- run Logit gate;
- reproduce APC/KV;
- choose the next step;
- create an Attempt;
- create a Grant;
- select another provider.

The purpose is Runtime reconciliation evidence, not feature parity.

---

## 9. Legacy Responsibility -> Target Owner Matrix

| Legacy Fixed responsibility | MRR-03B owner | Status |
|---|---|---|
| TaskCompiler / CanonicalTaskSpec admission | pre-mainline admission | KEEP |
| Planner prompt / semantic objective | not migrated | LEGACY ONLY |
| Fixed topology | StaticRoleRecipeCompiler | MIGRATE |
| Step creation | ApprovedPlan -> Runtime | MIGRATE |
| Retry / attempt creation | AdaptiveRuntimeEngine | MIGRATE |
| Capability grant | AdaptiveRuntimeEngine | MIGRATE |
| Retrieval implementation | deterministic compatibility handler | STUB/BRIDGE |
| Prompt rendering | not migrated | LEGACY ONLY |
| Semantic State | not migrated | FUTURE |
| Memory/replay | disabled for compatibility lane | FUTURE |
| Executor / CodeAct | deterministic compatibility handler | STUB/BRIDGE |
| Summarization LLM | deterministic compatibility handler | STUB/BRIDGE |
| Artifact truth | minimal typed output only | FUTURE FULL PARITY |
| Evaluator/benchmark | not switched | LEGACY ONLY |

---

## 10. Implementation Sequence

1. Add fixed product request/builder.
2. Use MRR-02 recipe to produce ApprovedPlanBundle.
3. Build a minimal logical capability registry.
4. Bind three deterministic builtin handlers.
5. Enter generalized Mainline with `STRICT_FIXED`.
6. Verify Mainline delegates to same Runtime Engine.
7. Verify Runtime creates attempts/grants.
8. Verify no legacy `run_smoke()` or `RuntimeDriver.run(RuntimeDriverInput)` call.
9. Leave legacy benchmark untouched.

---

## 11. Unit Tests

```text
test_fixed_mainline_builder_emits_strict_fixed_envelope
test_fixed_mainline_uses_static_recipe_bundle
test_compatibility_handlers_are_capability_scoped
test_compatibility_handlers_return_declared_ref_kinds
test_fixed_mainline_disables_memory_commit_for_minimal_bridge
```

---

## 12. Negative Tests

Primary family: **compatibility layer cannot regain orchestration authority**.

```text
test_fixed_handler_cannot_replace_approved_plan
test_fixed_handler_cannot_create_next_step
test_fixed_handler_result_with_wrong_grant_hash_fails
test_fixed_handler_result_with_wrong_attempt_id_fails
test_fixed_handler_wrong_output_ref_kind_fails
test_fixed_mainline_does_not_call_role_path_runner
test_fixed_mainline_does_not_call_legacy_runtime_driver_run
```

---

## 13. Integration Test

A single deterministic fixed task:

```text
TaskContract
-> StaticRoleRecipe
-> ApprovedPlanBundle
-> FixedMainlineRequest
-> AdaptiveMainlineRunner
-> AdaptiveRuntimeEngine
-> retrieve handler
-> execute handler
-> summarize handler
-> completed RuntimeTaskSession
```

Evidence must show:

```text
workflow_mode = strict_fixed
approved_plan_hash
three runtime workflow steps
three Runtime-created Attempt records
three CapabilityGrant hashes
completed = true
```

Do not compare benchmark quality or latency.

---

## 14. Source Gate

PASS when:

```text
FixedMainlineRequest exists
no new execution engine exists
legacy run_smoke source is untouched
```

---

## 15. Mechanism Gate

PASS when all three deterministic compatibility handlers physically execute under Runtime-created Grants.

---

## 16. Integration Gate

PASS when the fixed recipe completes via generalized Mainline + same Runtime Engine.

This is the first Batch-1 gate allowed to claim:

```text
canonical fixed control-flow integration
```

It may not claim feature parity.

---

## 17. Regression Risk

1. `AdaptiveMainlineRunner` currently asserts `ADAPTIVE_BOUNDED`.
2. planner telemetry naming assumes adaptive mode.
3. memory commit defaults to enabled.
4. source/state infrastructure is created even when bridge does not need it.
5. tests may assume role graph from adaptive fixture.

Mitigation:

```text
mode-specific admission only
memory_commit_enabled=False for compatibility bridge
reuse existing infrastructure rather than delete it
no legacy entrypoint switch
```

---

## 18. Rollback

Remove/disable Fixed canonical facade.

MRR-03A engine capability may remain; legacy strict continues to run.

---

## 19. DESIGN_CONFLICT Stop Conditions

Stop if:

1. `AdaptiveMainlineRunner` cannot admit STRICT_FIXED without changing Adaptive semantics;
2. Fixed compatibility handlers need State/Memory to produce even a minimal typed result;
3. the mainline requires an LLM planner invocation even when an ApprovedPlanBundle is already supplied;
4. a compatibility handler must choose another handler/provider to complete.

---

## 20. Evidence Artifacts

```text
artifacts/mrr-03b/fixed_approved_plan_bundle.json
artifacts/mrr-03b/fixed_canonical_session.json
artifacts/mrr-03b/fixed_attempt_records.json
artifacts/mrr-03b/fixed_dispatch_records.json
artifacts/mrr-03b/no_rolepath_no_legacy_driver.txt
```

---

## 21. Next Allowed Slice

```text
MRR-04 Logical Capability / Provider Eligibility + Binding
```
