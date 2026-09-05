# StateBus MRR Batch 2 — Codex Ready Pack

- Repository: `https://github.com/qcrs/os`
- Source of Truth branch: `feat/mrr-04-capability-provider-binding`
- Date: `2026-09-05`
- Mode: **Architecture / source review / implementation readiness only**
- Source code modified in this round: **NO**
- Tests modified in this round: **NO**


## Codex execution discipline

All implementation slices in this pack follow these rules:

- do not use Git SHA/history/merge-base analysis as implementation or file-management machinery; the named branch plus current working tree is sufficient;
- do not run full-repository pytest, Docker, vLLM, benchmark, coverage, whole-repo lint or whole-repo type checking unless a Slice explicitly requires it;
- targeted tests only, plus at most 1 directly adjacent regression by default;
- do not add defensive/future-proof abstractions, silent fallback, broad exception handling, generic retry frameworks or unrelated compatibility layers;
- do not refactor unrelated modules, rename architecture, or clean technical debt;
- after required targeted tests, mechanism evidence, `git diff --check`, and scope check pass, stop immediately; no post-implementation broad audit;
- do not commit, push, reset, clean, rebase, merge, or use `git add .`; user performs repository finalization after review.

## Final Batch 2 decision

Batch 1 (`MRR-01` → `MRR-04`) is treated as **CLOSED**.

Batch 2 is split by correctness boundary, not by document symmetry:

```text
MRR-05A
Invocation Identity + Wire Projection
        ↓
MRR-05B
Physical Response Correlation + Admission
        ↓
MRR-06A
Attempt Authority + Lifecycle Origin Truth
        ↓
MRR-06B
Late Result Fencing + Timeout/Cancel Settlement
```

`MRR-05` and `MRR-06` should **not** be merged into one implementation slice. The current source couples control protocol, RuntimeSession, RuntimeSupervisor and provider dispatch strongly enough that a single patch would be difficult to test, rollback and review.

## Central design decisions

1. **Do not add the historical full `ProtocolInvocationBinding` contract now.**
   Use the existing `ControlHeader + ExecRequest + ExecutionBindingReceipt + CapabilityGrant` as the canonical authority chain, but extend the wire projection with the missing execution scope.
   Add a physical `invocation_id`; do not create a second hashed authority graph.

2. **Do not add a generic `WorkerEvent` hierarchy now.**
   `AckReceived`, `RunStart`, `Heartbeat`, `SuccessResult`, `ErrorResult`, and `TrapFatal` already are typed worker/control messages.
   The missing problem is admission/origin and Attempt-aware lifecycle mutation, not another event wrapper.

3. **Do not add a generic `ControlResponseBinder`.**
   Add a narrow response-admission validator/receipt that proves one observed physical response belongs to the exact request scope before business code consumes it.

4. **`RuntimeTaskSession` becomes the semantic owner of `active_attempt(step)`.**
   `RuntimeSupervisor` becomes the operational/liveness tracker keyed by an Attempt-scoped key.
   `AdaptiveRuntimeEngine` remains the orchestrator, not the source of truth for active-attempt membership.

5. **A transport timeout is Runtime/transport truth, not a worker result.**
   The current subprocess transport synthesizes an `ErrorResult("subprocess_timeout")`; Batch 2 must stop representing locally derived timeout as if it came from the worker.

6. **Local in-process providers do not have worker ACKs.**
   They may truthfully transition `DISPATCHED → RUNNING` at local invocation.
   Protobuf subprocess worker ACK/RUN_START/HEARTBEAT are real worker observations.
   UTF-8 text carrier events are adapter-derived and must not be reported as native typed worker evidence.

7. **Late results are fenced at commit/admission, not “fixed” by trying to guarantee exactly-once execution.**
   StateBus should tolerate duplicate/late physical execution while guaranteeing stale attempts cannot mutate the current semantic Step.

## Documents

1. `StateBus-MRR-Batch2-Readiness-Review.md`
2. `StateBus-MRR-Batch2-Protocol-Attempt-Truth-Deep-Design.md`
3. `StateBus-MRR-Batch2-Source-Reconciliation-and-Reference-Study.md`
4. `StateBus-MRR-Batch2-Implementation-Plan.md`
5. `MRR-05A-Invocation-Identity-Wire-Projection-Slice-Spec.md`
6. `MRR-05B-Physical-Response-Correlation-Admission-Slice-Spec.md`
7. `MRR-06A-Attempt-Authority-Lifecycle-Origin-Truth-Slice-Spec.md`
8. `MRR-06B-Late-Result-Fencing-Settlement-Slice-Spec.md`

## NEXT_ALLOWED_SLICE

```text
MRR-05A
Invocation Identity + Wire Projection
```

Gate: **GO**.

Codex should read the Readiness Review, Deep Design, Implementation Plan and MRR-05A spec before touching code.
