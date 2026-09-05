# MRR-02 — Fixed Recipe + Plan Provenance Slice Spec


> **Source freeze**
>
> - Current Source of Truth: `qcrs/os`
> - Branch: `master`
> - Audited commit: `8bfc6464ec236c0e121911095fc283129b0e7696`
> - Historical/context evidence: `statebus.7z` (reference only)
> - This document is a **source-level implementation specification**, not an implementation record.
> - No production source was modified and no formal benchmark was executed in this review.


## 1. Goal

Create a provider-neutral static Fixed PlanSource and make plan normalization/policy provenance explicit.

The slice ends at:

```text
Static Role Recipe
-> PlanProposal
-> mechanical normalization
-> PlanNormalizationReceipt
-> PlanPolicyReport
-> ApprovedPlan
-> ApprovedPlanBundle
```

No provider executes.

---

## 2. Architecture Invariant

```text
TaskCompiler owns task admission, not runtime topology.

PlanSource may propose logical steps.
Normalizer may only perform mechanical binding.
PlanPolicy is the sole approval boundary.
Semantic graph changes require a new PlanProposal.
ApprovedPlan contains no physical provider identity.
```

Planner is a PlanSource. It is not automatically a runtime execution step.

---

## 3. Current Source Truth

### `TaskCompiler`

Current `TaskCompiler.compile()` creates/validates `CanonicalTaskSpec`.

It does not own:

```text
PlanStepProposal
ApprovedPlan
Attempt
CapabilityGrant
Provider
```

Therefore it stays task admission.

### `RolePathRunner`

Current class owns many role prompt/selection functions and also has:

```python
propose_plan(...) -> PlanProposal
```

The source explicitly calls this result an **untrusted plan candidate**.

Static recipe compilation should not be added into this LLM-heavy class.

### Legacy fixed topology

Two explicit topology helpers exist:

```text
statebus/runtime/driver.py::build_default_workflow
statebus/runtime/smoke.py::_workflow_template
```

and `run_smoke()` has additional implicit sequencing.

These are compatibility facts, not the new plan truth.

### Mechanical normalizer

`compile_required_input_wiring()` is already correctly scoped to typed edge completion.

### Mainline repair gap

`PlanPolicyValidator.validate_with_single_repair()` has a strict semantic-equivalence guard.

`AdaptiveMainlineRunner._assemble_plan()` currently has a separate `repair_plan` callback that can replace the effective proposal before another validation.

Therefore provenance is incomplete even though final policy validation still occurs.

---

## 4. Exact Source Files to Read

```text
statebus/runtime/compiler.py
statebus/runtime/role_path.py
statebus/runtime/adaptive_plan_compiler.py
statebus/runtime/plan_policy.py
statebus/runtime/adaptive_mainline.py
statebus/runtime/domain_packs.py
statebus/runtime/driver.py
statebus/runtime/smoke.py
statebus/contracts/adaptive.py
statebus/contracts/__init__.py
tests/test_adaptive_planner_policy.py
tests/test_adaptive_mainline_integration.py
```

---

## 5. Exact Files Expected to Change

Primary production files:

```text
ADD    statebus/runtime/static_role_recipe.py
ADD    statebus/contracts/plan_provenance.py
MODIFY statebus/contracts/__init__.py
MODIFY statebus/runtime/adaptive_mainline.py
MODIFY statebus/runtime/plan_policy.py
```

Optional only if imports demand it:

```text
MODIFY statebus/runtime/__init__.py
```

Tests:

```text
ADD    tests/test_static_role_recipe.py
ADD    tests/test_plan_provenance.py
EXTEND tests/test_adaptive_planner_policy.py
EXTEND tests/test_adaptive_mainline_integration.py
```

### Must not change in this slice

```text
statebus/runtime/compiler.py
statebus/runtime/role_path.py
statebus/runtime/driver.py
statebus/runtime/smoke.py
```

They are source references and legacy compatibility, not target owners for this slice.

---

## 6. Exact Classes / Functions Affected

