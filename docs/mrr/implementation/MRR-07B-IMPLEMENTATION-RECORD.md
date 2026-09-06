# MRR-07B Implementation Record

## Goal

Freeze the Runtime-local State lifetime invariant: an authorized live consumer
pin prevents physical reclaim, while owner release and consumer unpin are
logical, safe, and idempotent operations.

## Files changed

Production:

- `statebus/state/store.py`
- `statebus/state/semantic_state.py`
- `statebus/runtime/adaptive_runtime.py`
- `statebus/runtime/adaptive_dispatcher.py`
- `statebus/runtime/adaptive_mainline.py`

Tests:

- `tests/test_mrr_07b_state_lifetime.py`
- `tests/test_adaptive_mainline_integration.py`

Evidence and record:

- `artifacts/mrr-07b/pin_release_trace.txt`
- `artifacts/mrr-07b/idempotent_release.txt`
- `artifacts/mrr-07b/attempt_cleanup.txt`
- `artifacts/mrr-07b/targeted_tests.txt`
- `docs/mrr/implementation/MRR-07B-IMPLEMENTATION-RECORD.md`

## Lifetime model

`LayeredStateStore` now retains one `StateLifetimeRecord` per immutable
publication. It stores the Runtime/session publication owner, producer Step and
Attempt as provenance, logical owner-release state, Runtime-local live and
released consumer pins, and physical reclaim state.

`StatePin` is a lifetime dependency only. It records the exact Ref, consumer
Attempt/provider/role, access-grant ID, optional physical invocation, and
acquisition time. It cannot authorize READ, publication, another Ref, or
another Attempt.

## Owner release rule

Canonical Runtime cleanup calls `release_owner(ref_id, owner_session_id=...)`.
It validates the publication owner, changes `owner_released` once, and is
idempotent. The existing `release(ref_id)` remains a compatibility projection
for publications without scoped producer provenance and now has the same
logical/idempotent semantics.

Producer Attempt settlement does not release the publication owner.

## Pin/unpin rule

The public canonical acquisition seam is
`RuntimeStateAccessAuthority.acquire_pin()`. It first requires the exact active
Attempt and validates the existing READ `StateAccessGrant`, including execution,
binding, Grant, Ref identity, consumer, invocation, and expiry scope. The Store
then records the admitted lifetime dependency.

`unpin` validates ownership by session/Step/Attempt but does not require that
Attempt to remain active. A first unpin moves the pin out of `live_pins`; a
repeat observes the explicit released state and returns without another
transition.

## Physical reclaim condition

All explicit Store release and teardown paths reach backend cleanup only
through:

```text
owner_released
AND live_pin_count == 0
AND not physical_reclaimed
```

The existing backend actions remain narrow: SharedMemory close/unlink, Runtime
memfd close, mmap unlink, or inline materialization removal.

## Attempt settlement cleanup

Adaptive Runtime terminal settlement goes through one helper. It first clears
the semantic active-Attempt pointer through `RuntimeSessionManager`, then
unpins only consumer dependencies owned by that exact Attempt. It does not
owner-release State produced by the Attempt. The pre-dispatch expiry path has
no State authority or pin to clean.

## Canonical consumer integration

The semantic subprocess is pinned after its invocation-bound READ witness is
issued and before transport execution; the pin is released when physical
consumption ends. The Runtime-local query read likewise pins before resolving
the State and unpins in its completion path. Mainline teardown performs the
separate Runtime/session owner release.

## Tests actually run

```text
source /home/qcrs/statebus/project/deploy/activate_statebus_host.sh
PYTHONDONTWRITEBYTECODE=1
PYTHONPATH=/home/qcrs/statebus/os

python -m pytest -q tests/test_mrr_07b_state_lifetime.py
python -m pytest -q tests/test_adaptive_mainline_integration.py::test_adaptive_product_retrieval_owns_cross_process_semantic_state
```

No full suite, Docker, vLLM, benchmark, coverage, performance test, or broad
predecessor regression was run.

## Results

The three primary lifetime tests passed in 0.80 seconds. They cover real
SharedMemory survival until final unpin, repeated owner release/unpin, stale
pin rejection, stale cleanup permission, and two-consumer settlement behavior.

The adjacent canonical semantic integration initially encountered the
restricted environment's UDS bind denial. The identical test then passed
outside that restriction in 1.76 seconds, including real UDS/protobuf worker
access and the worker/local pin history.

## Source Gate

`SOURCE_GATE_PASS`

Identity, READ authority, and lifetime remain separate. Owner release/unpin are
explicit idempotent transitions, active READ authority is required for new
pins, stale Attempts may only reduce their prior dependencies, settlement does
not destroy publication ownership, and explicit physical reclaim is gated by
owner release plus zero live pins. No distributed refcount or Artifact/Memory
authority was introduced.

## Mechanism Gate

`MECHANISM_GATE_PASS`

A real SharedMemory publication remained loadable and reopenable after owner
release while pinned, then became non-reopenable after final unpin triggered
physical reclaim.

## Integration Gate

`INTEGRATION_GATE_PASS`

The canonical semantic State path completed through the existing 07A READ
authority checks, real cross-process worker acquisition, Runtime-local read,
pin/unpin cleanup, and final owner release.

## Competition Gate

`COMPETITION_GATE_UNVALIDATED`

## Known limitations

Lifetime accounting is intentionally Runtime-local and assumes trusted
StateBus code. It does not implement distributed reference counting, hostile
process mapping revocation, persistent lifetime recovery, Artifact lifecycle,
Memory admission, replay eligibility, or competition end-to-end validation.

## NEXT_ALLOWED_SLICE

`NEXT_ALLOWED_SLICE = MRR-07B_GATE_REVIEW`
