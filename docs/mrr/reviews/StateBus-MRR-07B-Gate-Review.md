# StateBus MRR-07B Gate Review

## Review Scope

- Review role: Runtime / State Lifetime correctness reviewer
- Slice: MRR-07B - State Ownership, Pin, Release, and Reclaim Lifecycle
- Branch: `feat/mrr-07b-state-lifetime`
- Review mode: source and recorded-evidence review only
- Source/history audit: not performed
- Test rerun: not required
- Competition validation: unvalidated

## Gate Verdict

```text
MRR-07B_GATE_PASS
```

MRR-07B is closed. The State Lifetime Plane is frozen, and MRR-07 State
Lifecycle is closed. MRR-08 Artifact/Evidence Truth is ready for
implementation.

## Boundary Assessment

The implementation keeps the three State planes separate:

- Identity remains the immutable `SemanticStateRef` content identity.
- Access authority remains the Runtime-issued `StateAccessGrant` and the
  Runtime-owned validation path in `RuntimeStateAccessAuthority`.
- Lifetime is represented separately by `StatePin` and `StateLifetimeRecord`
  in `LayeredStateStore`.

A `StatePin` records an admitted consumer lifetime. It does not carry State
content, grant READ authority, or provide a pin-to-State resolution API. The
canonical acquisition path first proves the Attempt is active, validates the
READ grant against the Runtime identity, execution binding, consumer scope,
State identity, provider, invocation, and expiry, and only then records the
pin in the Store.

## Mandatory Checklist

| # | Review item | Result | Source basis |
|---|---|---|---|
| 1 | Identity, authority, and lifetime are separate | PASS | `SemanticStateRef`, `StateAccessGrant`, and `StatePin` / `StateLifetimeRecord` remain distinct contracts. |
| 2 | `StatePin` is lifetime-only | PASS | `statebus/state/store.py:191`; the pin contains consumer and grant witness metadata but no State payload or resolution authority. |
| 3 | New pin requires an active authorized consumer | PASS | `statebus/runtime/adaptive_runtime.py:244`, `:352`, and `:377`; active Attempt and READ grant validation precede Store pin recording. |
| 4 | Owner release is logical | PASS | `statebus/state/store.py:425`; release marks `owner_released` and delegates physical action to the reclaim predicate. |
| 5 | Owner release is idempotent | PASS | Repeated release returns no state change; recorded by `idempotent_release.txt`. |
| 6 | Unpin is idempotent | PASS | `statebus/state/store.py:377`; released pins are retained as witnesses and repeated unpin returns false without another reclaim. |
| 7 | A live pin prevents reclaim | PASS | `pin_release_trace.txt` records owner release with one live pin while SharedMemory remains reopenable. |
| 8 | Reclaim requires owner release and zero pins | PASS | `statebus/state/store.py:449`; both predicates are checked before backend close/unlink and materialization removal. |
| 9 | Multiple consumers are isolated correctly | PASS | `test_attempt_settlement_cleans_own_pin_and_preserves_other_consumer` retains consumer B after consumer A settles. |
| 10 | Attempt settlement cleans only its own pins | PASS | `statebus/runtime/adaptive_runtime.py:1540` and `statebus/state/store.py:399` use exact session, step, and Attempt scope. |
| 11 | Producer settlement preserves publication | PASS | Attempt settlement unpins that Attempt but does not release the Runtime session's publication ownership. |
| 12 | `StateAccessGrant` remains the root READ witness | PASS | `RuntimeStateAccessAuthority.acquire_pin` validates the grant before pin creation; dispatcher and local Runtime reads use that path. |
| 13 | No OS-lifetime shortcut controls normal reclaim | PASS | Normal reclaim is contract-driven; PID/process exit is not used as the lifetime predicate. |
| 14 | No distributed reference counting was introduced | PASS | Lifetime records and pin maps are Runtime-local Store state only. |
| 15 | No Artifact/Memory scope expansion occurred | PASS | The implementation is confined to State lifetime and the existing adaptive Runtime integration path. |

