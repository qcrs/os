# StateBus MRR Batch 1 — Implementation Readiness Review


> **Source freeze**
>
> - Current Source of Truth: `qcrs/os`
> - Branch: `master`
> - Audited commit: `8bfc6464ec236c0e121911095fc283129b0e7696`
> - Historical/context evidence: `statebus.7z` (reference only)
> - This document is a **source-level implementation specification**, not an implementation record.
> - No production source was modified and no formal benchmark was executed in this review.


## 1. Review Scope

This review converts the frozen Mainline Runtime Reconciliation architecture into source-level Codex execution slices.

Frozen architecture is **not reopened**:

```text
Canonical Product Assembly
    = generalized AdaptiveMainlineRunner

Canonical Execution Authority
    = generalized AdaptiveRuntimeEngine

Fixed RolePath
    = Static Recipe / PlanSource / compatibility provider adapters

Mechanism Harness
    = test / benchmark / diagnostic only
```

The review covers only:

```text
MRR-01 Identity + Authority Invariants
MRR-02 Fixed Recipe + Plan Provenance
MRR-03 STRICT_FIXED -> Same Canonical Runtime Engine
MRR-04 Logical Capability / Provider Eligibility + Binding
```

State/Memory lifecycle, scheduler, persistent workers, routing optimization, Dataset replacement, Latent/Hidden, APC and Explicit KV remain out of scope.

---

## 2. Source-Level Verdict

### 2.1 Overall

**No DESIGN_CONFLICT was found.**

The frozen architecture is implementable on the current `os/master` source base. The current code already contains most of the execution object graph needed for reconciliation:

- `PlanProposal`
- `PlanPolicyReport`
- `ApprovedPlan`
- `RuntimeWorkflowStep`
- `StepAttemptRecord`
- `RuntimeTaskSession`
- `CapabilityGrant`
- `AdaptiveMainlineRunner`
- `AdaptiveRuntimeEngine`
- `AdaptiveCapabilityDispatcher`

The work is therefore primarily **authority migration + contract separation**, not a third Runtime rewrite.

### 2.2 Required Slice Boundary Change

The original `MRR-03` is **NO-GO as one slice because it is oversized**.

It must be split into:

```text
MRR-03A Engine Mode Generalization
MRR-03B Fixed Compatibility Mainline Bridge
```

Reason: `run_smoke()` currently performs most Fixed work *before* `RuntimeDriver.run()`:

```text
TaskCompiler
-> RolePath planner
-> semantic-plan resolution
-> RetrieverFanoutPipeline
-> semantic state publication/selection
-> workspace materialization
-> memory lookup/replay decision
-> retriever route/tool selection
-> executor choice / Logit gate
-> optional CodeAct
-> summarizer
-> output materialization
-> validators / quality floor
-> RuntimeDriver.run(...)
```

Trying to move all of those responsibilities in one MRR-03 diff would violate the project's slice rule:

```text
one primary responsibility
one runtime seam
one negative-test family
~ <= 6 primary production files where possible
```

The corrected dependency chain is:

```text
MRR-01
  |
  v
MRR-02
  |
  v
MRR-03A
  |
  v
MRR-03B
  |
  v
MRR-04
```

---

# 3. Current Source Truth by Slice

## 3.1 MRR-01 — Identity

### SOURCE FACT

`RuntimeTaskSession` already separates:

```text
session_id
trace_id
task_id
current_step_id
current_attempt_id
```

and `StepAttemptRecord` already contains:

```text
task_id
step_id
attempt_id
worker_id
state
```

So the session/attempt data model is not missing.

### SOURCE FACT

The identity *creation policy* is not canonical.

Legacy Runtime:

```python
session_id = f"session-{{runtime_input.task_id}}"
```

Adaptive Runtime:

```python
session_id = f"adaptive-session-{{request.task_id}}"
attempt_id = f"adaptive-attempt-{{attempt_count}}"
```

`run_smoke()` separately constructs:

```python
trace_id = f"trace-smoke-{{safe_task_id}}-{{time.time_ns()}}"
step_id = "step-execute"
attempt_id = "attempt-1"
```

### SOURCE FACT

`WorkspaceManager.layout_for_task(task_id)` builds:

```text
workspace_root / task_id
```

and step workspaces build:

```text
workspace_root / task_id / steps / step_id
```

Therefore current `task_id` is simultaneously logical identity and filesystem component.

### DESIGN DECISION

MRR-01 must **not** perform a global rename or filesystem migration.

First version introduces one explicit runtime identity aggregate and preserves legacy projections:

```text
RuntimeIdentity
  external_case_id      optional metadata
  runtime_task_id       canonical logical runtime task id
  run_id                one physical run
  session_id            one runtime session
  trace_id              telemetry correlation id
  task_contract         TaskContractIdentity
```

Compatibility:

