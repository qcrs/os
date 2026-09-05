# StateBus MRR Batch 2 — Implementation Plan

## 1. Purpose

Translate the Batch 2 architecture into four small Codex-executable slices.

Rule:

```text
one Slice
=
one primary correctness invariant
```

No Slice may use “full pytest”, Docker, vLLM, full benchmark, coverage, whole-repo mypy or whole-repo lint as its default gate.

No Slice may use Git SHA/history/merge-base analysis for source management or evidence. Do not create source-SHA ledgers.

Testing bullets in Slice Specs are **coverage requirements, not a mandate to create one test per bullet**. Consolidate them into the smallest useful targeted test set. Default budget: targeted Slice tests plus at most one directly adjacent regression.

Implementation must remain minimal: no defensive/future-proof abstraction, generic retry/fallback framework, silent repair, unrelated cleanup, or post-pass broad audit. Once required gates, `git diff --check`, and scope check finish, stop.

---

## 2. Dependency DAG

```text
MRR-04 PASS
  ↓
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
Late Result Fencing + Settlement
  ↓
BATCH 2 GATE
  ↓
MRR-07 State Lifecycle readiness
```

---

## 3. Slice scope summary

| Slice | Primary invariant | Expected primary production scope | Mechanism proof |
|---|---|---|---|
| MRR-05A | Physical request/event does not lose Runtime/Binding/Grant scope | control message/schema/worker + request construction | real UDS + real subprocess round trip carries exact scope |
| MRR-05B | Raw physical response is never business-consumed before exact correlation/contract admission | new narrow control admission + transport/dispatcher | real UDS success admitted; mismatch/duplicate rejected |
| MRR-06A | Semantic active Attempt has one owner; lifecycle origin is truthful | session + supervisor + adaptive runtime | no synthetic remote ACK; real protobuf worker events remain distinguishable |
| MRR-06B | Terminal/superseded A can never mutate Step after B becomes active | session + supervisor + runtime + narrow transport seam | controlled A-timeout/B-active/late-A-success fencing |

---

## 4. Cross-slice invariants

### Invariant I — no duplicate authority object

Do not add a second canonical object that independently chooses provider or capability.

### Invariant II — exact request/response scope

All physical events/results must preserve:

```text
task (RuntimeTaskID wire projection)
run
session
step
attempt
invocation
binding hash
grant hash
protocol version
```

### Invariant III — local != remote

Local in-process provider:

```text
no worker ACK
no worker heartbeat
```

Remote/subprocess protobuf worker:

```text
ACK/RUN_START/HEARTBEAT only from observed worker messages
```

Text carrier:

```text
adapter-derived lifecycle
```

### Invariant IV — session owns active Attempt

A Step may have historical Attempts A/B/C, but exactly one may be active for commit.

### Invariant V — late result is expected failure mode

Do not throw broad exceptions and hope it disappears.

```text
stale → fence → audit → no commit
```

### Invariant VI — no exactly-once claim

Execution can happen more than once. Commit/admission must be at-most-one-current-attempt.

---

## 5. File-Level Reconciliation Map

### `statebus/control/messages.py`
`EXTEND`

Add Batch 2 header fields; strict identity helpers only if required.

### `statebus/control/statebus_control.proto`
`EXTEND`

Additive field numbers only.

### `statebus/control/schema.py`
`EXTEND`

Mirror new additive fields for current dynamic schema mechanism.
Do not redesign codegen in the same slice.

### `statebus/control/subprocess_worker.py`
`EXTEND`

Reject missing required invocation scope; echo request scope; do not become the Runtime authority.

### `statebus/control/transport.py`
`EXTEND` in 05B/06B only

Use response admission; represent local transport timeout as transport outcome, not fake worker result.

### `statebus/control/admission.py`
`ADD` in 05B

Small, explicit physical response validator/receipt.

### `statebus/runtime/adaptive_dispatcher.py`
`EXTEND`

Construct physical request from Runtime/BoundGrant scope and consume only admitted response.

### `statebus/runtime/adaptive_runtime.py`
`EXTEND`

Pass exact Runtime identity to physical construction as needed; activate/settle Attempts; remove synthetic ACK/RUN_START; enforce result admission.

### `statebus/runtime/session.py`
`EXTEND` in 06A/06B

Own active attempt per Step and atomic-ish activation/settlement invariants.

### `statebus/runtime/supervisor.py`
`REFACTOR` narrowly in 06A

Attempt-scoped operational key instead of step-only key.

### DO NOT TOUCH

```text
statebus/state/**
statebus/memory/**
statebus/runtime/workspace.py
statebus/runtime/replay.py
deploy/**
docker/**
scripts/**
```

unless a `DESIGN_CONFLICT` proves the Slice impossible without crossing the boundary.

---

## 6. MRR-05A implementation sequence

1. Freeze field numbers and expected identity semantics.
2. Extend Python `ControlHeader`.
3. Extend `.proto`.
4. Extend dynamic `schema.py`.
5. Make encode/decode fail closed on required Batch 2 identity/version.
6. Update canonical physical request construction:
   - real trace/run/session from RuntimeIdentity;
   - invocation_id created once per physical exchange;
   - binding/grant hashes projected.
7. Worker validates presence/equality of duplicate grant hash and echoes immutable header.
8. Keep text carrier compatible by preserving request scope.
9. Targeted real subprocess test.

No response-admission framework yet beyond round-trip equality tests.

---

## 7. MRR-05B implementation sequence

1. Add `ControlResponseAdmissionReceipt`.
2. Add validator for legal event class and exact header scope.
3. Add per-exchange terminal-event guard.
4. Add operation-specific terminal result checks needed by current integrated semantic-select path.
5. Apply admission before dispatcher consumes selection payload.
6. Unit negatives:
   - wrong session;
   - wrong attempt;
   - wrong invocation;
   - wrong binding/grant;
   - wrong result type;
   - output contract mismatch;
   - duplicate terminal.