### New `StaticRoleRecipeCompiler`

Suggested interface:

```text
compile(
    runtime_task_id,
    envelope,
    recipe,
    available_input_refs
) -> PlanProposal
```

The recipe must name only logical capabilities and contracts.

It must not:

```text
call LLM
run retrieval
select a physical provider
create workspace
create Attempt
issue Grant
```

### New provenance contracts

```text
PlanNormalizationReceipt
ApprovedPlanBundle
```

### Existing

`AdaptiveMainlineRunner._assemble_plan`
- emit/return explicit normalization receipt
- stop treating semantic proposal replacement as ordinary "repair"
- preserve original proposal provenance
- preserve fallback provenance

`PlanPolicyValidator`
- expose/reuse one semantic-equivalence predicate for mechanical repair
- avoid two independent definitions of "schema-only"
- review the hard-coded global minimum `2 <= len(steps)`:
  - if single-step plans are valid under an envelope/domain, move minimum semantics into the envelope/domain policy;
  - if current Batch-1 recipes all require >=2, do not broaden behavior unnecessarily, but document this as a policy assumption.

---

## 7. Contract Changes

### 7.1 `PlanNormalizationReceipt`

Minimum:

```text
normalization_id
normalizer_id
normalizer_version
source_proposal_hash
effective_proposal_hash
normalization_class = mechanical_binding
before_semantic_hash
after_semantic_hash
changed_fields
schema_version
```

Hard invariant:

```text
before_semantic_hash == after_semantic_hash
```

A canonical semantic hash must exclude non-semantic planner telemetry fields but include:

```text
task identity projection
step IDs
roles
logical capability IDs
goals
dependencies
input ref ids/kinds
output contracts
completion criteria
failure semantics
required input fields
final output contract
requested memory policy
```

### 7.2 `ApprovedPlanBundle`

Minimum provenance references:

```text
runtime_task_id
task_contract_hash
source_proposal_hash
effective_proposal_hash
normalization_receipt_hash
plan_policy_report_hash
approved_plan_hash
logical_capability_registry_digest
schema_version
```

It may embed objects or hold hashes plus objects; hash relationships must be verifiable.

### 7.3 Static recipe shape

First version should be explicit and small:

```text
recipe_id
recipe_version
steps[]
final_output_contract
requested_memory_policy
```

A representative competition-style fixed recipe should compile post-plan execution:

```text
retriever
  -> executor
  -> summarizer
```

Do not carry physical `ExecutionKind` or provider id in the recipe.

---

## 8. Compatibility Bridge

Legacy:

```text
build_default_workflow()
_workflow_template()
run_smoke role ordering
```

remain unchanged.

The new static recipe is opt-in and produces `PlanProposal`.

For structural parity evidence:

```text
legacy post-plan roles: retriever -> executor -> summarizer
new recipe roles:       retriever -> executor -> summarizer
```

Do not force the old runtime's synthetic `planner.plan` lifecycle step into the canonical ApprovedPlan merely to make lists equal.

`AdaptivePlannerAssemblyRecord` remains available as compatibility telemetry. New `ApprovedPlanBundle` is the stronger provenance object.

---

## 9. Explicit Non-Goals

Do not:

```text
execute any role
migrate RolePath prompts
migrate retrieval
migrate State/Memory
change provider dispatch
delete build_default_workflow
switch benchmark entrypoints
add routing optimization
```

---

## 10. Implementation Sequence

1. Define semantic plan hash helper and `PlanNormalizationReceipt`.
2. Define `ApprovedPlanBundle`.
3. Implement `StaticRoleRecipeCompiler`.
4. Compile a deterministic 3-step logical recipe into `PlanProposal`.
5. Run `compile_required_input_wiring()` as mechanical normalizer where needed.
6. Generate receipt and reject semantic hash drift.
7. Run `PlanPolicyValidator`.
8. Assemble bundle.
9. Tighten `AdaptiveMainlineRunner._assemble_plan()` so semantic replacement is not labeled schema repair.
10. Preserve legacy fallback/reporting compatibility.
11. Add structural parity and negative tests.

