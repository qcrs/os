# StateBus MRR-07A Gate Review

## Verdict

```text
MRR-07A_GATE_PASS
```

```text
MRR-07A
=
CLOSED

State Identity / Access Authority
=
FROZEN
```

This was a read-only correctness review. No production source was modified and
no test was rerun. The current source agrees with the implementation record and
the existing targeted evidence is sufficient for this gate.

## Review boundary

Reviewed against:

- `docs/mrr/batch3/MRR-07A-State-Access-Authority-Immutable-Ref-Slice-Spec.md`
- `docs/mrr/batch3/StateBus-MRR-Batch3-State-Artifact-Truth-Deep-Design.md`
- `docs/mrr/batch3/StateBus-MRR-Batch3-v2-Amendment-Ledger.md`
- `docs/mrr/implementation/MRR-07A-IMPLEMENTATION-RECORD.md`
- the current MRR-07A production source, focused tests, and recorded evidence

No SHA or history evidence was used. Competition benchmarks, Docker, vLLM,
coverage, performance tests, and broader regression suites were not run.

## Required checklist

```text
[1] Identity != Authority
PASS

[2] StateAccessGrant is derived witness
PASS

[3] CapabilityGrant.input_ref_ids remains root input allowlist
PASS

[4] RUNTIME_INTERMEDIATE constrained
PASS

[5] Ref reuse forbidden
PASS

[6] Local canonical enforcement
PASS

[7] Worker canonical enforcement before acquisition
PASS

[8] Stale Attempt cannot mint new authority
PASS

[9] No 07B lifetime scope creep
PASS

[10] No Artifact/Memory authority scope creep
PASS
```

## Gate findings

### 1. Identity is not authority

`SemanticStateRef.state_identity_hash` identifies immutable publication facts
only. `RefHandle` remains an identity projection. Neither type carries an
access decision.

The canonical adaptive semantic path fails closed without
`RuntimeStateAccessAuthority`, carries a separate `StateAccessGrant` beside the
`RefHandle`, and admits that witness before local or worker physical access.
Knowing only `ref_id` is therefore insufficient on the canonical product path.

Relevant seams:

- `statebus/refs/models.py:50`
- `statebus/contracts/state_access.py:19`
- `statebus/runtime/adaptive_dispatcher.py:330`
- `statebus/control/subprocess_worker.py:206`

### 2. StateAccessGrant remains derived

`RuntimeStateAccessAuthority` is created by the Runtime from the current
`RuntimeIdentity` and exact `BoundCapabilityGrant`. Issuance rechecks the active
Attempt and Grant expiry, binds the ExecutionBinding and CapabilityGrant
hashes, copies the bound provider, binds the consumer and optional physical
invocation, and limits expiry to the earlier of Grant and State lease expiry.

The witness does not create or activate an Attempt, select a provider, enlarge
a capability, publish by itself, or own State lifetime. The public dataclass is
the wire contract; the canonical issuance call chain remains Runtime-owned.

Relevant seams:

- `statebus/runtime/adaptive_runtime.py:234`
- `statebus/runtime/adaptive_runtime.py:291`
- `statebus/contracts/provider_binding.py:302`

### 3. Capability input authority has one root allowlist

For `CAPABILITY_INPUT`, `issue_read()` directly requires membership in the
existing `CapabilityGrant.input_ref_ids`. There is no independent State input
allowlist or State-owned capability decision.

Relevant seam: `statebus/runtime/adaptive_runtime.py:303`.

### 4. RUNTIME_INTERMEDIATE is constrained

The Runtime enables dense semantic intermediate publication only when all of
the following hold:

- the current registered implementation is `RETRIEVAL_ADAPTER`;
- the descriptor output contract matches the current CapabilityGrant output
  contract;
- the descriptor is registered to produce `canonical_evidence_pack`;
- the current Attempt remains active under the exact BoundCapabilityGrant;
- publication uses the Runtime-owned, dense-semantic-only method;
- immutable publication succeeds and its identity is registered before a READ
  witness can be issued.

This is an explicit execution-kind/output-contract mapping, not a
`capability_id` string exception. The dense State is an internal mechanism for
producing the already-authorized canonical evidence output; it is not exposed
as a new logical capability output. A provider cannot select an arbitrary
State kind because the Runtime seam has no generic `object_kind` publication
entry point.

Relevant seams:

- `statebus/runtime/adaptive_runtime.py:259`
- `statebus/runtime/adaptive_runtime.py:306`
- `statebus/runtime/adaptive_runtime.py:1499`
- `statebus/runtime/adaptive_dispatcher.py:394`

### 5. Ref identity is immutable after publication

