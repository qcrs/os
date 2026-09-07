# MRR-09C Slice Spec — Canonical Memory Consumption + Current Attempt Commit

> Project: StateBus Mainline Runtime Reconciliation
> Phase: Batch 4 / MRR-09 — Memory / Replay
> Mode: DESIGN ONLY / READ ONLY
> Design input: Batch 3 closed truth + current MRR-09 source reconciliation.
> No SHA/history identity is used as design evidence.
> No source/test modification, no test execution, no benchmark.

Frozen prerequisites:

```text
Batch 1 = CLOSED
Batch 2 = CLOSED
Batch 3 = CLOSED
MRR-07 = CLOSED
MRR-08 = CLOSED

State Identity / Authority / Lifetime = FROZEN
Artifact Candidate / Runtime Verification Truth = FROZEN
```


## Status

```text
BLOCKED_BY_MRR-09B
```

## Invariant

> **A current Attempt may consume assist Memory or reuse a verified historical procedure, but the resulting semantic output can commit only through the existing current Attempt result-admission authority.**

## Canonical MRR-09 modes

### ASSIST_CONTEXT

```text
historical Memory
→ current role context/input
→ current execution runs normally
```

Required:
- MemoryAdmissionReceipt;
- current CapabilityGrant.memory_ref_ids.

No ReplayEligibilityReceipt.

### VERIFIED_PROCEDURE_REUSE

```text
historical verified recipe
→ current input
→ current execution/recompute
→ current validator
→ current AdaptiveStepResult
```

Required:
- MemoryAdmissionReceipt;
- current CapabilityGrant.memory_ref_ids;
- ReplayEligibilityReceipt.

## Current Attempt authority

```text
Attempt B active
→ current result B
→ RuntimeSessionManager.admit_attempt_result(B)
→ COMMIT or FENCE
```

Therefore:

```text
ReplayAdmissionReceipt = NOT_REQUIRED
```

## Stale semantics

```text
B eligibility valid
B execution delayed
B settles
C active
late B result
→ FENCED_STALE_ATTEMPT
→ no workflow mutation
→ no Artifact promotion
→ no final adoption
```

The historical Memory remains admitted.

## Producer / consumer provenance

Preserve both:

```text
Produced by:
Task A / Session A / Step X / Attempt A1
ArtifactVerificationReceipt A
MemoryAdmissionReceipt M

Consumed by:
Task B / Session B / Step Y / Attempt B3
CapabilityGrant B
ReplayEligibilityReceipt B (procedure mode)
```

Do not overwrite producer metadata.

## Competition metric truth

Freeze:

```text
assist visible != work skipped

recipe actually reused
→ may record specific skipped generation/LLM work
```

Formal benefit remains outside MRR-09 implementation.

## Exact Artifact replay

Explicit non-goal.

The strict/history `runtime/replay.py` lane remains non-canonical.

## Likely production files

```text
statebus/runtime/adaptive_dispatcher.py
statebus/runtime/adaptive_runtime.py
statebus/memory/models.py
statebus/runtime/adaptive_mainline.py
```

## Non-goals

```text
direct exact Artifact resurrection
provider-bypass optimization
new worker lifecycle
new Attempt type
Memory-owned final adoption
benchmark/performance tuning
```

## Test blueprint

Primary:
1. cross-task verified procedure reuse recomputes current input and commits as B;
2. stale B after eligibility is fenced;
3. assist remains normal execution and records no false skip.

Adjacent:
- one MRR-08 production Artifact verification integration.

## Implementation discipline

When implementation is explicitly authorized:

```text
NO SHA / HISTORY AUDIT
NO DEFENSIVE FALLBACK
NO OVERPROGRAMMING
NO FULL-SUITE TESTING
NO EXACT_ARTIFACT_REPLAY
NO MRR-10 WORK
```

Testing limit:

```text
<= 3 primary targeted test functions
+ at most 1 directly adjacent regression
```

Do not add fake worker lifecycle for procedure reuse. Current recompute/reuse
must continue through the current Attempt's normal result admission. User owns
Git actions. After required tests and `git diff --check`, STOP and request
`MRR-09C_GATE_REVIEW`.

## Gates

```text
SOURCE_GATE:
assist vs procedure reuse mechanics are distinguishable.

MECHANISM_GATE:
reuse result still traverses current Attempt admission.

INTEGRATION_GATE:
historical A → current B actual reuse → current Artifact truth.

COMPETITION_GATE:
producer/consumer reuse auditable; performance benefit still UNVALIDATED.
```

## PASS

```text
No Memory/replay path can mutate current workflow without current Attempt admission.
```

After implementation PASS:

```text
NEXT_ALLOWED_ACTION = MRR-09C_GATE_REVIEW
```

Only after `MRR-09C_GATE_PASS`:

```text
Batch 4 = READY_FOR_GATE_REVIEW
```

No MRR-10 work is authorized.