---

## 11. Unit Tests

```text
test_static_recipe_compiles_stable_plan_proposal
test_static_recipe_contains_no_provider_identity
test_static_recipe_contains_no_execution_kind
test_normalization_receipt_preserves_semantic_hash
test_required_input_wiring_is_mechanical
test_approved_plan_bundle_hash_links_all_provenance
test_same_recipe_same_contract_produces_stable_semantic_plan
```

---

## 12. Negative Tests

Primary family: **semantic mutation cannot masquerade as normalization/repair**.

```text
test_normalizer_cannot_change_capability
test_normalizer_cannot_change_goal
test_normalizer_cannot_add_semantic_stage
test_normalizer_cannot_change_memory_policy
test_normalizer_cannot_change_final_output_contract
test_mainline_repair_callback_cannot_replace_semantic_graph_as_schema_repair
test_invalid_role_cardinality_rejected_by_envelope_policy
test_dependency_cycle_rejected
```

Fallback provenance:

```text
test_fallback_is_recorded_as_fallback_not_plain_approved_repair
```

---

## 13. Integration Test

Plan-only integration:

```text
CanonicalTaskSpec
-> RuntimeIdentity from MRR-01
-> fixed recipe
-> PlanProposal
-> compile_required_input_wiring
-> PlanNormalizationReceipt
-> PlanPolicyValidator
-> ApprovedPlanBundle
```

Assert:

```text
no AdaptiveRuntimeEngine.run call
no Dispatcher call
no role LLM call
no workspace side effect
```

Compare only logical post-plan role topology against the legacy fixed path.

---

## 14. Source Gate

PASS when:

```text
StaticRoleRecipeCompiler exists
PlanNormalizationReceipt exists
ApprovedPlanBundle exists
semantic mutation negative tests pass
mainline repair provenance is unambiguous
```

---

## 15. Mechanism Gate

N/A.

Plan compilation is control-plane mechanism only.

---

## 16. Integration Gate

PASS when one current representative fixed task produces a policy-approved `ApprovedPlanBundle` without executing a provider.

---

## 17. Regression Risk

Main risks:

1. Existing tests rely on `_assemble_plan()` repair callback accepting a full replacement.
2. Fallback reporting may currently expect only boolean flags.
3. Canonical payload hashes will change if existing contracts are modified rather than wrapped.
4. Fixed topology confusion between legacy four lifecycle labels and target three post-plan execution roles.

Mitigation:

```text
add wrappers rather than rewriting PlanProposal/ApprovedPlan v1
keep AdaptivePlannerAssemblyRecord compatibility
keep legacy workflow helpers untouched
```

---

## 18. Rollback

Disable static recipe PlanSource and continue using existing adaptive proposal path.

New provenance contracts are additive.

Do not delete legacy workflow helpers in rollback or forward implementation.

---

## 19. DESIGN_CONFLICT Stop Conditions

Stop if:

1. a Fixed recipe cannot be expressed with existing `PlanStepProposal` semantics without physical provider fields;
2. PlanPolicy requires a physical provider to approve the logical plan;
3. current task semantics require Planner to execute *inside* the runtime DAG rather than serve as PlanSource;
4. mechanical required-input wiring necessarily changes capability/goal semantics.

Current source does not show these conflicts.

---

## 20. Evidence Artifacts

```text
artifacts/mrr-02/fixed_plan_proposal.json
artifacts/mrr-02/plan_normalization_receipt.json
artifacts/mrr-02/plan_policy_report.json
artifacts/mrr-02/approved_plan.json
artifacts/mrr-02/approved_plan_bundle.json
artifacts/mrr-02/semantic_mutation_negative_tests.txt
artifacts/mrr-02/legacy_structural_parity.txt
```

---

## 21. Next Allowed Slice

Only:

```text
MRR-03A Engine Mode Generalization
```

after MRR-02 Integration Gate PASS.