`LayeredStateStore.publish()` checks both the live materialization registry and
the persistent metadata marker before storage selection or physical
materialization. Duplicate publication raises `state_ref_reuse_forbidden`; it
does not replace, release, rename, or add a generation to the prior object.

The existing immutable publication evidence verifies that the original handle,
payload, and metadata remain unchanged after a duplicate attempt.

Relevant seam: `statebus/state/store.py:229`.

### 6. Local and worker paths enforce the same authority semantics

The local Runtime read requires an active Attempt and validates task/run/session,
Step/Attempt, Binding, Grant, Ref, bound provider, local consumer role, empty
local invocation scope, expiry, and immutable identity before entering the
low-level resolver. It does not manufacture a ControlHeader, invocation ID, or
worker lifecycle event.

The provider-internal semantic worker validates the equivalent scope using the
real ControlHeader and physical invocation ID. Both paths consume witnesses
issued from the same Runtime authority object.

Relevant seams:

- `statebus/runtime/adaptive_runtime.py:346`
- `statebus/runtime/adaptive_dispatcher.py:436`
- `statebus/runtime/adaptive_dispatcher.py:531`

### 7. Worker admission precedes physical acquisition

For `semantic_select_v1`, the worker first requires exactly one Ref and one
StateAccessGrant, then validates execution scope, Binding hash, Grant hash,
Ref, provider/role, invocation, READ mode, and expiry. It reconstructs the
immutable identity from the sidecar and compares the State identity hash before
`select_dense_semantic_state()` reaches the SharedMemory or mmap open.

The general memfd compatibility reader is not reached with an encoded memfd Ref
on this canonical semantic path: dense semantic publication is restricted to
the named SharedMemory/mmap backends and the request carries the ordinary State
ID. Existing rejection evidence shows invalid authority stops before the
instrumented physical resolver, while the integration evidence covers a real
UDS/protobuf worker acquisition.

Relevant seams:

- `statebus/control/subprocess_worker.py:206`
- `statebus/control/subprocess_worker.py:244`
- `statebus/control/subprocess_worker.py:292`
- `statebus/state/semantic_state.py:306`

### 8. Settlement revokes new authority only

Publication, READ issuance, and local acquisition all enter
`_require_active_attempt()`. Once settlement clears the active Attempt pointer,
those operations fail with `state_access_attempt_not_active`.

The worker does not consult a second active-Attempt registry after dispatch and
does not attempt mid-flight mapping revocation. Already-dispatched physical
work remains subject to the frozen Batch 2 stale-result admission fence.

Relevant seam: `statebus/runtime/adaptive_runtime.py:243`.

### 9. Lifetime remains outside 07A

The 07A production changes add no StatePin, pin/unpin API, owner-release state,
consumer refcount, settlement cleanup, or physical reclaim policy. Existing
release behavior is unchanged and remains work for MRR-07B.

### 10. Artifact and Memory authority remain separate

The new witness is used only for semantic State publication and READ. The 07A
changes do not alter Artifact verification, replay eligibility, Memory
admission, or final adoption authority.

## Source contradiction

```text
NONE
```

The implementation record accurately describes the current authority object,
wire projection, canonical local/worker call chain, immutable ref guard, and
test evidence.

## Test rerun

```text
NOT_REQUIRED
```

No record/source contradiction was found, so the review did not invoke the
single exceptional targeted-test allowance. Existing evidence remains:

- `artifacts/mrr-07a/authorized_state_access.txt`
- `artifacts/mrr-07a/state_access_rejection.txt`
- `artifacts/mrr-07a/immutable_ref_publication.txt`
- `artifacts/mrr-07a/targeted_tests.txt`

## Non-blocking observations

- Low-level `load/get/resolve_*` functions remain identity/materialization
  primitives. Current production call-site review found no canonical adaptive
  semantic consumer bypassing the new authority seam.
- The logit-State acquisition path is currently referenced by smoke,
  benchmark, and tests rather than the canonical adaptive semantic mainline.
  It is non-blocking for 07A; promotion into a future product mainline must use
  the same authority boundary.
- The pure-text carrier does not acquire semantic State and rejects typed State
  fields, so it is not a State authority bypass.
- This gate establishes trusted StateBus correctness enforcement, not
  hostile-process or cryptographic isolation.
- The competition brief additionally requires multi-Agent coverage, matched
  text/structured experiments, shared Memory storage/retrieval/reuse,
  performance evidence, stable repeated runs, and openEuler delivery. None of
  those end-to-end claims
  is inferred from this narrow gate.

## Competition gate

```text
COMPETITION_GATE_UNVALIDATED
```

## Next allowed slice

```text
MRR-07B
State Ownership + Pin / Release Lifecycle
=
READY_FOR_IMPLEMENTATION
```

```text
NEXT_ALLOWED_SLICE = MRR-07B
```
