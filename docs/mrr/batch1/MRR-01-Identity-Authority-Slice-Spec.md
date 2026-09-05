# MRR-01 — Identity + Authority Slice Spec


> **Source freeze**
>
> - Current Source of Truth: `qcrs/os`
> - Branch: `master`
> - Audited commit: `8bfc6464ec236c0e121911095fc283129b0e7696`
> - Historical/context evidence: `statebus.7z` (reference only)
> - This document is a **source-level implementation specification**, not an implementation record.
> - No production source was modified and no formal benchmark was executed in this review.


## 1. Goal

Introduce a minimal first-class runtime identity contract and freeze authority invariants without renaming every existing `task_id` or migrating all filesystem/state paths.

Success means later slices can prove exactly:

```text
External benchmark case
!= logical RuntimeTask
!= physical Run
!= Runtime Session
!= Step
!= Attempt
```

while existing legacy callers remain compatible.

---

## 2. Architecture Invariant

```text
PlanSource MAY identify a task.
Runtime assembly MAY create a run/session identity.
Only Runtime execution authority MAY create an Attempt.
Only Runtime execution authority MAY issue a CapabilityGrant.
Benchmark adapters MUST NOT become provider or attempt authority.
```

`task_id` remains a compatibility field in Batch 1; it is no longer treated as the complete identity model.

---

## 3. Current Source Truth

### 3.1 Existing identity fields

`statebus/runtime/session.py`

- `RuntimeTaskSession`
  - `session_id`
  - `trace_id`
  - `task_id`
  - `canonical_task_spec_hash`
  - `current_step_id`
  - `current_attempt_id`
- `RuntimeWorkflowStep`
  - `step_id`
  - `attempt_id`
- `StepAttemptRecord`
  - `task_id`
  - `step_id`
  - `attempt_id`
  - `worker_id`
  - lifecycle timestamps

The storage model can already represent distinct session/step/attempt identity.

### 3.2 Current identity creation is branch-specific

`RuntimeDriver.run()`:

```text
session-{task_id}
```

`AdaptiveRuntimeEngine.run()`:

```text
adaptive-session-{task_id}
adaptive-attempt-{global attempt counter}
```

`run_smoke()`:

```text
trace-smoke-{safe_task_id}-{time_ns}
step-execute
attempt-1
```

### 3.3 Filesystem coupling

`WorkspaceManager.layout_for_task(task_id)`:

```text
workspace_root / task_id
```

`WorkspaceManager.step_layout(...)`:

```text
workspace_root / task_id / steps / step_id
```

Therefore legacy `task_id` is a path component.

### 3.4 Task contract identity is duplicated as a hash

Current contracts repeatedly carry:

```text
canonical_task_spec_hash
```

in envelope/request/session rather than a single explicit task-contract identity object.

---

## 4. Exact Source Files to Read

Mandatory before editing:

```text
statebus/runtime/session.py
statebus/runtime/adaptive_runtime.py
statebus/runtime/adaptive_mainline.py
statebus/runtime/driver.py
statebus/runtime/workspace.py
statebus/runtime/smoke.py
statebus/contracts/adaptive.py
statebus/contracts/__init__.py
tests/test_adaptive_driver.py
tests/test_adaptive_mainline_integration.py
```

Reference-only:

```text
statebus/refs/models.py
statebus/state/*
```

Do not modify State/Memory in this slice.

---

## 5. Exact Files Expected to Change

Primary production files, target maximum 6:

```text
ADD    statebus/contracts/identity.py
MODIFY statebus/contracts/__init__.py
ADD    statebus/runtime/identity.py
MODIFY statebus/runtime/adaptive_mainline.py
MODIFY statebus/runtime/adaptive_runtime.py
MODIFY statebus/runtime/driver.py
```

Tests:

```text
ADD    tests/test_runtime_identity.py
EXTEND tests/test_adaptive_driver.py
EXTEND tests/test_adaptive_mainline_integration.py
```

### Explicitly not expected to change