## Canonical Call Chains

### Worker consumer

```text
Runtime issues invocation-bound StateAccessGrant
  -> RuntimeStateAccessAuthority.acquire_pin
  -> active Attempt and READ witness validation
  -> LayeredStateStore.acquire_pin
  -> worker transport
  -> RuntimeStateAccessAuthority.unpin in finally
```

### Runtime-local consumer

```text
RuntimeStateAccessAuthority.read_query_embedding
  -> active Attempt and READ witness validation
  -> acquire pin
  -> resolve/load State
  -> unpin in finally
```

### Attempt settlement

```text
Runtime settles exact Attempt
  -> cleanup_attempt_pins(session_id, step_id, attempt_id)
  -> publication ownership remains unchanged
```

These paths preserve `StateAccessGrant` as authority and use the pin only as a
lifetime witness.

## Adaptive Mainline Change

The `adaptive_mainline.py` change from legacy release to
`release_owner(state_id, owner_session_id=runtime_identity.session_id)` is
necessary for Runtime-owned logical cleanup. It proves which Runtime session
owns the publication and prevents normal product cleanup from treating
publication completion as permission for immediate physical unlink. Any live
consumer pin continues to defer physical reclaim.

## Allowed Compatibility And Shutdown Boundaries

`LayeredStateStore.release(ref_id)` remains a low-level compatibility method
for publications without scoped producer provenance. It routes through the
logical owner-release mechanism and rejects scoped canonical publications;
the adaptive product path therefore cannot use it to bypass lifetime checks.

`LayeredStateStore.teardown()` routes materializations through logical owner
release. A materialization with live pins is not reclaimed by normal teardown.
The weak-reference orphan finalizer is limited to process shutdown or
catastrophic Store abandonment, which is the explicitly allowed forced-cleanup
boundary and is not used as a normal execution lifetime mechanism.

The Store-level `load`, `get`, and pin-recording methods remain trusted
low-level primitives. They are not authority-bearing business APIs: the
canonical Runtime path owns admission, and a pin identifier cannot resolve or
read State.

## Evidence Reviewed

- `artifacts/mrr-07b/pin_release_trace.txt`
- `artifacts/mrr-07b/idempotent_release.txt`
- `artifacts/mrr-07b/attempt_cleanup.txt`
- `artifacts/mrr-07b/targeted_tests.txt`
- `docs/mrr/implementation/MRR-07B-IMPLEMENTATION-RECORD.md`

Recorded results:

- Primary lifecycle suite: 3 passed.
- Adjacent cross-process integration: the restricted sandbox denied UDS bind;
  the identical targeted command passed in the authorized environment.
- No Docker, vLLM, benchmark, performance, coverage, or full-suite claim is
  made.

The evidence and current source agree, so another targeted test run is not
required by this gate review.

## Source Contradiction

```text
NONE
```

## Non-Blocking Observations

- Lifetime tracking is Runtime-local and does not claim crash-recovery,
  distributed reference counting, hostile-process mapping revocation, or
  recovery-ledger semantics.
- Store primitives remain callable by trusted internal code, as they were in
  the frozen MRR-07A boundary; correctness of the canonical product path is
  enforced by `RuntimeStateAccessAuthority` and exact Attempt settlement.
- Competition behavior remains unvalidated and must not be inferred from the
  local targeted evidence.

## Gates

```text
IDENTITY_AUTHORITY_LIFETIME_SEPARATION_PASS
STATE_PIN_CONTRACT_PASS
OWNER_RELEASE_CONTRACT_PASS
RECLAIM_GATE_PASS
ATTEMPT_CLEANUP_PASS
MULTI_CONSUMER_PASS
INTEGRATION_GATE_PASS
COMPETITION_GATE_UNVALIDATED
```

```text
MRR-07 STATUS = CLOSED
STATE LIFETIME PLANE = FROZEN
NEXT_ALLOWED_SLICE = MRR-08
```
