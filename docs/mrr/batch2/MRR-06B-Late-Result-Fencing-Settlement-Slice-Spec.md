# MRR-06B Slice Spec — Late Result Fencing / Timeout-Cancel Settlement

## Goal

Prove the defining Batch 2 invariant:

```text
Attempt A terminal/superseded
+
Attempt B active
+
late A event/result
=
FENCE + AUDIT
NEVER COMMIT
```

## Why this Slice exists

MRR-05A/05B give physical correlation; MRR-06A gives active-attempt ownership and attempt-aware lifecycle.

This Slice closes the commit-time freshness check.

## Architecture invariant

For Step S:

```text
Only session.active_attempt(S)
may mutate the semantic workflow result.

No event/result from a non-active or terminal Attempt
may update:
- RuntimeWorkflowStep outputs
- completion state
- adopted refs
- artifact/state promotion
```

Physical cancellation success is not required for semantic safety.

## Current source truth

Before Batch 2:

- timeout truth is split;
- transport can synthesize worker-looking `ErrorResult(subprocess_timeout)`;
- Supervisor has timeout primitives but canonical runtime is not driven by real events;
- no active-attempt result fence exists.

## Exact symbols involved

```text
statebus.runtime.session.RuntimeSessionManager
statebus.runtime.supervisor.RuntimeSupervisor
statebus.runtime.adaptive_runtime.AdaptiveRuntimeEngine
statebus.control.transport.SubprocessExecutorTransport
statebus.control.admission.ControlResponseAdmissionReceipt
```

## Files to read

```text
statebus/runtime/session.py
statebus/runtime/supervisor.py
statebus/runtime/adaptive_runtime.py
statebus/control/transport.py
statebus/control/admission.py
tests created in 05A/05B/06A
```

## Expected production files changed

Target <= 4:

```text
statebus/runtime/session.py
statebus/runtime/supervisor.py
statebus/runtime/adaptive_runtime.py
statebus/control/transport.py
```

If a tiny admission extension is required, `statebus/control/admission.py` may be the fifth.

## Contracts added/changed

### Transport timeout outcome

Represent locally detected timeout as an explicit local transport outcome/exception/status, not `ErrorResult`.

No new generic transport framework.

### Fencing/admission receipt

Late response admission should record at minimum:

```text
step_id
observed_attempt_id
active_attempt_id
invocation_id
decision = FENCED_STALE_ATTEMPT
reason
```

This can extend the existing 05B admission receipt or use a small Runtime-level result admission receipt.

Avoid adding both unless code ownership clearly requires two layers.

### Settlement rule

Terminalization:

```text
mark A terminal
retain A history
clear active pointer only if active == A
```

Activation of B must occur only after the Runtime has semantically settled A.

## Retry / Rebind scope

This Slice does not create a generic retry engine.

The delayed-result mechanism may use the narrowest existing re-execution/fallback/test hook that can produce:

```text
A → terminal
B → active
```

If real production code needs a small same-Step new-Attempt helper, add only that helper.

Do not add provider ranking or scheduler.

## Implementation sequence

1. Remove/replace synthetic transport timeout `ErrorResult`.
2. Route timeout to Runtime as local timeout observation.
3. Runtime terminalizes and settles A.
4. Best-effort physical cancel/terminate A.
5. Activate B.
6. Allow controlled test worker A to emit late terminal result.
7. 05B physical correlation proves it belongs to A.
8. Session active-attempt check observes B.
9. Produce fence decision.
10. Assert zero semantic mutation from late A.
11. Let B complete.
12. Verify duplicate terminal handling.
13. Record mechanism evidence.

## Cancellation rule

```text
cancel requested
→ Runtime semantic terminalization/fence first
→ physical CancelCommand/terminate best effort
→ old worker may still run
→ late output remains unauthorized
```

Do not wait for physical cancellation acknowledgement to protect semantic state.

## Non-goals

```text
exactly-once execution
persistent worker
distributed lease service
resource scheduler
State GC
Artifact GC
provider health ranking
generic retry policy
```

## Targeted tests

Keep this Slice centered on the single late-result mechanism test. Add at most 2 small supporting tests only when required by the implementation seam.

Primary required mechanism test:

```text
test_late_attempt_a_result_is_fenced_after_attempt_b_activation
```

Required shape:

```text
A active
A real physical invocation starts
A deadline expires
A terminal/settled
B active
A sends late SuccessResult
response physically decodes and correlates to A
Runtime fence receipt produced
Step output unchanged by A
B remains active
B success commits
```

Additional:

```text
cancelled A late result fenced
duplicate A terminal does not mutate state twice
settling old A cannot clear active B
transport timeout not represented as worker ErrorResult
```

## Integration test

Use the narrowest real UDS/subprocess delayed-worker fixture possible.

Test-only fixture changes are allowed.

Do not build persistent worker infrastructure just to create the scenario.

## Evidence

Required trace:

```text
T0 A activated
T1 A dispatched
T2 A timeout/cancel decision
T3 A terminal settlement
T4 B activated
T5 late A terminal observed
T6 FENCED_STALE_ATTEMPT
T7 B still active
T8 B commits
```

## Source Gate

PASS if pre-slice source lacks active-attempt late-result fence and transport timeout is worker-shaped.

## Mechanism Gate

**Do not mark PASS** unless the controlled late result truly traverses the physical control path after B activation.

A fabricated `AdaptiveStepResult(attempt_id="A")` unit test alone is insufficient.

## Integration Gate

Canonical mainline still settles success/failure normally and does not leak active Attempt pointers.

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

Revert 06B only; 06A active-attempt/lifecycle improvements can remain, but Batch 2 remains incomplete and MRR-07 remains blocked.

## DESIGN_CONFLICT stop conditions

Stop and report if:

1. physical transport fundamentally cannot deliver a late message after timeout without a broad persistent-worker rewrite;
2. active Attempt cannot be checked before workflow output mutation;
3. late output has already been promoted into State/Artifact before Runtime result admission and cannot be quarantined without entering Batch 3.

In case (3), do not redesign State/Artifact inside 06B. Record the exact source seam and mark 06B NO-GO pending a revised boundary.

## NEXT_ALLOWED_SLICE

After PASS:

```text
BATCH 2 GATE REVIEW
```

Then, and only then:

```text
MRR-07 State Lifecycle
READY
```