```text
statebus/runtime/workspace.py
statebus/runtime/smoke.py
statebus/state/*
statebus/memory/*
```

If implementation requires those for correctness, stop and report scope expansion before editing them.

---

## 6. Exact Classes / Functions Affected

### New

`statebus/contracts/identity.py`

```text
TaskContractIdentity
RuntimeIdentity
```

`statebus/runtime/identity.py`

```text
validate_runtime_id_component(...)
compatibility_runtime_identity(...)
resolve_runtime_identity(...)
new_run_id(...)
```

Names may vary slightly, but responsibility may not.

### Existing

`AdaptiveMainlineRequest`
- add optional `runtime_identity`

`AdaptiveMainlineRunner.run`
- resolve identity once at product-assembly boundary
- assert `runtime_task_id` projection agrees with legacy `request.task_id`
- assert task contract hash agrees with `request.canonical_task_spec_hash`
- pass identity to Runtime request

`AdaptiveRuntimeRequest`
- add optional/required-by-canonical-path `runtime_identity`

`AdaptiveRuntimeEngine.run`
- stop re-deriving session identity when explicit identity exists
- use Runtime-created attempt IDs associated with the explicit run/session
- preserve legacy behavior through compatibility projection

`RuntimeDriverInput`
- optional `runtime_identity`

`RuntimeDriver.run`
- use compatibility projection for legacy callers
- do not migrate old workspace layout

---

## 7. Contract Changes

### 7.1 `TaskContractIdentity` v1

Minimum schema:

```text
contract_kind
contract_hash
public_context_hash      optional
input_asset_set_hash     optional
legacy_canonical_task_spec_hash
schema_version
```

Invariant:

```text
contract_hash == legacy_canonical_task_spec_hash
```

for current CanonicalTaskSpec-backed requests.

Do not invent a second semantic hash in MRR-01.

### 7.2 `RuntimeIdentity` v1

Minimum schema:

```text
external_case_id         optional, never a filesystem authority
runtime_task_id
run_id
session_id
trace_id
task_contract
schema_version
```

### 7.3 First-version type decision

Actually introduce:

```text
RuntimeTaskID semantics
RunID
SessionID
TaskContractIdentity
```

as fields/invariants of `RuntimeIdentity`.

Compatibility projection only:

```text
ExternalCaseID -> metadata string
legacy task_id -> runtime_task_id
canonical_task_spec_hash -> TaskContractIdentity.contract_hash
```

Do **not** introduce wrapper classes for every `StepID` and `AttemptID` yet. Existing `str` fields stay in place.

---

## 8. Compatibility Bridge

### Legacy caller

```text
task_id
trace_id
canonical_task_spec_hash
    |
    v
compatibility_runtime_identity(...)
    |
    + runtime_task_id = task_id
    + generated run_id
    + branch-compatible session_id
    + existing trace_id
    + TaskContractIdentity(hash=canonical_task_spec_hash)
```

### Canonical caller

Must provide an explicit identity or call a single product-owned factory before execution.

### Workspace

Legacy:

```text
workspace_root / task_id
```

remains unchanged in MRR-01.

Canonical Batch-1 path requires `runtime_task_id` to be path-safe, but full run-scoped workspace migration is deferred.

---

## 9. Explicit Non-Goals

Do not:

```text
rename every task_id field
change StateRef identity
change MemoryRef identity
change ArtifactRef identity
move workspace to /run_id/
change benchmark case IDs
implement late-result fencing
implement provider binding
change scheduler behavior
```

---

## 10. Implementation Sequence

1. Add identity contracts with canonical payload/hash.
2. Add safe component validation and compatibility identity factory.
3. Add `runtime_identity` to Adaptive Mainline request.
4. Resolve/validate identity once in `AdaptiveMainlineRunner.run`.
5. Pass identity into `AdaptiveRuntimeRequest`.
6. Make Adaptive Runtime use explicit session/run identity when present.
7. Add optional compatibility identity to legacy `RuntimeDriverInput`.
8. Freeze negative authority tests.
9. Run existing adaptive driver/mainline regression tests.