```text
legacy task_id == runtime_task_id
canonical_task_spec_hash == task_contract.contract_hash
```

`StepID` and `AttemptID` remain strings in existing contracts in MRR-01; their creation/validation law is frozen without a big-bang wrapper migration.

---

## 3.2 MRR-02 — Plan Provenance

### SOURCE FACT

`TaskCompiler` compiles/validates `CanonicalTaskSpec`. It does not construct `PlanProposal`, create runtime steps, or bind providers.

**Verdict:** do not evolve `TaskCompiler` into the Static Role Recipe compiler.

### SOURCE FACT

`RolePathRunner` is a large LLM/prompt/selection implementation and already exposes:

```python
propose_plan(...) -> PlanProposal
```

with the explicit comment that the result is an untrusted plan candidate and policy approval remains outside the role.

**Verdict:** reuse prompt/schema behavior where needed, but do not put static recipe authority inside `RolePathRunner`.

### SOURCE FACT

Fixed topology exists in multiple legacy representations:

```text
runtime/driver.py::build_default_workflow()
runtime/smoke.py::_workflow_template()
run_smoke() orchestration order
```

These are legacy execution projections, not a canonical logical plan.

### SOURCE FACT

`adaptive_plan_compiler.compile_required_input_wiring()` is already appropriately narrow:

- does not choose capabilities;
- does not add semantic stages;
- does not change goals;
- only completes/reorders required typed edges.

This should remain the mechanical normalizer.

### SOURCE FACT — Important

`PlanPolicyValidator.validate_with_single_repair()` guards schema-only repair with `_is_schema_only_repair()`.

But `AdaptiveMainlineRunner._assemble_plan()` has a separate `repair_plan` callback path which can replace the effective proposal and then simply run policy validation again.

Therefore current mainline provenance can record a semantic graph replacement as `policy_repair_used`.

### DESIGN DECISION

Add:

```text
PlanNormalizationReceipt
ApprovedPlanBundle
StaticRoleRecipeCompiler
```

and make every semantic change produce a new `PlanProposal`.

The target fixed recipe models **post-plan execution**:

```text
Retriever -> Executor -> Summarizer
```

Planner is a `PlanSource`, not a second execution step inside the fixed ApprovedPlan.

---

## 3.3 MRR-03 — One Engine

### SOURCE FACT

`RuntimeDriver.run_mode()` currently dispatches:

```text
strict_fixed      -> RuntimeDriver.run()
adaptive_bounded  -> AdaptiveMainlineRunner -> AdaptiveRuntimeEngine
adaptive_shadow   -> strict runner + audit
```

### SOURCE FACT

`AdaptiveRuntimeEngine.run()` explicitly rejects:

```text
WorkflowMode.STRICT_FIXED
```

with:

```text
strict_fixed_must_use_RuntimeDriver_run
```

### SOURCE FACT

Adaptive Runtime already derives `RuntimeWorkflowStep` directly from `ApprovedPlan`, calculates READY steps, creates attempts, issues CapabilityGrants, invokes the dispatcher and commits step lifecycle.

### SOURCE FACT

`run_smoke()` is the actual Fixed orchestration authority today. It precomputes and materializes most execution products before calling `RuntimeDriver.run()`.

### DESIGN DECISION

MRR-03 is split:

**MRR-03A** proves:

```text
same ApprovedPlan model
same RuntimeWorkflowStep projection
same Attempt authority
same AdaptiveRuntimeEngine
```

for `STRICT_FIXED`, using a deliberately minimal deterministic execution callback.

**MRR-03B** introduces a canonical Fixed product-assembly bridge:

```text
StaticRoleRecipe
-> ApprovedPlanBundle
-> generalized Mainline
-> same Runtime Engine
-> deterministic compatibility handlers
```

It does **not** migrate legacy Semantic State, Memory, CodeAct, Logit, prompt rendering or benchmark parity.

Legacy `run_smoke()` remains the regression/comparator lane.

---

## 3.4 MRR-04 — Capability / Provider

### SOURCE FACT

Current `CapabilityDescriptor` mixes:

**logical contract**
- capability id/version
- owner role
- accepted/required ref kinds
- input/output contract versions
- risk/side-effect class
- validators
- fallback capability
- completion criteria

with implementation/runtime facts:
- `ExecutionKind`
- `max_runtime_ms`
- `supports_replay`

### SOURCE FACT

`PlanPolicyValidator` consumes physical leakage:

```text
ExecutionKind.LLM_BOUNDED_PYTHON
ExecutionKind.RETRIEVAL_ADAPTER
descriptor.max_runtime_ms
```

### SOURCE FACT

`AdaptiveCapabilityDispatcher` selects physical implementation by:

```python
handler = self._handlers[descriptor.execution_kind]
```

### SOURCE FACT

`LLMConfig.ProviderConfig` describes OpenAI-compatible model endpoints. This is **not** equivalent to a StateBus execution provider.

