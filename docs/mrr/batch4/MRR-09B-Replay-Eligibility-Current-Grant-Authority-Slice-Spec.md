# MRR-09B Slice Spec — Replay Eligibility + Current Grant Memory Authority

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
BLOCKED_BY_MRR-09A
```

## Invariant

> **A Memory lookup hit is only a candidate. Current Runtime must explicitly authorize the Memory for the current capability execution, and verified procedure reuse must be decided for the current active Attempt.**

## Current source gap

Current:

```text
MemoryMatchResult
→ _memory_inputs_for_step()
→ downstream role input
```

The Memory ID is not an explicit current Grant Memory authority edge.

Current `MemoryCompatibilityDecision` also lacks:
- current run/session/Step/Attempt;
- current BoundCapabilityGrant;
- current provider binding;
- current capability version;
and still reads `replay_ready`.

## Authority model

Do not create:

```text
MemoryAccessGrant
Replay-owned Attempt
```

Do not use ReplayEligibilityReceipt as an access capability.

Recommended:

```text
CapabilityGrant
  ├─ input_ref_ids   # ApprovedPlan semantic data edges
  └─ memory_ref_ids  # Runtime-only supplemental Memory authority
```

`memory_ref_ids`:
- selected only by Runtime;
- not Planner-proposed semantic graph;
- part of Grant hash;
- requires valid MemoryAdmissionReceipt and current policy.

### Grant mint ordering

The current source selects Memory after Grant issuance. MRR-09B must move the
selection/authorization seam before final immutable Grant mint rather than
mutating a Grant after issuance:

```text
active Attempt
→ ExecutionBindingReceipt
→ Memory lookup candidates
→ validate admission + compatibility
→ Runtime selects memory_ref_ids
→ mint CapabilityGrant(memory_ref_ids=...)
→ optional ReplayEligibilityReceipt
→ dispatch
```

`ASSIST_CONTEXT` requires current Grant Memory authority but no
ReplayEligibilityReceipt. `VERIFIED_PROCEDURE_REUSE` requires both.

## ReplayEligibilityReceipt

Required for procedure reuse.

It binds:
- MemoryAdmissionReceipt;
- current task/run/session/Step/Attempt;
- current ExecutionBinding;
- current CapabilityGrant;
- current capability ID/version;
- task contract;
- input schema;
- Runtime signature;
- validator digest;
- output contract;
- recipe hash;
- decision/reason/policy.

Canonical mode:

```text
VERIFIED_PROCEDURE_REUSE
```

## Assist Memory

Assist is not replay.

Required:

```text
valid MemoryAdmissionReceipt
+ Memory ID in current CapabilityGrant.memory_ref_ids
+ current policy allows assist
```

No ReplayEligibilityReceipt.

## Compatibility

Procedure reuse should bind only current source-backed dimensions:
- capability semantic identity;
- execution kind;
- recipe hash;
- task family / intent;
- required outputs;
- required tools / argument shape where represented;
- output contract;
- input schema;
- Runtime compatibility signature;
- validator digest.

Exact historical input-lineage equality is not required because current input
is intentionally recomputed. Current consumer lineage may be recorded for
audit, but it must not be an eligibility equality predicate for procedure
reuse.

## `replay_ready`

Canonical eligibility ignores it as authority.

```text
ExecutionArtifactRef.replay_ready
=
legacy compatibility projection only
```

## Likely production files

```text
statebus/contracts/adaptive.py
statebus/contracts/*memory*
statebus/memory/store.py
statebus/runtime/adaptive_runtime.py
statebus/runtime/adaptive_dispatcher.py
statebus/runtime/replay_eligibility.py  # optional
```

## Non-goals

```text
exact Artifact replay
strict history replay rewrite
Memory query per role
planner Memory
generic policy DSL
global namespace/tenant system
```

## Test blueprint

Primary:
1. Task A admitted Memory → Task B current Grant + eligible procedure receipt;
2. compatibility/admission mismatch → no eligible replay;
3. B stale / C active → B eligibility cannot authorize C.

Adjacent:
- one `lookup_hybrid()` regression.

## Implementation discipline

When implementation is explicitly authorized:

```text
NO SHA / HISTORY AUDIT
NO DEFENSIVE FALLBACK
NO OVERPROGRAMMING
NO FULL-SUITE TESTING
NO MRR-09C WORK
```

Testing limit:

```text
<= 3 primary targeted test functions
+ at most 1 directly adjacent regression
```

Do not mutate an already-issued CapabilityGrant and do not add a
MemoryAccessGrant. User owns Git actions. After required tests and
`git diff --check`, STOP and request `MRR-09B_GATE_REVIEW`.

## Gates

```text
SOURCE_GATE:
current Memory injection outside explicit Grant authority demonstrated.

MECHANISM_GATE:
lookup hit alone cannot reach consumer/replay.

INTEGRATION_GATE:
producer A remains historical; consumer B receives fresh Runtime authority.

COMPETITION_GATE:
later Agent can retrieve and be explicitly authorized to reuse historical Memory.
Benefit remains UNVALIDATED.
```

## PASS

```text
Memory lookup != current input authority
Replay eligibility != current input authority
CapabilityGrant remains current authority owner
```

## Next

```text
MRR-09B_GATE_REVIEW
```

Only after Gate PASS:

```text
MRR-09C-Canonical-Memory-Consumption-Current-Attempt-Commit
```
