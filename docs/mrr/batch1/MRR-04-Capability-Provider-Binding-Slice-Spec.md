# MRR-04 — Capability / Provider Binding Slice Spec


> **Source freeze**
>
> - Current Source of Truth: `qcrs/os`
> - Branch: `master`
> - Audited commit: `8bfc6464ec236c0e121911095fc283129b0e7696`
> - Historical/context evidence: `statebus.7z` (reference only)
> - This document is a **source-level implementation specification**, not an implementation record.
> - No production source was modified and no formal benchmark was executed in this review.


## 1. Goal

Separate logical capability authority from physical execution-provider binding with an additive compatibility projection.

The first version must establish:

```text
ApprovedPlan contains logical capability only
READY Attempt computes provider eligibility from hard facts
Runtime deterministically binds one provider
ExecutionBindingReceipt exists
CapabilityGrant is issued after binding
compatibility dispatcher executes the bound implementation
```

No routing optimization.

---

## 2. Architecture Invariant

```text
Logical Capability != Physical Provider

Planner/ApprovedPlan chooses WHAT.
Runtime binding chooses HOW.

Provider change:
    same semantic Step
    new Attempt
    new Binding
    new Grant
    unchanged ApprovedPlan
```

---

## 3. Current Source Truth

### Capability mixing

`CapabilityDescriptor` contains logical semantics and physical/runtime implementation data.

### Policy leakage

`PlanPolicyValidator` uses:

```text
descriptor.execution_kind
descriptor.max_runtime_ms
```

for authorization/budget logic.

### Dispatcher coupling

`AdaptiveCapabilityDispatcher` maps:

```text
ExecutionKind -> handler
```

and obtains `execution_kind` from the logical descriptor.

### DomainPack coupling

Capability registration constructs one combined descriptor per capability.

### Model provider is a different concept

`integrations/llm.py`:

```text
ProviderConfig
RoleLLMConfig.provider
RoleDispatchLLMClient
```

describe LLM service endpoints.

Do not reuse those types as generic Runtime execution-provider identity.

---

## 4. Exact Source Files to Read

```text
statebus/contracts/adaptive.py
statebus/runtime/capability_registry.py
statebus/runtime/domain_packs.py
statebus/runtime/adaptive_runtime.py
statebus/runtime/adaptive_dispatcher.py
statebus/runtime/adaptive_mainline.py
statebus/integrations/llm.py
tests/test_adaptive_capability_surface.py
tests/test_adaptive_driver.py
tests/test_adaptive_dispatcher.py
tests/test_adaptive_mainline_integration.py
```

---

## 5. Exact Files Expected to Change

Primary production target, keep <=6 where possible:

```text
ADD    statebus/contracts/provider_binding.py
ADD    statebus/runtime/provider_registry.py
MODIFY statebus/contracts/__init__.py
MODIFY statebus/runtime/capability_registry.py
MODIFY statebus/runtime/adaptive_runtime.py
MODIFY statebus/runtime/adaptive_dispatcher.py
```

`statebus/contracts/adaptive.py` change is allowed only for additive compatibility fields on `CapabilityGrant`; if that makes seven primary files, place binding metadata in a new grant wrapper first and defer schema bump.

Tests:

```text
ADD tests/test_provider_binding_reconciliation.py
EXTEND tests/test_adaptive_driver.py
EXTEND tests/test_adaptive_dispatcher.py
```

### Do not mass-edit `domain_packs.py` in v1

Use a compatibility projection from current registered descriptors first.

A domain-pack migration can follow once the bridge is proven.

---

## 6. Exact Classes / Functions Affected

### New contracts

```text
LogicalCapabilityDescriptor
ExecutionProviderDescriptor
ProviderRuntimeFacts
ProviderRejection
ProviderEligibilityProjection
ExecutionBindingReceipt
```

### New runtime registry/policy

```text
ExecutionProviderRegistry
project_legacy_capability(...)
project_legacy_provider(...)
compute_provider_eligibility(...)
select_provider_deterministically(...)
```

### Existing

`CapabilityRegistry`
- retain existing registration API
- add logical public-view/projection API
- planner-facing public view must not expose provider id
- do not delete `CapabilityDescriptor`

`AdaptiveRuntimeEngine.run`
- after READY + input validation + Attempt creation:
  - compute eligibility
  - choose stable provider
  - create binding receipt
  - then issue Grant
- no scoring/ranking beyond deterministic stable choice