### DESIGN DECISION

First version is a bridge, not a big-bang removal:

```text
CapabilityDescriptor
  |
  +--> LogicalCapabilityDescriptor projection
  |
  +--> legacy ExecutionProviderDescriptor projection
```

Provider decision is:

```text
READY Step
-> ProviderEligibilityProjection
-> stable deterministic choice
-> ExecutionBindingReceipt
-> CapabilityGrant
-> compatibility dispatcher
```

Eligibility v1 is hard-fact-only:

```text
logical capability compatibility
contract compatibility
risk compatibility
provider registered/enabled
runtime prerequisites
health/readiness
stable deterministic provider id
```

Explicitly excluded:

```text
latency prediction
queue scoring
learned routing
resource scheduling
cost optimization
```

---

# 4. Authority / Hidden Dependency Audit

| Question | Verdict |
|---|---|
| Does MRR-02 require MRR-01? | Yes, but only identity projection into proposal/bundle provenance. |
| Does MRR-03 require MRR-02? | Yes. Fixed must enter the engine as a policy-approved plan, not a legacy workflow tuple. |
| Does MRR-03 require the full MRR-04 provider abstraction first? | No. Existing `RUNTIME_BUILTIN` + `builtin_handlers` can be used as an intentionally temporary deterministic compatibility bridge. |
| Will MRR-04 force MRR-03B to be rewritten? | Not if MRR-03B does not invent a new provider API and uses only existing handler bindings. |
| Should MRR-04 move before MRR-03B? | No. First prove one execution authority; then separate physical provider identity. |
| Does MRR-01 need a workspace-layout migration? | No. Canonical new identity can be safe while legacy path remains a compatibility projection. |
| Does MRR-02 need RolePath prompt migration? | No. Static recipe compilation is independent from LLM role execution. |

---

# 5. Slice Size Audit

| Slice | Original Size | Verdict | Action |
|---|---:|---|---|
| MRR-01 | bounded | **OK** | Keep one slice |
| MRR-02 | bounded if recipe/provenance only | **OK** | Keep one slice |
| MRR-03 | too large | **SPLIT REQUIRED** | MRR-03A + MRR-03B |
| MRR-04 | medium/high | **OK WITH HARD SCOPE** | compatibility projection only |

---

# 6. GO / NO-GO

## MRR-01 — **GO**

Source contracts and call sites are sufficiently understood. No further architecture research is required.

## MRR-02 — **GO**

Current planner/normalizer/policy responsibility is sufficiently explicit, including the mainline repair/provenance gap.

## MRR-03 — **NO-GO AS ORIGINALLY SIZED**

The architecture is valid, but the original slice boundary is unsafe.

### MRR-03A — **GO**

The engine-mode boundary is localized and testable.

### MRR-03B — **GO AFTER MRR-03A**

The compatibility bridge can be implemented without migrating legacy mechanisms.

## MRR-04 — **GO AFTER MRR-03B**

Logical/physical coupling is concrete and a compatibility-projection migration path is clear.

---

# 7. Recommended Execution Order

```text
MRR-01  GO NOW
  |
  v
MRR-02
  |
  v
MRR-03A
  |
  v
MRR-03B
  |
  v
MRR-04
```

Do not allow Codex to skip an Integration Gate merely because the next spec is already marked source-ready.

---

# 8. Required Evidence Discipline

Every slice must distinguish:

```text
Source Gate
Mechanism Gate
Integration Gate
Competition Gate
```

For Batch 1:

```text
MRR-01 Competition Gate = NO
MRR-02 Competition Gate = NO
MRR-03A Competition Gate = NO
MRR-03B Competition Gate = NO
MRR-04 Competition Gate = NO
```

No Batch-1 slice may claim StateBus competition E2E completion.

---

# 9. DESIGN_CONFLICT Stop Conditions

Stop the implementation and return to architecture review only if source work discovers one of these:

1. `ApprovedPlan` cannot remain provider-neutral without changing user-visible task semantics.
2. Fixed execution cannot enter `AdaptiveRuntimeEngine` without reintroducing a second Attempt authority.
3. A required Fixed semantic step has no representable logical capability contract and cannot be represented through a compatibility handler.
4. A provider must change the semantic plan in order to execute an already-approved capability.
5. Identity separation requires rewriting State/Memory semantics inside Batch 1 rather than using compatibility projection.

None of these conflicts is currently evidenced by `os/master`.

---

# 10. Final Readiness Answer

**The first slice to give Codex is `MRR-01 Identity + Authority Invariants`.**

It is the smallest dependency root and can be implemented incrementally without touching State/Memory or changing runtime semantics. Its primary purpose is to make all subsequent evidence unambiguous:

```text
which logical task?
which physical run?
which session?
which task contract?
who created the attempt?
```

Only after MRR-01 Integration Gate passes should Codex receive MRR-02.
