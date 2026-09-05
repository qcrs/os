# MRR-06A Slice Spec — Attempt Authority / Lifecycle Origin Truth

## Goal

Give semantic active-Attempt authority to `RuntimeTaskSession`, make Supervisor attempt-aware, and eliminate fake remote-worker lifecycle transitions from the canonical Runtime.

## Why this Slice exists

The current source has two incompatible truths:

```text
AdaptiveRuntimeEngine:
ACK/RUNNING synthesized before dispatch

subprocess_worker:
real ACK/RUN_START/HEARTBEAT
```

At the same time, `RuntimeSupervisor` is keyed by Step ID, so multiple Attempts cannot coexist safely.

## Architecture invariant

```text
Session decides:
which Attempt is active for semantic commit.

Supervisor tracks:
operational state of a concrete Attempt.

Lifecycle state source is truthful:
Runtime-derived local start != real worker ACK.
```

## Current source truth

- `AdaptiveRuntimeEngine._dispatch_lifecycle()` calls `supervisor.ack()` and `run_start()` before provider dispatch.
- `RuntimeSupervisor.steps` is step-keyed.
- Session has attempt records but no `active_attempt(step)` authority API.
- current real subprocess is provider-internal semantic selection, not a universal outer provider.

## Exact symbols involved

```text
statebus.runtime.session.RuntimeTaskSession
statebus.runtime.session.RuntimeSessionManager
statebus.runtime.session.StepAttemptRecord
statebus.runtime.session.RuntimeWorkflowStep

statebus.runtime.supervisor.RuntimeSupervisor
statebus.runtime.supervisor.StepRuntimeRecord

statebus.runtime.adaptive_runtime.AdaptiveRuntimeEngine._dispatch_lifecycle
statebus.runtime.adaptive_runtime.AdaptiveRuntimeEngine.run
```

## Files to read

```text
statebus/runtime/session.py
statebus/runtime/supervisor.py
statebus/runtime/adaptive_runtime.py
statebus/runtime/adaptive_dispatcher.py
statebus/control/transport.py
statebus/control/subprocess_worker.py
```

## Expected production files changed

Preferred:

```text
statebus/runtime/session.py
statebus/runtime/supervisor.py
statebus/runtime/adaptive_runtime.py
```

Potentially `adaptive_dispatcher.py` only if a small lifecycle observer hook is required.

Keep <= 4 primary production files.

## Contracts changed

### Session active Attempt

Add narrow methods equivalent to:

```text
activate_attempt(session_id, step_id, attempt_id)
active_attempt_id(session_id, step_id)
settle_attempt(session_id, step_id, attempt_id, terminal_state, ...)
```

Rules:

```text
activation is explicit
historical attempt records are retained
settlement clears active pointer only if equal
non-active attempt cannot perform commit-authoritative workflow mutation
```

### Supervisor key

Replace step-only key with an Attempt-scoped key, preferably:

```text
(session_id, step_id, attempt_id)
```

A small immutable key type is acceptable if it replaces repeated tuples. Do not create a generic resource identity framework.

### Lifecycle states

Prefer existing states plus `BOUND` if needed.

Local provider may transition:

```text
PENDING → BOUND → DISPATCHED → RUNNING
```

without ACK.

Remote/protobuf control invocation may have:

```text
... → DISPATCHED → ACKED → RUNNING
```

only when observed.

## WorkerEvent decision

Do **not** add generic `WorkerEvent`.

Consume/record existing typed messages.

Event origin must be distinguishable:

```text
WORKER_OBSERVED
ADAPTER_DERIVED
LOCAL_RUNTIME
```

This may be telemetry/details rather than a new hierarchy.

## Critical current-source nuance

The existing semantic-select subprocess is inside a retrieval provider.

Do not update outer semantic Step `ACKED/RUNNING` merely because that inner subprocess ACKed.

Real worker events can be recorded as physical invocation observations. They only drive the semantic provider lifecycle if/when the bound provider's execution boundary is explicitly that worker.

## Implementation sequence

1. Add active-Attempt Session API.
2. Make attempt activation happen before binding/dispatch work that belongs to that attempt.
3. Record BOUND after binding+grant if state enum is extended.
4. Change Supervisor to Attempt-scoped key.
5. Remove unconditional synthetic `ack()` and `run_start()` calls.
6. Local provider:
   - mark DISPATCHED immediately before call;
   - mark RUNNING on actual local handler entry;
   - no ACK.
7. Preserve/capture 05B-admitted worker control events with correct origin.
8. Update attempt/workflow mutations to use the active Attempt.
9. Tests for A/B records and no overwrite.

## Non-goals

```text
late-result fence mechanism completion
retry scheduler
rebind policy
persistent worker
heartbeat scheduler
state release
resource admission
parallel READY scheduling
```

## Targeted tests

These are coverage conditions. Consolidate into <= 4 targeted functions where practical; do not create one test per bullet.

```text
session activates exactly one attempt per step
settling A does not clear active B
supervisor retains A and B independently
local provider emits no ACK state
local provider RUNNING occurs only at invocation
protobuf worker event origin is worker-observed
text carrier event origin is adapter-derived
```

## Integration test

Run canonical adaptive local provider path and the existing semantic subprocess path.

Assert telemetry/state does not claim the provider-internal worker ACK is the outer Step's remote ACK.

## Evidence

Capture transition trace with:

```text
step_id
attempt_id
old_state
new_state
origin
timestamp
```

## Source Gate

PASS only if step-keyed overwrite and synthetic ACK/RUNNING are reproduced against the pre-slice source.

## Mechanism Gate

PASS only if:

1. local path has no fake worker ACK; and
2. at least one real protobuf subprocess ACK/RUN_START/HEARTBEAT is observed and identified as worker-origin.

## Integration Gate

Canonical mainline completes without relying on synthetic ACK.

## Competition Gate

`UNVALIDATED` in this Slice. This Slice may improve the truthfulness of later competition evidence but does not validate competition E2E or performance claims.

## Execution discipline

- no Git SHA/history/merge-base analysis or source-SHA ledger;
- testing bullets are coverage requirements, not test-count requirements; consolidate/parameterize aggressively;
- targeted tests only plus at most 1 directly adjacent regression by default;
- no defensive/future-proof abstraction, generic fallback/retry framework, silent repair, or unrelated cleanup;
- after required gate evidence, `git diff --check`, and scope check, stop; no broad post-implementation audit;
- do not commit/push/reset/clean/rebase/merge and do not use `git add .`.

## Rollback

Revert session/supervisor/runtime changes together. Do not leave a mixed step-keyed supervisor with active-Attempt session semantics.

## DESIGN_CONFLICT stop conditions

Stop if:

- semantic active Attempt must be stored in a new global coordinator;
- existing mainline requires a fake ACK to function;
- worker event integration would require persistent workers/scheduler;
- provider-internal worker events cannot be kept separate from semantic Step state without a broad provider rewrite.

## NEXT_ALLOWED_SLICE

```text
MRR-06B
Late Result Fencing + Timeout/Cancel Settlement
```