`AdaptiveRuntimeEngine._issue_grant`
- consume final binding
- bind Grant to execution binding hash/provider identity either directly or through wrapper

`AdaptiveCapabilityDispatcher.dispatch`
- verify the binding corresponds to the implementation it will execute
- first version may internally bridge bound provider -> existing ExecutionKind/handler

---

## 7. Contract Changes

### 7.1 `LogicalCapabilityDescriptor`

Must include only semantic/authority surface:

```text
capability_id
version
owner_role
description
input_ref_kinds
required_input_ref_kinds
input_contract_version
output_ref_kinds
output_contract_version
side_effect_class
validator_ids
fallback_capability_id
completion_criteria_contract
semantic_contract_hash
```

Do not include:

```text
provider endpoint
model name
ExecutionKind
health
queue
latency
```

### 7.2 `ExecutionProviderDescriptor`

Minimum:

```text
provider_id
provider_version
provider_kind
supported_capability_ids
supported_semantic_contract_hashes
implementation_kind
runtime_prerequisites
enabled
schema_version
```

Compatibility provider may carry the old `ExecutionKind` internally.

### 7.3 `ProviderRuntimeFacts`

First version hard facts:

```text
provider_id
ready
healthy
prerequisites_satisfied
observed_at_ns
facts_digest
```

No dynamic performance model.

### 7.4 `ProviderEligibilityProjection`

Minimum:

```text
task_id/session_id/step_id/attempt_id
approved_plan_hash
logical_capability_id
logical_capability_version
semantic_contract_hash
provider_registry_digest
candidate_provider_ids
rejected_candidates[provider_id, reason_codes]
eligible_provider_ids
runtime_facts_digest
policy_version
projection_hash
```

### 7.5 `ExecutionBindingReceipt`

Minimum:

```text
binding_id
task_id
session_id
step_id
attempt_id
approved_plan_hash
logical_capability_id
logical_capability_version
semantic_contract_hash
provider_registry_digest
provider_runtime_facts_digest
eligibility_projection_hash
selected_provider_id
selected_provider_version
selected_provider_kind
binding_policy_version
binding_hash
```

Fields for rebind may be additive later:

```text
supersedes_binding_hash
rebind_reason_code
```

### 7.6 Grant binding

Frozen invariant:

```text
ExecutionBindingReceipt MUST exist before CapabilityGrant.
```

Grant must be cryptographically/logically linked to the binding.

Preferred eventual fields:

```text
provider_id
provider_version
execution_binding_hash
eligibility_projection_hash
```

If preserving `CapabilityGrant` v1 is necessary, use an additive wrapper:

```text
BoundCapabilityGrant(
    grant,
    execution_binding_hash,
    provider_id,
    provider_version
)
```

Do not silently issue an unbound grant and add telemetry afterward.

---

## 8. Compatibility Bridge

Current:

```text
CapabilityDescriptor
-> ExecutionKind
-> AdaptiveCapabilityDispatcher handler
```

Bridge:

```text
CapabilityDescriptor
  |
  +--> LogicalCapabilityDescriptor
  |
  +--> ExecutionProviderDescriptor(provider_id = stable legacy provider id,
                                    implementation_kind = existing ExecutionKind)
          |
          v
ProviderEligibilityProjection
          |
          v
ExecutionBindingReceipt
          |
          v
Bound Grant
          |
          v
Compatibility dispatcher
          |
          v
existing handler
```

This lets MRR-04 prove separation before `domain_packs.py` is rewritten.

---

## 9. Provider Eligibility v1

Allowed hard filters only:

1. provider is registered;
2. provider is enabled;
3. provider advertises the exact logical capability/version or semantic contract hash;
4. input/output contracts are compatible;
5. risk/side-effect requirements are allowed by the envelope;
6. runtime prerequisites are satisfied;
7. provider health/readiness is true;
8. provider can honor required runtime budget/contract.

Deterministic choice:

```text
sort by stable provider_id (or explicit deterministic registration priority)
select first eligible
```

Do not use:

```text
predicted latency
queue depth score
learned model
historical win rate
GPU load score
cost score
```

---

## 10. Explicit Non-Goals

```text
routing optimization
resource scheduler
persistent worker selection
latency prediction
queue scoring
learned routing
fallback graph redesign
LLM endpoint redesign
APC/KV provider work
remote provider implementation
```

---

## 11. Implementation Sequence

