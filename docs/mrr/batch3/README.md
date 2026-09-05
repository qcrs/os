# StateBus MRR Batch 3 — Codex Ready Pack v2

Status:

```text
Batch 1 = CLOSED
Batch 2 = CLOSED / BATCH_2_GATE_PASS
Batch 3 = DESIGN FROZEN FOR IMPLEMENTATION SLICES
```

This pack contains design/specification material only. It does not contain
StateBus production source modifications.

## Frozen Batch 3 sequence

```text
MRR-07A
State Access Authority + Immutable Ref Identity
        ↓
MRR-07B
State Ownership + Pin / Release Lifecycle
        ↓
MRR-08
Artifact / Evidence Truth
```

`MRR-07B` is blocked by 07A implementation/gate acceptance.

`MRR-08` is design-ready, but implementation should follow State authority
closure unless the reviewer explicitly authorizes parallel work.

## v2 amendments

The v2 freeze adds four explicit boundaries:

1. Canonical State access authorization applies to **local/in-process and
   cross-process** consumers; direct `load/get/resolve_*` is not business-level
   authority.
2. `RUNTIME_INTERMEDIATE` is constrained by the current active
   Attempt/Binding/Grant and authorized output contract; it is not a general
   Runtime expansion privilege.
3. Attempt settlement revokes **new** State authority but does not require
   mid-flight revocation of an already-dispatched invocation's already-issued
   witness; Batch 2 result fencing remains the semantic safety boundary.
4. Existing `ExecutionArtifactRef.verification_state` and `replay_ready` are
   compatibility projections, not independent Artifact authority roots.

## Non-goals

```text
no generation by default
no BoundRefHandle
no State-owned Attempt authority
no distributed reference counting
no mid-flight mapping revocation framework
no generic capability subsystem
no Memory/replay implementation in 07A/07B
```

## Next allowed implementation slice

```text
MRR-07A
```