No step may require State/Memory changes.

---

## 11. Unit Tests

New `tests/test_runtime_identity.py`:

```text
test_runtime_identity_hash_is_stable
test_runtime_identity_distinguishes_reruns
test_runtime_task_id_is_stable_across_reruns
test_task_contract_identity_projects_canonical_spec_hash
test_explicit_session_id_is_not_silently_rederived
test_legacy_identity_projection_is_deterministic_except_run_id
```

---

## 12. Negative Tests

```text
test_runtime_task_id_rejects_parent_traversal
test_runtime_task_id_rejects_path_separator
test_run_id_rejects_empty_or_invalid_component
test_runtime_identity_rejects_task_id_projection_mismatch
test_runtime_identity_rejects_task_contract_hash_mismatch
test_mainline_rejects_envelope_identity_mismatch
```

Authority family:

```text
test_plan_source_has_no_attempt_factory
test_provider_callback_receives_attempt_but_cannot_allocate_next_attempt
```

The second test should be an API/contract test, not introspection theater.

---

## 13. Integration Test

Use the existing minimal `AdaptiveMainlineRequest` fixture style from `tests/test_adaptive_mainline_integration.py`.

Run twice with:

```text
same runtime_task_id
same TaskContractIdentity
different run_id
different session_id
```

Assert:

```text
same ApprovedPlan semantics
distinct RuntimeTaskSession.session_id
attempt records belong to their run/session
legacy task_id projection remains unchanged
```

Also run one legacy request with no explicit identity and assert compatibility startup still succeeds.

---

## 14. Source Gate

PASS only when:

```text
identity contracts import cleanly
canonical payload/hash tests pass
all new identity negative tests pass
legacy request construction remains source-compatible
```

---

## 15. Mechanism Gate

Not applicable to State/Memory mechanisms.

For this slice, mechanism evidence means:

```text
Runtime actually creates distinct run/session identity
and attempt records are attached to the resolved session
```

---

## 16. Integration Gate

PASS only when both:

```text
Adaptive canonical request uses explicit RuntimeIdentity
Legacy request still reaches existing path through compatibility projection
```

No claim of one-engine Fixed execution yet.

---

## 17. Regression Risk

High-risk points:

1. Dataclass constructor compatibility if new fields are inserted without defaults.
2. Tests/fixtures that compare complete canonical payloads.
3. Session IDs used as persistence keys.
4. Telemetry expectations containing current `adaptive-session-{task_id}` convention.
5. Code assuming `trace_id` and session_id can be reconstructed from task_id.

Mitigation:

```text
append optional fields
compatibility factory
do not rewrite workspace
do not remove legacy IDs
```

---

## 18. Rollback

Identity contracts and optional request fields are additive.

Rollback path:

```text
disable explicit RuntimeIdentity at assembly boundary
retain legacy task_id / trace_id / derived session conventions
```

No persisted State/Memory migration is allowed in this slice.

---

## 19. DESIGN_CONFLICT Stop Conditions

Stop immediately if:

1. `RuntimeTaskSession` cannot accept an externally resolved session identity without breaking persistence semantics.
2. `task_id` must be renamed across State/Memory to make the canonical path execute at all.
3. introducing `run_id` requires changing replay/memory identity before MRR-09.
4. any role/provider must allocate its own attempt in order for current Adaptive Runtime to function.

These conditions are **not currently evidenced**.

---

## 20. Evidence Artifacts

Codex must produce:

```text
artifacts/mrr-01/runtime_identity_payload.json
artifacts/mrr-01/runtime_identity_negative_tests.txt
artifacts/mrr-01/adaptive_identity_integration.txt
artifacts/mrr-01/legacy_identity_compatibility.txt
```

The payload must show:

```text
runtime_task_id
run_id
session_id
trace_id
task_contract_hash
```

No secrets/environment credentials.

---

## 21. Next Allowed Slice

Only:

```text
MRR-02 Fixed Recipe + Plan Provenance
```

after MRR-01 Integration Gate is PASS.