7. Real UDS integration success.
8. Optional UDS loopback negative injection; no need for a generalized malicious-worker framework.

---

## 8. MRR-06A implementation sequence

1. Add Session methods:
   - activate attempt for Step;
   - get active attempt;
   - settle current attempt;
   - refuse mutation by non-active attempt where commit-authoritative.
2. Change Supervisor key to Attempt-scoped identity.
3. Add/retain `BOUND` transition if required by implementation.
4. Replace `_dispatch_lifecycle()` synthetic remote ACK/RUN_START behavior:
   - register/bind/dispatch only before invocation;
   - local handler enters RUNNING truthfully;
   - no local ACK.
5. Preserve/capture real subprocess ACK/RUN_START/HEARTBEAT as physical invocation observations with origin.
6. Do not map provider-internal worker events to semantic Step worker identity unless source explicitly says the bound provider is that subprocess.
7. Regression:
   - canonical local handler path succeeds;
   - attempt history remains intact across two attempts.

---

## 9. MRR-06B implementation sequence

1. Replace synthesized worker `ErrorResult(subprocess_timeout)` with local transport timeout outcome.
2. On timeout/cancel:
   - terminalize/settle A;
   - clear active A if still active;
   - best-effort cancel/terminate physical work.
3. Start B only after A settlement.
4. Route any late A response through:
   - physical 05B admission;
   - session active-attempt fence.
5. Emit explicit fence/audit receipt/telemetry.
6. Assert no workflow output/state mutation from A.
7. Assert B stays active and can complete.
8. Duplicate terminal for same invocation is rejected/idempotently ignored according to admission policy.
9. No generic retry scheduler.

---

## 10. Test strategy

### Targeted tests

Use existing control/session/runtime test modules when appropriate; add narrowly named tests rather than broad suites.

Suggested tests:

```text
test_control_header_roundtrip_preserves_runtime_invocation_scope
test_subprocess_worker_echoes_invocation_scope
test_control_response_admission_rejects_wrong_invocation
test_control_response_admission_rejects_wrong_binding
test_control_response_admission_rejects_duplicate_terminal
test_session_active_attempt_is_step_scoped
test_supervisor_keeps_attempt_a_and_b_separate
test_local_provider_does_not_emit_synthetic_worker_ack
test_late_attempt_a_result_is_fenced_after_b_activation
test_transport_timeout_is_not_worker_error_result
```

### Adjacent regressions

At most 1–2 adjacent suites per Slice, e.g.:

```text
existing control-plane tests
existing adaptive mainline/provider-binding integration
```

Do not default to full repository tests.

---

## 11. Gate definitions

### SOURCE GATE

Pass only if:

```text
the test reproduces the old gap
and
the implementation directly addresses that gap
```

### MECHANISM GATE

#### 05A
Must cross real UDS/protobuf subprocess.

#### 05B
At least one admitted real physical result; negative correlation tests exercise the real validator.

#### 06A
Must show lifecycle truth changed:
- no synthetic ACK for local provider;
- at least one real worker control event is observed as worker-origin.

#### 06B
Must execute actual delayed-result fencing sequence.
A fake dataclass stale result without lifecycle transition is insufficient.

### INTEGRATION GATE

Canonical mainline uses the changed seam successfully.

### COMPETITION GATE

No unsupported performance claim. Evidence records can truthfully say which events were worker-observed vs runtime-derived.

---

## 12. Evidence artifacts Codex must leave

Per Slice implementation record should include:

```text
current branch and scoped working-tree status
changed production files
changed test files
exact test commands
test outputs
mechanism trace excerpt
negative test evidence
known limitations
gate status with reasons
next allowed slice
```

For control mechanism, record at least:

```text
request:
task/run/session/step/attempt/invocation/binding/grant

observed ACK:
same exact scope

observed terminal:
same exact scope
```

For late result:

```text
A active
A terminal reason
B active
late A observed
fence decision
B still active
workflow outputs unchanged by A
```

---

## 13. Rollback model

Each Slice must be independently revertible.

- Revert 05A: wire returns to MRR-04 shape.
- Revert 05B: no response admission seam; 05A fields can remain but Batch 2 is not safe.
- Revert 06A: active-attempt/lifecycle truth reverts; do not run 06B.
- Revert 06B: timeout/late-result correctness not claimed.

No Slice may depend on a hidden manual migration.

---

## 14. DESIGN_CONFLICT stop conditions

Codex must stop and report `DESIGN_CONFLICT` if any of the following appears:

1. Current branch source differs materially from `a8345d60f3a6e7078dda22e271e9d1ab02a931fd` in a touched authority seam.
2. A required change needs modifying `statebus/state/**`, `statebus/memory/**`, artifact/replay, scheduler or deployment.
3. The only way to pass tests is to synthesize missing identity/ACK/result.
4. Supporting compatibility requires accepting a request with unknown/missing Batch 2 authority fields on the canonical path.
5. A generic event/scheduler/plugin framework becomes “necessary” without a concrete source call site.
6. A late result cannot be exercised without redesigning the whole dispatcher/provider model; in that case stop at 06B and report the missing mechanism rather than fake a PASS.

---

## 15. Batch 2 completion gate

Batch 2 is CLOSED only when all are true:

```text
05A PASS
05B PASS
06A PASS
06B PASS

No physical response can bypass correlation.
No semantic result can bypass active-attempt admission.
No local path claims remote ACK.
No transport timeout is represented as worker business result.
A real delayed A result after B activation is fenced.
```

Only then may MRR-07 State Lifecycle move from readiness design to implementation.