1. Define logical/provider/binding contracts.
2. Add `ExecutionProviderRegistry`.
3. Add compatibility projection from existing `CapabilityDescriptor`.
4. Generate one legacy provider per current implementation surface used by MRR-03B.
5. Add deterministic hard eligibility.
6. Add execution binding receipt.
7. Modify Runtime so binding happens before Grant.
8. Link Grant to binding.
9. Modify dispatcher to honor/verify bound provider through compatibility mapping.
10. Add no-eligible-provider fail-closed test.
11. Add two-provider deterministic/rebind contract tests without implementing runtime scheduling.

---

## 12. Unit Tests

```text
test_legacy_capability_projects_to_logical_descriptor
test_legacy_capability_projects_to_execution_provider
test_logical_descriptor_excludes_execution_kind
test_logical_public_view_excludes_provider_identity
test_provider_registry_digest_is_stable
test_eligibility_accepts_compatible_ready_provider
test_eligibility_rejects_unhealthy_provider
test_eligibility_rejects_semantic_contract_mismatch
test_deterministic_binding_is_stable
test_binding_hash_covers_selected_provider_and_attempt
```

---

## 13. Negative Tests

Primary family: **no execution without valid binding**.

```text
test_no_eligible_provider_fails_before_grant
test_grant_cannot_be_issued_without_binding
test_dispatch_rejects_provider_binding_mismatch
test_binding_rejects_wrong_attempt_id
test_binding_rejects_wrong_approved_plan_hash
test_provider_change_does_not_change_approved_plan_hash
test_planner_public_surface_contains_no_provider_id
```

Do not add queue/latency tests.

---

## 14. Integration Test

Use the canonical fixed lane from MRR-03B.

For each logical step:

```text
READY
-> eligibility projection
-> one selected provider
-> binding receipt
-> bound Grant
-> compatibility dispatcher
-> AdaptiveStepResult
```

Assert every Attempt has:

```text
exactly one eligibility projection
exactly one active binding
exactly one bound Grant
```

and the `ApprovedPlan` hash stays provider-neutral.

---

## 15. Source Gate

PASS:

```text
logical/provider contracts import
legacy descriptors project without mass domain-pack rewrite
planner public view is provider-neutral
```

---

## 16. Mechanism Gate

PASS when the bound compatibility provider is actually the implementation invoked by the dispatcher.

Telemetry-only binding is not sufficient.

---

## 17. Integration Gate

PASS when the MRR-03B fixed canonical task completes and every executed Attempt has:

```text
ProviderEligibilityProjection
ExecutionBindingReceipt
Bound CapabilityGrant
```

---

## 18. Regression Risk

1. `PlanPolicyValidator` currently reads `ExecutionKind` and `max_runtime_ms`.
2. Dispatcher keys directly on `ExecutionKind`.
3. Many tests instantiate `CapabilityDescriptor` directly.
4. Domain packs rely on descriptor digest.
5. ApprovedPlan stores capability registry digest.
6. Grant canonical hash changes if fields are added.

Mitigation:

```text
compatibility projection
no descriptor deletion
no mass DomainPack rewrite
new logical registry digest distinct from legacy registry digest
additive grant wrapper if schema compatibility is too costly
```

---

## 19. Rollback

Disable provider projection/binding and return Runtime to legacy descriptor -> ExecutionKind dispatcher path.

MRR-03 one-engine path must remain functional after rollback.

---

## 20. DESIGN_CONFLICT Stop Conditions

Stop if:

1. a logical capability cannot be described without naming its current `ExecutionKind`;
2. planner/policy semantics genuinely require choosing a physical provider before ApprovedPlan;
3. existing handler behavior differs semantically between providers advertised as the same logical capability;
4. dispatcher cannot verify the chosen provider without creating a second routing authority.

No such conflict is currently proven.

---

## 21. Evidence Artifacts

```text
artifacts/mrr-04/logical_capability_registry.json
artifacts/mrr-04/execution_provider_registry.json
artifacts/mrr-04/provider_eligibility_projection.json
artifacts/mrr-04/execution_binding_receipt.json
artifacts/mrr-04/bound_capability_grant.json
artifacts/mrr-04/provider_binding_negative_tests.txt
artifacts/mrr-04/canonical_fixed_binding_integration.txt
```

---

## 22. Next Allowed Slice

Not State/Memory automatically.

Return to the Batch-1 review gate and confirm MRR-01/02/03A/03B/04 evidence set is coherent before opening the next Runtime truth slice.
